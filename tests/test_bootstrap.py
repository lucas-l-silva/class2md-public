from pathlib import Path

import pytest
from typer.testing import CliRunner

from core.config import get_settings
from scripts.bootstrap import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch, tmp_path):
    casa = tmp_path / "casa"
    casa.mkdir()
    monkeypatch.setenv("HOME", str(casa))
    for nome in ("CLASS2MD_HOME", "AGENT_DATA_DIR", "STAGING_DIR", "CACHE_DIR", "LOGS_DIR"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    projeto = tmp_path / "projeto"
    projeto.mkdir()
    monkeypatch.chdir(projeto)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_bootstrap_usa_class2md_home(monkeypatch, tmp_path):
    destino = tmp_path / "x"
    monkeypatch.setenv("CLASS2MD_HOME", str(destino))

    resultado = runner.invoke(app, [])

    assert resultado.exit_code == 0, resultado.stdout
    assert (destino / "estudos" / "inbox").is_dir()
    assert not (Path.home() / "agent-data").exists()


def test_bootstrap_le_env_do_projeto(tmp_path):
    destino = tmp_path / "dados-do-env"
    Path(".env").write_text(f"CLASS2MD_HOME={destino}\nANTHROPIC_API_KEY=k\n")

    resultado = runner.invoke(app, [])

    assert resultado.exit_code == 0, resultado.stdout
    assert (destino / "estudos" / "output").is_dir()


def test_bootstrap_nao_reclama_de_segredos_com_env_local(tmp_path):
    Path(".env").write_text(f"CLASS2MD_HOME={tmp_path / 'd'}\nANTHROPIC_API_KEY=k\n")

    resultado = runner.invoke(app, ["--dry-run"])

    assert "não achei o arquivo com a chave" not in resultado.stdout


def test_bootstrap_avisa_quando_nao_ha_arquivo_de_chave(tmp_path):
    resultado = runner.invoke(app, ["--dry-run"])

    assert "não achei o arquivo com a chave" in resultado.stdout


def test_bootstrap_cria_trash_e_arquivo(monkeypatch, tmp_path):
    monkeypatch.setenv("CLASS2MD_HOME", str(tmp_path / "y"))

    runner.invoke(app, [])

    assert (tmp_path / "y" / "estudos" / "trash").is_dir()
    assert (tmp_path / "y" / "estudos" / "arquivo").is_dir()
