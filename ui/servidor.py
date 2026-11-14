"""Sobe a interface local. Só escuta em loopback."""

from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from ui.app import criar_app
from ui.seguranca import HOST_PADRAO, PORTA_PADRAO, verificar_host_recusado


class _ServidorComThreads(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _SemLog(WSGIRequestHandler):
    def log_message(self, *args):  # a URL pode ter ids; o terminal fica limpo
        pass


def servir(host: str = HOST_PADRAO, porta: int = PORTA_PADRAO) -> None:
    verificar_host_recusado(host)  # S1: recusa antes de abrir a porta
    app = criar_app(porta=porta)
    with make_server(
        HOST_PADRAO, porta, app, server_class=_ServidorComThreads, handler_class=_SemLog
    ) as servidor:
        print(f"class2md: http://{HOST_PADRAO}:{porta}  (Ctrl+C para parar)")
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nEncerrado.")
