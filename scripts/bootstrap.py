"""Prepara a estrutura de pastas de dados para o primeiro uso do pipeline.

A pasta de dados vem de CLASS2MD_HOME ou AGENT_DATA_DIR (ambiente ou `.env` do projeto);
sem nenhuma das duas, é ~/agent-data.

Uso: uv run python scripts/bootstrap.py [--dry-run]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer

app = typer.Typer()


def _diretorios_a_criar(agent_data_dir: Path) -> list[Path]:
    estudos_dir = agent_data_dir / "estudos"
    return [
        estudos_dir / "inbox",
        estudos_dir / "output",
        estudos_dir / "crops",
        estudos_dir / "pdfs",
        estudos_dir / "index",
        estudos_dir / "processed",
        estudos_dir / "promovidas",
        estudos_dir / "flashcards",
        estudos_dir / "arquivo",
        estudos_dir / "trash",
        agent_data_dir / "passos",
        agent_data_dir / "cache",
        agent_data_dir / "logs",
    ]


def _valor_dos_arquivos_de_config() -> dict[str, str]:
    """Lê os dois arquivos de configuração sem instanciar `Settings`, que exige que a pasta
    de dados já exista. O `.env` do projeto vence o de ~/agent-secrets, como em `Settings`."""
    from dotenv import dotenv_values

    valores: dict[str, str] = {}
    for arquivo in (Path.home() / "agent-secrets" / "estudos.env", Path(".env")):
        if arquivo.exists():
            valores.update({k.upper(): v for k, v in dotenv_values(arquivo).items() if v})
    return valores


def resolver_pasta_de_dados() -> Path:
    """Ordem: ambiente (CLASS2MD_HOME, AGENT_DATA_DIR), arquivos de config, padrão."""
    import os

    arquivos = _valor_dos_arquivos_de_config()
    for nome in ("CLASS2MD_HOME", "AGENT_DATA_DIR"):
        valor = os.environ.get(nome) or arquivos.get(nome)
        if valor:
            return Path(valor).expanduser()
    return Path.home() / "agent-data"


@app.command()
def main(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Só lista o que seria criado, não cria nada."
    ),
) -> None:
    """Cria a estrutura de pastas do pipeline e valida a configuração."""
    agent_data_dir = resolver_pasta_de_dados()
    diretorios = _diretorios_a_criar(agent_data_dir)

    typer.echo(f"Diretório de dados: {agent_data_dir}")
    for caminho in diretorios:
        if dry_run:
            typer.echo(f"  [dry-run] criaria: {caminho}")
        else:
            caminho.mkdir(parents=True, exist_ok=True)
            typer.echo(f"  ok: {caminho}")

    secrets_env = Path.home() / "agent-secrets" / "estudos.env"
    if not secrets_env.exists() and not Path(".env").exists():
        typer.echo(
            "\nAviso: não achei o arquivo com a chave da API.\n"
            "Crie um .env na pasta do projeto:\n"
            "  cp .env.example .env\n"
            "E preencha ANTHROPIC_API_KEY."
        )
    elif secrets_env.exists():
        modo = oct(secrets_env.parent.stat().st_mode)[-3:]
        if modo != "700":
            typer.echo(
                f"\nAviso: ~/agent-secrets está com permissão {modo}, "
                "recomendado 700 (chmod 700 ~/agent-secrets)."
            )

    if dry_run:
        typer.echo("\ndry-run: nada foi criado de fato.")
        return

    try:
        from core.config import get_settings

        get_settings()
    except Exception as erro:  # noqa: BLE001 — reportar qualquer falha de config em linguagem humana
        typer.echo(f"\nEstrutura criada, mas a configuração ainda não valida: {erro}")
        raise typer.Exit(code=1) from erro

    typer.echo("\nTudo certo: estrutura criada e configuração validada.")


if __name__ == "__main__":
    app()
