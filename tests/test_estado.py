import pytest

from core.config import get_settings
from core.estado import (
    RunnerJaEmExecucao,
    TransicaoInvalida,
    conectar,
    criar_job,
    custo_do_mes,
    job_por_id,
    job_por_prefixo_id,
    limpar_reprocessamento,
    lock_runner,
    marcar_pdf_indexado,
    marcar_promovido,
    marcar_reprocessamento,
    pdf_por_sha,
    pdfs_por_aula,
    pdfs_por_disciplina,
    proximo_da_fila,
    registrar_custo_lancamento,
    registrar_passo,
    registrar_pdf_estado,
    transicionar,
)


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_criar_job_e_transicao_valida():
    job_id = criar_job("aula", disciplina="calculo")

    conn = conectar()
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "na_fila"

    transicionar(job_id, "rodando")

    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "rodando"


def test_transicao_na_fila_para_concluido_e_invalida():
    job_id = criar_job("aula")

    with pytest.raises(TransicaoInvalida):
        transicionar(job_id, "concluido")


def test_transicao_concluido_para_rodando_e_invalida():
    job_id = criar_job("aula")
    transicionar(job_id, "rodando")
    transicionar(job_id, "concluido")

    with pytest.raises(TransicaoInvalida):
        transicionar(job_id, "rodando")


def test_transicao_concluido_para_na_fila_e_valida():
    job_id = criar_job("aula")
    transicionar(job_id, "rodando")
    transicionar(job_id, "concluido")

    transicionar(job_id, "na_fila")

    conn = conectar()
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "na_fila"


def test_proximo_da_fila_respeita_ordem_de_criacao():
    primeiro = criar_job("aula", disciplina="calculo")
    segundo = criar_job("aula", disciplina="fisica")

    assert proximo_da_fila()["id"] == primeiro

    transicionar(primeiro, "rodando")

    assert proximo_da_fila()["id"] == segundo


def test_registrar_passo_grava_e_le_de_volta():
    job_id = criar_job("aula")

    registrar_passo(
        job_id,
        "extrator",
        "ok",
        modelo="sonnet",
        tokens_in=1000,
        tokens_out=200,
        custo_usd=0.05,
    )

    conn = conectar()
    row = conn.execute(
        "SELECT * FROM passos WHERE job_id=? AND nome=?", (job_id, "extrator")
    ).fetchone()

    assert row["status"] == "ok"
    assert row["modelo"] == "sonnet"
    assert row["tokens_in"] == 1000
    assert row["custo_usd"] == 0.05


def test_custo_do_mes_soma_mes_corrente_e_ignora_outro_mes():
    job_id = criar_job("aula")
    registrar_custo_lancamento(job_id, "extrator", "sonnet", 100, 50, 0.05)
    registrar_custo_lancamento(job_id, "compositor", "sonnet", 100, 50, 0.03)

    conn = conectar()
    conn.execute(
        "INSERT INTO custos(job_id, passo, custo_usd, em) VALUES (?, ?, ?, ?)",
        (job_id, "passo_mes_passado", 100.0, "2020-01-15T00:00:00+00:00"),
    )
    conn.commit()

    assert custo_do_mes() == pytest.approx(0.08)


def test_custo_nao_vem_de_passos(monkeypatch):
    """`passos` é estado, não livro-caixa: escrever ali não move o orçamento."""
    job_id = criar_job("aula")
    registrar_passo(job_id, "extrator", "ok", custo_usd=99.0)

    assert custo_do_mes() == pytest.approx(0.0)


def test_segunda_aquisicao_do_lock_levanta_erro():
    with lock_runner():
        with pytest.raises(RunnerJaEmExecucao):
            with lock_runner():
                pass


def test_job_por_id_encontra_job_existente():
    job_id = criar_job("aula")

    assert job_por_id(job_id)["id"] == job_id


def test_job_por_id_inexistente_retorna_none():
    assert job_por_id("nao-existe") is None


def test_job_por_prefixo_id_resolve_prefixo_unico():
    job_id = criar_job("aula")

    encontrado = job_por_prefixo_id(job_id[:8])

    assert encontrado["id"] == job_id


def test_job_por_prefixo_id_ambiguo_retorna_none(monkeypatch):
    # forçamos dois ids com o mesmo prefixo criando jobs até colidir seria frágil;
    # em vez disso, testamos via IDs sintéticos inseridos direto no banco.
    conn = conectar()
    conn.execute(
        "INSERT INTO jobs(id, tipo, status, criado_em, atualizado_em) VALUES (?, 'aula', 'na_fila', '', '')",
        ("prefixoabc-1",),
    )
    conn.execute(
        "INSERT INTO jobs(id, tipo, status, criado_em, atualizado_em) VALUES (?, 'aula', 'na_fila', '', '')",
        ("prefixoabc-2",),
    )
    conn.commit()

    assert job_por_prefixo_id("prefixoabc") is None


def test_marcar_reprocessamento_sem_passo_grava_curinga():
    job_id = criar_job("aula")

    marcar_reprocessamento(job_id)

    assert job_por_id(job_id)["forcar_reprocessamento"] == "*"


def test_marcar_reprocessamento_com_passo_grava_nome():
    job_id = criar_job("aula")

    marcar_reprocessamento(job_id, "extrator")

    assert job_por_id(job_id)["forcar_reprocessamento"] == "extrator"


def test_limpar_reprocessamento_remove_a_marca():
    job_id = criar_job("aula")
    marcar_reprocessamento(job_id, "extrator")

    limpar_reprocessamento(job_id)

    assert job_por_id(job_id)["forcar_reprocessamento"] is None


def test_marcar_promovido_transiciona_status_e_grava_avaliacao():
    job_id = criar_job("aula")
    transicionar(job_id, "rodando")
    transicionar(job_id, "concluido")

    marcar_promovido(job_id, 4)

    job = job_por_id(job_id)
    assert job["status"] == "promovido"
    avaliacao = (
        conectar()
        .execute("SELECT nota_qualidade FROM avaliacoes WHERE job_id=?", (job_id,))
        .fetchone()
    )
    assert avaliacao["nota_qualidade"] == 4


def test_marcar_promovido_falha_se_job_nao_esta_concluido():
    job_id = criar_job("aula")

    with pytest.raises(TransicaoInvalida):
        marcar_promovido(job_id, 4)


def _registrar_pdf_teste(sha256="a" * 64, **overrides):
    base = dict(
        sha256=sha256,
        caminho="/x/estudos/pdfs/Calculo/livro.pdf",
        nome_arquivo="livro.pdf",
        disciplina="Calculo",
        tipo="livro",
        modo="indexado",
        paginas=300,
        chars_total=500_000,
        tem_texto_nativo=True,
        data_aula=None,
    )
    base.update(overrides)
    registrar_pdf_estado(**base)


def test_registrar_pdf_estado_e_idempotente_por_sha():
    _registrar_pdf_teste()
    _registrar_pdf_teste(paginas=301)  # mesmo sha, dado atualizado

    registro = pdf_por_sha("a" * 64)
    assert registro["paginas"] == 301
    assert conectar().execute("SELECT COUNT(*) AS n FROM pdfs").fetchone()["n"] == 1


def test_pdf_por_sha_inexistente_devolve_none():
    assert pdf_por_sha("nao-existe") is None


def test_pdfs_por_disciplina_filtra_por_tipo():
    _registrar_pdf_teste(sha256="a" * 64, tipo="livro")
    _registrar_pdf_teste(sha256="b" * 64, tipo="exercicios", nome_arquivo="lista01.pdf")

    todos = pdfs_por_disciplina("Calculo")
    so_livros = pdfs_por_disciplina("Calculo", tipo="livro")

    assert len(todos) == 2
    assert len(so_livros) == 1
    assert so_livros[0]["tipo"] == "livro"


def test_pdfs_por_aula_filtra_disciplina_e_data():
    _registrar_pdf_teste(sha256="a" * 64, tipo="aula", data_aula="2026-07-15", modo="direto")
    _registrar_pdf_teste(sha256="b" * 64, tipo="aula", data_aula="2026-07-22", modo="direto")

    resultado = pdfs_por_aula("Calculo", "2026-07-15")

    assert len(resultado) == 1
    assert resultado[0]["sha256"] == "a" * 64


def test_marcar_pdf_indexado_preenche_indexado_em():
    _registrar_pdf_teste()
    assert pdf_por_sha("a" * 64)["indexado_em"] is None

    marcar_pdf_indexado("a" * 64)

    assert pdf_por_sha("a" * 64)["indexado_em"] is not None


def test_transicao_parcial_para_fila_permitida_e_parcial_para_promovido_proibida():
    from core.estado import TransicaoInvalida

    job_id = criar_job("aula", disciplina="MAT1", data="2026-08-10")
    transicionar(job_id, "rodando")
    transicionar(job_id, "parcial")

    with pytest.raises(TransicaoInvalida):
        transicionar(job_id, "promovido")
    with pytest.raises(TransicaoInvalida):
        transicionar(job_id, "concluido")
    transicionar(job_id, "na_fila")
