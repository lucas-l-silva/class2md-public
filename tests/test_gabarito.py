from pathlib import Path

import pytest

from core.config import get_settings
from projetos.estudos.biblioteca import LivroNaoEncontrado, livro_da_disciplina
from projetos.estudos.gabarito import (
    gabaritos_da_disciplina,
    indice_de_solucoes,
    localizar,
    localizar_capitulos,
    secao_onde_conferir,
)
from projetos.estudos.pdf_ingestao import registrar_pdf
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


def _gabarito(pdfs_dir: Path):
    caminho = pdfs_dir / "MAT1" / "Solutions Manual for Introduction to Algorithms.pdf"
    criar_pdf(
        caminho,
        paginas=4,
        texto_por_pagina=[
            "Chapter 1\nExercise 1.1-1\nUm exemplo qualquer de ordenação no mundo real.",
            "Exercise 1.2-1\nUm programa que escolhe música.\nExercise 1.2-2\nOutra resposta.",
            "Chapter 2\nExercise 2.1-1\n31 41 59 26 41 58\nExercise 2.1-2\nAlgoritmo não crescente.",
            "Problem 2-2\nBubblesort é correto porque ...",
        ],
    )
    return registrar_pdf(caminho, disciplina="MAT1")


def test_solutions_manual_e_classificado_como_gabarito(pdfs_dir):
    registro = _gabarito(pdfs_dir)

    assert registro.tipo == "gabarito"
    assert [r.nome_arquivo for r in gabaritos_da_disciplina("MAT1")] == [registro.nome_arquivo]


def test_gabarito_nao_conta_como_livro_da_disciplina(pdfs_dir):
    """Sem isso, o manual de soluções seria escolhido como livro-texto."""
    _gabarito(pdfs_dir)

    with pytest.raises(LivroNaoEncontrado, match="nenhum livro registrado"):
        livro_da_disciplina("MAT1")


def test_indice_de_solucoes_mapeia_exercicio_para_pagina(pdfs_dir):
    registro = _gabarito(pdfs_dir)

    indice = indice_de_solucoes(registro)

    assert indice["1.1-1"] == 1
    assert indice["1.2-2"] == 2
    assert indice["2.1-1"] == 3
    assert indice["2-2"] == 4


def test_indice_e_cacheado_e_nao_reabre_o_pdf(pdfs_dir, monkeypatch):
    registro = _gabarito(pdfs_dir)
    indice_de_solucoes(registro)

    import projetos.estudos.gabarito as mod

    def _explode(*args, **kwargs):
        raise AssertionError("não deveria reabrir o PDF")

    monkeypatch.setattr(mod, "texto_paginas", _explode)

    assert indice_de_solucoes(registro)["2.1-1"] == 3


def test_localizar_devolve_arquivo_referencia_e_pagina(pdfs_dir):
    _gabarito(pdfs_dir)

    achados = localizar("MAT1", ["2.1-1", "9.9-9"])

    assert len(achados) == 1
    assert achados[0].referencia == "2.1-1"
    assert achados[0].pagina == 3
    assert "p. 3" in str(achados[0])


def test_localizar_capitulos_filtra_pelo_numero_do_capitulo(pdfs_dir):
    _gabarito(pdfs_dir)

    do_dois = localizar_capitulos("MAT1", [2])

    assert {loc.referencia for loc in do_dois} == {"2.1-1", "2.1-2", "2-2"}
    assert localizar_capitulos("MAT1", [7]) == []


def test_secao_onde_conferir_aponta_sem_copiar_a_solucao(pdfs_dir):
    _gabarito(pdfs_dir)

    secao = secao_onde_conferir(localizar("MAT1", ["2.1-1"]))

    assert "Onde conferir a solução" in secao
    assert "p. 3" in secao
    # o conteúdo da solução nunca aparece
    assert "31 41 59" not in secao
    assert secao_onde_conferir([]) == ""


def test_gabarito_dentro_da_pasta_de_livros_ainda_e_gabarito(pdfs_dir):
    """A pasta diz onde o arquivo está; o nome diz o que ele é."""
    caminho = pdfs_dir / "MAT1" / "livros" / "Solutions Manual (CLRS).pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="Exercise 1.1-1\nresposta")

    registro = registrar_pdf(caminho, disciplina="MAT1")

    assert registro.tipo == "gabarito"


def test_gabarito_de_prova_dentro_da_pasta_de_provas_tambem(pdfs_dir):
    caminho = pdfs_dir / "MAT1" / "provas" / "GABARITO AP1 - MAT1 - 2021.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="resposta da questão 1")

    assert registrar_pdf(caminho, disciplina="MAT1").tipo == "gabarito"


def test_tipo_explicito_ainda_vence_o_nome(pdfs_dir):
    caminho = pdfs_dir / "MAT1" / "Solutions Manual (CLRS).pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="x")

    assert registrar_pdf(caminho, tipo="livro", disciplina="MAT1").tipo == "livro"
