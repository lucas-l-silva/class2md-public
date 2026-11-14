import pytest

from core.config import get_settings
from projetos.estudos.disciplinas import (
    Coletor,
    Disciplina,
    Docente,
    Horario,
    Registro,
    salvar_registro,
)
from projetos.estudos.ementa import salvar as salvar_ementa
from projetos.estudos.moc import (
    caminho_moc,
    caminho_moc_central,
    gerar_moc_central,
    gerar_moc_disciplina,
    notas_da_disciplina,
)
from projetos.estudos.programa import salvar as salvar_programa
from projetos.estudos.remendo_nota import blocos
from projetos.estudos.schemas import (
    AulaPrograma,
    Ementa,
    ItemEmenta,
    ParteEmenta,
    Programa,
)


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "estudos" / "index").mkdir(parents=True)
    (tmp_path / "estudos" / "output" / "MAT1").mkdir(parents=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def registro():
    salvar_registro(
        Registro(
            semestre_atual="2030.2",
            disciplinas=[
                Disciplina(
                    nome="MAT1",
                    titulo="Matemática Discreta",
                    codigo="ALG0203",
                    semestre="2030.2",
                    monitoria=True,
                    docentes=[Docente(nome="Docente Exemplo")],
                    horarios=[
                        Horario(dia="seg", inicio="08:00", fim="10:00"),
                        Horario(
                            dia="sex",
                            inicio="08:00",
                            fim="10:00",
                            tipo="monitoria",
                            ate="2026-01-01",
                        ),
                    ],
                    coletor=Coletor(tipo="site_exemplo", url="http://exemplo/mat1/"),
                    a_confirmar=["sobrenome do docente"],
                ),
                Disciplina(
                    nome="GRUPO",
                    titulo="Reunião do grupo",
                    semestre="2030.2",
                    tipo="reuniao",
                    horarios=[
                        Horario(
                            dia="qua",
                            inicio="10:00",
                            fim="12:00",
                            tipo="reuniao",
                            periodicidade="quinzenal",
                        )
                    ],
                ),
            ],
        )
    )


@pytest.fixture
def nota_de_aula(tmp_path):
    caminho = tmp_path / "estudos" / "output" / "MAT1" / "2026-08-10 Aula 01 — Ordenação.md"
    caminho.write_text(
        "---\ndata: 2026-08-10\ndisciplina: MAT1\naula: 1\ntags: []\n---\n\n"
        "# Aula 1 — Ordenação\n\n"
        "## Resumo da aula\nx\n\n"
        "## Pontos de atenção do professor\n\n"
        "- **A ideia importa mais que o pseudocódigo.**\n\n"
        "## Ver também\nx\n",
        encoding="utf-8",
    )
    return caminho


def test_notas_ignora_stub_e_o_proprio_moc(tmp_path, nota_de_aula):
    pasta = tmp_path / "estudos" / "output" / "MAT1"
    (pasta / "2026-08-12 Aula — (a processar).md").write_text("stub", encoding="utf-8")
    (pasta / "MAT1 - MOC.md").write_text("moc", encoding="utf-8")

    notas = notas_da_disciplina("MAT1")

    assert [n.caminho.name for n in notas] == [nota_de_aula.name]
    assert notas[0].numero == 1
    assert notas[0].data == "2026-08-10"


def test_moc_traz_identificacao_e_pendencias(registro):
    caminho = gerar_moc_disciplina("MAT1")
    conteudo = caminho.read_text(encoding="utf-8")

    assert "| **Código** | ALG0203 |" in conteudo
    assert "Docente Exemplo" in conteudo
    assert "Segunda, 08:00–10:00" in conteudo
    assert "até 2026-01-01" in conteudo
    assert "A confirmar" in conteudo


def test_moc_nao_cita_calendario(registro):
    """O calendário não existe na versão pública: nenhum link quebrado na nota-home."""
    disciplina = gerar_moc_disciplina("MAT1").read_text(encoding="utf-8")
    central = gerar_moc_central().read_text(encoding="utf-8")

    for conteudo in (disciplina, central):
        assert "calendario" not in conteudo.lower().replace("calendário", "calendario")
        assert "file://" not in conteudo
        assert "```dataview" not in conteudo


def test_moc_cruza_programa_com_as_notas_existentes(registro, nota_de_aula):
    salvar_programa(
        Programa(
            disciplina="MAT1",
            aulas=[
                AulaPrograma(numero=1, titulo="Algoritmos básicos de ordenação"),
                AulaPrograma(numero=2, titulo="Acelerando o algoritmo da bolha"),
            ],
        )
    )

    conteudo = gerar_moc_disciplina("MAT1").read_text(encoding="utf-8")

    assert (
        "| 01 | Algoritmos básicos de ordenação | 2026-08-10 | [[2026-08-10 Aula 01 — Ordenação]] |"
        in conteudo
    )
    assert "| 02 | Acelerando o algoritmo da bolha | — | — |" in conteudo


def test_moc_agrega_pontos_de_atencao_das_notas(registro, nota_de_aula):
    conteudo = gerar_moc_disciplina("MAT1").read_text(encoding="utf-8")

    assert "A ideia importa mais que o pseudocódigo" in conteudo
    assert "[[2026-08-10 Aula 01 — Ordenação]]" in conteudo


def test_moc_mostra_ementa_com_a_fonte(registro):
    salvar_ementa(
        Ementa(
            disciplina="MAT1",
            partes=[ParteEmenta(numero=1, titulo="Ordenação", fonte="foto 013")],
            pesos=[ItemEmenta(texto="1ª prova: 15%", fonte="foto 013")],
        )
    )

    conteudo = gerar_moc_disciplina("MAT1").read_text(encoding="utf-8")

    assert "1. **Ordenação**" in conteudo
    assert "1ª prova: 15%" in conteudo
    assert "foto 013" in conteudo


def test_regerar_e_idempotente(registro, nota_de_aula):
    primeira = gerar_moc_disciplina("MAT1").read_text(encoding="utf-8")
    segunda = gerar_moc_disciplina("MAT1").read_text(encoding="utf-8")

    assert primeira == segunda


def test_texto_fora_dos_marcadores_nunca_e_tocado(registro):
    caminho = caminho_moc("MAT1")
    gerar_moc_disciplina("MAT1")
    caminho.write_text(
        caminho.read_text(encoding="utf-8") + "\n## Minhas anotações\n\nnão me apague\n",
        encoding="utf-8",
    )

    salvar_ementa(
        Ementa(disciplina="MAT1", partes=[ParteEmenta(numero=1, titulo="Nova", fonte="f")])
    )
    gerar_moc_disciplina("MAT1")

    conteudo = caminho.read_text(encoding="utf-8")
    assert "não me apague" in conteudo
    assert "1. **Nova**" in conteudo


def test_moc_central_separa_disciplina_de_reuniao(registro):
    conteudo = gerar_moc_central().read_text(encoding="utf-8")

    assert "### Disciplinas ativas" in conteudo
    assert "### Reuniões" in conteudo
    assert "GRUPO" in conteudo
    assert "ALG0203" in conteudo
    # o GRUPO aparece na grade com a marcação do tipo
    assert "(reuniao)" in conteudo


def test_blocos_gerenciados_estao_todos_presentes(registro):
    gerar_moc_disciplina("MAT1")

    chaves = set(blocos(caminho_moc("MAT1").read_text(encoding="utf-8")))

    assert chaves == {
        "identificacao",
        "ementa",
        "avaliacao",
        "bibliografia",
        "aulas",
        "pontos_de_atencao",
        "materiais",
        "conceitos",
    }

    gerar_moc_central()
    assert set(blocos(caminho_moc_central().read_text(encoding="utf-8"))) == {
        "grade_semestre",
    }


def test_fonte_aparece_uma_vez_por_bloco_nao_por_item(registro):
    salvar_ementa(
        Ementa(
            disciplina="MAT1",
            avaliacao=[
                ItemEmenta(texto="4 provas", fonte="foto 013 | manuscrito"),
                ItemEmenta(texto="1 trabalho", fonte="foto 013 | manuscrito"),
            ],
            pesos=[ItemEmenta(texto="1ª: 15%", fonte="foto 013 | manuscrito")],
        )
    )

    conteudo = gerar_moc_disciplina("MAT1").read_text(encoding="utf-8")

    assert conteudo.count("foto 013") == 1
    assert "<sub>Fonte: foto 013</sub>" in conteudo
    assert "- 4 provas\n" in conteudo


def test_bloco_com_duas_origens_lista_as_duas(registro):
    salvar_ementa(
        Ementa(
            disciplina="MAT1",
            bibliografia_basica=[
                ItemEmenta(texto="Cormen", fonte="foto 014"),
                ItemEmenta(texto="Papadimitriou", fonte="plano-de-ensino.pdf"),
            ],
        )
    )

    conteudo = gerar_moc_disciplina("MAT1").read_text(encoding="utf-8")

    assert "<sub>Fonte: foto 014; plano-de-ensino.pdf</sub>" in conteudo
