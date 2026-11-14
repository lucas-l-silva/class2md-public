from pathlib import Path

from core.config import get_settings
from core.fileops import escrever
from core.images.crops import recortar
from projetos.estudos.schemas import Extracao

MARGEM_CROP = 0.03
FLAG_IMPORTANTE = "importante"
TIPOS_COM_CROP = {"diagrama"}


def _vale_crop(bloco) -> bool:
    return bloco.tipo in TIPOS_COM_CROP or FLAG_IMPORTANTE in bloco.flags


def _caminho_crop(disciplina: str, prefixo_nome: str, indice_crop: int) -> Path:
    nome = f"{prefixo_nome}_crop{indice_crop:02d}.png"
    return get_settings().agent_data_dir / "estudos" / "crops" / disciplina / nome


def gerar_crops(
    extracao: Extracao,
    caminho_imagem_preparada: Path,
    disciplina: str,
    prefixo_nome: str,
) -> dict[int, str]:
    mapa: dict[int, str] = {}
    indice_crop = 0

    for posicao, bloco in enumerate(extracao.blocos):
        if not _vale_crop(bloco):
            continue

        indice_crop += 1
        caminho_destino = _caminho_crop(disciplina, prefixo_nome, indice_crop)

        if not caminho_destino.exists():
            png_bytes = recortar(caminho_imagem_preparada, bloco.bbox, margem=MARGEM_CROP)
            escrever(caminho_destino, png_bytes)

        mapa[posicao] = str(caminho_destino)

    return mapa
