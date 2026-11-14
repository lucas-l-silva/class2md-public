from pathlib import Path

import pytest

from core.config import get_settings
from projetos.estudos.manifesto import _ler_manifesto, registrar_nota_manifesto


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_registrar_nota_manifesto_grava_entrada_correta():
    registrar_nota_manifesto(
        "job1", Path("nota.md"), "a_processar", ["a.jpg"], "2026-08-02T00:00:00"
    )

    manifesto = _ler_manifesto()

    assert manifesto["job1"]["caminho_nota"] == "nota.md"
    assert manifesto["job1"]["status"] == "a_processar"
    assert manifesto["job1"]["fotos"] == ["a.jpg"]
    assert manifesto["job1"]["criado_em"] == "2026-08-02T00:00:00"


def test_rodar_duas_vezes_nao_duplica_entrada():
    registrar_nota_manifesto(
        "job1", Path("nota.md"), "a_processar", ["a.jpg"], "2026-08-02T00:00:00"
    )
    registrar_nota_manifesto(
        "job1",
        Path("nota.md"),
        "a_processar",
        ["a.jpg", "b.jpg"],
        "2026-08-02T00:00:00",
    )

    manifesto = _ler_manifesto()

    assert len(manifesto) == 1
    assert manifesto["job1"]["fotos"] == ["a.jpg", "b.jpg"]


def test_registrar_nota_manifesto_com_conceitos_novos_e_duvidas():
    registrar_nota_manifesto(
        "job1",
        Path("nota.md"),
        "concluido",
        ["a.jpg"],
        "2026-08-02T00:00:00",
        conceitos_novos=["Dijkstra"],
        duvidas=["Por que funciona?"],
    )

    manifesto = _ler_manifesto()

    assert manifesto["job1"]["conceitos_novos"] == ["Dijkstra"]
    assert manifesto["job1"]["duvidas"] == ["Por que funciona?"]
