from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from core.agents.base import Agente
from core.config import get_settings
from core.estado import conectar, criar_job, marcar_reprocessamento
from core.llm.custos import OrcamentoExcedido, calcular_custo
from core.llm.tiers import Tier


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


class EntradaTeste(BaseModel):
    texto: str


class SaidaTeste(BaseModel):
    resultado: str


class AgenteTeste(Agente[EntradaTeste, SaidaTeste]):
    nome = "teste"
    tier = Tier.HAIKU
    Entrada = EntradaTeste
    Saida = SaidaTeste

    def __init__(self, prompt_file: Path):
        self.prompt_file = prompt_file

    def montar_mensagens(self, entrada: EntradaTeste) -> list[dict]:
        return [{"role": "user", "content": entrada.texto}]


@pytest.fixture
def agente(tmp_path) -> AgenteTeste:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("PROMPT_VERSION: 1\nVocê é um agente de teste.")
    return AgenteTeste(prompt_file)


def _resposta_mock(tokens_in: int = 100, tokens_out: int = 50, cache_read: int = 0):
    usage = SimpleNamespace(
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cache_read_input_tokens=cache_read,
    )
    return SimpleNamespace(usage=usage)


def test_cache_hit_nao_chama_a_api(agente):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (SaidaTeste(resultado="ok"), _resposta_mock())

        primeira = agente.run(job_id, EntradaTeste(texto="oi"))
        segunda = agente.run(job_id, EntradaTeste(texto="oi"))

    assert mock_chamar.call_count == 1
    assert primeira.resultado == "ok"
    assert segunda.resultado == "ok"


def test_entrada_diferente_nao_reaproveita_cache(agente):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (SaidaTeste(resultado="ok"), _resposta_mock())

        agente.run(job_id, EntradaTeste(texto="oi"))
        agente.run(job_id, EntradaTeste(texto="tchau"))

    assert mock_chamar.call_count == 2


def test_run_registra_custo_do_passo_na_tabela_passos(agente):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            SaidaTeste(resultado="ok"),
            _resposta_mock(tokens_in=1_000_000, tokens_out=1_000_000),
        )
        agente.run(job_id, EntradaTeste(texto="oi"))

    conn = conectar()
    passo = conn.execute(
        "SELECT * FROM passos WHERE job_id=? AND nome='teste'", (job_id,)
    ).fetchone()

    custo_esperado = calcular_custo(Tier.HAIKU, 1_000_000, 1_000_000)
    assert passo["custo_usd"] == pytest.approx(custo_esperado)
    assert passo["modelo"] == "claude-haiku-4-5-20251001"


def test_job_marcado_com_curinga_ignora_cache_e_regrava(agente):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (SaidaTeste(resultado="v1"), _resposta_mock())
        agente.run(job_id, EntradaTeste(texto="oi"))

        marcar_reprocessamento(job_id)  # "*" = todos os passos
        mock_chamar.return_value = (SaidaTeste(resultado="v2"), _resposta_mock())
        segunda = agente.run(job_id, EntradaTeste(texto="oi"))

    assert mock_chamar.call_count == 2
    assert segunda.resultado == "v2"


def test_job_marcado_com_passo_diferente_nao_afeta_este_agente(agente):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (SaidaTeste(resultado="v1"), _resposta_mock())
        agente.run(job_id, EntradaTeste(texto="oi"))

        marcar_reprocessamento(job_id, "outro_agente")
        agente.run(job_id, EntradaTeste(texto="oi"))

    assert mock_chamar.call_count == 1  # cache reaproveitado, marca não bate com self.nome


def test_job_marcado_com_nome_deste_agente_ignora_cache(agente):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (SaidaTeste(resultado="v1"), _resposta_mock())
        agente.run(job_id, EntradaTeste(texto="oi"))

        marcar_reprocessamento(job_id, agente.nome)
        agente.run(job_id, EntradaTeste(texto="oi"))

    assert mock_chamar.call_count == 2


def test_run_propaga_max_tokens_proprio_do_agente(tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("PROMPT_VERSION: 1\nVocê é um agente de teste.")

    class AgenteComTetoProprio(AgenteTeste):
        nome = "teste_teto"
        max_tokens = 8192

    agente_teto = AgenteComTetoProprio(prompt_file)
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (SaidaTeste(resultado="ok"), _resposta_mock())
        agente_teto.run(job_id, EntradaTeste(texto="oi"))

    assert mock_chamar.call_args.kwargs["max_tokens"] == 8192


def test_orcamento_excedido_bloqueia_chamada_nova(agente, monkeypatch):
    monkeypatch.setenv("TETO_MENSAL_USD", "0.01")
    get_settings.cache_clear()

    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            SaidaTeste(resultado="caro"),
            _resposta_mock(tokens_in=1_000_000, tokens_out=1_000_000),
        )
        agente.run(job_id, EntradaTeste(texto="primeira chamada estoura o teto"))
        mock_chamar.reset_mock()

        with pytest.raises(OrcamentoExcedido):
            agente.run(job_id, EntradaTeste(texto="segunda entrada, orcamento ja estourado"))

    assert mock_chamar.call_count == 0
