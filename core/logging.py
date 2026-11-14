import json
from datetime import UTC, datetime

from core.config import get_settings


def registrar_evento(
    *,
    ts: str | None = None,
    job: str | None = None,
    passo: str | None = None,
    modelo: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    custo_usd: float | None = None,
    cache_hit: bool | None = None,
    duracao_ms: int | None = None,
    resultado: str | None = None,
    aviso: str | None = None,
) -> None:
    campos = {
        "ts": ts or datetime.now(UTC).isoformat(),
        "job": job,
        "passo": passo,
        "modelo": modelo,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "custo_usd": custo_usd,
        "cache_hit": cache_hit,
        "duracao_ms": duracao_ms,
        "resultado": resultado,
        "aviso": aviso,
    }
    campos = {k: v for k, v in campos.items() if v is not None}

    settings = get_settings()
    data = datetime.now(UTC).strftime("%Y-%m-%d")
    caminho = settings.logs_dir / f"{data}.jsonl"

    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(campos, ensure_ascii=False) + "\n")
