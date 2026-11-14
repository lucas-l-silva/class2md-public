import hashlib
import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from core.fileops import ler

MIN_CHARS_TEXTO_NATIVO = 200

# PDF gerado por (pdf)TeX costuma emitir acento e letra como glifos separados: o
# extrator devolve "Constru¸ c˜ ao" em vez de "Construção". Sem recompor, a busca por
# título falha, o casamento por similaridade degrada e cada palavra acentuada custa
# tokens a mais.
#
# A recomposição é restrita a pares acento+letra que existem de fato nas línguas com
# que lidamos. Sem essa lista, "o valor ´ n vezes" viraria "ńvezes" — um acento solto
# seguido de qualquer letra não é evidência de acento quebrado.
_ACENTOS_SOLTOS = {
    "\u00b4": ("\u0301", "aeiouyAEIOUY"),  # ´  agudo
    "\u0060": ("\u0300", "aeiouAEIOU"),  # `  grave
    "\u02c6": ("\u0302", "aeiouAEIOU"),  # ˆ  circunflexo
    "\u02dc": ("\u0303", "aonAON"),  # ˜  til
    "\u00a8": ("\u0308", "aeiouAEIOU"),  # ¨  trema
    "\u00b8": ("\u0327", "cC"),  # ¸  cedilha
}
_RE_ACENTO_SOLTO = re.compile("([" + "".join(_ACENTOS_SOLTOS) + r"]) ?([A-Za-z])")
_LIGATURAS = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}


def normalizar_texto(texto: str) -> str:
    """Recompõe acentos soltos e ligaduras de PDFs gerados por TeX.

    Texto que já vem correto passa inalterado. Par acento+letra que não existe na
    língua é deixado como está — é mais provável ser conteúdo do que erro de extração.
    """
    if not texto:
        return texto

    for ligatura, expansao in _LIGATURAS.items():
        texto = texto.replace(ligatura, expansao)

    def _recompor(match: re.Match) -> str:
        combinante, letras_validas = _ACENTOS_SOLTOS[match.group(1)]
        if match.group(2) not in letras_validas:
            return match.group(0)
        return match.group(2) + combinante

    texto = _RE_ACENTO_SOLTO.sub(_recompor, texto)
    return unicodedata.normalize("NFC", texto)


class PdfInvalido(Exception):
    pass


@dataclass(frozen=True)
class EntradaTOC:
    titulo: str
    nivel: int  # 0 = topo
    pagina_inicio: int  # 1-based


@dataclass(frozen=True)
class MetadadosPdf:
    paginas: int
    chars_total: int
    chars_por_pagina: list[int]
    tem_texto_nativo: bool
    landscape: bool  # mediana(largura) > mediana(altura)
    titulo: str | None
    autor: str | None


def _abrir(caminho: Path) -> PdfReader:
    try:
        return PdfReader(BytesIO(ler(caminho)))
    except PdfReadError as erro:
        raise PdfInvalido(f"não foi possível abrir {caminho}: {erro}") from erro


def sha256_pdf(caminho: Path) -> str:
    return hashlib.sha256(ler(caminho)).hexdigest()


def _mediana(valores: list[float]) -> float:
    ordenados = sorted(valores)
    meio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[meio]
    return (ordenados[meio - 1] + ordenados[meio]) / 2


def metadados(caminho: Path) -> MetadadosPdf:
    reader = _abrir(caminho)
    paginas = reader.pages

    chars_por_pagina = []
    larguras, alturas = [], []
    for pagina in paginas:
        try:
            texto = pagina.extract_text() or ""
        except Exception:  # noqa: BLE001 — pypdf pode falhar em página individual malformada
            texto = ""
        chars_por_pagina.append(len(texto))
        caixa = pagina.mediabox
        larguras.append(float(caixa.width))
        alturas.append(float(caixa.height))

    chars_total = sum(chars_por_pagina)
    info = reader.metadata

    return MetadadosPdf(
        paginas=len(paginas),
        chars_total=chars_total,
        chars_por_pagina=chars_por_pagina,
        tem_texto_nativo=chars_total >= MIN_CHARS_TEXTO_NATIVO,
        landscape=bool(larguras) and _mediana(larguras) > _mediana(alturas),
        titulo=(info.title if info else None) or None,
        autor=(info.author if info else None) or None,
    )


def toc_nativo(caminho: Path) -> list[EntradaTOC]:
    reader = _abrir(caminho)
    entradas: list[EntradaTOC] = []

    def _percorrer(itens, nivel: int) -> None:
        for item in itens:
            if isinstance(item, list):
                _percorrer(item, nivel + 1)
                continue
            try:
                pagina = reader.get_destination_page_number(item)
            except Exception:  # noqa: BLE001 — destino inválido/quebrado no PDF de origem
                continue
            entradas.append(
                EntradaTOC(titulo=str(item.title), nivel=nivel, pagina_inicio=pagina + 1)
            )

    try:
        outline = reader.outline
    except Exception:  # noqa: BLE001 — outline corrompido não deve derrubar a extração
        outline = []
    _percorrer(outline, 0)
    return entradas


def texto_paginas(caminho: Path, inicio: int, fim: int) -> list[str]:
    reader = _abrir(caminho)
    total = len(reader.pages)
    if inicio < 1 or fim < inicio or fim > total:
        raise ValueError(f"faixa de páginas inválida: {inicio}-{fim} (PDF tem {total} páginas)")

    textos = []
    for indice in range(inicio - 1, fim):
        try:
            textos.append(normalizar_texto(reader.pages[indice].extract_text() or ""))
        except Exception:  # noqa: BLE001 — mesma tolerância de metadados()
            textos.append("")
    return textos


def texto_total(caminho: Path) -> str:
    reader = _abrir(caminho)
    partes = []
    for pagina in reader.pages:
        try:
            partes.append(normalizar_texto(pagina.extract_text() or ""))
        except Exception:  # noqa: BLE001
            partes.append("")
    return "\n".join(partes)


#: 150 dpi é o suficiente para manuscrito legível sem estourar o tamanho da imagem;
#: o pré-processamento de visão reduz para ~1568 px de qualquer forma.
DPI_RENDERIZACAO = 150


def renderizar_paginas(
    caminho: Path, inicio: int, fim: int, destino: Path, dpi: int = DPI_RENDERIZACAO
) -> list[Path]:
    """Rasteriza páginas de um PDF em PNG, para que possam ser lidas por visão.

    Existe porque nem todo PDF "sem texto" é digitalização: as notas de aula do
    professor são **manuscrito vetorial** (exportado de tablet) — não têm camada de
    texto nem imagem embutida para extrair, só traços. Rasterizar é a única forma
    de chegar ao conteúdo.

    Usa `pypdfium2` (licença permissiva, binário no próprio wheel) em vez de
    PyMuPDF (AGPL) ou pdf2image (exige poppler instalado no sistema).
    """
    import pypdfium2 as pdfium

    documento = pdfium.PdfDocument(str(caminho))
    try:
        total = len(documento)
        if inicio < 1 or fim < inicio or fim > total:
            raise ValueError(f"faixa de páginas inválida: {inicio}-{fim} (PDF tem {total} páginas)")

        destino.mkdir(parents=True, exist_ok=True)
        gerados = []
        for numero in range(inicio, fim + 1):
            saida = destino / f"p{numero:04d}.png"
            if not saida.exists():
                imagem = documento[numero - 1].render(scale=dpi / 72).to_pil()
                imagem.save(saida)
            gerados.append(saida)
        return gerados
    finally:
        documento.close()
