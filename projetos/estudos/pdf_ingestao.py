import re
from pathlib import Path
from statistics import median
from typing import Literal

from pydantic import BaseModel

from core.config import get_settings
from core.estado import (
    atualizar_caminho_pdf,
    pdf_por_sha,
    pdfs_por_disciplina,
    pdfs_por_tipo,
    registrar_pdf_estado,
    vincular_pdf_a_aula,
)
from core.fileops import escrever_texto, ler_texto, listar
from core.logging import registrar_evento
from core.pdf import (
    EntradaTOC,
    MetadadosPdf,
    metadados,
    sha256_pdf,
    texto_paginas,
    texto_total,
    toc_nativo,
)
from projetos.estudos.ingestao import _disciplinas_conhecidas

EXTENSOES_PDF = {".pdf"}

LIMIAR_PAGINAS_LIVRO = 40
MIN_ENTRADAS_TOC_LIVRO = 5
PAGINAS_MIN_TOC_LIVRO = 25

LIMIAR_PAGINAS_DIRETO = 40
LIMIAR_PAGINAS_DIRETO_SLIDES = 120
LIMIAR_CHARS_DIRETO = 60_000

LIMIAR_CHARS_PAGINA_SLIDE = 600

_RE_ENUNCIADO = re.compile(r"^\s*\d{1,2}[.)]\s", re.MULTILINE)
_MIN_FRACAO_ENUNCIADOS = 0.30
_PAGINAS_MAX_EXERCICIOS = 15

TipoPdf = Literal["livro", "aula", "slides", "exercicios", "prova", "ementa", "gabarito"]
ModoUso = Literal["direto", "indexado"]
Vigencia = Literal["atual", "antiga"]

# Duas gerações de layout convivem: `estudos/pdfs/<Disciplina>/<tipo>/` (o original) e
# `estudos/inbox/<SIGLA>/pdfs/<vigencia>/<tipo>/` (o do registro de disciplinas). Os
# nomes antigos continuam valendo para não invalidar quem já organizou a pasta.
_SUBPASTA_PARA_TIPO: dict[str, TipoPdf] = {
    "livros": "livro",
    "livro": "livro",
    "aulas": "aula",
    "notas": "aula",
    "slides": "slides",
    "exercicios": "exercicios",
    "listas": "exercicios",
    "provas": "prova",
    "ementa": "ementa",
    "gabaritos": "gabarito",
}

# Gabarito é reconhecido pelo nome porque costuma vir solto junto dos livros, e
# confundi-lo com livro tem consequência: a resposta pronta entraria na nota no
# lugar do raciocínio.
_RE_GABARITO = re.compile(
    r"\b(gabarito|solutions?[ _-]?manual|solu[cç][aã]o|solu[cç][oõ]es|resolu[cç][aã]o|answers?)\b",
    re.IGNORECASE,
)

_SUBPASTA_PARA_VIGENCIA: dict[str, Vigencia] = {
    "atuais": "atual",
    "antigas": "antiga",
}


class RegistroPdf(BaseModel):
    sha256: str
    caminho: str
    nome_arquivo: str
    disciplina: str
    tipo: TipoPdf
    modo: ModoUso
    paginas: int
    chars_total: int
    data_aula: str | None
    tem_texto_nativo: bool
    #: material de semestre passado nunca entra na composição de uma nota nova
    vigencia: Vigencia = "atual"
    numero_aula: int | None = None
    titulo_material: str | None = None
    #: autoria, quando conhecida — é o que permite priorizar material do docente atual
    autor: str | None = None
    #: qual etapa da cascata resolveu o vínculo com a aula (site, nome_arquivo, titulo, llm, manual)
    vinculo_fonte: str | None = None
    origem_url: str | None = None


def _pistas_do_caminho(caminho: Path) -> tuple[str | None, Vigencia]:
    """Tipo (pela subpasta) e vigência, olhando os diretórios acima do arquivo.

    A vigência pode estar um ou dois níveis acima (`antigas/provas/x.pdf`), então
    varremos os ancestrais até a raiz do material.
    """
    dica_tipo = None
    vigencia: Vigencia = "atual"
    for parte in reversed(caminho.parts[:-1]):
        if dica_tipo is None and parte in _SUBPASTA_PARA_TIPO:
            dica_tipo = parte
        if parte in _SUBPASTA_PARA_VIGENCIA:
            vigencia = _SUBPASTA_PARA_VIGENCIA[parte]
            break
        if parte in ("pdfs", "inbox", "estudos"):
            break
    return dica_tipo, vigencia


def _fracao_paginas_com_enunciado(caminho: Path, meta: MetadadosPdf) -> float:
    if meta.paginas == 0:
        return 0.0
    textos = texto_paginas(caminho, 1, meta.paginas)
    com_enunciado = sum(1 for texto in textos if _RE_ENUNCIADO.search(texto))
    return com_enunciado / meta.paginas


def classificar(
    caminho: Path, meta: MetadadosPdf, toc: list[EntradaTOC], dica_pasta: str | None
) -> TipoPdf:
    # O nome vem antes da pasta só para gabarito, e de propósito: um manual de
    # soluções mora junto dos livros, e um gabarito de prova mora junto das provas.
    # A pasta diz onde o arquivo está; o nome diz o que ele é. Errar aqui faz a nota
    # entregar a solução pronta. `--tipo` explícito continua vencendo tudo.
    if _RE_GABARITO.search(caminho.stem):
        return "gabarito"

    if dica_pasta in _SUBPASTA_PARA_TIPO:
        return _SUBPASTA_PARA_TIPO[dica_pasta]

    if meta.paginas >= LIMIAR_PAGINAS_LIVRO or (
        len(toc) >= MIN_ENTRADAS_TOC_LIVRO and meta.paginas >= PAGINAS_MIN_TOC_LIVRO
    ):
        return "livro"

    if (
        meta.landscape
        and meta.chars_por_pagina
        and median(meta.chars_por_pagina) < LIMIAR_CHARS_PAGINA_SLIDE
    ):
        return "slides"

    if meta.paginas <= _PAGINAS_MAX_EXERCICIOS:
        if _fracao_paginas_com_enunciado(caminho, meta) >= _MIN_FRACAO_ENUNCIADOS:
            return "exercicios"

    return "aula"


def decidir_modo(tipo: TipoPdf, meta: MetadadosPdf) -> ModoUso:
    if tipo == "livro":
        return "indexado"

    teto_paginas = LIMIAR_PAGINAS_DIRETO_SLIDES if tipo == "slides" else LIMIAR_PAGINAS_DIRETO
    if meta.chars_total <= LIMIAR_CHARS_DIRETO and meta.paginas <= teto_paginas:
        return "direto"
    return "indexado"


def _caminho_cache_pdf(sha256: str) -> Path:
    return get_settings().cache_dir / "pdf" / sha256


def _caminho_texto_direto(sha256: str) -> Path:
    return _caminho_cache_pdf(sha256) / "texto.txt"


def registrar_pdf(
    caminho: Path,
    tipo: TipoPdf | None = None,
    disciplina: str | None = None,
    data_aula: str | None = None,
    force: bool = False,
    vigencia: Vigencia | None = None,
    numero_aula: int | None = None,
    autor: str | None = None,
    vinculo_fonte: str | None = None,
    origem_url: str | None = None,
) -> RegistroPdf | None:
    sha256 = sha256_pdf(caminho)

    ja_registrado = pdf_por_sha(sha256)
    if not force and ja_registrado is not None:
        # mesmo conteúdo, caminho diferente: o arquivo foi movido ou renomeado. Não é
        # registro novo, mas deixar o caminho antigo apontaria para um arquivo morto.
        if ja_registrado["caminho"] != str(caminho):
            atualizar_caminho_pdf(sha256, str(caminho), caminho.name)
        if numero_aula is not None and ja_registrado["numero_aula"] is None:
            vincular_pdf_a_aula(sha256, numero_aula, vinculo_fonte)
        return None

    meta = metadados(caminho)
    if not meta.tem_texto_nativo:
        registrar_evento(
            passo="pdf_ingestao",
            resultado="sem_texto_nativo",
            aviso=f"{caminho.name}: sem camada de texto — não será usado no pipeline (sem OCR).",
        )

    disciplina_final = disciplina or caminho.parent.name
    if disciplina_final in _SUBPASTA_PARA_TIPO:
        # o PDF está direto em estudos/pdfs/<subpasta_de_tipo>/ sem pasta de disciplina —
        # nesse caso não há como inferir a disciplina do caminho; melhor recusar que adivinhar.
        raise ValueError(
            f"não foi possível inferir a disciplina de {caminho} — organize em "
            f"estudos/pdfs/<Disciplina>/ (opcionalmente com subpasta de tipo dentro)"
        )

    conhecidas = _disciplinas_conhecidas()
    if conhecidas is not None and disciplina_final not in conhecidas:
        registrar_evento(
            passo="pdf_ingestao",
            resultado="disciplina_nao_cadastrada",
            aviso=disciplina_final,
        )

    dica_pasta, vigencia_do_caminho = _pistas_do_caminho(caminho)
    vigencia_final = vigencia or vigencia_do_caminho
    toc = toc_nativo(caminho) if meta.tem_texto_nativo else []
    tipo_final = tipo or classificar(caminho, meta, toc, dica_pasta)
    modo_final = decidir_modo(tipo_final, meta)
    autor_final = autor or (meta.autor or None)

    registrar_pdf_estado(
        sha256=sha256,
        caminho=str(caminho),
        nome_arquivo=caminho.name,
        disciplina=disciplina_final,
        tipo=tipo_final,
        modo=modo_final,
        paginas=meta.paginas,
        chars_total=meta.chars_total,
        tem_texto_nativo=meta.tem_texto_nativo,
        data_aula=data_aula,
        vigencia=vigencia_final,
        numero_aula=numero_aula,
        titulo_material=meta.titulo or None,
        autor=autor_final,
        vinculo_fonte=vinculo_fonte,
        origem_url=origem_url,
    )
    registrar_evento(
        passo="pdf_ingestao",
        resultado="registrado",
        aviso=f"{caminho.name} ({tipo_final}/{modo_final})",
    )

    return RegistroPdf(
        sha256=sha256,
        caminho=str(caminho),
        nome_arquivo=caminho.name,
        disciplina=disciplina_final,
        tipo=tipo_final,
        modo=modo_final,
        paginas=meta.paginas,
        chars_total=meta.chars_total,
        data_aula=data_aula,
        tem_texto_nativo=meta.tem_texto_nativo,
        vigencia=vigencia_final,
        numero_aula=numero_aula,
        titulo_material=meta.titulo or None,
        autor=autor_final,
        vinculo_fonte=vinculo_fonte,
        origem_url=origem_url,
    )


def obter_registro(
    caminho: Path,
    tipo: TipoPdf | None = None,
    disciplina: str | None = None,
    data_aula: str | None = None,
    force: bool = False,
    numero_aula: int | None = None,
    vinculo_fonte: str | None = None,
) -> RegistroPdf:
    """Como registrar_pdf, mas sempre devolve o RegistroPdf (registrando se preciso, ou lendo
    o que já existe) — para comandos que precisam do registro, não só de saber se é novo."""
    resultado = registrar_pdf(
        caminho,
        tipo=tipo,
        disciplina=disciplina,
        data_aula=data_aula,
        force=force,
        numero_aula=numero_aula,
        vinculo_fonte=vinculo_fonte,
    )
    if resultado is not None:
        return resultado
    row = pdf_por_sha(sha256_pdf(caminho))
    return _registro_de_row(row)


def _raizes_de_material() -> list[tuple[Path, bool]]:
    """(pasta, disciplina_é_o_nome_da_pasta) para cada raiz onde PDFs podem estar.

    `estudos/pdfs/<Disciplina>/…` é o layout original; `estudos/inbox/<SIGLA>/pdfs/…`
    é o do registro de disciplinas. Os dois valem ao mesmo tempo.
    """
    estudos = get_settings().agent_data_dir / "estudos"
    raizes: list[tuple[Path, bool]] = []

    pasta_pdfs = estudos / "pdfs"
    if pasta_pdfs.is_dir():
        for pasta_disciplina in listar(pasta_pdfs, "*"):
            if pasta_disciplina.is_dir():
                raizes.append((pasta_disciplina, True))

    inbox = estudos / "inbox"
    if inbox.is_dir():
        for pasta_disciplina in listar(inbox, "*"):
            pdfs_da_disciplina = pasta_disciplina / "pdfs"
            if pdfs_da_disciplina.is_dir():
                raizes.append((pdfs_da_disciplina, False))

    return raizes


def varrer_pdfs() -> list[RegistroPdf]:
    registrados = []

    for raiz, disciplina_na_raiz in _raizes_de_material():
        disciplina = raiz.name if disciplina_na_raiz else raiz.parent.name
        for caminho in sorted(raiz.rglob("*")):
            if not caminho.is_file() or caminho.suffix.lower() not in EXTENSOES_PDF:
                continue
            resultado = registrar_pdf(caminho, disciplina=disciplina)
            if resultado is not None:
                registrados.append(resultado)

    # PDF solto direto em inbox/<SIGLA>/ (fora de pdfs/) também conta: é onde o
    # arquivo cai quando você só arrasta para a pasta da disciplina.
    inbox = get_settings().agent_data_dir / "estudos" / "inbox"
    if inbox.is_dir():
        for pasta_disciplina in listar(inbox, "*"):
            if not pasta_disciplina.is_dir():
                continue
            for caminho in listar(pasta_disciplina, "*.pdf"):
                resultado = registrar_pdf(caminho, disciplina=pasta_disciplina.name)
                if resultado is not None:
                    registrados.append(resultado)

    return registrados


def _campo(row, nome, padrao=None):
    """Lê uma coluna que pode não existir em bancos criados antes da migração."""
    try:
        valor = row[nome]
    except (IndexError, KeyError):
        return padrao
    return padrao if valor is None else valor


def _registro_de_row(row) -> RegistroPdf:
    return RegistroPdf(
        sha256=row["sha256"],
        caminho=row["caminho"],
        nome_arquivo=row["nome_arquivo"],
        disciplina=row["disciplina"],
        tipo=row["tipo"],
        modo=row["modo"],
        paginas=row["paginas"],
        chars_total=row["chars_total"],
        data_aula=row["data_aula"],
        tem_texto_nativo=bool(row["tem_texto_nativo"]),
        vigencia=_campo(row, "vigencia", "atual"),
        numero_aula=_campo(row, "numero_aula"),
        titulo_material=_campo(row, "titulo_material"),
        autor=_campo(row, "autor"),
        vinculo_fonte=_campo(row, "vinculo_fonte"),
        origem_url=_campo(row, "origem_url"),
    )


def registros_por_tipo(tipo: TipoPdf) -> list[RegistroPdf]:
    return [_registro_de_row(row) for row in pdfs_por_tipo(tipo)]


def registros_por_disciplina(disciplina: str, tipo: TipoPdf | None = None) -> list[RegistroPdf]:
    return [_registro_de_row(row) for row in pdfs_por_disciplina(disciplina, tipo=tipo)]


def texto_direto(registro: RegistroPdf) -> str:
    if registro.modo != "direto":
        raise ValueError(f"{registro.nome_arquivo} não está em modo 'direto' (é '{registro.modo}')")

    caminho_cache = _caminho_texto_direto(registro.sha256)
    try:
        return ler_texto(caminho_cache)
    except FileNotFoundError:
        pass

    texto = texto_total(Path(registro.caminho))
    # Texto vazio NÃO vira cache. PDF sem camada de texto devolve "" aqui, e gravar
    # isso faria o arquivo de cache existir — o que a leitura por visão interpreta
    # como "já tenho o texto" e pula o PDF, silenciosamente e para sempre.
    if texto.strip():
        escrever_texto(caminho_cache, texto)
    return texto


def texto_de_paginas(registro: RegistroPdf, inicio: int, fim: int) -> str:
    caminho_cache = _caminho_cache_pdf(registro.sha256) / "paginas" / f"{inicio:04d}-{fim:04d}.txt"
    try:
        return ler_texto(caminho_cache)
    except FileNotFoundError:
        pass

    paginas = texto_paginas(Path(registro.caminho), inicio, fim)
    texto = "\n".join(paginas)
    escrever_texto(caminho_cache, texto)
    return texto
