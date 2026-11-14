from pathlib import Path
from unittest.mock import patch

import pytest

from core.config import get_settings
from core.estado import pdf_por_sha
from core.pdf import renderizar_paginas
from projetos.estudos.agentes import AgenteExtrator
from projetos.estudos.pdf_ingestao import registrar_pdf
from projetos.estudos.pdf_ocr import (
    OcrRecusado,
    custo_estimado,
    extrair_por_visao,
    precisa_de_visao,
)
from projetos.estudos.schemas import Bloco, Extracao
from tests.pdf_fabrica import criar_pdf


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
def pdfs_dir(tmp_path) -> Path:
    caminho = tmp_path / "estudos" / "pdfs"
    caminho.mkdir(parents=True)
    return caminho


def _extracao():
    return Extracao(
        blocos=[
            Bloco(
                tipo="texto",
                conteudo="Entrada: vetor A[p..r]",
                latex=None,
                bbox=(0, 0, 1, 1),
                confianca=0.9,
                flags=[],
            )
        ],
        idioma="pt",
        observacoes="",
    )


def test_renderizar_paginas_gera_png_e_e_idempotente(pdfs_dir, tmp_path):
    caminho = pdfs_dir / "Calculo" / "notas.pdf"
    criar_pdf(caminho, paginas=3, texto_por_pagina="conteúdo")
    destino = tmp_path / "render"

    primeira = renderizar_paginas(caminho, 1, 2, destino)
    mtimes = [p.stat().st_mtime_ns for p in primeira]
    segunda = renderizar_paginas(caminho, 1, 2, destino)

    assert [p.name for p in primeira] == ["p0001.png", "p0002.png"]
    assert all(p.stat().st_size > 0 for p in primeira)
    # já renderizado não é refeito
    assert [p.stat().st_mtime_ns for p in segunda] == mtimes


def test_renderizar_recusa_faixa_invalida(pdfs_dir, tmp_path):
    caminho = pdfs_dir / "Calculo" / "notas.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="x")

    with pytest.raises(ValueError, match="faixa de páginas inválida"):
        renderizar_paginas(caminho, 1, 5, tmp_path / "r")


def test_pdf_com_texto_nativo_nao_precisa_de_visao(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "notas.pdf"
    criar_pdf(caminho, paginas=3, texto_por_pagina="texto de verdade " * 30)
    registro = registrar_pdf(caminho)

    assert registro.tem_texto_nativo
    assert not precisa_de_visao(registro)


def test_pdf_sem_texto_e_lido_por_visao_e_fica_no_cache(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "manuscrito.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="")
    registro = registrar_pdf(caminho)
    assert precisa_de_visao(registro)

    with patch.object(AgenteExtrator, "run", return_value=_extracao()) as mock:
        resultado = extrair_por_visao("job-1", registro)

    assert mock.call_count == 2  # uma chamada por página
    assert resultado.paginas_lidas == 2
    assert "Entrada: vetor A[p..r]" in resultado.caminho_texto.read_text(encoding="utf-8")
    assert "--- página 1 ---" in resultado.caminho_texto.read_text(encoding="utf-8")
    # depois de lido, deixa de estar pendente
    assert not precisa_de_visao(registro)
    assert pdf_por_sha(registro.sha256)["ocr_em"] is not None


def test_nao_relê_o_que_ja_tem_texto(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "manuscrito.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="")
    registro = registrar_pdf(caminho)

    with patch.object(AgenteExtrator, "run", return_value=_extracao()):
        extrair_por_visao("job-1", registro)

    with patch.object(AgenteExtrator, "run") as mock:
        resultado = extrair_por_visao("job-1", registro)

    mock.assert_not_called()
    assert "já disponível" in resultado.avisos[0]


def test_pdf_grande_exige_force(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livro_escaneado.pdf"
    criar_pdf(caminho, paginas=60, texto_por_pagina="")
    registro = registrar_pdf(caminho)

    with pytest.raises(OcrRecusado, match="60 páginas"):
        extrair_por_visao("job-1", registro)


def test_custo_estimado_soma_paginas(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "a.pdf"
    criar_pdf(caminho, paginas=10, texto_por_pagina="")
    registro = registrar_pdf(caminho)

    paginas, custo = custo_estimado([registro, registro])

    assert paginas == 20
    assert custo == pytest.approx(20 * 0.022)


def test_texto_vazio_nao_vira_cache(pdfs_dir):
    """Gravar "" faria o arquivo de cache existir, e a leitura por visão pularia o PDF."""
    from projetos.estudos.pdf_ingestao import _caminho_texto_direto, texto_direto

    caminho = pdfs_dir / "Calculo" / "manuscrito.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="")
    registro = registrar_pdf(caminho)

    assert texto_direto(registro).strip() == ""
    assert not _caminho_texto_direto(registro.sha256).exists()
    assert precisa_de_visao(registro)


def test_cache_vazio_preexistente_nao_bloqueia_a_visao(pdfs_dir):
    from projetos.estudos.pdf_ingestao import _caminho_texto_direto

    caminho = pdfs_dir / "Calculo" / "manuscrito.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="")
    registro = registrar_pdf(caminho)

    vazio = _caminho_texto_direto(registro.sha256)
    vazio.parent.mkdir(parents=True, exist_ok=True)
    vazio.write_text("\n", encoding="utf-8")

    assert precisa_de_visao(registro)

    with patch.object(AgenteExtrator, "run", return_value=_extracao()) as mock:
        extrair_por_visao("job-1", registro)

    assert mock.call_count == 2
