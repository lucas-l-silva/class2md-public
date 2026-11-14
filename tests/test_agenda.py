from unittest.mock import patch

import pytest

from core.config import get_settings
from core.estado import compromisso_por_prefixo_id, listar_compromissos
from projetos.estudos.agenda import (
    DataImplausivel,
    adicionar_manual,
    chave_de,
    confirmar,
    data_plausivel,
    descartar,
    extrair,
    proximas_ocorrencias,
    trecho_e_literal,
)
from projetos.estudos.agentes import AgenteCompromissos
from projetos.estudos.schemas import CompromissoExtraido, SaidaCompromissos


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


MATERIAL = (
    "- (texto) 5 grandes partes [administrativo]\n"
    "- (texto) AP1 31/08 [administrativo, prova]\n"
    "- (texto) monitorias -> sexta 8-10 [administrativo]\n"
)
ANCORA = "2026-08-10"


def _saida(*compromissos):
    return SaidaCompromissos(compromissos=list(compromissos), confianca=0.9)


def _ap1(**overrides):
    campos = dict(
        tipo="prova",
        titulo="AP1",
        data="2026-08-31",
        hora=None,
        recorrencia=None,
        origem_trecho="AP1 31/08",
        confianca=0.9,
    )
    campos.update(overrides)
    return CompromissoExtraido(**campos)


def test_trecho_e_literal_tolera_espaco_e_acento_mas_nao_parafrase():
    assert trecho_e_literal("AP1  31/08", MATERIAL)
    assert trecho_e_literal("MONITORIAS -> SEXTA 8-10", MATERIAL)
    assert not trecho_e_literal("a primeira prova será no fim de agosto", MATERIAL)
    assert not trecho_e_literal("   ", MATERIAL)


def test_data_plausivel_recusa_passado_distante_e_futuro_distante():
    assert data_plausivel("2026-08-31", ANCORA)
    assert data_plausivel(None, ANCORA)
    assert not data_plausivel("2025-08-31", ANCORA)
    assert not data_plausivel("2028-08-31", ANCORA)
    assert not data_plausivel("31/08/2026", ANCORA)


def test_extrair_sem_material_nao_chama_llm():
    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        resultado = extrair("job-1", "MAT1", ANCORA, "   ")

    mock_chamar.assert_not_called()
    assert resultado.propostos == []


def test_compromissos_nascem_propostos_com_o_trecho_de_origem():
    saida = _saida(
        _ap1(),
        CompromissoExtraido(
            tipo="monitoria",
            titulo="Monitoria de MAT1",
            data="2026-08-14",
            hora="08:00",
            recorrencia="semanal-sex",
            origem_trecho="monitorias -> sexta 8-10",
            confianca=0.8,
        ),
    )

    with patch.object(AgenteCompromissos, "run", return_value=saida):
        resultado = extrair("job-1", "MAT1", ANCORA, MATERIAL)

    assert len(resultado.propostos) == 2
    linhas = listar_compromissos(disciplina="MAT1")
    assert {linha["status"] for linha in linhas} == {"proposto"}
    ap1 = next(linha for linha in linhas if linha["titulo"] == "AP1")
    assert ap1["data"] == "2026-08-31"
    assert ap1["origem_trecho"] == "AP1 31/08"
    assert ap1["origem_job"] == "job-1"


def test_guardrail_descarta_trecho_parafraseado():
    saida = _saida(_ap1(origem_trecho="a prova será dia 31 de agosto"))

    with patch.object(AgenteCompromissos, "run", return_value=saida):
        resultado = extrair("job-1", "MAT1", ANCORA, MATERIAL)

    assert resultado.propostos == []
    assert "literalmente" in resultado.descartados[0][1]
    assert listar_compromissos() == []


def test_guardrail_descarta_data_fora_da_janela():
    saida = _saida(_ap1(data="2020-08-31"))

    with patch.object(AgenteCompromissos, "run", return_value=saida):
        resultado = extrair("job-1", "MAT1", ANCORA, MATERIAL)

    assert resultado.propostos == []
    assert "fora da janela" in resultado.descartados[0][1]


def test_guardrail_descarta_sem_data_e_sem_recorrencia():
    saida = _saida(_ap1(data=None))

    with patch.object(AgenteCompromissos, "run", return_value=saida):
        resultado = extrair("job-1", "MAT1", ANCORA, MATERIAL)

    assert resultado.propostos == []
    assert "sem data e sem recorrência" in resultado.descartados[0][1]


def test_reextrair_nao_duplica_nem_ressuscita_o_que_foi_descartado():
    saida = _saida(_ap1())

    with patch.object(AgenteCompromissos, "run", return_value=saida):
        primeira = extrair("job-1", "MAT1", ANCORA, MATERIAL)
    descartar(primeira.propostos[0])

    with patch.object(AgenteCompromissos, "run", return_value=saida):
        segunda = extrair("job-1", "MAT1", ANCORA, MATERIAL)

    assert segunda.propostos == primeira.propostos
    linhas = listar_compromissos(disciplina="MAT1")
    assert len(linhas) == 1
    assert linhas[0]["status"] == "descartado"


def test_confirmar_muda_status_e_so_confirmados_saem_no_filtro():
    saida = _saida(_ap1())
    with patch.object(AgenteCompromissos, "run", return_value=saida):
        resultado = extrair("job-1", "MAT1", ANCORA, MATERIAL)

    assert listar_compromissos(status="confirmado") == []
    confirmar(resultado.propostos[0])
    assert len(listar_compromissos(status="confirmado")) == 1


def test_adicionar_manual_ja_nasce_confirmado():
    id_compromisso = adicionar_manual("FIS1", "prova", "AP1", data="2026-09-15")

    linha = compromisso_por_prefixo_id(id_compromisso[:8])
    assert linha["status"] == "confirmado"
    assert linha["origem_trecho"] == "digitado à mão"


def test_adicionar_manual_recusa_data_malformada():
    with pytest.raises(DataImplausivel):
        adicionar_manual("FIS1", "prova", "AP1", data="15/09/2026")


def test_chave_ignora_acento_e_caixa_do_titulo():
    assert chave_de("MAT1", "prova", "2026-08-31", "Avaliação 1") == chave_de(
        "MAT1", "prova", "2026-08-31", "AVALIACAO  1"
    )


def test_proximas_ocorrencias_expande_recorrencia_semanal():
    datas = proximas_ocorrencias("semanal-sex", "2026-08-10", quantas=3)

    assert datas == ["2026-08-14", "2026-08-21", "2026-08-28"]


def test_proximas_ocorrencias_quinzenal_e_formato_desconhecido():
    assert proximas_ocorrencias("quinzenal-sab", "2026-08-10", quantas=2) == [
        "2026-08-15",
        "2026-08-29",
    ]
    assert proximas_ocorrencias("as vezes", "2026-08-10") == []
    assert proximas_ocorrencias("semanal-sex", "data ruim") == []


def test_recorrencia_aceita_dia_por_extenso():
    """O agente grava "semanal-sexta" tanto quanto "semanal-sex"; exigir uma das formas
    fez a monitoria da MAT1 passar dias sem aparecer no calendário."""
    from projetos.estudos.agenda import proximas_ocorrencias

    abreviado = proximas_ocorrencias("semanal-sex", "2026-08-14", 3)
    extenso = proximas_ocorrencias("semanal-sexta", "2026-08-14", 3)

    assert abreviado == extenso == ["2026-08-14", "2026-08-21", "2026-08-28"]


def test_recorrencia_aceita_acento_e_maiuscula():
    from projetos.estudos.agenda import proximas_ocorrencias

    assert proximas_ocorrencias("semanal-Terça", "2026-08-11", 2) == [
        "2026-08-11",
        "2026-08-18",
    ]
    assert proximas_ocorrencias("semanal-terca", "2026-08-11", 2) == [
        "2026-08-11",
        "2026-08-18",
    ]


def test_dia_desconhecido_continua_devolvendo_vazio():
    from projetos.estudos.agenda import proximas_ocorrencias

    assert proximas_ocorrencias("semanal-lua-cheia", "2026-08-14", 2) == []
