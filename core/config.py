import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigInvalido(Exception):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # O último arquivo vence: um .env na pasta do projeto sobrescreve o de ~/agent-secrets.
        env_file=(Path.home() / "agent-secrets" / "estudos.env", Path(".env")),
        extra="ignore",
        populate_by_name=True,
    )

    anthropic_api_key: str
    embeddings_api_key: str | None = None

    # CLASS2MD_HOME é o nome público; AGENT_DATA_DIR continua valendo.
    agent_data_dir: Path = Field(
        default=Path.home() / "agent-data",
        validation_alias=AliasChoices("agent_data_dir", "class2md_home"),
    )
    # staging_dir/cache_dir/logs_dir são None por padrão e derivados de agent_data_dir em _validar —
    # setar STAGING_DIR/CACHE_DIR/LOGS_DIR no .env continua funcionando como override explícito.
    staging_dir: Path | None = None
    cache_dir: Path | None = None
    logs_dir: Path | None = None

    teto_mensal_usd: float = 25.0
    max_tokens_compositor: int = 8192
    #: uma foto de página cheia (lousa densa) passa de 4096 tokens de saída com folga
    max_tokens_extrator: int = 8192

    modelos: dict[str, str] = {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-5",
        "opus": "claude-opus-5",
    }

    # US$ por milhão de tokens (ordem de grandeza da §11, editável sem tocar código)
    precos_por_milhao: dict[str, dict[str, float]] = {
        "haiku": {"entrada": 1.0, "saida": 5.0},
        "sonnet": {"entrada": 3.0, "saida": 15.0},
        "opus": {"entrada": 15.0, "saida": 75.0},
    }
    desconto_cache_leitura: float = 0.10  # leitura de cache ≈ 10% do preço de entrada

    @property
    def allowlist_dirs(self) -> list[Path]:
        estudos_dir = self.agent_data_dir / "estudos"
        return [
            estudos_dir / "inbox",
            estudos_dir / "output",
            estudos_dir / "crops",
            estudos_dir / "pdfs",
            estudos_dir / "index",
            estudos_dir / "processed",
            estudos_dir / "promovidas",
            estudos_dir / "arquivo",
            # destino de tudo que o pipeline descarta; sem ele "mover para a lixeira" falharia
            estudos_dir / "trash",
            estudos_dir / "flashcards",
            estudos_dir / "disciplinas.txt",
            self.agent_data_dir / "passos",
            self.cache_dir,
            self.logs_dir,
        ]

    @model_validator(mode="after")
    def _validar(self) -> "Settings":
        if self.staging_dir is None:
            self.staging_dir = self.agent_data_dir / "estudos" / "output"
        if self.cache_dir is None:
            self.cache_dir = self.agent_data_dir / "cache"
        if self.logs_dir is None:
            self.logs_dir = self.agent_data_dir / "logs"

        if not self.agent_data_dir.exists():
            raise ConfigInvalido(
                f"caminho base não existe: {self.agent_data_dir} — "
                "rode 'uv run python scripts/bootstrap.py' para criar a estrutura"
            )

        # staging/cache/logs são diretórios de trabalho internos (não a allowlist de dados do
        # usuário) — criá-los sob demanda evita que quem só mudou AGENT_DATA_DIR precise saber
        # que existem três subpastas derivadas.
        for base in (self.staging_dir, self.cache_dir, self.logs_dir):
            base.mkdir(parents=True, exist_ok=True)

        proibidos = {Path("/").resolve(), Path.home().resolve()}
        for item in self.allowlist_dirs:
            if item.resolve() in proibidos:
                raise ConfigInvalido(f"item da allowlist inválido: {item}")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def chave_configurada() -> bool:
    """Diz se há uma chave da Anthropic configurada, sem nunca devolver o valor.

    A interface local precisa saber disso para mostrar a tela de primeira execução, e
    não pode ler `.env` nem a chave por conta própria. Procura onde `Settings` procuraria:
    variável de ambiente e os arquivos de `env_file`.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    arquivos = Settings.model_config.get("env_file") or ()
    if isinstance(arquivos, (str, Path)):
        arquivos = (arquivos,)
    for arquivo in arquivos:
        try:
            if dotenv_values(arquivo).get("ANTHROPIC_API_KEY"):
                return True
        except OSError:
            continue
    return False
