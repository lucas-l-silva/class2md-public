import pytest

from core.config import get_settings
from projetos.estudos.programa import (
    aula_por_numero,
    carregar,
    indice_resumido,
    mesclar,
    normalizar_titulo,
    registrar_data,
    salvar,
    titulos,
)
from projetos.estudos.schemas import AulaPrograma, MaterialPrograma, Programa


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "estudos" / "index").mkdir(parents=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _programa_mat1() -> Programa:
    return Programa(
        disciplina="MAT1",
        titulo_oficial="Matemática Discreta",
        fonte_url="http://exemplo/mat1/",
        aulas=[
            AulaPrograma(
                numero=1,
                titulo="Algoritmos básicos de ordenação",
                topicos=["seleção", "bolha", "inserção"],
                materiais=[
                    MaterialPrograma(nome="aula01.pdf", tipo="notas", url="http://x/aula01.pdf")
                ],
            ),
            AulaPrograma(numero=2, titulo="Acelerando o algoritmo da bolha"),
        ],
    )


def test_round_trip_no_index_da_disciplina():
    salvar(_programa_mat1())
    lido = carregar("MAT1")

    assert lido is not None
    assert titulos(lido) == {
        1: "Algoritmos básicos de ordenação",
        2: "Acelerando o algoritmo da bolha",
    }
    assert lido.aulas[0].materiais[0].nome == "aula01.pdf"
    assert carregar("FIS1") is None


def test_aula_por_numero_e_indice_resumido():
    programa = _programa_mat1()

    assert aula_por_numero(programa, 1).titulo == "Algoritmos básicos de ordenação"
    assert aula_por_numero(programa, 99) is None

    resumo = indice_resumido(programa)
    assert "01 — Algoritmos básicos de ordenação (seleção; bolha; inserção)" in resumo
    assert "02 — Acelerando o algoritmo da bolha" in resumo


def test_mesclar_preserva_a_data_que_o_site_nao_conhece():
    antigo = _programa_mat1()
    antigo.aulas[0].data = "2026-08-10"
    novo = _programa_mat1()
    novo.aulas[0].titulo = "Algoritmos básicos de ordenação (revisado)"

    resultado = mesclar(antigo, novo)

    assert resultado.aulas[0].titulo.endswith("(revisado)")
    assert resultado.aulas[0].data == "2026-08-10"


def test_mesclar_mantem_aula_que_so_existe_no_programa_antigo():
    antigo = _programa_mat1()
    antigo.aulas.append(AulaPrograma(numero=9, titulo="Aula que eu anotei à mão"))
    novo = _programa_mat1()

    resultado = mesclar(antigo, novo)

    assert [aula.numero for aula in resultado.aulas] == [1, 2, 9]


def test_mesclar_sem_programa_anterior_devolve_o_novo():
    novo = _programa_mat1()
    assert mesclar(None, novo) is novo


def test_registrar_data_liga_nota_ao_numero_da_aula():
    salvar(_programa_mat1())

    registrar_data("MAT1", 1, "2026-08-10")

    assert carregar("MAT1").aulas[0].data == "2026-08-10"


def test_registrar_data_em_aula_inexistente_nao_quebra():
    salvar(_programa_mat1())

    resultado = registrar_data("MAT1", 42, "2026-08-10")

    assert resultado is not None
    assert all(aula.data is None for aula in carregar("MAT1").aulas)
    assert registrar_data("FIS1", 1, "2026-08-10") is None


def test_normalizar_titulo_remove_acento_e_palavra_vazia():
    tokens = normalizar_titulo("Algoritmos básicos de ordenação")

    assert tokens == {"algoritmos", "basicos", "ordenacao"}
    # o casamento com a nota real da MAT1 depende dessa interseção
    assert tokens & normalizar_titulo("Algoritmos de Ordenação: Seleção, Bolha e Inserção")
