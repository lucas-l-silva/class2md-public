import pytest

from core.config import get_settings
from projetos.estudos.nota import (
    caminho_nota_final,
    caminho_stub,
    criar_stub,
    nome_definitivo,
)


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_stub_frontmatter_so_tem_campos_do_template():
    caminho = criar_stub("2026-07-15", "Historia")
    frontmatter = caminho.read_text().split("---")[1]

    assert "data: 2026-07-15" in frontmatter
    assert "disciplina: Historia" in frontmatter
    assert "aula: null" in frontmatter
    assert "tags: []" in frontmatter

    for proibido in ("job_id", "status", "fotos", "aviso"):
        assert proibido not in frontmatter


def test_stub_fica_no_staging_nao_no_vault():
    caminho = criar_stub("2026-07-15", "Historia")

    settings = get_settings()
    assert caminho.is_relative_to(settings.agent_data_dir / "estudos" / "output")


def test_caminho_stub_bate_com_arquivo_criado():
    caminho = criar_stub("2026-07-15", "Historia")

    assert caminho == caminho_stub("2026-07-15", "Historia")


def test_nome_definitivo_com_aula_numero():
    nome = nome_definitivo("2026-07-15", 5, "Caminhos mínimos: Dijkstra")

    assert nome == "2026-07-15 Aula 05 — Caminhos mínimos: Dijkstra.md"


def test_nome_definitivo_sem_aula_numero():
    nome = nome_definitivo("2026-07-15", None, "Caminhos mínimos: Dijkstra")

    assert nome == "2026-07-15 Aula — Caminhos mínimos: Dijkstra.md"


def test_caminho_nota_final_fica_no_staging():
    caminho = caminho_nota_final("2026-07-15", "Historia", 5, "Dijkstra")

    settings = get_settings()
    assert caminho.is_relative_to(settings.agent_data_dir / "estudos" / "output")
    assert caminho.name == "2026-07-15 Aula 05 — Dijkstra.md"
