import pytest

from core.config import get_settings
from core.estado import (
    conectar,
    editar_compromisso,
    historico_compromisso,
    listar_compromissos,
    mudar_status_compromisso,
    registrar_compromisso,
)


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "logs").mkdir()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ap1(**extra) -> str:
    return registrar_compromisso(
        chave=extra.pop("chave", "MAT1:prova:AP1"),
        disciplina="MAT1",
        tipo="prova",
        titulo="AP1",
        data=extra.pop("data", "2026-08-31"),
        **extra,
    )


def test_cada_transicao_vira_uma_linha_no_log():
    id_ = _ap1()

    mudar_status_compromisso(id_, "confirmado")
    mudar_status_compromisso(id_, "concluido")

    acoes = [linha["acao"] for linha in historico_compromisso(id_)]
    assert acoes == ["concluido", "confirmado"]  # mais recente primeiro


def test_log_guarda_de_onde_para_onde_e_a_origem():
    id_ = _ap1()

    mudar_status_compromisso(id_, "confirmado", origem="web")

    linha = historico_compromisso(id_)[0]
    assert (linha["de"], linha["para"], linha["origem"]) == (
        "proposto",
        "confirmado",
        "web",
    )


def test_status_repetido_nao_polui_o_log():
    id_ = _ap1()
    mudar_status_compromisso(id_, "confirmado")

    mudar_status_compromisso(id_, "confirmado")

    assert len(historico_compromisso(id_)) == 1


def test_status_invalido_e_recusado():
    id_ = _ap1()

    with pytest.raises(ValueError, match="status inválido"):
        mudar_status_compromisso(id_, "quase_pronto")


def test_concluido_e_um_status_valido():
    id_ = _ap1()

    mudar_status_compromisso(id_, "concluido")

    assert listar_compromissos(status="concluido")[0]["id"] == id_


def test_editar_marca_o_campo_e_registra_no_log():
    id_ = _ap1()

    editar_compromisso(id_, data="2026-09-02", titulo="AP1 (adiada)")

    linha = conectar().execute("SELECT * FROM compromissos WHERE id=?", (id_,)).fetchone()
    assert linha["data"] == "2026-09-02"
    acoes = {evento["acao"] for evento in historico_compromisso(id_)}
    assert acoes == {"editou:data", "editou:titulo"}


def test_reextracao_nao_desfaz_a_edicao_manual():
    """Corrigir a data de uma prova e depois reprocessar a aula devolveria a data errada,
    e a correção sumiria sem aviso."""
    id_ = _ap1(data="2026-08-31")
    editar_compromisso(id_, data="2026-09-02")

    # a mesma aula é reprocessada e o agente extrai de novo a data original
    _ap1(data="2026-08-31")

    linha = conectar().execute("SELECT * FROM compromissos WHERE id=?", (id_,)).fetchone()
    assert linha["data"] == "2026-09-02"


def test_reextracao_ainda_atualiza_campo_nao_editado():
    id_ = _ap1(data="2026-08-31")
    editar_compromisso(id_, data="2026-09-02")

    registrar_compromisso(
        chave="MAT1:prova:AP1",
        disciplina="MAT1",
        tipo="prova",
        titulo="AP1 — sala 15",
        data="2026-08-31",
    )

    linha = conectar().execute("SELECT * FROM compromissos WHERE id=?", (id_,)).fetchone()
    assert linha["titulo"] == "AP1 — sala 15"  # título não foi editado à mão
    assert linha["data"] == "2026-09-02"  # data foi


def test_campo_fora_da_lista_e_recusado():
    id_ = _ap1()

    with pytest.raises(ValueError, match="não editável"):
        editar_compromisso(id_, status="concluido")


def test_editar_sem_mudanca_nao_registra_nada():
    id_ = _ap1(data="2026-08-31")

    editar_compromisso(id_, data="2026-08-31")

    assert historico_compromisso(id_) == []


def test_semeadura_do_passado_roda_uma_vez_so():
    """O log nasceu depois dos compromissos: o histórico anterior é deduzido, e deduzir
    duas vezes duplicaria cada linha."""
    id_ = _ap1()
    mudar_status_compromisso(id_, "confirmado")
    antes = len(historico_compromisso(id_))

    conectar()  # reconectar dispara as migrações de novo
    conectar()

    assert len(historico_compromisso(id_)) == antes


def test_historico_geral_junta_titulo_e_disciplina():
    id_ = _ap1()
    mudar_status_compromisso(id_, "confirmado")

    linha = historico_compromisso()[0]

    assert linha["titulo"] == "AP1"
    assert linha["disciplina"] == "MAT1"
