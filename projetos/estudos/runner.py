import json
import re
from pathlib import Path

from core.config import get_settings
from core.estado import (
    enfileirar,
    fotos_do_job,
    job_por_prefixo_id,
    limpar_reprocessamento,
    marcar_promovido,
    marcar_reprocessamento,
    proximo_da_fila,
    registrar_aviso_job,
    registrar_etapas_feitas,
    registrar_numero_aula,
    registrar_passo,
    transicionar,
)
from core.fileops import escrever_texto, ler_texto, listar, mover, remover
from core.images.preprocess import preparar
from core.logging import registrar_evento
from projetos.estudos.agenda import extrair as extrair_compromissos
from projetos.estudos.agentes import (
    AgenteCompositor,
    AgenteContexto,
    AgenteExtrator,
    AgenteFlashcards,
    AgenteTriagem,
    validar_completo,
    validar_conceito_completo,
)
from projetos.estudos.biblioteca import materiais_da_aula
from projetos.estudos.conceitos import caminho_conceito, gerar_paginas_conceito
from projetos.estudos.disciplinas import nome_do_baralho, perfil_de
from projetos.estudos.ementa import atualizar as atualizar_ementa
from projetos.estudos.etapas import fechar_dependencias
from projetos.estudos.flashcards import gera_csv_basico, gera_csv_cloze
from projetos.estudos.manifesto import ler_entrada_manifesto, registrar_nota_manifesto
from projetos.estudos.markdown_fmt import juntar_paragrafos
from projetos.estudos.moc import atualizar_apos_job
from projetos.estudos.nota import caminho_nota_final, caminho_stub
from projetos.estudos.recortes import gerar_crops
from projetos.estudos.schemas import (
    Bloco,
    Contexto,
    EntradaCompositor,
    EntradaContexto,
    EntradaFlashcards,
    EntradaImagem,
    Extracao,
    Flashcards,
    FonteEmenta,
    NotaComposta,
    Validacao,
)

PASSOS_AULA = ("ingestao",)
MAX_BLOCOS = 40


class GuardrailAcionado(Exception):
    def __init__(self, pergunta: str):
        self.pergunta = pergunta
        super().__init__(pergunta)


def _caminho_processado(disciplina: str, nome_final: str) -> Path:
    return get_settings().agent_data_dir / "estudos" / "processed" / disciplina / nome_final


def _caminho_output_ref(job_id: str, sha_curto: str, passo: str) -> Path:
    return get_settings().agent_data_dir / "passos" / job_id / f"{passo}_{sha_curto}.json"


def _persistir_output_ref(job_id: str, sha_curto: str, passo: str, saida) -> str:
    caminho = _caminho_output_ref(job_id, sha_curto, passo)
    escrever_texto(caminho, saida.model_dump_json(indent=2))
    return str(caminho)


def _persistir_json(job_id: str, sha_curto: str, passo: str, dados: dict) -> str:
    caminho = _caminho_output_ref(job_id, sha_curto, passo)
    escrever_texto(caminho, json.dumps(dados, indent=2))
    return str(caminho)


def _processar_foto(job_id: str, foto_row) -> tuple[Extracao, dict[int, str]]:
    sha_curto = foto_row["sha256"][:12]
    caminho_original = _caminho_processado(foto_row["disciplina"], foto_row["nome_final"])

    triagem = AgenteTriagem().run(
        job_id, EntradaImagem(caminho=str(caminho_original)), sufixo_passo=sha_curto
    )
    _persistir_output_ref(job_id, sha_curto, "triagem", triagem)

    if not triagem.contem_conteudo_academico:
        raise GuardrailAcionado(
            f"Foto {foto_row['nome_final']} não parece ter conteúdo acadêmico "
            "(categoria detectada: "
            f"{triagem.categoria}) — confirmar ou descartar do job?"
        )

    if triagem.qualidade != "boa":
        registrar_evento(
            job=job_id,
            passo="triagem",
            resultado="aviso_qualidade",
            aviso=f"{foto_row['nome_final']}: qualidade {triagem.qualidade}",
        )

    caminho_preparado = preparar(caminho_original, triagem.receita_preproc)

    extracao = AgenteExtrator().run(
        job_id, EntradaImagem(caminho=str(caminho_preparado)), sufixo_passo=sha_curto
    )
    _persistir_output_ref(job_id, sha_curto, "extracao", extracao)

    if len(extracao.blocos) > MAX_BLOCOS:
        raise GuardrailAcionado(
            f"Foto {foto_row['nome_final']} gerou {len(extracao.blocos)} blocos "
            f"(> {MAX_BLOCOS}) — imagem pode estar ruim ou mal enquadrada, revisar."
        )

    prefixo_nome = Path(foto_row["nome_final"]).stem
    mapa_crops = gerar_crops(extracao, caminho_preparado, foto_row["disciplina"], prefixo_nome)
    caminho_mapa = _persistir_json(job_id, sha_curto, "recortes", mapa_crops)
    registrar_passo(job_id, f"recortes:{sha_curto}", "ok", output_ref=caminho_mapa)

    return extracao, mapa_crops


def _consolidar_extracao_texto(extracoes: list[Extracao]) -> str:
    linhas = []
    for extracao in extracoes:
        for bloco in extracao.blocos:
            texto = bloco.latex if bloco.tipo == "formula" and bloco.latex else bloco.conteudo
            flags = f" [{', '.join(bloco.flags)}]" if bloco.flags else ""
            linhas.append(f"- ({bloco.tipo}) {texto}{flags}")
    return "\n".join(linhas) + "\n"


def blocos_com_flag(extracoes: list[Extracao], flag: str) -> list[Bloco]:
    """Blocos de todas as fotos do job que carregam uma flag específica.

    Usado por quem consome a extração fora da composição da nota: os blocos
    "administrativo" alimentam a ementa/MOC da disciplina e os "prova" alimentam
    tanto a seção de pontos de atenção quanto a agenda.
    """
    return [bloco for extracao in extracoes for bloco in extracao.blocos if flag in bloco.flags]


def texto_dos_blocos(blocos: list[Bloco]) -> str:
    """Mesma forma de linha de `_consolidar_extracao_texto`, para um subconjunto de blocos."""
    linhas = []
    for bloco in blocos:
        texto = bloco.latex if bloco.tipo == "formula" and bloco.latex else bloco.conteudo
        flags = f" [{', '.join(bloco.flags)}]" if bloco.flags else ""
        linhas.append(f"- ({bloco.tipo}) {texto}{flags}")
    return "\n".join(linhas) + "\n" if linhas else ""


def _consolidar_recortes(
    resultados_fotos: list[tuple[Extracao, dict[int, str]]],
) -> dict[str, str]:
    mapa: dict[str, str] = {}
    for extracao, crops in resultados_fotos:
        for indice, caminho in crops.items():
            bloco = extracao.blocos[indice]
            descricao = bloco.conteudo[:60] or f"bloco {indice}"
            mapa[descricao] = Path(caminho).name
    return mapa


def _notas_da_disciplina(disciplina: str, excluir: Path) -> list[Path]:
    pasta = get_settings().agent_data_dir / "estudos" / "output" / disciplina
    if not pasta.exists():
        return []
    return [arquivo for arquivo in listar(pasta, "*.md") if arquivo != excluir]


def _titulos_existentes(disciplina: str, excluir: Path) -> list[str]:
    titulos = []
    for arquivo in _notas_da_disciplina(disciplina, excluir):
        for linha in ler_texto(arquivo).splitlines():
            if linha.startswith("# "):
                titulos.append(linha[2:].strip())
                break
    return titulos


def _datas_das_notas(disciplina: str, excluir: Path, data_do_job: str) -> list[str]:
    """Datas das outras notas de aula da disciplina.

    Ignora as notas do MESMO dia: elas são deste job. Sem isso, uma segunda passada do
    compositor (ciclo de correção, ou reprocessamento) contaria a nota que o próprio job
    acabou de escrever — foi assim que a aula 1 da MAT1 virou "Aula 03" e "Aula 04" ao
    mesmo tempo.
    """
    datas = []
    for arquivo in _notas_da_disciplina(disciplina, excluir):
        data = None
        for linha in ler_texto(arquivo).splitlines():
            if linha.startswith("data:"):
                data = linha.partition(":")[2].strip()
            elif linha.startswith("#"):
                break
        if data and data != data_do_job:
            datas.append(data)
    return datas


def _numero_pela_ordem_cronologica(disciplina: str, excluir: Path, data_do_job: str) -> int:
    """Posição desta data na sequência de aulas da disciplina.

    Substituiu um "maior número usado + 1", que embutia a suposição de que o job em
    composição é sempre o mais recente. É verdade quando as aulas são processadas em
    ordem, e falso ao **reprocessar uma aula antiga**: com a aula 02 já no disco, a aula
    de 10/08 foi renumerada como 3 — depois da aula 2, sendo dois dias anterior a ela.
    """
    datas = sorted(set(_datas_das_notas(disciplina, excluir, data_do_job)))
    anteriores = sum(1 for data in datas if data < data_do_job)
    return anteriores + 1


def _rodar_contexto(job_id: str, job, extracoes: list[Extracao]) -> tuple[Contexto, str | None]:
    caminho_nota = caminho_stub(job["data"], job["disciplina"])
    titulos = _titulos_existentes(job["disciplina"], excluir=caminho_nota)

    entrada = EntradaContexto(
        disciplina=job["disciplina"],
        perfil=perfil_de(job["disciplina"]),
        extracao_consolidada=_consolidar_extracao_texto(extracoes),
        titulos_existentes=titulos,
    )
    contexto = AgenteContexto().run(job_id, entrada)
    _persistir_output_ref(job_id, "job", "contexto", contexto)

    esperado = _numero_pela_ordem_cronologica(
        job["disciplina"], excluir=caminho_nota, data_do_job=job["data"]
    )
    aviso = None
    if contexto.aula_numero is not None and contexto.aula_numero != esperado:
        aviso = (
            f"aula_numero sugerido pelo A4 ({contexto.aula_numero}) diverge da sequência "
            f"esperada ({esperado}) para {job['disciplina']} — revisar antes de compor a nota."
        )
    return contexto, aviso


def _numero_escrito_no_material(numero: int, texto: str) -> bool:
    """ "Aula 5", "aula05", "PNL_aula05" escrito na lousa, no slide ou no caderno."""
    return re.search(rf"aula[\s_-]*0*{numero}(?!\d)", texto, re.IGNORECASE) is not None


def resolver_aula_numero(
    job_id: str, job, contexto: Contexto, extracoes: list[Extracao] | None = None
) -> int:
    """Número da aula deste job, resolvido UMA vez.

    Recalcular a cada chamada do compositor fazia o número mudar entre a primeira
    tentativa e a correção, gerando dois arquivos para a mesma aula.

    O número sugerido pelo agente de contexto só vence a ordem cronológica quando está
    **escrito** no material ("Aula 5" na lousa, `aula05` no slide). Em FIS1, o Haiku
    propôs "Aula 9" para 25/08 e "Aula 4" para 27/08 — nenhuma das duas escrita em lugar
    nenhum —, duplicando a Aula 04 de 20/08. O aviso de divergência já existia; ele só não
    impedia o número errado de virar nome de arquivo.
    """
    # Reprocessar não pode renumerar: o número já decidido para este job é um fato, e
    # trocá-lo renomeia a nota, quebra os links do MOC e desliga o material vinculado.
    ja_decidido = job["numero_aula"] if "numero_aula" in job.keys() else None
    if ja_decidido:
        return int(ja_decidido)

    numero = _numero_pela_ordem_cronologica(
        job["disciplina"],
        excluir=caminho_stub(job["data"], job["disciplina"]),
        data_do_job=job["data"],
    )
    sugerido = contexto.aula_numero
    if sugerido is not None and sugerido != numero:
        texto = _consolidar_extracao_texto(extracoes or [])
        if _numero_escrito_no_material(sugerido, texto):
            registrar_evento(
                job=job_id,
                passo="compositor",
                resultado="aula_numero_do_material",
                aviso=f"{job['disciplina']} {job['data']}: {sugerido} escrito no material "
                f"(a sequência daria {numero})",
            )
            return sugerido
        registrar_evento(
            job=job_id,
            passo="compositor",
            resultado="aula_numero_sugerido_descartado",
            aviso=f"{job['disciplina']} {job['data']}: sugerido {sugerido} não aparece no "
            f"material; usada a sequência, {numero}",
        )
        return numero
    if sugerido is not None:
        return sugerido
    registrar_evento(
        job=job_id,
        passo="compositor",
        resultado="aula_numero_inferido_pela_sequencia",
        aviso=f"{job['disciplina']} {job['data']}: assumido {numero}",
    )
    return numero


def _rodar_compositor(
    job_id: str,
    job,
    extracoes: list[Extracao],
    contexto: Contexto,
    mapa_recortes: dict[str, str],
    aula_numero: int,
    problemas_anteriores: list[str] | None = None,
    caminho_anterior: Path | None = None,
) -> tuple[NotaComposta, Path]:
    # do_livro sobrevive a reprocessamento: se um "preencher-lacunas" anterior já resolveu
    # a seção do livro, ela é lida de volta do manifesto em vez de nascer vazia de novo.
    entrada_anterior = ler_entrada_manifesto(job_id) or {}

    # o número resolvido é do job, não só da nota: é o que liga material a aula
    registrar_numero_aula(job_id, aula_numero)

    entrada = EntradaCompositor(
        disciplina=job["disciplina"],
        data=job["data"],
        aula_numero=aula_numero,
        titulo_sugerido=contexto.titulo_sugerido,
        topicos=contexto.topicos,
        tags=contexto.tags,
        perfil=perfil_de(job["disciplina"]),
        extracao_consolidada=_consolidar_extracao_texto(extracoes),
        mapa_recortes=mapa_recortes,
        do_livro=entrada_anterior.get("secao_do_livro", ""),
        materiais_da_aula=materiais_da_aula(job["disciplina"], job["data"]),
        problemas_anteriores=problemas_anteriores or [],
    )
    nota = AgenteCompositor().run(job_id, entrada)
    # O modelo imita a quebra de linha do template. Desfazer aqui, em código, é a mesma
    # escolha de `fontes.py`: um prompt pode pedir e ser ignorado; um passo não.
    nota = nota.model_copy(update={"markdown": juntar_paragrafos(nota.markdown)})
    _persistir_output_ref(job_id, "job", "compositor", nota)

    caminho_final = caminho_nota_final(
        job["data"], job["disciplina"], aula_numero, contexto.titulo_sugerido
    )
    escrever_texto(caminho_final, nota.markdown)

    caminho_antigo_stub = caminho_stub(job["data"], job["disciplina"])
    if caminho_antigo_stub != caminho_final:
        remover(caminho_antigo_stub)

    # Reprocessar costuma mudar o título sugerido, e o nome do arquivo vem do título:
    # sem remover a versão anterior, a mesma aula fica com duas notas no staging e o
    # índice do MOC passa a listar as duas. Vale tanto para a nota da execução passada
    # (manifesto) quanto para a da tentativa anterior DESTA execução (ciclo de correção).
    for candidato in (entrada_anterior.get("caminho_nota"), caminho_anterior):
        anterior = Path(candidato) if candidato else None
        if anterior is None or anterior == caminho_final:
            continue
        remover(anterior)
        registrar_evento(
            job=job_id,
            passo="compositor",
            resultado="nota_anterior_substituida",
            aviso=f"{anterior.name} → {caminho_final.name}",
        )

    return nota, caminho_final


def _validar_e_corrigir(
    job_id: str,
    job,
    extracoes: list[Extracao],
    contexto: Contexto,
    mapa_recortes: dict[str, str],
    nota: NotaComposta,
    caminho_nota: Path,
    aula_numero: int,
) -> tuple[NotaComposta, Path, Validacao]:
    pasta_crops = get_settings().agent_data_dir / "estudos" / "crops" / job["disciplina"]

    perfil = perfil_de(job["disciplina"])
    validacao = validar_completo(
        job_id,
        nota.markdown,
        job["disciplina"],
        job["data"],
        pasta_crops,
        perfil=perfil,
    )
    _persistir_output_ref(job_id, "job", "validacao", validacao)
    if validacao.aprovado:
        return nota, caminho_nota, validacao

    # Reprovado: volta ao A5 UMA vez com os problemas anexados, revalida. Nunca trava
    # silenciosamente e nunca descarta o trabalho — mesmo se reprovar de novo, o resultado
    # da segunda tentativa (o melhor que conseguimos) vai pro staging mesmo assim.
    problemas_texto = [
        f"{p.onde}: {p.descricao} (sugestão: {p.sugestao})" for p in validacao.problemas
    ]
    nota, caminho_nota = _rodar_compositor(
        job_id,
        job,
        extracoes,
        contexto,
        mapa_recortes,
        aula_numero,
        problemas_anteriores=problemas_texto,
        caminho_anterior=caminho_nota,
    )
    validacao = validar_completo(
        job_id,
        nota.markdown,
        job["disciplina"],
        job["data"],
        pasta_crops,
        perfil=perfil,
    )
    _persistir_output_ref(job_id, "job", "validacao_2", validacao)

    return nota, caminho_nota, validacao


def _caminho_flashcards(disciplina: str, data: str, tipo: str) -> Path:
    return (
        get_settings().agent_data_dir / "estudos" / "flashcards" / disciplina / f"{data}_{tipo}.csv"
    )


def _rodar_flashcards(job_id: str, job, nota: NotaComposta) -> Flashcards:
    entrada = EntradaFlashcards(
        disciplina=job["disciplina"],
        markdown=nota.markdown,
        duvidas_brutas=nota.duvidas,
        perfil=perfil_de(job["disciplina"]),
    )
    flashcards = AgenteFlashcards().run(job_id, entrada)
    _persistir_output_ref(job_id, "job", "flashcards", flashcards)

    disciplina, data = job["disciplina"], job["data"]
    cards_basico = [card for card in flashcards.cards if card.tipo == "basico"]
    cards_cloze = [card for card in flashcards.cards if card.tipo == "cloze"]
    baralho = nome_do_baralho(disciplina)

    # Só grava o arquivo do tipo que teve pelo menos 1 card — e sempre reescreve (nunca
    # apensa), então reprocessar não duplica nem deixa lixo de uma rodada anterior parado.
    if cards_basico:
        escrever_texto(
            _caminho_flashcards(disciplina, data, "basico"),
            gera_csv_basico(cards_basico, disciplina, data, baralho),
        )
    if cards_cloze:
        escrever_texto(
            _caminho_flashcards(disciplina, data, "cloze"),
            gera_csv_cloze(cards_cloze, disciplina, data, baralho),
        )

    return flashcards


def _rodar_conceitos(job_id: str, job, nota: NotaComposta, caminho_nota: Path) -> list[str]:
    avisos = gerar_paginas_conceito(
        job_id,
        job["disciplina"],
        nota.conceitos_novos,
        nota.markdown,
        caminho_nota.stem,
    )

    for nome_conceito in nota.conceitos_novos:
        caminho = caminho_conceito(job["disciplina"], nome_conceito)
        if not caminho.exists():
            continue  # acima do teto de gerar_paginas_conceito — não foi criado, nada a validar
        validacao = validar_conceito_completo(job_id, ler_texto(caminho), job["disciplina"])
        _persistir_output_ref(job_id, "job", f"validacao_conceito_{nome_conceito}", validacao)
        if not validacao.aprovado:
            avisos.append(f"conceito '{nome_conceito}': validação encontrou problemas")

    return avisos


def _rodar_administrativo(job_id: str, job, extracoes: list[Extracao]) -> None:
    """Encaminha o que é da disciplina (e não da aula) para a ementa e para a agenda.

    Falhar aqui não pode derrubar o job: a nota da aula já está pronta e validada.
    Um erro na ementa ou na extração de datas vira aviso no log, não job falhado.
    """
    administrativos = blocos_com_flag(extracoes, "administrativo")
    de_prova = blocos_com_flag(extracoes, "prova")
    if not administrativos and not de_prova:
        return

    disciplina = job["disciplina"]
    data = job["data"]
    nome_fonte = f"manuscrito da aula de {data}"

    try:
        if administrativos:
            atualizar_ementa(
                job_id,
                disciplina,
                [
                    FonteEmenta(
                        nome=nome_fonte,
                        tipo="manuscrito",
                        texto=texto_dos_blocos(administrativos),
                    )
                ],
            )
    except Exception as erro:
        registrar_evento(job=job_id, passo="ementa", resultado="falhou", aviso=str(erro))

    try:
        # Blocos de prova entram junto: "AP1 31/08" costuma ser os dois ao mesmo tempo,
        # e um aviso de prova sem flag administrativa também é compromisso.
        vistos = {id(bloco) for bloco in administrativos}
        fonte = administrativos + [bloco for bloco in de_prova if id(bloco) not in vistos]
        extrair_compromissos(job_id, disciplina, data, texto_dos_blocos(fonte))
    except Exception as erro:
        registrar_evento(job=job_id, passo="compromissos", resultado="falhou", aviso=str(erro))


def _tem_bloco_suspeito(extracoes: list[Extracao]) -> bool:
    return any(
        "possivel_injecao" in bloco.flags for extracao in extracoes for bloco in extracao.blocos
    )


#: marca que torna a anotação idempotente: reprocessar não duplica o bloco
MARCA_ORIGEM_DAS_DATAS = "[!info]- De que dia são as fotos"

_EXPLICACAO_DA_FONTE = {
    "escrita": "fotografada fora do dia da aula; a data foi lida na própria folha",
    "escrita_reconciliada": (
        "a data escrita na folha não era dia de aula; a foto foi atribuída a esta aula, o "
        "dia de aula vizinho com fotos da lousa"
    ),
    "pasta": "a data veio da pasta `AAAA-MM-DD/` em que a foto foi deixada no inbox",
}


def anotar_origem_das_datas(caminho_nota: Path, fotos) -> bool:
    """Diz na nota quando a data de alguma foto não veio do EXIF. Devolve se escreveu.

    A decisão é tomada na ingestão (`datacao.py`), mas quem precisa saber é quem lê a nota:
    uma folha datada 02/09 que aparece na aula de 03/09 sem explicação parece erro.
    """
    linhas = [
        f"> - `{foto['nome_final']}`: {_EXPLICACAO_DA_FONTE[foto['data_fonte']]}"
        for foto in fotos
        if "data_fonte" in foto.keys() and foto["data_fonte"] in _EXPLICACAO_DA_FONTE
    ]
    if not linhas or not caminho_nota.exists():
        return False
    atual = ler_texto(caminho_nota)
    if MARCA_ORIGEM_DAS_DATAS in atual:
        return False
    bloco = "\n".join([f"> {MARCA_ORIGEM_DAS_DATAS}", ">", *linhas])
    escrever_texto(caminho_nota, atual.rstrip() + "\n\n" + bloco + "\n")
    return True


def _concluir_job(
    job_id: str,
    job,
    caminho_nota: Path,
    nota: NotaComposta,
    extracoes: list[Extracao],
    duvidas: list[str],
    aviso: str | None = None,
    precisa_revisao: bool = False,
    problemas_validacao: list[str] | None = None,
    avisos_conceitos: list[str] | None = None,
) -> None:
    fotos_atuais = [foto["nome_final"] for foto in fotos_do_job(job_id)]
    entrada_anterior = ler_entrada_manifesto(job_id) or {}
    registrar_nota_manifesto(
        job_id,
        caminho_nota,
        "concluido",
        fotos_atuais,
        job["criado_em"],
        pergunta=aviso,
        conceitos_novos=nota.conceitos_novos,
        duvidas=duvidas,
        precisa_revisao=precisa_revisao,
        problemas_validacao=problemas_validacao,
        avisos_conceitos=avisos_conceitos,
        possivel_injecao=_tem_bloco_suspeito(extracoes),
        secao_do_livro=entrada_anterior.get("secao_do_livro"),
    )
    limpar_reprocessamento(job_id)


def _pausar_job(job_id: str, job, pergunta: str) -> None:
    transicionar(job_id, "aguardando_humano")
    registrar_aviso_job(job_id, pergunta)
    fotos_atuais = [foto["nome_final"] for foto in fotos_do_job(job_id)]
    registrar_nota_manifesto(
        job_id,
        caminho_stub(job["data"], job["disciplina"]),
        "aguardando_humano",
        fotos_atuais,
        job["criado_em"],
        pergunta=pergunta,
    )


def _rodar_job_de_ementa(job_id: str, job) -> None:
    """Só extrai e encaminha para ementa/agenda — nenhuma nota de aula é escrita.

    A foto aqui é de um documento da disciplina (plano de ensino, quadro de datas). Ela
    não descreve um dia de aula, então passar pelo compositor produziria uma nota sobre
    um documento administrativo.
    """
    extracoes = [
        extracao for extracao, _ in (_processar_foto(job_id, foto) for foto in fotos_do_job(job_id))
    ]
    blocos = [bloco for extracao in extracoes for bloco in extracao.blocos]
    disciplina, data = job["disciplina"], job["data"]

    atualizar_ementa(
        job_id,
        disciplina,
        [
            FonteEmenta(
                nome=f"documento da disciplina fotografado em {data}",
                tipo="manuscrito",
                texto=texto_dos_blocos(blocos),
            )
        ],
    )
    # Compromissos nascem propostos: nada entra no calendário sem você confirmar.
    extrair_compromissos(job_id, disciplina, data, texto_dos_blocos(blocos))
    atualizar_apos_job(disciplina)


def drenar_fila(
    flashcards: bool = True,
    etapas: list[str] | None = None,
    somente_job: str | None = None,
) -> dict:
    """Processa todos os jobs na fila.

    `etapas=None` roda a cadeia inteira, como sempre. Com uma lista, roda só essas etapas
    e as dependências delas (ver `etapas.py`). Sem `nota`, o job para depois da leitura e
    fica `parcial`: o que já foi lido está no cache, então retomar com
    `reprocessar --com-cache` não paga a leitura de novo. `somente_job` restringe a
    execução a um job, o que a interface usa; a fila dos outros não é tocada.

    `flashcards=False` pula o agente de flashcards e conclui o job com as dúvidas que o
    compositor já levantou. Perde-se só a consolidação que aquele agente fazia (dedup e
    fusão das dúvidas), não as dúvidas: elas são o que a nota tem de mais útil para
    revisar, e sumir com elas para economizar um card seria trocar o importante pelo
    acessório. Os cards saem depois com `estudos reprocessar <job> --passo flashcards`.
    """
    processados = 0
    falhados = 0
    pausados = 0
    parciais = 0

    ativas = None if etapas is None else fechar_dependencias(list(etapas))
    fazer_flashcards = flashcards and (ativas is None or "flashcards" in ativas)
    ignorados: set[str] = set()

    def _pedida(nome: str) -> bool:
        return ativas is None or nome in ativas

    while (job := proximo_da_fila(somente_job, frozenset(ignorados))) is not None:
        job_id = job["id"]
        if job["tipo"] == "ementa" and not _pedida("disciplina"):
            ignorados.add(job_id)  # fica na fila para uma execução que peça a etapa
            continue
        transicionar(job_id, "rodando")

        if job["tipo"] == "ementa":
            try:
                _rodar_job_de_ementa(job_id, job)
            except Exception as erro:
                registrar_evento(passo="runner", resultado="falhou", aviso=f"{job_id}: {erro}")
                transicionar(job_id, "falhou")
                falhados += 1
                continue
            transicionar(job_id, "concluido")
            processados += 1
            continue

        try:
            for nome in PASSOS_AULA:
                registrar_passo(job_id, nome, "ok")

            resultados_fotos = [
                _processar_foto(job_id, foto_row) for foto_row in fotos_do_job(job_id)
            ]
            extracoes = [extracao for extracao, _ in resultados_fotos]
            mapa_recortes = _consolidar_recortes(resultados_fotos)

            if not _pedida("nota"):
                registrar_etapas_feitas(job_id, ["leitura"])
                registrar_evento(job=job_id, passo="runner", resultado="parcial")
                transicionar(job_id, "parcial")
                parciais += 1
                continue

            contexto, aviso_contexto = _rodar_contexto(job_id, job, extracoes)
            aula_numero = resolver_aula_numero(job_id, job, contexto, extracoes)
            nota, caminho_nota = _rodar_compositor(
                job_id, job, extracoes, contexto, mapa_recortes, aula_numero
            )
            nota, caminho_nota, validacao = _validar_e_corrigir(
                job_id,
                job,
                extracoes,
                contexto,
                mapa_recortes,
                nota,
                caminho_nota,
                aula_numero,
            )
            if fazer_flashcards:
                duvidas = _rodar_flashcards(job_id, job, nota).duvidas
            else:
                duvidas = nota.duvidas
                registrar_evento(job=job_id, passo="flashcards", resultado="flashcards_adiados")
            avisos_conceitos = (
                _rodar_conceitos(job_id, job, nota, caminho_nota) if _pedida("conceitos") else []
            )
            if _pedida("disciplina"):
                _rodar_administrativo(job_id, job, extracoes)
        except GuardrailAcionado as guardrail:
            _pausar_job(job_id, job, guardrail.pergunta)
            pausados += 1
            continue
        except Exception as erro:
            registrar_evento(passo="runner", resultado="falhou", aviso=f"{job_id}: {erro}")
            transicionar(job_id, "falhou")
            falhados += 1
            continue

        transicionar(job_id, "concluido")
        registrar_etapas_feitas(job_id, None if ativas is None else ativas)
        anotar_origem_das_datas(caminho_nota, fotos_do_job(job_id))
        problemas_texto = (
            [f"{p.onde}: {p.descricao}" for p in validacao.problemas]
            if not validacao.aprovado
            else None
        )
        _concluir_job(
            job_id,
            job,
            caminho_nota,
            nota,
            extracoes,
            duvidas=duvidas,
            aviso=aviso_contexto,
            precisa_revisao=not validacao.aprovado,
            problemas_validacao=problemas_texto,
            avisos_conceitos=avisos_conceitos,
        )
        # o MOC é derivado: mantê-lo em dia é barato (nenhuma chamada de modelo) e
        # evita que o índice de aulas fique defasado. Falhar aqui não pode custar o
        # job — a nota já está escrita e validada.
        try:
            atualizar_apos_job(job["disciplina"])
        except Exception as erro:  # noqa: BLE001
            registrar_evento(job=job_id, passo="moc", resultado="falhou", aviso=str(erro))
        processados += 1

    resultado = {
        "processados": processados,
        "falhados": falhados,
        "pausados": pausados,
    }
    if ativas is not None:
        resultado["parciais"] = parciais
    return resultado


def aprovar_job(id_ou_prefixo: str) -> str:
    job = job_por_prefixo_id(id_ou_prefixo)
    if job is None:
        raise ValueError(f"job não encontrado: {id_ou_prefixo}")
    if job["status"] != "aguardando_humano":
        raise ValueError(
            f"job {job['id'][:8]} não está aguardando_humano (status atual: {job['status']})"
        )

    enfileirar(job["id"])
    registrar_aviso_job(job["id"], None)
    return job["id"]


def reprocessar_job(id_ou_prefixo: str, passo: str | None = None, com_cache: bool = False) -> str:
    job = job_por_prefixo_id(id_ou_prefixo)
    if job is None:
        raise ValueError(f"job não encontrado: {id_ou_prefixo}")

    status = job["status"]
    if status == "aguardando_humano":
        raise ValueError(
            f"job {job['id'][:8]} está aguardando_humano — use 'estudos aprovar' para resolver."
        )
    if status == "parcial" and not com_cache:
        raise ValueError(
            f"job {job['id'][:8]} parou de propósito antes da nota. Para retomar, use "
            "'estudos reprocessar <job> --com-cache' e depois 'estudos processar'."
        )
    if status not in ("concluido", "falhou", "parcial"):
        raise ValueError(
            f"job {job['id'][:8]} não pode ser reprocessado agora (status atual: {status})"
        )

    if com_cache and passo:
        raise ValueError(
            "Use --passo para refazer um agente, ou --com-cache para refazer a nota "
            "aproveitando tudo. Os dois juntos não fazem sentido."
        )

    transicionar(job["id"], "na_fila")
    if com_cache:
        # volta para a fila sem marca: o próximo processar reaproveita o cache de cada agente
        limpar_reprocessamento(job["id"])
    else:
        marcar_reprocessamento(job["id"], passo)
    return job["id"]


def promover_job(id_ou_prefixo: str, nota_qualidade: int) -> str:
    # Chamado via SSH pelo promotor (máquina do vault) logo após a cópia da nota pro vault ter dado
    # certo do lado de lá — este passo só arquiva a cópia local em promovidas/ (fonte do
    # índice `notas`) e registra o estado; nunca escreve no vault (isso é sempre máquina do vault).
    job = job_por_prefixo_id(id_ou_prefixo)
    if job is None:
        raise ValueError(f"job não encontrado: {id_ou_prefixo}")
    if job["status"] != "concluido":
        raise ValueError(
            f"job {job['id'][:8]} não está concluido (status atual: {job['status']}) — não promovido"
        )

    entrada = ler_entrada_manifesto(job["id"])
    if entrada is None:
        raise ValueError(f"job {job['id'][:8]} não tem entrada no manifesto de staging")

    output_dir = get_settings().agent_data_dir / "estudos" / "output"
    promovidas_dir = get_settings().agent_data_dir / "estudos" / "promovidas"
    caminho_nota = Path(entrada["caminho_nota"])
    destino = promovidas_dir / caminho_nota.relative_to(output_dir)
    mover(caminho_nota, destino)

    marcar_promovido(job["id"], nota_qualidade)
    return job["id"]
