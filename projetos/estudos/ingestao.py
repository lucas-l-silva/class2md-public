import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps

from core.config import get_settings
from core.estado import (
    arquivo_por_sha,
    conectar,
    ja_ingerido,
    job_por_id,
    registrar_arquivo,
)
from core.fileops import ler_texto, listar, mover
from core.logging import registrar_evento
from projetos.estudos.agrupamento import agrupar_pendentes, agrupar_pendentes_ementa
from projetos.estudos.datacao import (
    RE_PASTA_DATA,
    Datacao,
    datar,
    leitor_de_data_escrita,
)
from projetos.estudos.disciplinas import nomes_conhecidos

_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_DATETIME = 0x0132


def sha256_de(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def remover_exif(origem: Path, destino: Path) -> None:
    imagem = Image.open(origem)
    imagem = ImageOps.exif_transpose(imagem)
    imagem.save(destino, format="JPEG")


def _timestamp_da_imagem(caminho: Path) -> datetime:
    exif = Image.open(caminho).getexif()
    bruto = exif.get(_TAG_DATETIME_ORIGINAL) or exif.get(_TAG_DATETIME)
    if bruto:
        return datetime.strptime(bruto, "%Y:%m:%d %H:%M:%S")
    return datetime.fromtimestamp(caminho.stat().st_mtime)


def _proximo_sequencial(data: str, slug: str) -> int:
    prefixo = f"{data}_{slug}_"
    conn = conectar()
    rows = conn.execute(
        "SELECT nome_final FROM arquivos WHERE nome_final LIKE ?", (prefixo + "%",)
    ).fetchall()
    if not rows:
        return 1
    return max(int(row["nome_final"][len(prefixo) : len(prefixo) + 3]) for row in rows) + 1


def _slugify(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", "_", sem_acento.strip().lower())


def _disciplinas_conhecidas() -> set[str] | None:
    """Siglas válidas, ou None quando não há nenhuma fonte configurada.

    Prefere o registro (`estudos/index/disciplinas.json`), que sabe muito mais que
    um nome; `disciplinas.txt` continua valendo como fallback para quem ainda não
    migrou. None mantém a validação desligada, como antes.
    """
    do_registro = nomes_conhecidos()
    if do_registro is not None:
        return do_registro

    caminho = get_settings().agent_data_dir / "estudos" / "disciplinas.txt"
    try:
        conteudo = ler_texto(caminho)
    except FileNotFoundError:
        return None
    return {linha.strip() for linha in conteudo.splitlines() if linha.strip()}


#: subpasta de `inbox/<SIGLA>/` cujas fotos NÃO são da aula
SUBPASTA_MONITORIA = "monitoria"
#: foto de documento físico da disciplina (plano de ensino, quadro com as datas de prova)
#: largada na pasta de ementa. É material administrativo, não conteúdo de aula.
SUBPASTA_EMENTA = "pdfs/ementa"


def _origem_e_disciplina(caminho: Path) -> tuple[str, str]:
    """(origem, disciplina) a partir de onde a foto está.

    Foto em `inbox/<SIGLA>/monitoria/` é da monitoria, não da aula: misturá-la no job
    do dia faria a nota da aula afirmar coisas que o professor não disse em aula.
    """
    if caminho.parent.name == SUBPASTA_MONITORIA:
        return SUBPASTA_MONITORIA, caminho.parent.parent.name
    if caminho.parent.name == "ementa" and caminho.parent.parent.name == "pdfs":
        return "ementa", caminho.parent.parent.parent.name
    # `inbox/<SIGLA>/AAAA-MM-DD/`: a pasta carrega a data da aula, não a disciplina
    if RE_PASTA_DATA.match(caminho.parent.name):
        return "aula", caminho.parent.parent.name
    return "aula", caminho.parent.name


def ingerir_imagem(origem: Path, datacao: Datacao | None = None) -> str | None:
    """Move a foto para `processed/`, sem EXIF, com o nome da data da aula.

    `datacao` decide a data (ver `datacao.py`). Sem ela, vale o EXIF, que é o comportamento
    de sempre. Datação ambígua (`data=None`) **não ingere**: a foto fica no inbox, porque
    depois de movida e sem EXIF não há mais como decidir.
    """
    sha256 = sha256_de(origem)
    if ja_ingerido(sha256):
        registrar_evento(passo="ingestao", resultado="duplicada", aviso=str(origem))
        return None

    timestamp = _timestamp_da_imagem(origem)
    fonte = "exif"
    if datacao is not None:
        if datacao.data is None:
            registrar_evento(
                passo="ingestao", resultado="data_ambigua", aviso=f"{origem}: {datacao.aviso}"
            )
            return None
        fonte = datacao.fonte
        if datacao.data != timestamp.date():
            # a hora do EXIF é mantida só para ordenar as fotos dentro do dia
            timestamp = datetime.combine(datacao.data, timestamp.time())
        if datacao.aviso:
            registrar_evento(
                passo="ingestao", resultado=f"data_{fonte}", aviso=f"{origem.name}: {datacao.aviso}"
            )
    data = timestamp.strftime("%Y-%m-%d")
    # A subpasta é só um palpite inicial. Numa iteração futura, a disciplina deve ser
    # INFERIDA pelo conteúdo da foto (papel do A4 — Identificador de Contexto), cruzando
    # com disciplinas.txt, e a pasta vira só um valor de partida a confirmar/corrigir.
    tipo_origem, disciplina = _origem_e_disciplina(origem)
    slug = _slugify(disciplina)
    if tipo_origem != "aula":
        slug = f"{slug}_{tipo_origem}"

    conhecidas = _disciplinas_conhecidas()
    if conhecidas is not None and disciplina not in conhecidas:
        registrar_evento(passo="ingestao", resultado="disciplina_nao_cadastrada", aviso=disciplina)

    sequencial = _proximo_sequencial(data, slug)
    nome_final = f"{data}_{slug}_{sequencial:03d}.jpg"

    remover_exif(origem, origem)

    processed_dir = get_settings().agent_data_dir / "estudos" / "processed" / disciplina
    destino = processed_dir / nome_final
    mover(origem, destino)

    registrar_arquivo(
        sha256,
        nome_final,
        disciplina=disciplina,
        tirada_em=timestamp.isoformat(),
        origem=tipo_origem,
        data_fonte=fonte,
    )
    registrar_evento(passo="ingestao", resultado="ingerida", aviso=nome_final)
    return nome_final


EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png"}


def varrer_inbox(ler_escrita=None, avisos: list | None = None) -> list[str]:
    """Ingere as fotos das pastas que o pipeline conhece e **relata** as que ignorou.

    A pasta de ementa entrou aqui depois de quatro fotos de plano de ensino ficarem
    paradas nela por dias: o varredor só olhava a raiz e `monitoria/`, e uma imagem em
    `pdfs/ementa/` era pulada sem dizer nada. Pular em silêncio é o pior modo de falha
    possível — não dá para distinguir "olhei e não achei" de "nunca olhei".

    Duas passadas por disciplina. A primeira só lê EXIF e pasta, para saber **que dias já
    têm foto confiável**; a segunda data cada foto, e é ela que precisa dessa informação
    para reconciliar uma data escrita que caiu fora de dia de aula (ver `datacao.py`).
    `ler_escrita` é injetável para teste; por padrão chama o agente de visão.
    """
    inbox = get_settings().agent_data_dir / "estudos" / "inbox"
    ingeridos = []
    for pasta_disciplina in listar(inbox, "*"):
        if not pasta_disciplina.is_dir():
            continue
        sigla = pasta_disciplina.name
        pastas = [pasta_disciplina, *_pastas_de_data(pasta_disciplina)]
        for subpasta in (SUBPASTA_MONITORIA, SUBPASTA_EMENTA):
            candidata = pasta_disciplina / subpasta
            if candidata.is_dir():
                pastas.append(candidata)

        fotos = [
            caminho
            for pasta in pastas
            for caminho in listar(pasta, "*")
            if caminho.suffix.lower() in EXTENSOES_IMAGEM
        ]
        confiaveis = _datas_confiaveis(sigla, fotos)
        leitor = ler_escrita or leitor_de_data_escrita(sigla, sha256_de)

        for caminho in fotos:
            origem, _ = _origem_e_disciplina(caminho)
            datacao = None
            if origem == "aula" and not ja_ingerido(sha256_de(caminho)):
                datacao = datar(caminho, sigla, _timestamp_da_imagem(caminho), confiaveis, leitor)
            resultado = ingerir_imagem(caminho, datacao)
            if resultado:
                ingeridos.append(resultado)
            if datacao is not None and datacao.aviso and avisos is not None:
                avisos.append((f"{sigla}/{caminho.name}", datacao.aviso))

        for esquecida in imagens_fora_das_pastas_conhecidas(pasta_disciplina):
            registrar_evento(
                passo="ingestao",
                resultado="imagem_em_pasta_nao_varrida",
                aviso=str(esquecida),
            )
    return ingeridos


def _pastas_de_data(pasta_disciplina: Path) -> list[Path]:
    return sorted(
        p for p in pasta_disciplina.iterdir() if p.is_dir() and RE_PASTA_DATA.match(p.name)
    )


def _datas_confiaveis(sigla: str, fotos: list[Path]) -> set:
    """Dias que já têm foto de aula com data segura: pasta, EXIF em dia de aula, ou foto
    já ingerida antes. É contra esse conjunto que uma data escrita ambígua é reconciliada."""
    from projetos.estudos.datacao import data_da_pasta, dias_de_aula

    dias = dias_de_aula(sigla) or set()
    datas = set()
    for caminho in fotos:
        if _origem_e_disciplina(caminho)[0] != "aula":
            continue
        da_pasta = data_da_pasta(caminho)
        if da_pasta is not None:
            datas.add(da_pasta)
            continue
        exif = _timestamp_da_imagem(caminho)
        if exif.weekday() in dias:
            datas.add(exif.date())

    conn = conectar()
    for row in conn.execute(
        "SELECT tirada_em FROM arquivos WHERE disciplina = ? AND tirada_em IS NOT NULL "
        "AND (origem IS NULL OR origem = 'aula')",
        (sigla,),
    ):
        datas.add(datetime.fromisoformat(row["tirada_em"]).date())
    return datas


def imagens_fora_das_pastas_conhecidas(pasta_disciplina: Path) -> list[Path]:
    """Imagens que existem no inbox da disciplina mas em pasta que ninguém varre."""
    conhecidas = {
        pasta_disciplina,
        pasta_disciplina / SUBPASTA_MONITORIA,
        pasta_disciplina / SUBPASTA_EMENTA,
        *_pastas_de_data(pasta_disciplina),
    }
    return sorted(
        caminho
        for caminho in pasta_disciplina.rglob("*")
        if caminho.suffix.lower() in EXTENSOES_IMAGEM
        and caminho.is_file()
        and caminho.parent not in conhecidas
    )


def processar_inbox() -> dict:
    avisos_de_data: list[tuple[str, str]] = []
    ingeridos = varrer_inbox(avisos=avisos_de_data)
    resultado_agrupamento = agrupar_pendentes()
    resultado_ementa = agrupar_pendentes_ementa()
    return {
        "fotos_ingeridas": len(ingeridos),
        "jobs_criados": resultado_agrupamento["jobs_criados"],
        "jobs_reaproveitados": resultado_agrupamento["jobs_reaproveitados"],
        "jobs_de_ementa": resultado_ementa["jobs_criados"],
        "datas": avisos_de_data,
    }


def fotos_ja_processadas() -> list[tuple[Path, str]]:
    """Fotos que continuam no inbox mesmo já tendo virado nota. Devolve [(caminho, motivo)].

    Três condições, todas necessárias: a foto está registrada, o job dela **concluiu**, e
    existe a cópia normalizada em `processed/`. Faltando qualquer uma, a foto fica onde
    está — o inbox é a única cópia que resta de uma foto ainda não processada, e o erro
    de tirá-la cedo é irrecuperável.

    **PDF nunca entra aqui.** O registro guarda o caminho dentro do inbox: para os PDFs,
    o inbox é o lugar definitivo, não uma fila de entrada.
    """
    raiz = get_settings().agent_data_dir / "estudos"
    prontas = []

    for caminho in sorted((raiz / "inbox").rglob("*")):
        if caminho.suffix.lower() not in EXTENSOES_IMAGEM or not caminho.is_file():
            continue

        registro = arquivo_por_sha(sha256_de(caminho))
        if registro is None or not registro["job_id"]:
            continue

        job = job_por_id(registro["job_id"])
        if job is None or job["status"] not in ("concluido", "promovido"):
            continue

        copia = raiz / "processed" / (registro["disciplina"] or "") / registro["nome_final"]
        if copia.exists():
            prontas.append((caminho, f"{registro['nome_final']} · job {job['status']}"))

    return prontas


def mover_fotos_processadas(fotos: list[Path]) -> Path:
    """Move para `estudos/trash/<carimbo>/inbox/`, espelhando a árvore, com README."""
    carimbo = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
    raiz = get_settings().agent_data_dir / "estudos"
    destino_raiz = raiz / "trash" / carimbo / "inbox"

    movidas = []
    for origem in fotos:
        destino = destino_raiz / origem.relative_to(raiz / "inbox")
        mover(origem, destino)
        movidas.append(destino.relative_to(destino_raiz))

    linhas = [
        f"# Fotos do inbox movidas em {carimbo}",
        "",
        "Cada uma destas já virou nota: está registrada, o job dela concluiu e a versão",
        "normalizada está em `estudos/processed/`. O que ficou no inbox era cópia.",
        "",
        "Movidas, não apagadas.",
        "",
        f"Total: {len(movidas)}",
        "",
    ] + [f"- {caminho}" for caminho in movidas]
    (destino_raiz.parent / "README.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")

    return destino_raiz.parent
