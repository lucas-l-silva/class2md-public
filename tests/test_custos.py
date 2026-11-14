import pytest

from core.config import get_settings
from core.estado import conectar, criar_job, custo_do_mes
from core.llm.custos import (
    OrcamentoExcedido,
    calcular_custo,
    registrar_custo,
    relatorio_mensal,
    verificar_orcamento,
)
from core.llm.tiers import Tier
from core.logging import registrar_evento


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


def test_calcular_custo_bate_com_tabela_da_secao_11():
    custo = calcular_custo(Tier.SONNET, tokens_in=1_000_000, tokens_out=1_000_000)

    assert custo == pytest.approx(3.0 + 15.0)


def test_calcular_custo_aplica_desconto_de_cache():
    custo = calcular_custo(Tier.SONNET, tokens_in=0, tokens_out=0, tokens_cache_leitura=1_000_000)

    assert custo == pytest.approx(3.0 * 0.10)


def test_registrar_custo_grava_passo_com_modelo_e_custo():
    job_id = criar_job("aula")

    custo = registrar_custo(job_id, "extrator", Tier.SONNET, tokens_in=1000, tokens_out=500)

    conn = conectar()
    passo = conn.execute(
        "SELECT * FROM passos WHERE job_id=? AND nome=?", (job_id, "extrator")
    ).fetchone()

    assert passo["custo_usd"] == pytest.approx(custo)
    assert passo["modelo"] == "claude-sonnet-5"
    assert passo["tokens_in"] == 1000
    assert passo["tokens_out"] == 500


def test_verificar_orcamento_nao_levanta_dentro_do_teto():
    verificar_orcamento()


def test_verificar_orcamento_levanta_quando_estourado():
    job_id = criar_job("aula")
    registrar_custo(job_id, "caro", Tier.OPUS, tokens_in=1_000_000, tokens_out=1_000_000)

    with pytest.raises(OrcamentoExcedido):
        verificar_orcamento()


def test_relatorio_mensal_total_bate_com_custo_do_mes():
    job_id = criar_job("aula")
    registrar_custo(job_id, "extrator", Tier.SONNET, tokens_in=1000, tokens_out=500)

    relatorio = relatorio_mensal()

    assert relatorio["total"] == pytest.approx(custo_do_mes())
    assert relatorio["total_linhas"] == pytest.approx(relatorio["total"])
    assert not relatorio["diverge_muito"]


def test_relatorio_mensal_normaliza_sufixo_por_foto():
    job_id = criar_job("aula")
    registrar_custo(job_id, "extrator:abc123def456", Tier.SONNET, tokens_in=1000, tokens_out=500)
    registrar_custo(job_id, "extrator:xyz789", Tier.SONNET, tokens_in=2000, tokens_out=1000)

    relatorio = relatorio_mensal()

    passos_reportados = [linha["passo"] for linha in relatorio["linhas"]]
    assert passos_reportados == ["extrator"]

    linha = relatorio["linhas"][0]
    assert linha["chamadas"] == 2
    assert linha["tokens_in"] == 3000
    assert linha["tokens_out"] == 1500


def test_relatorio_mensal_calcula_pct_cache_hit():
    job_id = criar_job("aula")
    registrar_custo(job_id, "triagem", Tier.HAIKU, tokens_in=100, tokens_out=50)
    registrar_evento(
        job=job_id,
        passo="triagem",
        modelo="claude-haiku-4-5-20251001",
        cache_hit=True,
        resultado="ok",
    )

    relatorio = relatorio_mensal()

    linha = next(x for x in relatorio["linhas"] if x["passo"] == "triagem")
    assert linha["pct_cache_hit"] == pytest.approx(50.0)


def test_relatorio_mensal_ignora_eventos_espurios_do_log():
    registrar_evento(job="x", passo="p0.2", resultado="ok")

    relatorio = relatorio_mensal()

    assert relatorio["linhas"] == []


def test_relatorio_mensal_avisa_quando_projecao_estoura_teto(monkeypatch):
    monkeypatch.setenv("TETO_MENSAL_USD", "0.01")
    get_settings.cache_clear()

    job_id = criar_job("aula")
    registrar_custo(job_id, "caro", Tier.OPUS, tokens_in=1_000_000, tokens_out=1_000_000)

    relatorio = relatorio_mensal()

    assert relatorio["estoura_teto"] is True


def test_reprocessar_um_passo_nao_apaga_o_custo_da_tentativa_anterior():
    """`passos` é estado (upsert por job+nome); dinheiro gasto não se sobrescreve."""
    job_id = criar_job("aula")
    primeiro = registrar_custo(job_id, "extrator", Tier.SONNET, tokens_in=1000, tokens_out=500)
    segundo = registrar_custo(job_id, "extrator", Tier.SONNET, tokens_in=2000, tokens_out=800)

    assert custo_do_mes() == pytest.approx(primeiro + segundo)

    conn = conectar()
    # o estado do passo continua sendo o da última tentativa
    assert conn.execute("SELECT COUNT(*) FROM passos WHERE job_id=?", (job_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM custos WHERE job_id=?", (job_id,)).fetchone()[0] == 2


def test_livro_caixa_nao_duplica_o_historico_no_backfill():
    job_id = criar_job("aula")
    custo = registrar_custo(job_id, "extrator", Tier.SONNET, tokens_in=1000, tokens_out=500)

    conectar()  # uma reconexão não pode semear de novo
    conectar()

    assert custo_do_mes() == pytest.approx(custo)


def test_detalhamento_menor_que_o_total_nao_e_defeito():
    """Depois de reprocessar, `passos` tem só a última tentativa e o livro-caixa tem todas."""
    job_id = criar_job("aula")
    registrar_custo(job_id, "extrator", Tier.SONNET, tokens_in=1000, tokens_out=500)
    registrar_custo(job_id, "extrator", Tier.SONNET, tokens_in=1000, tokens_out=500)

    relatorio = relatorio_mensal()

    assert relatorio["detalhamento_parcial"] is True
    assert relatorio["diverge_muito"] is False
    assert relatorio["total_linhas"] < relatorio["total"]


def test_reconciliar_completa_o_livro_caixa_a_partir_do_log():
    from core.llm.custos import reconciliar_do_log

    job_id = criar_job("aula")
    registrar_custo(job_id, "extrator", Tier.SONNET, tokens_in=1000, tokens_out=500)

    # simula o livro-caixa tendo perdido metade (o caso de quem começou a registrar tarde)
    conn = conectar()
    conn.execute("DELETE FROM custos")
    conn.commit()
    assert custo_do_mes() == pytest.approx(0.0)

    antes, depois, lancamentos = reconciliar_do_log()

    assert antes == pytest.approx(0.0)
    assert depois > 0
    assert lancamentos >= 1


def test_reconciliar_nunca_reduz_o_total():
    from core.llm.custos import reconciliar_do_log

    job_id = criar_job("aula")
    registrar_custo(job_id, "extrator", Tier.SONNET, tokens_in=1000, tokens_out=500)
    total = custo_do_mes()

    antes, depois, _ = reconciliar_do_log()

    assert antes == pytest.approx(total)
    assert depois == pytest.approx(total)
