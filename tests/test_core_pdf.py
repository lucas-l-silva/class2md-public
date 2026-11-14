from pathlib import Path

import pytest

from core.config import get_settings
from core.fileops import CaminhoForaDaAllowlist
from core.pdf import (
    PdfInvalido,
    metadados,
    normalizar_texto,
    sha256_pdf,
    texto_paginas,
    texto_total,
    toc_nativo,
)
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
    caminho = tmp_path / "estudos" / "pdfs" / "Historia"
    caminho.mkdir(parents=True)
    return caminho


def test_toc_nativo_devolve_titulos_niveis_e_paginas_1based(pdfs_dir):
    caminho = pdfs_dir / "livro.pdf"
    criar_pdf(
        caminho,
        paginas=10,
        texto_por_pagina="conteúdo de exemplo " * 20,
        toc=[
            ("Capítulo 1", 0, 1),
            ("Seção 1.1", 1, 2),
            ("Capítulo 2", 0, 6),
        ],
    )

    entradas = toc_nativo(caminho)

    assert [e.titulo for e in entradas] == ["Capítulo 1", "Seção 1.1", "Capítulo 2"]
    assert [e.nivel for e in entradas] == [0, 1, 0]
    assert [e.pagina_inicio for e in entradas] == [1, 2, 6]


def test_toc_nativo_sem_outline_devolve_lista_vazia(pdfs_dir):
    caminho = pdfs_dir / "sem_toc.pdf"
    criar_pdf(caminho, paginas=3, texto_por_pagina="texto qualquer " * 20)

    assert toc_nativo(caminho) == []


def test_texto_paginas_e_inclusivo_nas_duas_pontas(pdfs_dir):
    caminho = pdfs_dir / "livro.pdf"
    criar_pdf(caminho, paginas=5, texto_por_pagina=[f"pagina {i}" for i in range(1, 6)])

    textos = texto_paginas(caminho, 2, 4)

    assert len(textos) == 3
    assert "pagina 2" in textos[0]
    assert "pagina 4" in textos[2]


def test_texto_paginas_faixa_fora_do_range_leva_a_erro(pdfs_dir):
    caminho = pdfs_dir / "livro.pdf"
    criar_pdf(caminho, paginas=3, texto_por_pagina="x " * 20)

    with pytest.raises(ValueError):
        texto_paginas(caminho, 1, 10)

    with pytest.raises(ValueError):
        texto_paginas(caminho, 0, 2)


def test_metadados_pdf_so_imagem_tem_texto_nativo_falso(pdfs_dir):
    caminho = pdfs_dir / "escaneado.pdf"
    criar_pdf(caminho, paginas=2, so_imagem=True)

    meta = metadados(caminho)

    assert meta.tem_texto_nativo is False
    assert meta.paginas == 2


def test_metadados_pdf_com_texto_tem_texto_nativo_verdadeiro(pdfs_dir):
    caminho = pdfs_dir / "com_texto.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="conteúdo suficientemente longo " * 20)

    meta = metadados(caminho)

    assert meta.tem_texto_nativo is True
    assert meta.chars_total > 0
    assert len(meta.chars_por_pagina) == 2


def test_metadados_pdf_landscape_detectado_pela_mediana(pdfs_dir):
    caminho = pdfs_dir / "slides.pdf"
    criar_pdf(caminho, paginas=3, texto_por_pagina="slide", landscape_=True)

    assert metadados(caminho).landscape is True


def test_metadados_pdf_retrato_nao_e_landscape(pdfs_dir):
    caminho = pdfs_dir / "livro.pdf"
    criar_pdf(caminho, paginas=3, texto_por_pagina="texto " * 20, landscape_=False)

    assert metadados(caminho).landscape is False


def test_texto_total_concatena_todas_as_paginas(pdfs_dir):
    caminho = pdfs_dir / "livro.pdf"
    criar_pdf(caminho, paginas=3, texto_por_pagina=["um", "dois", "tres"])

    texto = texto_total(caminho)

    assert "um" in texto
    assert "dois" in texto
    assert "tres" in texto


def test_pdf_fora_da_allowlist_recusa(tmp_path):
    fora = tmp_path / "fora_da_allowlist.pdf"
    criar_pdf(fora, paginas=1, texto_por_pagina="x")

    with pytest.raises(CaminhoForaDaAllowlist):
        metadados(fora)


def test_pdf_corrompido_da_erro_claro(pdfs_dir):
    caminho = pdfs_dir / "corrompido.pdf"
    caminho.write_bytes(b"isto nao e um pdf valido")

    with pytest.raises(PdfInvalido):
        metadados(caminho)


def test_sha256_pdf_muda_quando_conteudo_muda(pdfs_dir):
    caminho = pdfs_dir / "livro.pdf"
    criar_pdf(caminho, paginas=1, texto_por_pagina="versão 1")
    hash_1 = sha256_pdf(caminho)

    criar_pdf(caminho, paginas=1, texto_por_pagina="versão 2, bem diferente da primeira")
    hash_2 = sha256_pdf(caminho)

    assert hash_1 != hash_2


def test_normalizar_texto_recompoe_acentos_soltos_do_tex():
    bruto = "Matem´ atica Discreta"

    assert normalizar_texto(bruto) == "Matemática Discreta"


def test_normalizar_texto_expande_ligaduras():
    assert normalizar_texto("Veriﬁcar e aﬂora") == "Verificar e aflora"


def test_normalizar_texto_nao_toca_em_texto_correto_nem_em_acento_isolado():
    assert normalizar_texto("função, ação, número") == "função, ação, número"
    # acento seguido de letra que não forma par válido é conteúdo, não erro de extração
    assert normalizar_texto("o valor ´ n vezes") == "o valor ´ n vezes"
    assert normalizar_texto("") == ""


def test_texto_paginas_ja_devolve_texto_normalizado(pdfs_dir):
    caminho = pdfs_dir / "tex.pdf"
    criar_pdf(caminho, paginas=1, texto_por_pagina=["Constru¸ c˜ ao"])

    # o reportlab escreve o texto como está; o que importa é a normalização na leitura
    assert "¸ c˜ " not in texto_paginas(caminho, 1, 1)[0]
