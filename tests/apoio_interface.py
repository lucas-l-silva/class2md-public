import io
import json
from urllib.parse import urlsplit

from PIL import Image

CHAVE_DE_TESTE = "sk-ant-TESTE-reconhecivel-0123456789"
PORTA = 8765
TOKEN = "token-de-teste"


def foto(cor=(200, 30, 30), formato="JPEG", tamanho=(64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", tamanho, cor).save(buffer, formato)
    return buffer.getvalue()


def multipart(campos: dict, arquivos: list[tuple[str, bytes]]):
    limite = "----limite123"
    partes = []
    for nome, valor in campos.items():
        partes.append(
            f'--{limite}\r\nContent-Disposition: form-data; name="{nome}"\r\n\r\n{valor}\r\n'.encode()
        )
    for nome, conteudo in arquivos:
        partes.append(
            (
                f'--{limite}\r\nContent-Disposition: form-data; name="arquivos"; '
                f'filename="{nome}"\r\nContent-Type: application/octet-stream\r\n\r\n'
            ).encode()
            + conteudo
            + b"\r\n"
        )
    partes.append(f"--{limite}--\r\n".encode())
    return f"multipart/form-data; boundary={limite}", b"".join(partes)


class Resposta:
    def __init__(self, status, cabecalhos, corpo):
        self.status = int(status.split()[0])
        self.cabecalhos = dict(cabecalhos)
        self.corpo = corpo

    def json(self):
        return json.loads(self.corpo)

    @property
    def texto(self):
        return self.corpo.decode("utf-8")


def chamar(
    app,
    metodo,
    caminho,
    corpo=None,
    tipo=None,
    cabecalhos=None,
    token=TOKEN,
    host=f"127.0.0.1:{PORTA}",
):
    if isinstance(corpo, (dict, list)):
        corpo = json.dumps(corpo).encode()
        tipo = "application/json"
    corpo = corpo or b""
    partes = urlsplit(caminho)
    ambiente = {
        "REQUEST_METHOD": metodo,
        "PATH_INFO": partes.path,
        "QUERY_STRING": partes.query,
        "HTTP_HOST": host,
        "CONTENT_LENGTH": str(len(corpo)),
        "CONTENT_TYPE": tipo or "",
        "wsgi.input": io.BytesIO(corpo),
    }
    if token and metodo in ("POST", "DELETE"):
        ambiente["HTTP_X_CLASS2MD_TOKEN"] = token
    for chave, valor in (cabecalhos or {}).items():
        ambiente["HTTP_" + chave.upper().replace("-", "_")] = valor
    capturado = {}

    def start(status, heads):
        capturado["status"], capturado["heads"] = status, heads

    saida = b"".join(app(ambiente, start))
    return Resposta(capturado["status"], capturado["heads"], saida)
