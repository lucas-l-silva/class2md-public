"""App WSGI da interface local: rotas, cabeçalhos de segurança e arquivos estáticos."""

import json
import re
import sys
import traceback
from pathlib import Path
from urllib.parse import quote

from ui.multipart import ler_multipart
from ui.seguranca import (
    CSP,
    MAX_FOTO_BYTES,
    MAX_FOTOS_POR_ENVIO,
    PORTA_PADRAO,
    PedidoRecusado,
    gerar_token,
    verificar_pedido,
)
from ui.servico import Servico, _sem_segredos

ESTATICO = Path(__file__).parent / "estatico"
MAX_CORPO = MAX_FOTOS_POR_ENVIO * MAX_FOTO_BYTES + 1024 * 1024
STATUS = {
    200: "200 OK",
    400: "400 Bad Request",
    401: "401 Unauthorized",
    402: "402 Payment Required",
    403: "403 Forbidden",
    404: "404 Not Found",
    405: "405 Method Not Allowed",
    409: "409 Conflict",
    413: "413 Payload Too Large",
    500: "500 Internal Server Error",
}
ARQUIVOS = {
    "/estatico/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/estatico/ui.css": ("ui.css", "text/css; charset=utf-8"),
    "/estatico/fluxo-class2md.svg": ("fluxo-class2md.svg", "image/svg+xml"),
    "/estatico/icones.svg": ("icones.svg", "image/svg+xml"),
}


def criar_app(porta: int = PORTA_PADRAO, token: str | None = None, servico: Servico | None = None):
    token = token or gerar_token()
    servico = servico or Servico()

    def json_resposta(codigo: int, dados: dict):
        return (
            codigo,
            "application/json; charset=utf-8",
            json.dumps(dados, ensure_ascii=False).encode("utf-8"),
            [],
        )

    def corpo_json(environ) -> dict:
        bruto = _ler_corpo(environ)
        if not bruto:
            return {}
        try:
            dados = json.loads(bruto)
        except ValueError:
            raise PedidoRecusado(
                400, "json_invalido", "O corpo do pedido não é JSON válido."
            ) from None
        if not isinstance(dados, dict):
            raise PedidoRecusado(
                400, "json_invalido", "O corpo do pedido precisa ser um objeto JSON."
            )
        return dados

    def roteiro(environ):
        metodo = environ["REQUEST_METHOD"]
        caminho = environ.get("PATH_INFO", "/")
        consulta = environ.get("QUERY_STRING", "")

        if metodo == "GET" and caminho == "/":
            html = (ESTATICO / "index.html").read_text(encoding="utf-8").replace("{{TOKEN}}", token)
            return 200, "text/html; charset=utf-8", html.encode("utf-8"), []
        if metodo == "GET" and caminho in ARQUIVOS:
            nome, tipo = ARQUIVOS[caminho]
            arquivo = ESTATICO / nome
            if not arquivo.exists():
                raise PedidoRecusado(404, "nao_encontrado", "Arquivo não encontrado.")
            return 200, tipo, arquivo.read_bytes(), []

        if not caminho.startswith("/api/"):
            raise PedidoRecusado(404, "nao_encontrado", "Página não encontrada.")

        if metodo == "GET" and caminho == "/api/estado":
            return json_resposta(200, servico.estado())
        if metodo == "GET" and caminho == "/api/plano":
            material = dict(p.split("=", 1) for p in consulta.split("&") if "=" in p).get(
                "material", ""
            )
            return json_resposta(200, servico.plano(material))
        if metodo == "POST" and caminho == "/api/materiais":
            campos, arquivos = ler_multipart(environ.get("CONTENT_TYPE", ""), _ler_corpo(environ))
            return json_resposta(200, servico.receber(campos, arquivos))
        achado = re.fullmatch(r"/api/materiais/([0-9a-f]{32})/([0-9a-f]{16})", caminho)
        if achado and metodo == "DELETE":
            return json_resposta(200, servico.remover(*achado.groups()))
        if metodo == "POST" and caminho == "/api/estimativa":
            return json_resposta(200, servico.estimativa(corpo_json(environ)))
        if metodo == "POST" and caminho == "/api/processar":
            return json_resposta(200, servico.processar(corpo_json(environ)))
        if metodo == "GET" and caminho == "/api/notas":
            return json_resposta(200, servico.notas())

        achado = re.fullmatch(r"/api/jobs/([0-9a-f-]{8,36})", caminho)
        if achado and metodo == "GET":
            return json_resposta(200, servico.job(achado.group(1)))
        achado = re.fullmatch(r"/api/jobs/([0-9a-f-]{8,36})/continuar", caminho)
        if achado and metodo == "POST":
            return json_resposta(200, servico.continuar(achado.group(1), corpo_json(environ)))
        achado = re.fullmatch(r"/api/execucao/([0-9a-f-]{8,36})", caminho)
        if achado and metodo == "GET":
            return json_resposta(200, servico.execucao(achado.group(1)))

        achado = re.fullmatch(r"/api/notas/([0-9a-f-]{8,36})", caminho)
        if achado and metodo == "GET":
            return json_resposta(200, servico.nota(achado.group(1)))
        achado = re.fullmatch(r"/api/notas/([0-9a-f-]{8,36})/fotos/(\d{1,3})", caminho)
        if achado and metodo == "GET":
            conteudo, tipo = servico.foto(achado.group(1), int(achado.group(2)))
            return 200, tipo, conteudo, []
        achado = re.fullmatch(r"/api/notas/([0-9a-f-]{8,36})/baixar", caminho)
        if achado and metodo == "GET":
            conteudo, nome = servico.baixar(achado.group(1))
            nome_seguro = re.sub(r"[^A-Za-z0-9._-]", "_", nome)
            cabecalho = (
                "Content-Disposition",
                f"attachment; filename=\"{nome_seguro}\"; filename*=UTF-8''{quote(nome)}",
            )
            return 200, "text/markdown; charset=utf-8", conteudo, [cabecalho]

        if caminho in ("/api/duvidas", "/api/duvidas/aprovar"):
            servico.duvidas()
        if caminho == "/api/economia":
            servico.economia()

        raise PedidoRecusado(404, "nao_encontrado", "Rota não encontrada.")

    def app(environ, start_response):
        try:
            verificar_pedido(environ, porta, token)
            codigo, tipo, corpo, extras = roteiro(environ)
        except PedidoRecusado as recusa:
            codigo, tipo, corpo, extras = json_resposta(
                recusa.status, {"erro": recusa.codigo, "mensagem": recusa.mensagem}
            )
        except Exception as erro:  # noqa: BLE001 - nunca devolver rastro de pilha
            print(_sem_segredos(traceback.format_exc()), file=sys.stderr)
            codigo, tipo, corpo, extras = json_resposta(
                500,
                {
                    "erro": "erro_interno",
                    "mensagem": "Algo deu errado dentro do programa. Veja o terminal.",
                },
            )
            del erro
        cabecalhos = [
            ("Content-Type", tipo),
            ("Content-Length", str(len(corpo))),
            ("Content-Security-Policy", CSP),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("Cache-Control", "no-store"),
            *extras,
        ]
        start_response(STATUS.get(codigo, f"{codigo} Erro"), cabecalhos)
        return [corpo]

    app.token = token
    app.servico = servico
    return app


def _ler_corpo(environ) -> bytes:
    try:
        tamanho = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        raise PedidoRecusado(400, "corpo_invalido", "Tamanho do corpo inválido.") from None
    if tamanho > MAX_CORPO:
        raise PedidoRecusado(413, "corpo_grande", "O envio passa do limite permitido.")
    return environ["wsgi.input"].read(tamanho) if tamanho else b""
