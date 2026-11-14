import calendar
import json
from datetime import UTC, datetime

from core.config import get_settings
from core.estado import (
    conectar,
    custo_do_mes,
    registrar_custo_lancamento,
    registrar_passo,
)
from core.fileops import ler_texto, listar
from core.llm.tiers import Tier, modelo_do_tier, precos_do_tier
from core.logging import registrar_evento


class OrcamentoExcedido(Exception):
    pass


def calcular_custo(
    tier: Tier, tokens_in: int, tokens_out: int, tokens_cache_leitura: int = 0
) -> float:
    precos = precos_do_tier(tier)
    desconto = get_settings().desconto_cache_leitura

    custo_entrada = (tokens_in / 1_000_000) * precos["entrada"]
    custo_cache = (tokens_cache_leitura / 1_000_000) * precos["entrada"] * desconto
    custo_saida = (tokens_out / 1_000_000) * precos["saida"]

    return custo_entrada + custo_cache + custo_saida


def registrar_custo(
    job_id: str,
    passo: str,
    tier: Tier,
    tokens_in: int,
    tokens_out: int,
    tokens_cache_leitura: int = 0,
    cache_hit: bool = False,
    duracao_ms: int | None = None,
) -> float:
    custo = calcular_custo(tier, tokens_in, tokens_out, tokens_cache_leitura)
    modelo = modelo_do_tier(tier)

    registrar_passo(
        job_id,
        passo,
        "ok",
        modelo=modelo,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        custo_usd=custo,
    )
    # `passos` é estado (upsert por job+nome); o livro-caixa é append-only. Sem ele,
    # reprocessar um job apagaria o custo da tentativa anterior — que foi gasta.
    registrar_custo_lancamento(job_id, passo, modelo, tokens_in, tokens_out, custo)
    registrar_evento(
        job=job_id,
        passo=passo,
        modelo=modelo,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        custo_usd=custo,
        cache_hit=cache_hit,
        duracao_ms=duracao_ms,
        resultado="ok",
    )

    return custo


def verificar_orcamento() -> None:
    teto = get_settings().teto_mensal_usd
    gasto = custo_do_mes()
    if gasto >= teto:
        raise OrcamentoExcedido(f"orçamento mensal estourado: ${gasto:.2f} / ${teto:.2f}")


def _normalizar_nome_passo(nome: str) -> str:
    return nome.partition(":")[0]


def _agregar_passos_sql(ano: int, mes: int) -> dict[tuple[str, str], dict]:
    conn = conectar()
    prefixo = f"{ano:04d}-{mes:02d}"
    rows = conn.execute(
        "SELECT nome, modelo, tokens_in, tokens_out, custo_usd FROM passos "
        "WHERE substr(fim_em, 1, 7) = ?",
        (prefixo,),
    ).fetchall()

    agregados: dict[tuple[str, str], dict] = {}
    for row in rows:
        nome = _normalizar_nome_passo(row["nome"])
        modelo = row["modelo"] or ""
        chave = (nome, modelo)
        agregado = agregados.setdefault(
            chave,
            {
                "passo": nome,
                "modelo": modelo,
                "chamadas": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "custo": 0.0,
            },
        )
        agregado["chamadas"] += 1
        agregado["tokens_in"] += row["tokens_in"] or 0
        agregado["tokens_out"] += row["tokens_out"] or 0
        agregado["custo"] += row["custo_usd"] or 0.0

    return agregados


def _contar_cache_hit_por_passo(
    ano: int, mes: int, nomes_validos: set[str]
) -> tuple[dict[str, int], dict[str, int]]:
    logs_dir = get_settings().logs_dir
    padrao = f"{ano:04d}-{mes:02d}-*.jsonl"

    cache_hits: dict[str, int] = {}
    totais: dict[str, int] = {}

    for arquivo in listar(logs_dir, padrao):
        for linha in ler_texto(arquivo).splitlines():
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                continue

            passo_bruto = evento.get("passo")
            if not passo_bruto:
                continue

            nome = _normalizar_nome_passo(passo_bruto)
            if nome not in nomes_validos:
                continue

            totais[nome] = totais.get(nome, 0) + 1
            if evento.get("cache_hit"):
                cache_hits[nome] = cache_hits.get(nome, 0) + 1

    return cache_hits, totais


def relatorio_mensal(ano: int | None = None, mes: int | None = None) -> dict:
    agora = datetime.now(UTC)
    ano = ano or agora.year
    mes = mes or agora.month

    total = custo_do_mes(ano, mes)

    dias_no_mes = calendar.monthrange(ano, mes)[1]
    if (ano, mes) == (agora.year, agora.month):
        dias_decorridos = agora.day
    elif (ano, mes) < (agora.year, agora.month):
        dias_decorridos = dias_no_mes
    else:
        dias_decorridos = 0

    projecao = (total / dias_decorridos * dias_no_mes) if dias_decorridos else 0.0

    agregados = _agregar_passos_sql(ano, mes)
    nomes_validos = {chave[0] for chave in agregados}
    cache_hits, totais_log = _contar_cache_hit_por_passo(ano, mes, nomes_validos)

    linhas = []
    for (nome, _modelo), agregado in agregados.items():
        total_log = totais_log.get(nome, 0)
        hits = cache_hits.get(nome, 0)
        agregado["pct_cache_hit"] = (hits / total_log * 100) if total_log else 0.0
        linhas.append(agregado)
    linhas.sort(key=lambda linha: -linha["custo"])

    total_linhas = sum(linha["custo"] for linha in linhas)
    # O detalhamento vem de `passos`, que guarda só a ÚLTIMA tentativa de cada passo;
    # o total vem do livro-caixa, que tem todas. Depois de um reprocessamento, o
    # detalhamento ser menor é o esperado, não um defeito. O que seria defeito é o
    # detalhamento passar do total — aí há lançamento a mais em algum lugar.
    diverge_muito = total > 0 and (total_linhas - total) / total > 0.01
    detalhamento_parcial = total > 0 and (total - total_linhas) / total > 0.01

    teto = get_settings().teto_mensal_usd

    return {
        "ano": ano,
        "mes": mes,
        "total": total,
        "dias_no_mes": dias_no_mes,
        "dias_decorridos": dias_decorridos,
        "projecao": projecao,
        "teto": teto,
        "estoura_teto": projecao > teto,
        "linhas": linhas,
        "total_linhas": total_linhas,
        "diverge_muito": diverge_muito,
        "detalhamento_parcial": detalhamento_parcial,
    }


def _lancamentos_do_log(ano: int, mes: int) -> list[dict]:
    """Chamadas de modelo registradas no log de eventos do mês.

    O log é append-only por construção: cada chamada escreve uma linha e nada é
    reescrito. Por isso ele é a fonte mais fiel que existe aqui — mais que `passos`
    (que é estado) e mais que o próprio livro-caixa, se este começou tarde.
    """
    prefixo = f"{ano:04d}-{mes:02d}"
    achados = []
    for caminho in sorted(get_settings().logs_dir.glob(f"{prefixo}-*.jsonl")):
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if '"custo_usd"' not in linha:
                continue
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if evento.get("custo_usd"):
                achados.append(evento)
    return achados


def reconciliar_do_log(ano: int | None = None, mes: int | None = None) -> tuple[float, float, int]:
    """Completa o livro-caixa com o que o log tem e ele não. Devolve (antes, depois, inseridos).

    Só **acrescenta**: se o livro-caixa já registra mais que o log, nada muda. O log pode
    estar incompleto (arquivo rotacionado, apagado), mas o livro-caixa nunca conta a mais —
    então a diferença, quando existe, é sempre gasto real que ficou de fora.
    """
    agora = datetime.now(UTC)
    ano = ano or agora.year
    mes = mes or agora.month

    do_log = _lancamentos_do_log(ano, mes)
    total_log = sum(evento["custo_usd"] for evento in do_log)
    total_livro = custo_do_mes(ano, mes)

    if total_log <= total_livro:
        return total_livro, total_livro, 0

    diferenca = total_log - total_livro
    registrar_custo_lancamento(
        job_id=None,
        passo="reconciliacao",
        modelo=None,
        tokens_in=None,
        tokens_out=None,
        custo_usd=diferenca,
    )
    registrar_evento(
        passo="custos/reconciliacao",
        resultado=f"{ano:04d}-{mes:02d}: livro-caixa ajustado em +{diferenca:.4f}",
    )
    return total_livro, custo_do_mes(ano, mes), len(do_log)
