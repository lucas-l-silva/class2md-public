from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from core.config import get_settings
from core.images.preprocess import preparar


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


def _criar_imagem(caminho: Path, tamanho=(3000, 1500), cor: str = "blue") -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", tamanho, color=cor).save(caminho, format="JPEG")


def _origem(tmp_path: Path) -> Path:
    return tmp_path / "estudos" / "processed" / "Historia" / "foto.jpg"


def test_preparar_receita_nenhuma_redimensiona_lado_maior(tmp_path):
    origem = _origem(tmp_path)
    _criar_imagem(origem, tamanho=(3000, 1500))

    resultado = preparar(origem, "nenhuma")

    assert resultado.exists()
    with Image.open(resultado) as img:
        assert max(img.size) <= 1568


def test_preparar_e_idempotente_via_cache(tmp_path):
    origem = _origem(tmp_path)
    _criar_imagem(origem)

    resultado1 = preparar(origem, "nenhuma")
    mtime1 = resultado1.stat().st_mtime

    resultado2 = preparar(origem, "nenhuma")

    assert resultado1 == resultado2
    assert resultado2.stat().st_mtime == mtime1


def test_preparar_nao_amplia_imagem_pequena(tmp_path):
    origem = _origem(tmp_path)
    _criar_imagem(origem, tamanho=(400, 300))

    resultado = preparar(origem, "nenhuma")

    with Image.open(resultado) as img:
        assert img.size == (400, 300)


def test_receita_desconhecida_levanta_erro(tmp_path):
    origem = _origem(tmp_path)
    _criar_imagem(origem)

    with pytest.raises(ValueError):
        preparar(origem, "inexistente")


def _imagem_retangulo_rotacionado(
    tamanho=(900, 900), lado_retangulo=(600, 300), angulo=15
) -> Image.Image:
    canvas = np.zeros((tamanho[1], tamanho[0], 3), dtype="uint8")
    centro = (tamanho[0] // 2, tamanho[1] // 2)
    pontos = cv2.boxPoints((centro, lado_retangulo, angulo)).astype("int32")
    cv2.fillConvexPoly(canvas, pontos, (255, 255, 255))
    return Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))


def test_receita_quadro_endireita_retangulo_rotacionado(tmp_path):
    origem = _origem(tmp_path)
    origem.parent.mkdir(parents=True, exist_ok=True)
    _imagem_retangulo_rotacionado().save(origem, format="JPEG", quality=95)

    resultado = preparar(origem, "quadro")

    with Image.open(resultado) as corrigido:
        proporcao = corrigido.size[0] / corrigido.size[1]

    proporcao_esperada = 600 / 300
    assert abs(proporcao - proporcao_esperada) < 0.3


def test_receita_quadro_sem_quadrilatero_confiavel_faz_fallback(tmp_path):
    origem_quadro = _origem(tmp_path)
    _criar_imagem(origem_quadro, tamanho=(1000, 800), cor="gray")
    tamanho_quadro = Image.open(preparar(origem_quadro, "quadro")).size

    origem_nenhuma = tmp_path / "estudos" / "processed" / "Historia" / "foto2.jpg"
    _criar_imagem(origem_nenhuma, tamanho=(1000, 800), cor="gray")
    tamanho_nenhuma = Image.open(preparar(origem_nenhuma, "nenhuma")).size

    assert tamanho_quadro == tamanho_nenhuma


def test_receita_papel_corta_margens_e_reduz_tamanho(tmp_path):
    canvas = np.full((1000, 1000, 3), 255, dtype="uint8")
    cv2.rectangle(canvas, (300, 300), (700, 700), (0, 0, 0), -1)
    origem = _origem(tmp_path)
    origem.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)).save(origem, format="JPEG")

    resultado = preparar(origem, "papel")

    with Image.open(resultado) as img:
        assert img.size[0] < 1000 and img.size[1] < 1000


def test_receita_projecao_clareia_imagem_escura(tmp_path):
    origem = _origem(tmp_path)
    _criar_imagem(origem, tamanho=(600, 400), cor=(40, 40, 40))

    resultado = preparar(origem, "projecao")

    with Image.open(resultado) as img:
        media_original = 40
        media_corrigida = np.array(img).mean()
        assert media_corrigida > media_original
