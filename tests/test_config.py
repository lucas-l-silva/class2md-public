from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import ConfigInvalido, Settings


def test_anthropic_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_cache_dir_home(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", " ")
    monkeypatch.setenv("CACHE_DIR", str(Path.home()))

    with pytest.raises(ConfigInvalido):
        Settings()


def test_cache_dir_invalid(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", " ")
    monkeypatch.setenv("CACHE_DIR", "/")

    with pytest.raises(ConfigInvalido):
        Settings()


def test_class2md_home_define_pasta_de_dados(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("AGENT_DATA_DIR", raising=False)
    monkeypatch.setenv("CLASS2MD_HOME", str(tmp_path))
    for v in ("STAGING_DIR", "CACHE_DIR", "LOGS_DIR"):
        monkeypatch.delenv(v, raising=False)

    cfg = Settings(_env_file=None)

    assert cfg.agent_data_dir == tmp_path
    assert cfg.staging_dir == tmp_path / "estudos" / "output"


def test_agent_data_dir_continua_valendo(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("CLASS2MD_HOME", raising=False)
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))

    assert Settings(_env_file=None).agent_data_dir == tmp_path


def test_env_na_pasta_do_projeto(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLASS2MD_HOME", raising=False)
    monkeypatch.delenv("AGENT_DATA_DIR", raising=False)
    dados = tmp_path / "dados"
    dados.mkdir()
    (tmp_path / ".env").write_text(f"ANTHROPIC_API_KEY=k\nCLASS2MD_HOME={dados}\n")
    monkeypatch.chdir(tmp_path)

    cfg = Settings()

    assert cfg.anthropic_api_key == "k"
    assert cfg.agent_data_dir == dados
