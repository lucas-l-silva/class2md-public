import hashlib
import re
from pathlib import Path

from core.config import get_settings
from core.estado import (
    limpar_reprocessamento,
    marcar_pdf_indexado,
    marcar_reprocessamento,
    referencias_da_aula,
)
from core.fileops import escrever_texto, ler_texto
from core.llm.client import envelopar_dados
from core.logging import registrar_evento
from core.pdf import texto_paginas, toc_nativo
from projetos.estudos.agentes import (
    AgenteBibliotecario,
    AgenteIndexadorLivro,
    AgenteSeletorCapitulos,
)
from projetos.estudos.fontes import FonteOrdenada, prioridade_do_registro
from projetos.estudos.pdf_ingestao import (
    RegistroPdf,
    registros_por_disciplina,
    texto_direto,
)
from projetos.estudos.programa import (
    carregar as carregar_programa,
)
from projetos.estudos.programa import (
    tokens_de_assunto,
)
from projetos.estudos.schemas import (
    CapituloIndice,
    EntradaBibliotecario,
    EntradaIndexadorLivro,
    EntradaSeletorCapitulos,
    IndiceLivro,
    SaidaBibliotecario,
    TrechoFonte,
)

TAMANHO_JANELA_FALLBACK = 30
PAGINAS_INICIAIS_PARA_SUMARIO = 12
MAX_CAPITULOS_POR_RODADA = 3
#: seções são recortes menores; cabem mais de uma vez o número de capítulos
MAX_SECOES_POR_RODADA = 4
#: abaixo disso o recorte por seção não compensa e o capítulo inteiro é mantido
MINIMO_SECOES_PARA_RECORTAR = 3
LIMITE_CHARS_MATERIAIS = 40_000


class LivroNaoEncontrado(Exception):
    pass


def livro_da_disciplina(disciplina: str, nome_arquivo: str | None = None) -> RegistroPdf:
    livros = registros_por_disciplina(disciplina, tipo="livro")

    if nome_arquivo:
        for livro in livros:
            if livro.nome_arquivo == nome_arquivo:
                return livro
        raise LivroNaoEncontrado(f"livro '{nome_arquivo}' não encontrado para '{disciplina}'")

    if not livros:
        raise LivroNaoEncontrado(
            f"nenhum livro registrado para '{disciplina}' — adicione um PDF em "
            f"estudos/pdfs/{disciplina}/ e rode 'estudos processar' ou 'indexar-pdf'"
        )
    if len(livros) > 1:
        nomes = ", ".join(livro.nome_arquivo for livro in livros)
        raise LivroNaoEncontrado(
            f"'{disciplina}' tem mais de um livro registrado ({nomes}) — use --livro para escolher"
        )
    return livros[0]


def _caminho_cache_pdf(sha256: str) -> Path:
    return get_settings().cache_dir / "pdf" / sha256


def _caminho_cache_indice(sha256: str) -> Path:
    return _caminho_cache_pdf(sha256) / "indice.json"


def _capitulos_validos(capitulos: list[CapituloIndice], total_paginas: int) -> bool:
    if not capitulos:
        return False
    anterior = 0
    for capitulo in capitulos:
        if not (1 <= capitulo.pagina_inicio <= total_paginas):
            return False
        if capitulo.pagina_inicio <= anterior:
            return False  # deve ser estritamente crescente
        anterior = capitulo.pagina_inicio
    return True


def _indice_fallback(registro: RegistroPdf) -> IndiceLivro:
    capitulos = [
        CapituloIndice(
            numero=i // TAMANHO_JANELA_FALLBACK + 1,
            titulo=f"Páginas {i}-{min(i + TAMANHO_JANELA_FALLBACK - 1, registro.paginas)}",
            pagina_inicio=i,
        )
        for i in range(1, registro.paginas + 1, TAMANHO_JANELA_FALLBACK)
    ]
    return IndiceLivro(
        titulo_livro=registro.nome_arquivo,
        autor="",
        capitulos=capitulos,
        fonte_indice="fallback_paginas",
        confianca=0.5,
    )


def _montar_entrada(registro: RegistroPdf) -> tuple[EntradaIndexadorLivro, str]:
    caminho = Path(registro.caminho)
    toc = toc_nativo(caminho) if registro.tem_texto_nativo else []
    toc_bruto = "\n".join(
        f"{'  ' * entrada.nivel}{entrada.titulo} — p.{entrada.pagina_inicio}" for entrada in toc
    )

    if toc_bruto:
        return (
            EntradaIndexadorLivro(
                nome_arquivo=registro.nome_arquivo,
                total_paginas=registro.paginas,
                toc_bruto=toc_bruto,
                texto_paginas_iniciais="",
            ),
            "toc_nativo",
        )

    limite = min(PAGINAS_INICIAIS_PARA_SUMARIO, registro.paginas)
    texto_iniciais = "\n".join(texto_paginas(caminho, 1, limite))
    return (
        EntradaIndexadorLivro(
            nome_arquivo=registro.nome_arquivo,
            total_paginas=registro.paginas,
            toc_bruto="",
            texto_paginas_iniciais=texto_iniciais,
        ),
        "paginas_iniciais",
    )


def indice_do_livro(job_id: str, registro: RegistroPdf, force: bool = False) -> IndiceLivro:
    cache_path = _caminho_cache_indice(registro.sha256)
    if not force:
        try:
            return IndiceLivro.model_validate_json(ler_texto(cache_path))
        except FileNotFoundError:
            pass

    entrada, fonte_esperada = _montar_entrada(registro)
    if force:
        # force também precisa furar o cache do próprio Agente (chaveado por entrada, não
        # por job_id) — sem isso, reextrair com --force ainda devolveria o resultado antigo.
        marcar_reprocessamento(job_id, AgenteIndexadorLivro.nome)
    try:
        indice = AgenteIndexadorLivro().run(job_id, entrada)
    finally:
        if force:
            limpar_reprocessamento(job_id)

    if indice.fonte_indice != fonte_esperada and indice.capitulos:
        indice = indice.model_copy(update={"fonte_indice": fonte_esperada})

    if not _capitulos_validos(indice.capitulos, registro.paginas):
        registrar_evento(
            job=job_id,
            passo="indexador_livro",
            resultado="fallback_paginas",
            aviso=(
                f"{registro.nome_arquivo}: índice do modelo inválido ou vazio "
                f"(páginas fora do range ou não crescentes) — caindo para janelas fixas"
            ),
        )
        indice = _indice_fallback(registro)

    escrever_texto(cache_path, indice.model_dump_json())
    marcar_pdf_indexado(registro.sha256)
    return indice


def _indice_resumido(indice: IndiceLivro) -> str:
    linhas = []
    for capitulo in indice.capitulos:
        fim = f"-{capitulo.pagina_fim}" if capitulo.pagina_fim else "-fim"
        linhas.append(f"{capitulo.numero} — {capitulo.titulo} (p. {capitulo.pagina_inicio}{fim})")
    return "\n".join(linhas)


def resolver_capitulos(
    job_id: str,
    indice: IndiceLivro,
    disciplina: str,
    titulo_nota: str,
    topicos: list[str],
    lacunas: list[str],
    override: list[int] | None = None,
    maximo: int = MAX_CAPITULOS_POR_RODADA,
) -> tuple[list[int], str]:
    numeros_validos = {capitulo.numero for capitulo in indice.capitulos}

    if override:
        invalidos = [numero for numero in override if numero not in numeros_validos]
        if invalidos:
            raise ValueError(
                f"capítulo(s) inválido(s): {invalidos} — "
                f"capítulos disponíveis: {sorted(numeros_validos)}"
            )
        # override é sempre exato — nunca chama LLM, nunca tenta capítulo vizinho.
        return list(override), "manual"

    entrada = EntradaSeletorCapitulos(
        disciplina=disciplina,
        titulo_nota=titulo_nota,
        topicos=topicos,
        lacunas=lacunas,
        indice_resumido=_indice_resumido(indice),
    )
    sugestao = AgenteSeletorCapitulos().run(job_id, entrada)

    # filtro determinístico em código: números que o modelo pode ter inventado não sobrevivem.
    capitulos = [numero for numero in sugestao.capitulos if numero in numeros_validos]
    return capitulos[:maximo], "sugerido"


def _sha_indice(indice: IndiceLivro) -> str:
    return hashlib.sha256(indice.model_dump_json().encode()).hexdigest()[:12]


def _pagina_fim_capitulo(indice: IndiceLivro, numero: int, total_paginas: int) -> int:
    ordenados = sorted(indice.capitulos, key=lambda c: c.pagina_inicio)
    for posicao, capitulo in enumerate(ordenados):
        if capitulo.numero != numero:
            continue
        if capitulo.pagina_fim is not None:
            return capitulo.pagina_fim
        if posicao + 1 < len(ordenados):
            return ordenados[posicao + 1].pagina_inicio - 1
        return total_paginas
    raise ValueError(f"capítulo {numero} não encontrado no índice")


def trechos_dos_capitulos(
    registro: RegistroPdf, indice: IndiceLivro, numeros: list[int]
) -> list[TrechoFonte]:
    # Chaveado por hash do índice (não só do PDF): reindexar com faixas de página diferentes
    # gera uma pasta de cache nova em vez de servir texto do capítulo com o recorte antigo.
    sha_idx = _sha_indice(indice)
    mapa_capitulos = {capitulo.numero: capitulo for capitulo in indice.capitulos}

    trechos = []
    for numero in numeros:
        capitulo = mapa_capitulos.get(numero)
        if capitulo is None:
            raise ValueError(f"capítulo {numero} não encontrado no índice")
        pagina_fim = _pagina_fim_capitulo(indice, numero, registro.paginas)

        caminho_cache = (
            _caminho_cache_pdf(registro.sha256) / "capitulos" / sha_idx / f"{numero:03d}.txt"
        )
        try:
            texto = ler_texto(caminho_cache)
        except FileNotFoundError:
            paginas = texto_paginas(Path(registro.caminho), capitulo.pagina_inicio, pagina_fim)
            texto = "\n".join(paginas)
            escrever_texto(caminho_cache, texto)

        trechos.append(
            TrechoFonte(
                arquivo=registro.nome_arquivo,
                tipo="livro",
                capitulo=f"{capitulo.numero} — {capitulo.titulo}",
                pagina_inicio=capitulo.pagina_inicio,
                pagina_fim=pagina_fim,
                texto=texto,
            )
        )
    return trechos


def consultar(
    job_id: str,
    disciplina: str,
    titulo_nota: str,
    markdown: str,
    lacunas: list[str],
    trechos: list[TrechoFonte],
) -> SaidaBibliotecario:
    entrada = EntradaBibliotecario(
        disciplina=disciplina,
        titulo_nota=titulo_nota,
        markdown_nota=markdown,
        lacunas=lacunas,
        trechos=trechos,
    )
    return AgenteBibliotecario().run(job_id, entrada)


def materiais_da_aula(disciplina: str, data: str) -> str:
    """PDFs pequenos (modo 'direto': ementa, lista de exercícios, notas de aula, slides
    curtos) cuja data_aula casa com a aula — entram automaticamente na composição, já
    envelopados como dado. Vazio se nenhum PDF foi registrado com essa data."""
    registros = [
        registro
        for registro in registros_por_disciplina(disciplina)
        if registro.modo == "direto" and registro.data_aula == data
    ]
    if not registros:
        return ""

    partes = []
    total = 0
    truncado = False
    for registro in registros:
        texto = texto_direto(registro)
        se_coubesse = total + len(texto)
        if se_coubesse > LIMITE_CHARS_MATERIAIS:
            texto = texto[: max(0, LIMITE_CHARS_MATERIAIS - total)]
            truncado = True
        total += len(texto)
        partes.append(envelopar_dados(texto, f"{registro.nome_arquivo} ({registro.tipo})"))
        if truncado:
            break

    if truncado:
        registrar_evento(
            passo="materiais_da_aula",
            resultado="truncado",
            aviso=f"{disciplina}/{data}: limite de {LIMITE_CHARS_MATERIAIS} chars atingido",
        )

    return "\n\n".join(partes)


_TIPO_PDF_PARA_TRECHO = {
    "livro": "livro",
    "aula": "aula",
    "slides": "slides",
    "exercicios": "exercicios",
    "prova": "prova",
    "ementa": "ementa",
}


def trecho_de_pdf(registro: RegistroPdf) -> TrechoFonte | None:
    """Um PDF inteiro como trecho de fonte. None quando não há texto utilizável.

    Serve para material pequeno (`modo="direto"`), incluindo o que teve o texto
    recuperado por visão — `texto_direto` lê do cache e não sabe a diferença.
    """
    if registro.tipo == "gabarito":
        # gabarito nunca é fonte: ver projetos/estudos/gabarito.py
        return None
    if registro.modo != "direto":
        return None

    texto = texto_direto(registro)
    if not texto.strip():
        return None

    return TrechoFonte(
        arquivo=registro.nome_arquivo,
        tipo=_TIPO_PDF_PARA_TRECHO.get(registro.tipo, "aula"),
        capitulo=None,
        pagina_inicio=1,
        pagina_fim=registro.paginas,
        texto=texto,
    )


def fontes_da_aula(disciplina: str, numero_aula: int | None) -> list[FonteOrdenada]:
    """Material **deste semestre** vinculado à aula, mais o que foi citado nela.

    A citação entra porque o professor retoma material de outra aula: a questão 6 da
    lista da aula 1 é discutida na aula 2, e sem isso a nota da aula 2 não teria como
    falar do exercício que a aula inteira comentou.
    """
    if numero_aula is None:
        return []

    citados = {
        linha["sha256"]: linha["detalhe"] for linha in referencias_da_aula(disciplina, numero_aula)
    }

    fontes = []
    for registro in registros_por_disciplina(disciplina):
        se_citado = registro.sha256 in citados
        if registro.vigencia != "atual":
            continue
        if registro.numero_aula != numero_aula and not se_citado:
            continue
        trecho = trecho_de_pdf(registro)
        if trecho is not None:
            fontes.append(
                FonteOrdenada(
                    trecho=trecho,
                    prioridade=prioridade_do_registro(disciplina, registro),
                )
            )
    return fontes


def fontes_antigas_por_topico(
    disciplina: str, titulo_nota: str, topicos: list[str], minimo_tokens: int = 1
) -> list[FonteOrdenada]:
    """Material de semestre passado que fala do mesmo assunto.

    O casamento é por **tópico**, nunca pelo número no nome do arquivo: uma
    "Aula 5" de outro semestre não corresponde à aula 5 deste — a numeração é de
    outra oferta da disciplina, e usá-la ligaria conteúdos errados com confiança.

    Aqui basta **um** token de assunto, ao contrário do vínculo (`vinculo.por_titulo`),
    que exige dois. A assimetria é deliberada: vincular afirma um fato que fica gravado
    no banco e some da vista; sugerir uma fonte só oferece texto a um modelo que ainda
    precisa citá-lo para que a resposta sobreviva ao guardrail. Errar aqui custa alguns
    tokens; errar lá contamina a nota.
    """
    programa = carregar_programa(disciplina)
    titulo_oficial = programa.titulo_oficial if programa else ""

    alvo = tokens_de_assunto(titulo_nota, disciplina, titulo_oficial)
    for topico in topicos:
        alvo |= tokens_de_assunto(topico, disciplina, titulo_oficial)
    if not alvo:
        return []

    fontes = []
    for registro in registros_por_disciplina(disciplina):
        if registro.vigencia != "antiga":
            continue
        candidato = tokens_de_assunto(registro.nome_arquivo, disciplina, titulo_oficial)
        if len(candidato & alvo) < minimo_tokens:
            continue
        trecho = trecho_de_pdf(registro)
        if trecho is not None:
            fontes.append(
                FonteOrdenada(
                    trecho=trecho,
                    prioridade=prioridade_do_registro(disciplina, registro),
                )
            )
    return fontes


#: cabeçalho corrente do CLRS, repetido no topo de cada página: "2.3 Designing algorithms 37"
_RE_SECAO_CORRENTE = re.compile(r"(?m)^\s*(\d{1,2})\.(\d{1,2})\s+([A-Z][^\n]{2,70}?)\s*\d*\s*$")


def secoes_do_capitulo(trecho: TrechoFonte) -> list[TrechoFonte]:
    """Recorta um capítulo em seções, usando o cabeçalho corrente das páginas.

    Existe por custo, e o custo aqui é grande: o capítulo 4 do CLRS tem 109 mil
    caracteres, e uma questão sobre recorrência não precisa das 35 mil da prova do
    teorema mestre contínuo nem das de Akra-Bazzi. Mandar o capítulo inteiro para um
    modelo Opus, onze vezes, multiplica a conta por três sem melhorar a resposta.

    O recorte é **determinístico**: o cabeçalho que se repete no alto de cada página diz
    a que seção aquela página pertence. Nada de modelo adivinhando fronteira de seção.

    Devolve `[trecho]` inalterado quando o padrão não aparece o suficiente — livro com
    outra diagramação continua funcionando pelo capítulo inteiro, que é o comportamento
    de antes.
    """
    texto = trecho.texto
    marcas = [
        (m.start(), f"{m.group(1)}.{m.group(2)}", m.group(3).strip())
        for m in _RE_SECAO_CORRENTE.finditer(texto)
    ]
    # uma marca por seção, na primeira vez que ela aparece; o resto é repetição de página
    ordem: list[str] = []
    titulos: dict[str, str] = {}
    inicio: dict[str, int] = {}
    for posicao, chave, titulo in marcas:
        if chave not in inicio:
            ordem.append(chave)
            inicio[chave] = posicao
            titulos[chave] = titulo

    if len(ordem) < MINIMO_SECOES_PARA_RECORTAR:
        return [trecho]

    recortes: list[TrechoFonte] = []
    for posicao, chave in enumerate(ordem):
        comeco = inicio[chave]
        # a abertura do capítulo, antes do primeiro cabeçalho, entra junto da 1ª seção
        if posicao == 0:
            comeco = 0
        fim = inicio[ordem[posicao + 1]] if posicao + 1 < len(ordem) else len(texto)
        corpo = texto[comeco:fim].strip()
        if not corpo:
            continue
        recortes.append(
            trecho.model_copy(update={"capitulo": f"{chave} — {titulos[chave]}", "texto": corpo})
        )
    return recortes


def _numero_da_secao(rotulo: str) -> int:
    """ "4.3 — The substitution method" → 403. Inteiro estável para o seletor filtrar."""
    capitulo, _, resto = rotulo.partition(".")
    secao = resto.split(" ")[0].split("—")[0].strip()
    return int(capitulo) * 100 + int(secao)


def indice_de_secoes(secoes: list[TrechoFonte], indice: IndiceLivro) -> IndiceLivro:
    """Índice sintético em que cada "capítulo" é uma seção — para reusar o seletor.

    O `AgenteSeletorCapitulos` escolhe por título e devolve números, e o filtro
    determinístico de `resolver_capitulos` descarta número inventado. Nada nisso é
    específico de capítulo, então a peça se reaproveita inteira em vez de virar um
    segundo agente com o mesmo trabalho.
    """
    return indice.model_copy(
        update={
            "capitulos": [
                CapituloIndice(
                    numero=_numero_da_secao(secao.capitulo or ""),
                    titulo=(secao.capitulo or "").split("—", 1)[-1].strip(),
                    pagina_inicio=secao.pagina_inicio,
                    pagina_fim=secao.pagina_fim,
                )
                for secao in secoes
                if secao.capitulo and "." in secao.capitulo.split("—")[0]
            ]
        }
    )
