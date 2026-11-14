"""Leitura de `multipart/form-data` com a biblioteca padrão.

O módulo `cgi` saiu do Python 3.13, então o corpo é lido por `email.parser`. Devolve os
campos de texto e os arquivos; o nome do arquivo é só um dado para a tela.
"""

from email import policy
from email.parser import BytesParser

from ui.seguranca import PedidoRecusado


def ler_multipart(
    tipo_conteudo: str, corpo: bytes
) -> tuple[dict[str, str], list[tuple[str, bytes]]]:
    if not tipo_conteudo.lower().startswith("multipart/form-data"):
        raise PedidoRecusado(400, "corpo_invalido", "O envio precisa ser multipart/form-data.")
    mensagem = BytesParser(policy=policy.HTTP).parsebytes(
        b"Content-Type: " + tipo_conteudo.encode("latin-1") + b"\r\n\r\n" + corpo
    )
    if not mensagem.is_multipart():
        raise PedidoRecusado(400, "corpo_invalido", "O envio está vazio ou malformado.")

    campos: dict[str, str] = {}
    arquivos: list[tuple[str, bytes]] = []
    for parte in mensagem.iter_parts():
        nome_do_campo = parte.get_param("name", header="content-disposition")
        if not nome_do_campo:
            continue
        carga = parte.get_payload(decode=True) or b""
        nome_do_arquivo = parte.get_filename()
        if nome_do_arquivo is not None:
            arquivos.append((nome_do_arquivo, carga))
        else:
            campos[str(nome_do_campo)] = carga.decode("utf-8", errors="replace")
    return campos, arquivos
