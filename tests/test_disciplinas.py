import tomllib

import pytest

from core.config import get_settings
from projetos.estudos.disciplinas import (
    Disciplina,
    DisciplinaDesconhecida,
    Docente,
    Horario,
    Registro,
    RegistroAusente,
    RegistroInvalido,
    arquivar,
    autoria_de_docente_atual,
    caminho_registro,
    caminho_registro_legado,
    carregar_registro,
    criar_registro_exemplo,
    disciplina,
    disciplinas_ativas,
    docentes_atuais,
    nomes_conhecidos,
    perfil_de,
    registrar_docente,
    salvar_registro,
    sigla_valida,
)


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


def _registro_exemplo() -> Registro:
    return Registro(
        semestre_atual="2030.2",
        disciplinas=[
            Disciplina(
                nome="MAT1",
                titulo="Matemática Discreta",
                semestre="2030.2",
                monitoria=True,
                docentes=[Docente(nome="Maria de Souza Lima", fonte="foto 013")],
                horarios=[
                    Horario(dia="seg", inicio="08:00", fim="10:00"),
                    Horario(dia="sex", inicio="08:00", fim="10:00", tipo="monitoria"),
                ],
            ),
            Disciplina(nome="FIS1", titulo="Física Geral", semestre="2030.2"),
            Disciplina(nome="ED", titulo="Estruturas de Dados", semestre="2030.1", ativa=False),
        ],
    )


def test_sigla_valida_aceita_nome_de_pasta_e_recusa_acento_e_espaco():
    assert sigla_valida("MAT1")
    assert sigla_valida("ALEMAO-A1.1")
    assert not sigla_valida("Visualização")
    assert not sigla_valida("VIS DADOS")
    assert not sigla_valida("")


def test_carregar_sem_registro_orienta_a_criar():
    with pytest.raises(RegistroAusente, match="disciplinas --exemplo"):
        carregar_registro()


def test_round_trip_preserva_docentes_e_horarios():
    salvar_registro(_registro_exemplo())
    lido = carregar_registro()

    mat1 = next(d for d in lido.disciplinas if d.nome == "MAT1")
    assert mat1.titulo == "Matemática Discreta"
    assert mat1.monitoria is True
    assert [h.tipo for h in mat1.horarios] == ["aula", "monitoria"]
    assert mat1.docentes[0].fonte == "foto 013"


def test_disciplinas_ativas_filtra_semestre_e_arquivadas():
    salvar_registro(_registro_exemplo())

    ativas = {d.nome for d in disciplinas_ativas()}
    assert ativas == {"MAT1", "FIS1"}

    assert disciplinas_ativas("2030.1") == []


def test_disciplina_desconhecida_lista_as_conhecidas():
    salvar_registro(_registro_exemplo())

    with pytest.raises(DisciplinaDesconhecida, match="MAT1"):
        disciplina("NAOEXISTE")


def test_nomes_conhecidos_none_sem_registro_e_conjunto_com_registro():
    assert nomes_conhecidos() is None

    salvar_registro(_registro_exemplo())
    assert nomes_conhecidos() == {"MAT1", "FIS1", "ED"}


def test_docentes_atuais_ignora_disciplina_arquivada():
    registro = _registro_exemplo()
    registro.disciplinas[2].docentes = [Docente(nome="Outro Professor")]
    salvar_registro(registro)

    assert [d.nome for d in docentes_atuais("MAT1")] == ["Maria de Souza Lima"]
    assert docentes_atuais("ED") == []


def test_registrar_docente_nao_duplica_por_variacao_de_acento_e_caixa():
    salvar_registro(_registro_exemplo())

    registrar_docente("MAT1", Docente(nome="MARIA DE SOUZA LIMA"))
    assert len(disciplina("MAT1").docentes) == 1

    registrar_docente("MAT1", Docente(nome="João Monitor", papel="monitor"))
    assert len(disciplina("MAT1").docentes) == 2


def test_autoria_de_docente_atual_casa_por_sobrenome():
    salvar_registro(_registro_exemplo())

    assert autoria_de_docente_atual("MAT1", "M. S. Lima — notas de aula")
    assert autoria_de_docente_atual("MAT1", "souza")
    assert not autoria_de_docente_atual("MAT1", "Cormen")
    assert not autoria_de_docente_atual("MAT1", None)
    # partícula curta não pode casar sozinha
    assert not autoria_de_docente_atual("MAT1", "Pedro de Andrade")


def test_arquivar_tira_da_lista_de_ativas():
    salvar_registro(_registro_exemplo())

    arquivar("FIS1")
    assert {d.nome for d in disciplinas_ativas()} == {"MAT1"}


def test_criar_registro_exemplo_nao_sobrescreve_registro_existente():
    salvar_registro(_registro_exemplo())

    criado, caminho = criar_registro_exemplo()
    assert criado is False
    assert caminho == str(caminho_registro())
    assert {d.nome for d in carregar_registro().disciplinas} == {"MAT1", "FIS1", "ED"}


def test_criar_registro_exemplo_gera_toml_valido_quando_nao_existe():
    criado, _ = criar_registro_exemplo()
    assert criado is True

    dados = tomllib.loads(caminho_registro().read_text(encoding="utf-8"))
    assert dados["disciplinas"][0]["nome"] == "EXEMPLO"
    assert carregar_registro().semestre_atual == "2030.1"


def test_toml_aceita_comentario_do_usuario():
    """A razão de existir do TOML aqui: o registro é editado à mão."""
    salvar_registro(_registro_exemplo())
    caminho = caminho_registro()
    caminho.write_text(
        "# monitoria confirmada até 01/01/2026\n" + caminho.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    assert {d.nome for d in carregar_registro().disciplinas} == {"MAT1", "FIS1", "ED"}


def test_toml_quebrado_diz_o_arquivo_e_o_erro_em_vez_de_traceback():
    caminho = caminho_registro()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text('semestre_atual = "2030.2"\n[[disciplinas]\nnome = "X"\n', encoding="utf-8")

    with pytest.raises(RegistroInvalido, match="TOML inválido"):
        carregar_registro()


def test_campo_invalido_aponta_o_campo():
    caminho = caminho_registro()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        'semestre_atual = "2030.2"\n\n[[disciplinas]]\nnome = "X"\n'
        'titulo = "Y"\nsemestre = "2030.2"\ntipo = "palestra"\n',
        encoding="utf-8",
    )

    with pytest.raises(RegistroInvalido, match="tipo"):
        carregar_registro()


def test_json_legado_e_migrado_para_toml_sem_perder_nada():
    import json as _json

    legado = caminho_registro_legado()
    legado.parent.mkdir(parents=True, exist_ok=True)
    legado.write_text(
        _json.dumps(_registro_exemplo().model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    registro = carregar_registro()

    assert {d.nome for d in registro.disciplinas} == {"MAT1", "FIS1", "ED"}
    assert caminho_registro().exists()
    # o original fica onde está, para conferência
    assert legado.exists()


def test_perfil_derivado_do_tipo_e_sobrescrevivel():
    registro = _registro_exemplo()
    registro.disciplinas.append(
        Disciplina(nome="GRUPO", titulo="Reunião do grupo", semestre="2030.2", tipo="reuniao")
    )
    registro.disciplinas[1].perfil = "idioma"
    salvar_registro(registro)

    assert perfil_de("GRUPO") == "reuniao"
    assert perfil_de("FIS1") == "idioma"
    assert perfil_de("MAT1") == "tecnica"
    # disciplina fora do registro não quebra: cai no perfil padrão
    assert perfil_de("NAOEXISTE") == "tecnica"


def test_disciplinas_ativas_separa_disciplina_de_reuniao():
    registro = _registro_exemplo()
    registro.disciplinas.append(
        Disciplina(nome="GRUPO", titulo="Reunião do grupo", semestre="2030.2", tipo="reuniao")
    )
    salvar_registro(registro)

    assert {d.nome for d in disciplinas_ativas(tipo="disciplina")} == {"MAT1", "FIS1"}
    assert {d.nome for d in disciplinas_ativas(tipo="reuniao")} == {"GRUPO"}
    assert len(disciplinas_ativas()) == 3


def test_horario_guarda_local_e_fim_da_recorrencia():
    registro = _registro_exemplo()
    registro.disciplinas[0].horarios[1].ate = "2026-01-01"
    registro.disciplinas[0].horarios[0].local = "IMPARH"
    salvar_registro(registro)

    mat1 = disciplina("MAT1")
    assert mat1.horarios[0].local == "IMPARH"
    assert mat1.horarios[1].ate == "2026-01-01"
    assert mat1.horarios[1].periodicidade == "semanal"


def test_notas_do_usuario_sobrevivem_ao_round_trip():
    registro = _registro_exemplo()
    registro.disciplinas[0].notas = "professor falou que a AP1 pode mudar de data"
    salvar_registro(registro)

    assert "AP1 pode mudar" in disciplina("MAT1").notas
