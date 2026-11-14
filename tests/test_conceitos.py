from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.config import get_settings
from core.estado import criar_job, marcar_reprocessamento
from core.fileops import ler_texto
from projetos.estudos.conceitos import (
    MAX_CONCEITOS_POR_AULA,
    caminho_conceito,
    gerar_paginas_conceito,
)
from projetos.estudos.schemas import PaginaConceito


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


def _resposta_mock():
    usage = SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0)
    return SimpleNamespace(usage=usage)


def _pagina(definicao_a_completar: bool = False) -> PaginaConceito:
    return PaginaConceito(
        definicao_formal="Def.",
        intuicao="Intuição.",
        exemplo="Exemplo.",
        tags=["algoritmos"],
        definicao_a_completar=definicao_a_completar,
    )


def test_gera_uma_pagina_por_conceito(sem_cache_llm):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.side_effect = [
            (_pagina(), _resposta_mock()),
            (_pagina(), _resposta_mock()),
        ]
        gerar_paginas_conceito(
            job_id,
            "Historia",
            ["Bastilha", "Girondinos"],
            "# Aula\n...",
            "2026-07-15 Aula 01",
        )

    assert mock_chamar.call_count == 2
    assert caminho_conceito("Historia", "Bastilha").exists()
    assert caminho_conceito("Historia", "Girondinos").exists()


def test_teto_de_cinco_conceitos_por_aula(sem_cache_llm):
    job_id = criar_job("aula")
    conceitos = [f"Conceito {i}" for i in range(7)]

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.side_effect = [
            (_pagina(), _resposta_mock()) for _ in range(MAX_CONCEITOS_POR_AULA)
        ]
        gerar_paginas_conceito(job_id, "Historia", conceitos, "# Aula\n...", "2026-07-15 Aula 01")

    assert mock_chamar.call_count == MAX_CONCEITOS_POR_AULA
    for nome in conceitos[:MAX_CONCEITOS_POR_AULA]:
        assert caminho_conceito("Historia", nome).exists()
    for nome in conceitos[MAX_CONCEITOS_POR_AULA:]:
        assert not caminho_conceito("Historia", nome).exists()


def test_pagina_criada_com_aparece_em_correto(sem_cache_llm):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_pagina(), _resposta_mock())
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01 — X"
        )

    conteudo = ler_texto(caminho_conceito("Historia", "Bastilha"))
    assert "tipo: conceito" in conteudo
    assert "## Aparece em" in conteudo
    assert "- [[2026-07-15 Aula 01 — X]]" in conteudo


def test_aviso_definicao_a_completar(sem_cache_llm):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            _pagina(definicao_a_completar=True),
            _resposta_mock(),
        )
        avisos = gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01"
        )

    assert len(avisos) == 1
    assert "definição a completar" in avisos[0]


def test_rodar_duas_vezes_nao_duplica_nem_chama_llm_de_novo(sem_cache_llm):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_pagina(), _resposta_mock())
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01"
        )
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01"
        )

    assert mock_chamar.call_count == 1
    conteudo = ler_texto(caminho_conceito("Historia", "Bastilha"))
    assert conteudo.count("- [[2026-07-15 Aula 01]]") == 1


def test_frontmatter_contem_apenas_campos_do_template(sem_cache_llm):
    # Decisão 9: metadado de pipeline (ex. proveniência pra reprocessamento) não vai pro
    # frontmatter — a página fica 100% template, pronta pra ser promovida ao vault.
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_pagina(), _resposta_mock())
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01"
        )

    conteudo = ler_texto(caminho_conceito("Historia", "Bastilha"))
    frontmatter = conteudo.split("---")[1]
    chaves = {linha.split(":", 1)[0].strip() for linha in frontmatter.strip().splitlines()}
    assert chaves == {"tipo", "disciplina", "tags"}


def test_forcar_reprocessamento_regenera_pagina_de_conceito_existente(sem_cache_llm):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_pagina(), _resposta_mock())
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01"
        )

        marcar_reprocessamento(job_id)  # "*" — mesma marca que reprocessar_job() usa
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01"
        )

    assert mock_chamar.call_count == 2


def test_forcar_reprocessamento_regenera_definicao_mas_preserva_aparece_em(
    sem_cache_llm,
):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_pagina(), _resposta_mock())
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01"
        )
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula 2\n...", "2026-08-01 Aula 02"
        )

        marcar_reprocessamento(job_id)
        mock_chamar.return_value = (_pagina(), _resposta_mock())
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01"
        )

    assert (
        mock_chamar.call_count == 2
    )  # origem (cria) + regeneração forçada; citação não chama o LLM
    conteudo = ler_texto(caminho_conceito("Historia", "Bastilha"))
    assert "- [[2026-07-15 Aula 01]]" in conteudo
    assert "- [[2026-08-01 Aula 02]]" in conteudo


def test_forcar_reprocessamento_nota_que_so_cita_nao_regenera_definicao(sem_cache_llm):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_pagina(), _resposta_mock())
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01"
        )

        marcar_reprocessamento(job_id)
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula 2\n...", "2026-08-01 Aula 02"
        )

    assert mock_chamar.call_count == 1  # citação não regenera, mesmo sob force
    conteudo = ler_texto(caminho_conceito("Historia", "Bastilha"))
    assert "- [[2026-07-15 Aula 01]]" in conteudo
    assert "- [[2026-08-01 Aula 02]]" in conteudo


def test_rodar_para_nota_diferente_nao_chama_llm_e_acrescenta_aparece_em(sem_cache_llm):
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_pagina(), _resposta_mock())
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula\n...", "2026-07-15 Aula 01"
        )
        gerar_paginas_conceito(
            job_id, "Historia", ["Bastilha"], "# Aula 2\n...", "2026-08-01 Aula 02"
        )

    assert mock_chamar.call_count == 1
    conteudo = ler_texto(caminho_conceito("Historia", "Bastilha"))
    assert "- [[2026-07-15 Aula 01]]" in conteudo
    assert "- [[2026-08-01 Aula 02]]" in conteudo
