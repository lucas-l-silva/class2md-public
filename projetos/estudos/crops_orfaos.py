"""Recortes que nenhuma nota usa.

O extrator recorta todo bloco que "vale crop", mas o compositor decide quais realmente
entram na nota — e cada job reprocessado deixa os recortes da tentativa anterior no disco.
Nas primeiras semanas isso somou 126 arquivos órfãos de 181 (70%), boa parte herdada dos
jobs duplicados e renumerados da MAT1.

**Órfão é movido, nunca apagado.** Um recorte é a única cópia recortada daquele pedaço da
lousa; se a classificação errar, o arquivo tem de continuar existindo para você recuperar.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.config import get_settings
from core.fileops import mover

#: `![[nome.png]]` (wikilink do Obsidian) e `![alt](caminho/nome.png)`
_RE_REFERENCIA = re.compile(r"!\[\[([^\]|]+\.png)(?:\|[^\]]*)?\]\]|!\[[^\]]*\]\(([^)]+\.png)\)")


@dataclass(frozen=True)
class Inventario:
    usados: list[Path]
    orfaos: list[Path]

    @property
    def total(self) -> int:
        return len(self.usados) + len(self.orfaos)


def _raiz() -> Path:
    return get_settings().agent_data_dir / "estudos"


def nomes_referenciados() -> set[str]:
    """Nomes de PNG citados por alguma nota.

    Varre `output/` **e `promovidas/`**: promovida é nota que já foi para o vault e
    continua apontando para o recorte. Considerar só o staging apagaria o recorte de toda
    nota que você já revisou — exatamente as que mais importam.
    """
    nomes: set[str] = set()
    for pasta in ("output", "promovidas"):
        raiz = _raiz() / pasta
        if not raiz.is_dir():
            continue
        for nota in raiz.rglob("*.md"):
            for wikilink, markdown in _RE_REFERENCIA.findall(nota.read_text(encoding="utf-8")):
                nomes.add(Path(wikilink or markdown).name)
    return nomes


def inventariar(disciplina: str | None = None) -> Inventario:
    referenciados = nomes_referenciados()
    raiz = _raiz() / "crops"
    if disciplina:
        raiz = raiz / disciplina

    usados, orfaos = [], []
    for png in sorted(raiz.rglob("*.png")) if raiz.is_dir() else []:
        (usados if png.name in referenciados else orfaos).append(png)
    return Inventario(usados=usados, orfaos=orfaos)


def mover_para_trash(
    orfaos: list[Path], motivo: str = "recortes que nenhuma nota referencia"
) -> Path:
    """Move os órfãos para `estudos/trash/<AAAA-MM-DD_HHMMSS>/crops/<SIGLA>/`.

    Espelha a árvore de origem e deixa um README com o motivo e a lista, para que o
    diretório continue legível meses depois — sem isso, uma pasta de PNGs com carimbo de
    data não diz nada sobre por que foi criada.
    """
    carimbo = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
    destino_raiz = _raiz() / "trash" / carimbo / "crops"

    movidos = []
    for origem in orfaos:
        destino = destino_raiz / origem.parent.name / origem.name
        mover(origem, destino)
        movidos.append(destino)

    linhas = [
        f"# Recortes movidos em {carimbo}",
        "",
        f"Motivo: {motivo}.",
        "",
        "Movidos, não apagados: se algum destes fizer falta, é só mover de volta para",
        "`estudos/crops/<SIGLA>/`.",
        "",
        f"Total: {len(movidos)}",
        "",
    ] + [f"- {p.parent.name}/{p.name}" for p in movidos]
    (destino_raiz.parent / "README.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")

    return destino_raiz.parent
