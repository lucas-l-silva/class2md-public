import pytest

from core.config import get_settings
from core.llm.tiers import Tier, modelo_do_tier, precos_do_tier


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


def test_modelo_do_tier_retorna_string_configurada():
    assert modelo_do_tier(Tier.HAIKU) == "claude-haiku-4-5-20251001"
    assert modelo_do_tier(Tier.SONNET) == "claude-sonnet-5"
    assert modelo_do_tier(Tier.OPUS) == "claude-opus-5"


def test_modelo_do_tier_e_configuravel_via_env(monkeypatch):
    monkeypatch.setenv(
        "MODELOS",
        '{"haiku": "outro-haiku", "sonnet": "outro-sonnet", "opus": "outro-opus"}',
    )
    get_settings.cache_clear()

    assert modelo_do_tier(Tier.HAIKU) == "outro-haiku"


def test_precos_do_tier_bate_com_tabela_da_secao_11():
    precos = precos_do_tier(Tier.SONNET)

    assert precos["entrada"] == 3.0
    assert precos["saida"] == 15.0
