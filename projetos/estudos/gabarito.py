"""Gabaritos: a nota diz **onde** conferir a solução, nunca copia a solução.

Um manual de soluções é a fonte mais tentadora e a mais nociva para o objetivo do
pipeline: se o texto dele entra na nota, o exercício vem resolvido e o trabalho de
chegar lá — que é o que ensina — desaparece. Por isso o gabarito nunca vira
`TrechoFonte`: ele só alimenta um **localizador**.

O localizador é construído de forma determinística, varrendo o PDF por marcações
do tipo "Exercise 2.1-1" e "Problem 2-2" e anotando a página. Sem LLM, portanto
sem risco de inventar uma referência que não existe.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from core.fileops import escrever_texto, ler_texto
from core.logging import registrar_evento
from core.pdf import texto_paginas
from projetos.estudos.pdf_ingestao import (
    RegistroPdf,
    _caminho_cache_pdf,
    registros_por_disciplina,
)

NOME_CACHE = "solucoes.json"

_RE_REFERENCIA = re.compile(
    r"\b(?:Exerc[ií]cio|Exercise)\s+(\d{1,2}\.\d{1,2}-\d{1,2})"
    r"|\b(?:Problema|Problem)\s+(\d{1,2}-\d{1,2})",
    re.IGNORECASE,
)
_RE_CAPITULO_DA_REFERENCIA = re.compile(r"^(\d{1,2})")


@dataclass(frozen=True)
class Localizacao:
    arquivo: str
    referencia: str
    pagina: int

    def __str__(self) -> str:
        return f"{self.arquivo}, {self.referencia}, p. {self.pagina}"


def _caminho_indice(sha256: str):
    return _caminho_cache_pdf(sha256) / NOME_CACHE


def indice_de_solucoes(registro: RegistroPdf) -> dict[str, int]:
    """{referência do exercício → página}, cacheado por hash do PDF.

    Varre o PDF inteiro uma vez. É caro em I/O, não em API: nenhum modelo é chamado.
    """
    caminho_cache = _caminho_indice(registro.sha256)
    try:
        return json.loads(ler_texto(caminho_cache))
    except FileNotFoundError:
        pass

    encontrado: dict[str, int] = {}
    paginas = texto_paginas(Path(registro.caminho), 1, registro.paginas)
    for numero, texto in enumerate(paginas, start=1):
        for match in _RE_REFERENCIA.finditer(texto):
            referencia = match.group(1) or match.group(2)
            # a primeira ocorrência é onde a solução começa
            encontrado.setdefault(referencia, numero)

    escrever_texto(caminho_cache, json.dumps(encontrado, ensure_ascii=False, indent=2))
    registrar_evento(
        passo="gabarito",
        resultado=f"{registro.nome_arquivo}: {len(encontrado)} referências indexadas",
    )
    return encontrado


def gabaritos_da_disciplina(disciplina: str) -> list[RegistroPdf]:
    return registros_por_disciplina(disciplina, tipo="gabarito")


def localizar(disciplina: str, referencias: list[str]) -> list[Localizacao]:
    """Onde encontrar a solução de cada exercício pedido, nos gabaritos da disciplina."""
    achados: list[Localizacao] = []
    for registro in gabaritos_da_disciplina(disciplina):
        if not registro.tem_texto_nativo:
            continue
        indice = indice_de_solucoes(registro)
        for referencia in referencias:
            pagina = indice.get(referencia)
            if pagina is not None:
                achados.append(
                    Localizacao(
                        arquivo=registro.nome_arquivo,
                        referencia=referencia,
                        pagina=pagina,
                    )
                )
    return achados


def localizar_capitulos(
    disciplina: str, capitulos: list[int], limite: int = 8
) -> list[Localizacao]:
    """Primeiras soluções de cada capítulo — útil quando não se sabe o exercício exato."""
    achados: list[Localizacao] = []
    alvos = {str(c) for c in capitulos}
    for registro in gabaritos_da_disciplina(disciplina):
        if not registro.tem_texto_nativo:
            continue
        indice = indice_de_solucoes(registro)
        do_capitulo = [
            (ref, pagina)
            for ref, pagina in indice.items()
            if (m := _RE_CAPITULO_DA_REFERENCIA.match(ref)) and m.group(1) in alvos
        ]
        do_capitulo.sort(key=lambda par: par[1])
        achados.extend(
            Localizacao(arquivo=registro.nome_arquivo, referencia=ref, pagina=pagina)
            for ref, pagina in do_capitulo[:limite]
        )
    return achados


def secao_onde_conferir(localizacoes: list[Localizacao]) -> str:
    """Markdown pronto para a nota. Vazio quando não há nada a apontar."""
    if not localizacoes:
        return ""
    linhas = ["> [!tip] Onde conferir a solução", ">"]
    linhas += [f"> - {loc}" for loc in localizacoes]
    linhas.append(">")
    linhas.append("> As soluções não são copiadas para a nota de propósito — tente antes de olhar.")
    return "\n".join(linhas)
