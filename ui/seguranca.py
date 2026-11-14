"""Regras de segurança da interface local (S1 a S10 da especificação).

Sem dependência externa e sem acesso à chave da API: este módulo só decide se um pedido
pode entrar e se um arquivo enviado pode ser gravado.
"""

import hmac
import io
import os
import re
import secrets
from pathlib import Path

from PIL import Image, UnidentifiedImageError

HOST_PADRAO = "127.0.0.1"
PORTA_PADRAO = 8765
CABECALHO_TOKEN = "HTTP_X_CLASS2MD_TOKEN"

CSP = (
    "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

RE_DISCIPLINA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")

MAX_FOTO_BYTES = 12 * 1024 * 1024
MAX_FOTOS_POR_ENVIO = 60

FORMATOS_ACEITOS = {"JPEG": ".jpg", "PNG": ".png"}


class PedidoRecusado(Exception):
    """Erro com código HTTP, código curto e frase para a tela."""

    def __init__(self, status: int, codigo: str, mensagem: str):
        self.status = status
        self.codigo = codigo
        self.mensagem = mensagem
        super().__init__(mensagem)


def gerar_token() -> str:
    return secrets.token_urlsafe(32)


def hosts_permitidos(porta: int) -> set[str]:
    return {f"{HOST_PADRAO}:{porta}", f"localhost:{porta}"}


def verificar_host_recusado(host: str) -> None:
    """S1: a interface só escuta em loopback. Recusa antes de abrir a porta."""
    if host not in (HOST_PADRAO, "localhost"):
        raise ValueError(
            f"Recusado: a interface só escuta em {HOST_PADRAO}. "
            "Expor esta página na rede deixaria qualquer pessoa usar a sua chave."
        )


def verificar_pedido(environ: dict, porta: int, token: str) -> None:
    """S2, S3 e S10. Levanta `PedidoRecusado` se o pedido não pode entrar."""
    permitidos = hosts_permitidos(porta)
    if environ.get("HTTP_HOST", "") not in permitidos:
        raise PedidoRecusado(403, "host_recusado", "Endereço não permitido.")

    origem = environ.get("HTTP_ORIGIN")
    if origem is not None and origem not in {f"http://{h}" for h in permitidos}:
        raise PedidoRecusado(403, "origem_recusada", "Origem não permitida.")

    if environ.get("REQUEST_METHOD", "GET") in ("GET", "HEAD"):
        return

    enviado = environ.get(CABECALHO_TOKEN, "")
    if enviado and hmac.compare_digest(enviado, token):
        return

    autorizacao = environ.get("HTTP_AUTHORIZATION")
    if autorizacao is not None and origem is None:
        esperado = os.environ.get("CLASS2MD_API_TOKEN")
        if not esperado:
            raise PedidoRecusado(401, "api_desligada", "Acesso por token está desligado.")
        if hmac.compare_digest(autorizacao, f"Bearer {esperado}"):
            return
        raise PedidoRecusado(401, "token_invalido", "Token inválido.")

    raise PedidoRecusado(403, "token_ausente", "Pedido sem o token da sessão.")


def disciplina_valida(nome: str) -> str:
    if not isinstance(nome, str) or not RE_DISCIPLINA.match(nome):
        raise PedidoRecusado(
            400,
            "disciplina_invalida",
            "Use só letras, números, ponto, hífen e sublinhado. Até 32 caracteres.",
        )
    return nome


def dentro_da_pasta(caminho: Path, base: Path) -> Path:
    """S5: o caminho resolvido (seguindo links) tem de ficar dentro de `base`."""
    resolvido = caminho.resolve()
    if not resolvido.is_relative_to(base.resolve()):
        raise PedidoRecusado(400, "caminho_fora_da_pasta", "Caminho fora da pasta de dados.")
    return resolvido


def formato_da_imagem(conteudo: bytes) -> str:
    """S4: confere o conteúdo, não a extensão. Devolve a extensão ou recusa com motivo."""
    if conteudo[4:8] == b"ftyp" and conteudo[8:12] in (b"heic", b"heix", b"mif1", b"hevc"):
        raise PedidoRecusado(
            400,
            "heic",
            "Este arquivo está em HEIC. Exporte como JPEG e envie de novo. "
            "No iPhone: Ajustes, Câmera, Formatos, Mais Compatível.",
        )
    if conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP":
        raise PedidoRecusado(400, "webp", "WebP ainda não é aceito. Converta para JPEG ou PNG.")
    try:
        with Image.open(io.BytesIO(conteudo)) as imagem:
            formato = imagem.format
            imagem.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise PedidoRecusado(
            400, "nao_e_imagem", "O arquivo não é uma foto JPEG ou PNG válida."
        ) from None
    if formato not in FORMATOS_ACEITOS:
        raise PedidoRecusado(400, "formato_nao_aceito", "Só JPEG e PNG são aceitos neste envio.")
    return FORMATOS_ACEITOS[formato]
