from pathlib import Path

import pytest
from PIL import Image

from core.config import get_settings
from projetos.estudos.recortes import gerar_crops
from projetos.estudos.schemas import Bloco, Extracao


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "logs").mkdir()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def imagem_preparada(tmp_path) -> Path:
    # simula o local real (cache_dir/preproc/) de saída do core.images.preprocess (P2)
    caminho = tmp_path / "cache" / "preproc" / "img.jpg"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1000, 1000), color="blue").save(caminho, format="JPEG")
    return caminho


def _bloco(tipo="texto", flags=None, bbox=(0.1, 0.1, 0.4, 0.4)) -> Bloco:
    return Bloco(tipo=tipo, conteudo="x", latex=None, bbox=bbox, confianca=0.9, flags=flags or [])


def test_bloco_diagrama_gera_crop(imagem_preparada):
    extracao = Extracao(blocos=[_bloco(tipo="diagrama")], idioma="pt", observacoes="")

    mapa = gerar_crops(extracao, imagem_preparada, "Historia", "2026-08-02_historia_001")

    assert 0 in mapa
    assert Path(mapa[0]).exists()


def test_bloco_importante_gera_crop(imagem_preparada):
    extracao = Extracao(
        blocos=[_bloco(tipo="texto", flags=["importante"])], idioma="pt", observacoes=""
    )

    mapa = gerar_crops(extracao, imagem_preparada, "Historia", "2026-08-02_historia_001")

    assert 0 in mapa
    assert Path(mapa[0]).exists()


def test_bloco_texto_comum_nao_gera_crop(imagem_preparada):
    extracao = Extracao(blocos=[_bloco(tipo="texto")], idioma="pt", observacoes="")

    mapa = gerar_crops(extracao, imagem_preparada, "Historia", "2026-08-02_historia_001")

    assert mapa == {}


def test_nome_do_crop_segue_padrao_da_secao_9(imagem_preparada):
    extracao = Extracao(
        blocos=[
            _bloco(tipo="diagrama"),
            _bloco(tipo="formula"),
            _bloco(tipo="tabela", flags=["importante"]),
        ],
        idioma="pt",
        observacoes="",
    )

    mapa = gerar_crops(extracao, imagem_preparada, "Historia", "2026-08-02_historia_001")

    assert mapa[0].endswith("2026-08-02_historia_001_crop01.png")
    assert 1 not in mapa  # formula comum, sem crop
    assert mapa[2].endswith("2026-08-02_historia_001_crop02.png")
    assert "/crops/Historia/" in mapa[0]


def test_crop_recorta_da_imagem_preparada_com_bbox_correto(imagem_preparada):
    extracao = Extracao(
        blocos=[_bloco(tipo="diagrama", bbox=(0.2, 0.2, 0.4, 0.4))],
        idioma="pt",
        observacoes="",
    )

    mapa = gerar_crops(extracao, imagem_preparada, "Historia", "2026-08-02_historia_001")

    imagem_crop = Image.open(mapa[0])
    # bbox 0.2-0.4 em imagem 1000x1000 = 200px de largura/altura; margem 3% do bbox (200px) = 6px cada lado
    assert imagem_crop.size == (212, 212)


def test_rodar_duas_vezes_e_idempotente(imagem_preparada):
    extracao = Extracao(blocos=[_bloco(tipo="diagrama")], idioma="pt", observacoes="")

    mapa1 = gerar_crops(extracao, imagem_preparada, "Historia", "2026-08-02_historia_001")
    mtime1 = Path(mapa1[0]).stat().st_mtime

    mapa2 = gerar_crops(extracao, imagem_preparada, "Historia", "2026-08-02_historia_001")

    assert mapa1 == mapa2
    assert Path(mapa2[0]).stat().st_mtime == mtime1
