import json
from datetime import UTC, datetime

import pytest

from core.config import get_settings
from core.logging import registrar_evento


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    (tmp_path / "logs").mkdir()
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_evento_gravado_uma_linha_json_valido_com_ts():
    registrar_evento(job="teste", passo="p0.2", resultado="ok")

    settings = get_settings()
    arquivos = list(settings.logs_dir.glob("*.jsonl"))
    assert len(arquivos) == 1

    linhas = arquivos[0].read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 1

    evento = json.loads(linhas[0])
    assert "ts" in evento


def test_dois_eventos_geram_duas_linhas():
    registrar_evento(job="teste", passo="p0.2", resultado="ok")
    registrar_evento(job="teste", passo="p0.2", resultado="ok")

    settings = get_settings()
    arquivo = next(settings.logs_dir.glob("*.jsonl"))
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2


def test_acento_preservado():
    registrar_evento(job="teste", passo="p0.2", resultado="ação com acentuação")

    settings = get_settings()
    arquivo = next(settings.logs_dir.glob("*.jsonl"))
    conteudo = arquivo.read_text(encoding="utf-8")
    assert "ação com acentuação" in conteudo
    assert "\\u00e3" not in conteudo


def test_campo_nao_passado_nao_aparece():
    registrar_evento(job="teste", passo="p0.2", resultado="ok")

    settings = get_settings()
    arquivo = next(settings.logs_dir.glob("*.jsonl"))
    evento = json.loads(arquivo.read_text(encoding="utf-8").splitlines()[0])

    assert "aviso" not in evento
    assert "tokens_in" not in evento
    assert "duracao_ms" not in evento


def test_ts_fornecido_manualmente_e_respeitado():
    ts_manual = "2020-01-01T00:00:00+00:00"
    registrar_evento(ts=ts_manual, job="teste", passo="p0.2", resultado="ok")

    settings = get_settings()
    arquivo = next(settings.logs_dir.glob("*.jsonl"))
    evento = json.loads(arquivo.read_text(encoding="utf-8").splitlines()[0])

    assert evento["ts"] == ts_manual


def test_nome_do_arquivo_e_data_de_hoje_em_utc():
    registrar_evento(job="teste", passo="p0.2", resultado="ok")

    settings = get_settings()
    esperado = datetime.now(UTC).strftime("%Y-%m-%d") + ".jsonl"
    arquivos = list(settings.logs_dir.glob("*.jsonl"))

    assert len(arquivos) == 1
    assert arquivos[0].name == esperado
