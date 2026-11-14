import io
from pathlib import Path

import pytest
from PIL import Image

from core.config import get_settings
from core.images.crops import recortar


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


def _origem(tmp_path: Path, tamanho=(1000, 1000)) -> Path:
    caminho = tmp_path / "estudos" / "processed" / "Historia" / "foto.jpg"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", tamanho, color="blue").save(caminho, format="JPEG")
    return caminho


def test_recortar_aplica_margem_correta(tmp_path):
    origem = _origem(tmp_path, tamanho=(1000, 1000))

    resultado = recortar(origem, (0.2, 0.2, 0.4, 0.4), margem=0.1)

    imagem = Image.open(io.BytesIO(resultado))
    assert imagem.format == "PNG"
    assert imagem.size == (240, 240)


def test_recortar_clampa_bbox_na_borda_da_imagem(tmp_path):
    origem = _origem(tmp_path, tamanho=(1000, 1000))

    resultado = recortar(origem, (0.0, 0.0, 0.1, 0.1), margem=0.5)

    imagem = Image.open(io.BytesIO(resultado))
    assert imagem.size == (150, 150)


def test_recortar_sem_margem_bate_com_bbox_exato(tmp_path):
    origem = _origem(tmp_path, tamanho=(800, 400))

    resultado = recortar(origem, (0.25, 0.25, 0.75, 0.75), margem=0.0)

    imagem = Image.open(io.BytesIO(resultado))
    assert imagem.size == (400, 200)
