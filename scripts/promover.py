import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer

app = typer.Typer()

CONFIG_PATH = Path.home() / ".config" / "class2md" / "promotor.toml"
STAGING_LOCAL_DIR = Path("staging-local")
STAGING_CROPS_DIR = Path("staging-crops")
SSH_HOST = "servidor"
STAGING_REMOTO = "~/agent-data/estudos/output/"
CROPS_REMOTO = "~/agent-data/estudos/crops/"

_RE_EMBED = re.compile(r"!\[\[([^\]]+)\]\]")
_RE_JOB_ID = re.compile(r"^[0-9a-fA-F-]{36}$")

# Não é detecção de segurança forte (um atacante pode ofuscar) — é o mínimo pra chamar a
# atenção de quem revisa antes de aceitar. O documento processado é DADO, não instrução;
# quem decide é sempre o humano no loop do Movimento 2.
_PADROES_SUSPEITOS = (
    "ignore as instruções",
    "ignore all previous instructions",
    "disregard the above",
    "system prompt",
    "you are now",
    "aja como se",
    "execute o seguinte comando",
)


class ConfigPromotorInvalida(Exception):
    pass


@dataclass(frozen=True)
class ConfigPromotor:
    vault_dir: Path
    anexos_dir: Path
    repo_dir_servidor: str = "~/class2md"


@dataclass(frozen=True)
class ItemPromocao:
    job_id: str
    caminho_relativo: Path
    caminho_staging: Path
    caminho_vault: Path
    status: str  # "novo" | "identico" | "alterado"
    avisos: list[str]

    @property
    def conflito(self) -> bool:
        return self.status == "alterado"


def carregar_config(caminho: Path = CONFIG_PATH) -> ConfigPromotor:
    if not caminho.exists():
        raise ConfigPromotorInvalida(
            f"config não encontrada: {caminho} — crie com vault_dir e anexos_dir"
        )
    dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    try:
        vault_dir = Path(dados["vault_dir"]).expanduser()
        anexos_dir = Path(dados["anexos_dir"]).expanduser()
    except KeyError as erro:
        raise ConfigPromotorInvalida(f"campo obrigatório ausente na config: {erro}") from erro
    repo_dir_servidor = dados.get("repo_dir_servidor", "~/class2md")
    return ConfigPromotor(
        vault_dir=vault_dir, anexos_dir=anexos_dir, repo_dir_servidor=repo_dir_servidor
    )


def sincronizar_staging(
    destino_local: Path = STAGING_LOCAL_DIR,
    destino_local_crops: Path = STAGING_CROPS_DIR,
    host: str = SSH_HOST,
) -> None:
    # Duas pastas remotas: output/ (notas + manifesto) e crops/ (recortes que as notas
    # embutem via ![[...]]). O plano só precisa de output/; resolver embeds no Movimento 2
    # precisa de crops/ também — sincronizamos as duas juntas, de uma vez, por simplicidade
    # (rede local, sem custo relevante em puxar tudo de antemão).
    for remoto, local in (
        (STAGING_REMOTO, destino_local),
        (CROPS_REMOTO, destino_local_crops),
    ):
        local.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rsync", "-a", f"{host}:{remoto}", f"{local}/"], check=True)


def ler_manifesto(staging_local_dir: Path) -> dict:
    caminho = staging_local_dir / "_manifest.json"
    if not caminho.exists():
        return {}
    return json.loads(caminho.read_text(encoding="utf-8"))


def _relativo_ao_output(caminho_nota: str) -> Path:
    # caminho_nota no manifesto é o absoluto do lado do processamento (.../estudos/output/<Disciplina>/
    # arquivo.md); o rsync espelha 1:1 o conteúdo de output/ em staging-local/, então a parte
    # depois de "output" é o mesmo caminho relativo dos dois lados (staging-local e vault).
    partes = Path(caminho_nota).parts
    if "output" not in partes:
        raise ValueError(f"caminho_nota fora de .../output/: {caminho_nota}")
    indice = partes.index("output")
    return Path(*partes[indice + 1 :])


def _possivel_injecao(markdown: str) -> bool:
    texto = markdown.lower()
    return any(padrao in texto for padrao in _PADROES_SUSPEITOS)


def _avisos_da_entrada(entrada: dict, markdown_staging: str) -> list[str]:
    avisos = []
    if entrada.get("precisa_revisao"):
        avisos.append("precisa_revisao")
    for problema in entrada.get("problemas_validacao") or []:
        avisos.append(f"validação: {problema}")
    for aviso in entrada.get("avisos_conceitos") or []:
        avisos.append(f"conceito: {aviso}")
    if _possivel_injecao(markdown_staging):
        avisos.append("possivel_injecao")
    return avisos


def montar_plano(manifesto: dict, staging_local_dir: Path, vault_dir: Path) -> list[ItemPromocao]:
    itens = []
    for job_id, entrada in manifesto.items():
        relativo = _relativo_ao_output(entrada["caminho_nota"])
        caminho_staging = staging_local_dir / relativo
        caminho_vault = vault_dir / relativo

        if not caminho_staging.exists():
            continue  # manifesto referencia nota que o rsync ainda não trouxe

        markdown_staging = caminho_staging.read_text(encoding="utf-8")

        if not caminho_vault.exists():
            status = "novo"
        elif (
            hashlib.sha256(caminho_vault.read_bytes()).digest()
            == hashlib.sha256(markdown_staging.encode("utf-8")).digest()
        ):
            status = "identico"
        else:
            status = "alterado"

        itens.append(
            ItemPromocao(
                job_id=job_id,
                caminho_relativo=relativo,
                caminho_staging=caminho_staging,
                caminho_vault=caminho_vault,
                status=status,
                avisos=_avisos_da_entrada(entrada, markdown_staging),
            )
        )
    return itens


def imprimir_plano(itens: list[ItemPromocao]) -> None:
    if not itens:
        typer.echo("Nada a promover — manifesto vazio ou staging sem notas correspondentes.")
        return

    for item in itens:
        typer.echo(f"[{item.status}] {item.caminho_relativo}  (job {item.job_id[:8]})")
        for aviso in item.avisos:
            typer.echo(f"    aviso: {aviso}")

    novos = sum(1 for i in itens if i.status == "novo")
    alterados = sum(1 for i in itens if i.status == "alterado")
    identicos = sum(1 for i in itens if i.status == "identico")
    typer.echo(
        f"\nTotal: {len(itens)}  (novos {novos}, alterados {alterados}, idênticos {identicos})"
    )


@dataclass(frozen=True)
class ResolucaoRecortes:
    encontrados: list[Path] = field(default_factory=list)
    faltando: list[str] = field(default_factory=list)


def _extrair_embeds(markdown: str) -> list[str]:
    return _RE_EMBED.findall(markdown)


def resolver_recortes(markdown: str, staging_crops_dir: Path) -> ResolucaoRecortes:
    # O embed é só o nome do arquivo (achatado, sem disciplina) — mesma convenção que
    # validador._checar_embeds já assume. Busca recursiva porque staging_crops_dir espelha
    # crops/<Disciplina>/... e a nota não diz de qual disciplina veio o recorte.
    encontrados: list[Path] = []
    faltando: list[str] = []
    for nome_arquivo in _extrair_embeds(markdown):
        achados = list(staging_crops_dir.rglob(nome_arquivo))
        if achados:
            encontrados.append(achados[0])
        else:
            faltando.append(nome_arquivo)
    return ResolucaoRecortes(encontrados=encontrados, faltando=faltando)


def gerar_diff(conteudo_antigo: str, conteudo_novo: str, nome_arquivo: str) -> str:
    linhas = difflib.unified_diff(
        conteudo_antigo.splitlines(keepends=True),
        conteudo_novo.splitlines(keepends=True),
        fromfile=f"vault/{nome_arquivo}",
        tofile=f"staging/{nome_arquivo}",
    )
    return "".join(linhas)


def validar_nota_qualidade(bruto: str) -> int:
    try:
        valor = int(bruto)
    except ValueError as erro:
        raise ValueError(f"nota de qualidade precisa ser um inteiro, recebido: {bruto!r}") from erro
    if not 1 <= valor <= 5:
        raise ValueError(f"nota de qualidade precisa estar entre 1 e 5, recebido: {valor}")
    return valor


def copiar_nota_e_recortes(
    item: ItemPromocao,
    markdown: str,
    resolucao: ResolucaoRecortes,
    config: ConfigPromotor,
) -> None:
    item.caminho_vault.parent.mkdir(parents=True, exist_ok=True)
    item.caminho_vault.write_text(markdown, encoding="utf-8")

    anexos_dir = (
        config.anexos_dir
        if config.anexos_dir.is_absolute()
        else config.vault_dir / config.anexos_dir
    )
    anexos_dir.mkdir(parents=True, exist_ok=True)
    for crop in resolucao.encontrados:
        shutil.copy2(crop, anexos_dir / crop.name)


def finalizar_no_servidor(
    job_id: str, nota_qualidade: int, config: ConfigPromotor, host: str = SSH_HOST
) -> None:
    # job_id vem do _manifest.json, que é DADO do staging (não instrução) — mesmo sendo
    # gerado internamente por uuid4 no servidor, validamos o formato antes de compor o comando
    # remoto por ssh, defesa em profundidade contra injeção de shell.
    if not _RE_JOB_ID.match(job_id):
        raise ValueError(f"job_id com formato inesperado, recusando enviar via ssh: {job_id!r}")

    comando_remoto = (
        f"cd {config.repo_dir_servidor} && "
        f"uv run python scripts/estudos.py promover-finalizar {job_id} --nota {nota_qualidade}"
    )
    subprocess.run(["ssh", host, comando_remoto], check=True)


def _abrir_editor(caminho: Path) -> None:
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(caminho)], check=True)


def _revisar_item(item: ItemPromocao, staging_crops_dir: Path, config: ConfigPromotor) -> dict:
    markdown = item.caminho_staging.read_text(encoding="utf-8")

    while True:
        typer.echo(f"\n[{item.status}] {item.caminho_relativo}  (job {item.job_id[:8]})")
        for aviso in item.avisos:
            typer.echo(f"  aviso: {aviso}")

        decisao = typer.prompt("[a]ceitar / [p]ular / [e]ditar", default="p").strip().lower()

        if decisao == "e":
            tmp = item.caminho_staging.parent / f".editando_{item.caminho_staging.name}"
            tmp.write_text(markdown, encoding="utf-8")
            _abrir_editor(tmp)
            markdown = tmp.read_text(encoding="utf-8")
            tmp.unlink(missing_ok=True)
            continue

        if decisao != "a":
            typer.echo("Pulado.")
            return {"job_id": item.job_id, "aceito": False}

        if item.conflito:
            diff = gerar_diff(
                item.caminho_vault.read_text(encoding="utf-8"),
                markdown,
                item.caminho_relativo.name,
            )
            typer.echo(diff or "(sem diferenças de texto)")
            if not typer.confirm(
                "Nota já existe no vault e diverge — sobrescrever?", default=False
            ):
                typer.echo("Pulado (sobrescrita não confirmada).")
                return {"job_id": item.job_id, "aceito": False}

        resolucao = resolver_recortes(markdown, staging_crops_dir)
        for faltante in resolucao.faltando:
            typer.echo(f"  aviso: recorte referenciado e não encontrado: {faltante}")

        copiar_nota_e_recortes(item, markdown, resolucao, config)

        nota_qualidade = None
        while nota_qualidade is None:
            bruto = typer.prompt("Nota de qualidade (1-5)")
            try:
                nota_qualidade = validar_nota_qualidade(bruto)
            except ValueError as erro:
                typer.echo(str(erro))

        finalizar_no_servidor(item.job_id, nota_qualidade, config)

        typer.echo(f"Promovido para {item.caminho_vault}.")
        return {"job_id": item.job_id, "aceito": True, "nota_qualidade": nota_qualidade}


def _loop_interativo(
    itens: list[ItemPromocao], staging_crops_dir: Path, config: ConfigPromotor
) -> list[dict]:
    return [_revisar_item(item, staging_crops_dir, config) for item in itens]


@app.command()
def promover(
    simular: bool = typer.Option(
        True,
        "--simular/--sem-simular",
        help="Dry-run (padrão): só mostra o plano, não toca no vault.",
    ),
) -> None:
    """Sincroniza o staging do servidor e mostra o plano de promoção ao vault (sem escrever nada)."""
    config = carregar_config()
    sincronizar_staging()
    manifesto = ler_manifesto(STAGING_LOCAL_DIR)
    itens = montar_plano(manifesto, STAGING_LOCAL_DIR, config.vault_dir)
    imprimir_plano(itens)

    if simular:
        return

    itens_pendentes = [item for item in itens if item.status != "identico"]
    resultados = _loop_interativo(itens_pendentes, STAGING_CROPS_DIR, config)
    aceitos = sum(1 for r in resultados if r["aceito"])
    typer.echo(f"\n{aceitos}/{len(resultados)} notas promovidas.")


if __name__ == "__main__":
    app()
