from pathlib import Path

import pytest

from core.config import get_settings
from core.estado import (
    pdf_por_sha,
    pdfs_por_numero_aula,
    pdfs_sem_vinculo,
    vincular_pdf_a_aula,
)
from core.pdf import metadados, toc_nativo
from projetos.estudos.pdf_ingestao import (
    classificar,
    decidir_modo,
    registrar_pdf,
    registros_por_disciplina,
    texto_de_paginas,
    texto_direto,
    varrer_pdfs,
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
    caminho = tmp_path / "estudos" / "pdfs"
    caminho.mkdir(parents=True)
    return caminho


def test_classificar_livro_por_numero_de_paginas(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livro.pdf"
    criar_pdf(caminho, paginas=50, texto_por_pagina="conteúdo denso " * 10)

    meta = metadados(caminho)
    toc = toc_nativo(caminho)

    assert classificar(caminho, meta, toc, None) == "livro"


def test_classificar_livro_por_toc_rico_mesmo_com_poucas_paginas(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livro_curto.pdf"
    criar_pdf(
        caminho,
        paginas=30,
        texto_por_pagina="conteúdo " * 10,
        toc=[(f"Capítulo {i}", 0, i * 5 + 1) for i in range(6)],
    )

    meta = metadados(caminho)
    toc = toc_nativo(caminho)

    assert len(toc) >= 5
    assert classificar(caminho, meta, toc, None) == "livro"


def test_classificar_slides_por_landscape_e_baixa_densidade(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "aula.pdf"
    criar_pdf(caminho, paginas=20, texto_por_pagina="Título do slide", landscape_=True)

    meta = metadados(caminho)
    toc = toc_nativo(caminho)

    assert classificar(caminho, meta, toc, None) == "slides"


def test_classificar_exercicios_por_enunciados_numerados(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "lista.pdf"
    enunciados = [
        f"{i}. Calcule o limite da função f(x) quando x tende a {i}." for i in range(1, 11)
    ]
    criar_pdf(caminho, paginas=10, texto_por_pagina=enunciados)

    meta = metadados(caminho)
    toc = toc_nativo(caminho)

    assert classificar(caminho, meta, toc, None) == "exercicios"


def test_classificar_aula_e_o_default(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "notas.pdf"
    criar_pdf(
        caminho,
        paginas=5,
        texto_por_pagina="notas de aula em prosa corrida, sem lista numerada " * 5,
    )

    meta = metadados(caminho)
    toc = toc_nativo(caminho)

    assert classificar(caminho, meta, toc, None) == "aula"


def test_classificar_subpasta_vence_heuristica(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livros" / "arquivo_pequeno.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="pouco conteúdo")

    meta = metadados(caminho)
    toc = toc_nativo(caminho)

    assert classificar(caminho, meta, toc, "livros") == "livro"


def test_decidir_modo_livro_e_sempre_indexado(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livro.pdf"
    criar_pdf(caminho, paginas=5, texto_por_pagina="pouco texto")
    meta = metadados(caminho)

    assert decidir_modo("livro", meta) == "indexado"


def test_decidir_modo_pdf_pequeno_e_direto(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "lista.pdf"
    criar_pdf(caminho, paginas=3, texto_por_pagina="pouco texto")
    meta = metadados(caminho)

    assert decidir_modo("exercicios", meta) == "direto"


def test_decidir_modo_slides_tem_teto_de_paginas_maior(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "slides.pdf"
    criar_pdf(caminho, paginas=80, texto_por_pagina="pouco texto por slide", landscape_=True)
    meta = metadados(caminho)

    # 80 páginas passaria do teto normal (40) mas não do teto de slides (120)
    assert decidir_modo("slides", meta) == "direto"


def test_registrar_pdf_e_idempotente_por_sha(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livro.pdf"
    criar_pdf(caminho, paginas=50, texto_por_pagina="conteúdo " * 10)

    primeiro = registrar_pdf(caminho)
    segundo = registrar_pdf(caminho)

    assert primeiro is not None
    assert segundo is None  # já registrado, sha igual


def test_registrar_pdf_com_force_reprocessa(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livro.pdf"
    criar_pdf(caminho, paginas=50, texto_por_pagina="conteúdo " * 10)

    registrar_pdf(caminho)
    de_novo = registrar_pdf(caminho, force=True)

    assert de_novo is not None


def test_registrar_pdf_nao_move_nem_altera_o_arquivo_original(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livro.pdf"
    criar_pdf(caminho, paginas=10, texto_por_pagina="conteúdo " * 10)
    tamanho_original = caminho.stat().st_size

    registrar_pdf(caminho)

    assert caminho.exists()
    assert caminho.stat().st_size == tamanho_original


def test_pdf_editado_gera_registro_atualizado(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livro.pdf"
    criar_pdf(caminho, paginas=10, texto_por_pagina="versão 1")
    registrar_pdf(caminho)

    criar_pdf(caminho, paginas=60, texto_por_pagina="versão 2, bem mais longa " * 10)
    resultado = registrar_pdf(caminho)

    assert resultado is not None
    assert resultado.paginas == 60


def test_varrer_pdfs_duas_vezes_nao_duplica(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livro.pdf"
    criar_pdf(caminho, paginas=50, texto_por_pagina="conteúdo " * 10)

    primeira = varrer_pdfs()
    segunda = varrer_pdfs()

    assert len(primeira) == 1
    assert len(segunda) == 0


def test_varrer_pdfs_usa_subpasta_de_disciplina_mesmo_com_subpasta_de_tipo(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livros" / "stewart.pdf"
    criar_pdf(caminho, paginas=50, texto_por_pagina="conteúdo " * 10)

    registrados = varrer_pdfs()

    assert len(registrados) == 1
    assert registrados[0].disciplina == "Calculo"
    assert registrados[0].tipo == "livro"


def test_texto_direto_e_cacheado_sem_reabrir_o_pdf(pdfs_dir, monkeypatch):
    caminho = pdfs_dir / "Calculo" / "lista.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="conteúdo pequeno")
    registro = registrar_pdf(caminho)
    assert registro.modo == "direto"

    primeira = texto_direto(registro)

    chamadas = {"n": 0}
    import projetos.estudos.pdf_ingestao as mod

    original = mod.texto_total

    def _contando(*args, **kwargs):
        chamadas["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(mod, "texto_total", _contando)
    segunda = texto_direto(registro)

    assert segunda == primeira
    assert chamadas["n"] == 0  # cache hit — não reabriu o PDF


def test_texto_direto_falha_se_registro_nao_e_direto(pdfs_dir):
    caminho = pdfs_dir / "Calculo" / "livro.pdf"
    criar_pdf(caminho, paginas=50, texto_por_pagina="conteúdo " * 10)
    registro = registrar_pdf(caminho)
    assert registro.modo == "indexado"

    with pytest.raises(ValueError):
        texto_direto(registro)


def test_texto_de_paginas_e_cacheado(pdfs_dir, monkeypatch):
    caminho = pdfs_dir / "Calculo" / "livro.pdf"
    criar_pdf(caminho, paginas=50, texto_por_pagina=[f"pagina {i}" for i in range(1, 51)])
    registro = registrar_pdf(caminho)

    primeira = texto_de_paginas(registro, 3, 5)
    assert "pagina 3" in primeira

    chamadas = {"n": 0}
    import projetos.estudos.pdf_ingestao as mod

    original = mod.texto_paginas

    def _contando(*args, **kwargs):
        chamadas["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(mod, "texto_paginas", _contando)
    segunda = texto_de_paginas(registro, 3, 5)

    assert segunda == primeira
    assert chamadas["n"] == 0


@pytest.fixture
def inbox_dir(tmp_path) -> Path:
    caminho = tmp_path / "estudos" / "inbox"
    caminho.mkdir(parents=True)
    return caminho


def _pdf_simples(caminho: Path) -> Path:
    criar_pdf(caminho, paginas=2, texto_por_pagina="conteúdo de aula")
    return caminho


def test_subpasta_nova_mapeia_tipo_e_vigencia(inbox_dir):
    prova = _pdf_simples(inbox_dir / "MAT1" / "pdfs" / "antigas" / "provas" / "ap1-2025.pdf")
    lista = _pdf_simples(inbox_dir / "MAT1" / "pdfs" / "atuais" / "listas" / "lista01.pdf")
    ementa = _pdf_simples(inbox_dir / "MAT1" / "pdfs" / "ementa" / "plano.pdf")

    registros = {r.nome_arquivo: r for r in varrer_pdfs()}

    assert registros[prova.name].tipo == "prova"
    assert registros[prova.name].vigencia == "antiga"
    assert registros[lista.name].tipo == "exercicios"
    assert registros[lista.name].vigencia == "atual"
    assert registros[ementa.name].tipo == "ementa"
    assert {r.disciplina for r in registros.values()} == {"MAT1"}


def test_subpastas_antigas_continuam_valendo(pdfs_dir):
    _pdf_simples(pdfs_dir / "Calculo" / "exercicios" / "lista.pdf")

    registros = varrer_pdfs()

    assert registros[0].tipo == "exercicios"
    assert registros[0].vigencia == "atual"


def test_pdf_solto_na_pasta_da_disciplina_e_registrado(inbox_dir):
    _pdf_simples(inbox_dir / "MAT1" / "aula00 + lista 00.pdf")

    registros = varrer_pdfs()

    assert [r.disciplina for r in registros] == ["MAT1"]
    assert registros[0].numero_aula is None


def test_varrer_as_duas_raizes_sem_duplicar(pdfs_dir, inbox_dir):
    _pdf_simples(pdfs_dir / "Calculo" / "livro-antigo.pdf")
    _pdf_simples(inbox_dir / "MAT1" / "pdfs" / "atuais" / "notas" / "aula01.pdf")

    primeira = varrer_pdfs()
    segunda = varrer_pdfs()

    assert {r.disciplina for r in primeira} == {"Calculo", "MAT1"}
    assert segunda == []


def test_revarredura_nao_apaga_vinculo_ja_resolvido(inbox_dir):
    caminho = _pdf_simples(inbox_dir / "MAT1" / "pdfs" / "atuais" / "notas" / "aula03.pdf")
    registro = varrer_pdfs()[0]
    vincular_pdf_a_aula(registro.sha256, 3, "manual")

    varrer_pdfs()
    registrar_pdf(caminho, disciplina="MAT1", force=True)

    atual = registros_por_disciplina("MAT1")[0]
    assert atual.numero_aula == 3
    assert atual.vinculo_fonte == "manual"


def test_registrar_com_vinculo_e_origem_do_site(inbox_dir):
    caminho = _pdf_simples(inbox_dir / "MAT1" / "pdfs" / "atuais" / "notas" / "aula01.pdf")

    registro = registrar_pdf(
        caminho,
        disciplina="MAT1",
        numero_aula=1,
        vinculo_fonte="site",
        origem_url="http://exemplo/aula01.pdf",
        autor="Docente Exemplo",
    )

    assert registro.numero_aula == 1
    assert registro.vinculo_fonte == "site"
    assert registro.origem_url.endswith("aula01.pdf")
    assert registro.autor == "Docente Exemplo"
    assert [r["sha256"] for r in pdfs_por_numero_aula("MAT1", 1)] == [registro.sha256]
    assert pdfs_sem_vinculo("MAT1") == []


def test_arquivo_renomeado_atualiza_o_caminho_em_vez_de_apontar_para_o_vazio(inbox_dir):
    original = _pdf_simples(inbox_dir / "MAT1" / "pdfs" / "atuais" / "slides" / "sec02.pdf")
    registro = registrar_pdf(original, disciplina="MAT1")

    novo = original.parent / "aula01-sec02.pdf"
    original.rename(novo)
    assert registrar_pdf(novo, disciplina="MAT1") is None  # mesmo conteúdo, não é novo

    linha = pdf_por_sha(registro.sha256)
    assert linha["caminho"] == str(novo)
    assert linha["nome_arquivo"] == "aula01-sec02.pdf"


def test_revarredura_completa_o_vinculo_que_faltava(inbox_dir):
    caminho = _pdf_simples(inbox_dir / "MAT1" / "pdfs" / "atuais" / "notas" / "aula07.pdf")
    registro = registrar_pdf(caminho, disciplina="MAT1")
    assert registro.numero_aula is None

    registrar_pdf(caminho, disciplina="MAT1", numero_aula=7, vinculo_fonte="site")

    linha = pdf_por_sha(registro.sha256)
    assert linha["numero_aula"] == 7
    assert linha["vinculo_fonte"] == "site"
