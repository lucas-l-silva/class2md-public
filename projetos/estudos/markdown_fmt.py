"""Normalização de formatação do markdown gerado.

Os modelos quebram parágrafos em linhas de ~100 caracteres porque é isso que veem no
template — `ESTRUTURA_MARKDOWN.md` foi escrito com quebra manual, e tanto o compositor
quanto o bibliotecário imitam a disciplina de linha do exemplo. No Obsidian o parágrafo
até renderiza junto, mas o arquivo fica ruim de editar e qualquer diff vira ruído.

**A correção é aqui, em Python, não no prompt.** Um prompt pode pedir "não quebre linhas"
e ser ignorado; um passo determinístico depois da geração, não. É a mesma escolha já feita
em `fontes.py` para a ordenação das fontes.

O risco é o inverso: juntar o que *não* era parágrafo. Por isso a regra é conservadora —
só se juntam duas linhas quando **ambas** são prosa pura, e qualquer sinal de estrutura
(lista, tabela, título, citação, cerca de código, imagem, LaTeX de bloco) interrompe.
"""

import re

#: uma linha que começa com qualquer um destes carrega estrutura e nunca é juntada
_RE_ESTRUTURA = re.compile(
    r"""^\s*(
        \#{1,6}\s      # título
      | [-*+]\s        # lista não ordenada
      | \d+[.)]\s      # lista ordenada
      | >              # citação / callout
      | \|             # tabela
      | \$\$           # LaTeX de bloco
      | !\[            # imagem  ![[...]] ou ![](...)
      | ---\s*$        # regra horizontal / fim de frontmatter
      | :{3,}          # bloco de admonição
      | <              # HTML / marcador de bloco gerenciado
    )""",
    re.VERBOSE,
)

_RE_CERCA = re.compile(r"^\s*(```|~~~)")

#: linha que termina com dois espaços é quebra de linha *intencional* em markdown
_RE_QUEBRA_EXPLICITA = re.compile(r"\S {2,}$")


def _e_prosa(linha: str) -> bool:
    return bool(linha.strip()) and not _RE_ESTRUTURA.match(linha)


def juntar_paragrafos(markdown: str) -> str:
    """Junta linhas consecutivas de prosa num parágrafo só.

    Preserva byte a byte tudo que não for prosa contínua: frontmatter, blocos de código,
    tabelas, listas, callouts, títulos e linhas em branco (que separam parágrafos).
    """
    linhas = markdown.split("\n")
    saida: list[str] = []
    dentro_de_cerca = False
    dentro_de_frontmatter = linhas and linhas[0].strip() == "---"

    for indice, linha in enumerate(linhas):
        if _RE_CERCA.match(linha):
            dentro_de_cerca = not dentro_de_cerca
            saida.append(linha)
            continue

        if dentro_de_frontmatter:
            saida.append(linha)
            # o segundo "---" fecha o frontmatter (o primeiro é a linha 0)
            if indice > 0 and linha.strip() == "---":
                dentro_de_frontmatter = False
            continue

        anterior = saida[-1] if saida else ""
        pode_juntar = (
            not dentro_de_cerca
            and _e_prosa(linha)
            and _e_prosa(anterior)
            and not _RE_QUEBRA_EXPLICITA.search(anterior)
        )
        if pode_juntar:
            saida[-1] = f"{anterior.rstrip()} {linha.strip()}"
        else:
            saida.append(linha)

    return "\n".join(saida)
