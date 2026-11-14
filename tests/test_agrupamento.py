from datetime import datetime

import pytest

from core.config import get_settings
from core.estado import conectar, registrar_arquivo, transicionar
from projetos.estudos.agrupamento import agrupar_pendentes
from projetos.estudos.manifesto import _ler_manifesto
from projetos.estudos.nota import caminho_stub


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "logs").mkdir()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_fotos_mesma_data_disciplina_geram_um_job():
    registrar_arquivo(
        "sha_a",
        "a.jpg",
        disciplina="calculo",
        tirada_em=datetime(2026, 7, 15, 8, 0).isoformat(),
    )
    registrar_arquivo(
        "sha_b",
        "b.jpg",
        disciplina="calculo",
        tirada_em=datetime(2026, 7, 15, 17, 0).isoformat(),
    )

    resultado = agrupar_pendentes()

    assert resultado["jobs_criados"] == 1
    assert resultado["jobs_reaproveitados"] == 0

    conn = conectar()
    total_jobs = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
    assert total_jobs == 1


def test_rodar_agrupamento_duas_vezes_nao_duplica_job():
    registrar_arquivo(
        "sha_a",
        "a.jpg",
        disciplina="calculo",
        tirada_em=datetime(2026, 7, 15, 8, 0).isoformat(),
    )

    primeira = agrupar_pendentes()
    segunda = agrupar_pendentes()

    assert primeira["jobs_criados"] == 1
    assert segunda["jobs_criados"] == 0
    assert segunda["jobs_reaproveitados"] == 0  # nada pendente na segunda chamada

    conn = conectar()
    total_jobs = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
    assert total_jobs == 1


def test_foto_nova_mesma_chave_entra_no_job_existente_e_reenfileira():
    registrar_arquivo(
        "sha_a",
        "a.jpg",
        disciplina="calculo",
        tirada_em=datetime(2026, 7, 15, 8, 0).isoformat(),
    )
    job_id = agrupar_pendentes()["job_ids"][0]

    transicionar(job_id, "rodando")
    transicionar(job_id, "falhou")

    registrar_arquivo(
        "sha_b",
        "b.jpg",
        disciplina="calculo",
        tirada_em=datetime(2026, 7, 15, 17, 0).isoformat(),
    )
    resultado = agrupar_pendentes()

    assert resultado["jobs_criados"] == 0
    assert resultado["jobs_reaproveitados"] == 1

    conn = conectar()
    job = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert job["status"] == "na_fila"

    vinculos = conn.execute("SELECT sha256 FROM arquivos WHERE job_id=?", (job_id,)).fetchall()
    assert {linha["sha256"] for linha in vinculos} == {"sha_a", "sha_b"}


def test_foto_nova_em_job_concluido_nao_reenfileira_mas_registra_aviso():
    registrar_arquivo(
        "sha_a",
        "a.jpg",
        disciplina="calculo",
        tirada_em=datetime(2026, 7, 15, 8, 0).isoformat(),
    )
    job_id = agrupar_pendentes()["job_ids"][0]

    transicionar(job_id, "rodando")
    transicionar(job_id, "concluido")

    registrar_arquivo(
        "sha_b",
        "b.jpg",
        disciplina="calculo",
        tirada_em=datetime(2026, 7, 15, 17, 0).isoformat(),
    )
    agrupar_pendentes()

    conn = conectar()
    job = conn.execute(
        "SELECT status, aviso_reprocessamento FROM jobs WHERE id=?", (job_id,)
    ).fetchone()
    assert job["status"] == "concluido"
    assert job["aviso_reprocessamento"] is not None

    vinculos = conn.execute("SELECT sha256 FROM arquivos WHERE job_id=?", (job_id,)).fetchall()
    assert {linha["sha256"] for linha in vinculos} == {"sha_a", "sha_b"}


def test_disciplinas_diferentes_mesma_data_geram_jobs_separados():
    registrar_arquivo(
        "sha_a",
        "a.jpg",
        disciplina="calculo",
        tirada_em=datetime(2026, 7, 15, 8, 0).isoformat(),
    )
    registrar_arquivo(
        "sha_b",
        "b.jpg",
        disciplina="fisica",
        tirada_em=datetime(2026, 7, 15, 8, 0).isoformat(),
    )

    resultado = agrupar_pendentes()

    assert resultado["jobs_criados"] == 2


def test_datas_diferentes_mesma_disciplina_geram_jobs_separados():
    registrar_arquivo(
        "sha_a",
        "a.jpg",
        disciplina="calculo",
        tirada_em=datetime(2026, 7, 15, 8, 0).isoformat(),
    )
    registrar_arquivo(
        "sha_b",
        "b.jpg",
        disciplina="calculo",
        tirada_em=datetime(2026, 7, 16, 8, 0).isoformat(),
    )

    resultado = agrupar_pendentes()

    assert resultado["jobs_criados"] == 2


def test_agrupar_pendentes_cria_stub_e_entrada_no_manifesto():
    registrar_arquivo(
        "sha_a",
        "a.jpg",
        disciplina="Historia",
        tirada_em=datetime(2026, 7, 15, 8, 0).isoformat(),
    )

    resultado = agrupar_pendentes()
    job_id = resultado["job_ids"][0]

    caminho = caminho_stub("2026-07-15", "Historia")
    assert caminho.exists()
    assert "disciplina: Historia" in caminho.read_text()

    manifesto = _ler_manifesto()
    assert manifesto[job_id]["status"] == "a_processar"
    assert manifesto[job_id]["fotos"] == ["a.jpg"]


def test_rodar_agrupamento_duas_vezes_nao_recria_stub_mas_atualiza_manifesto():
    registrar_arquivo(
        "sha_a",
        "a.jpg",
        disciplina="Historia",
        tirada_em=datetime(2026, 7, 15, 8, 0).isoformat(),
    )
    resultado = agrupar_pendentes()
    job_id = resultado["job_ids"][0]

    caminho = caminho_stub("2026-07-15", "Historia")
    mtime_original = caminho.stat().st_mtime

    registrar_arquivo(
        "sha_b",
        "b.jpg",
        disciplina="Historia",
        tirada_em=datetime(2026, 7, 15, 17, 0).isoformat(),
    )
    agrupar_pendentes()

    assert caminho.stat().st_mtime == mtime_original

    manifesto = _ler_manifesto()
    assert set(manifesto[job_id]["fotos"]) == {"a.jpg", "b.jpg"}
