"""Testes da página estática: segurança (S7, S8) e acessibilidade por leitura do HTML e do CSS."""

import re
from html.parser import HTMLParser
from pathlib import Path

from apoio_interface import chamar

ESTATICO = Path(__file__).parents[2] / "ui" / "estatico"
HTML = (ESTATICO / "index.html").read_text(encoding="utf-8")
JS = (ESTATICO / "app.js").read_text(encoding="utf-8")
CSS = (ESTATICO / "ui.css").read_text(encoding="utf-8")


class _Lista(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def _tags():
    p = _Lista()
    p.feed(HTML)
    return p.tags


def test_js_nao_usa_innerhtml():
    for proibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert proibido not in JS


def test_html_nao_referencia_dominio_externo():
    for texto in (HTML, JS, CSS):
        sem_comentario = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
        assert not re.search(r"https?://|(?<![:\w])//[a-z0-9-]+\.[a-z]", sem_comentario)


def test_pagina_serve_token_na_meta(app):
    r = chamar(app, "GET", "/")
    assert f'content="{app.token}"' in r.texto and "{{TOKEN}}" not in r.texto
    assert chamar(app, "GET", "/estatico/app.js").status == 200
    assert chamar(app, "GET", "/estatico/ui.css").status == 200
    assert chamar(app, "GET", "/estatico/icones.svg").status == 200


def test_todo_campo_tem_rotulo():
    for tag, attrs in _tags():
        if tag in ("input", "select", "textarea"):
            assert "aria-label" in attrs or "id" in attrs  # rotulado por label for no JS


def test_nenhum_tabindex_positivo():
    for texto in (HTML, JS):
        for valor in re.findall(r"tabindex[\"']?\s*[:=,]\s*[\"']?(-?\d+)", texto):
            assert int(valor) <= 0


def test_nenhuma_opcao_vem_marcada():
    for _, attrs in _tags():
        assert "checked" not in attrs and "selected" not in attrs


def test_js_nao_marca_opcao_por_padrao():
    assert "checked: true" not in JS


def test_titulos_sem_salto():
    niveis = [int(t[1]) for t, _ in _tags() if re.fullmatch(r"h[1-6]", t)]
    assert niveis == [1]


def test_css_respeita_movimento_reduzido():
    sem_comentario = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    profundidade = 0
    esta_dentro = []
    for token in re.finditer(r"@media[^{]*\{|\{|\}|animation\s*:|transition\s*:", sem_comentario):
        t = token.group(0)
        if t.startswith("@media"):
            profundidade += 1
            esta_dentro.append("no-preference" in t)
        elif t == "{":
            profundidade += 1
            esta_dentro.append(esta_dentro[-1] if esta_dentro else False)
        elif t == "}":
            profundidade -= 1
            esta_dentro.pop()
        else:
            assert esta_dentro and esta_dentro[-1], (
                "animação fora de prefers-reduced-motion: no-preference"
            )


def test_cada_estado_da_lista_tem_marca_e_palavra():
    estados = {"espera", "rodando", "feito", "guardado", "aviso", "falhou", "pulada"}
    bloco = JS[JS.index("SITUACAO_ETAPA = {") :].split("};")[0]
    for estado in estados:
        assert re.search(rf"\b{estado}:\s*\[\"[^\"]+\",\s*\"[^\"]+\"\]", bloco)


def test_tela_nao_repete_numero_de_custo_fixo():
    assert not re.search(r"US\$\s*\d", JS)
