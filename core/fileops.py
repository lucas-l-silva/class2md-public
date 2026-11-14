import shutil
from pathlib import Path

from core.config import Settings, get_settings
from core.logging import registrar_evento


class CaminhoForaDaAllowlist(Exception):
    pass


def _validar(caminho: Path, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    resolvido = caminho.resolve()

    for base in settings.allowlist_dirs:
        if resolvido.is_relative_to(base.resolve()):
            return resolvido

    raise CaminhoForaDaAllowlist(f"caminho fora da allowlist: {resolvido}")


def ler(caminho: Path, settings: Settings | None = None) -> bytes:
    caminho = _validar(caminho, settings)
    conteudo = caminho.read_bytes()
    registrar_evento(passo="fileops.ler", resultado=str(caminho))
    return conteudo


def ler_texto(caminho: Path, encoding: str = "utf-8", settings: Settings | None = None) -> str:
    caminho = _validar(caminho, settings)
    conteudo = caminho.read_text(encoding=encoding)
    registrar_evento(passo="fileops.ler_texto", resultado=str(caminho))
    return conteudo


def escrever(caminho: Path, conteudo: bytes, settings: Settings | None = None) -> None:
    caminho = _validar(caminho, settings)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    registrar_evento(passo="fileops.escrever", resultado=str(caminho))


def escrever_texto(
    caminho: Path,
    conteudo: str,
    encoding: str = "utf-8",
    settings: Settings | None = None,
) -> None:
    caminho = _validar(caminho, settings)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(conteudo, encoding=encoding)
    registrar_evento(passo="fileops.escrever_texto", resultado=str(caminho))


def mover(origem: Path, destino: Path, settings: Settings | None = None) -> None:
    origem = _validar(origem, settings)
    destino = _validar(destino, settings)
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), str(destino))
    registrar_evento(passo="fileops.mover", resultado=f"{origem} -> {destino}")


def listar(diretorio: Path, padrao: str = "*", settings: Settings | None = None) -> list[Path]:
    diretorio = _validar(diretorio, settings)
    return list(diretorio.glob(padrao))


def remover(caminho: Path, settings: Settings | None = None) -> None:
    caminho = _validar(caminho, settings)
    caminho.unlink(missing_ok=True)
    registrar_evento(passo="fileops.remover", resultado=str(caminho))
