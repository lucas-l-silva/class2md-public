import re
from pathlib import Path

from projetos.estudos.schemas import Problema, Validacao

CAMPOS_TEMPLATE_AULA = {"data", "disciplina", "aula", "tags"}
CAMPOS_TEMPLATE_CONCEITO = {"tipo", "disciplina", "tags"}

SECOES_OBRIGATORIAS_PREFIXOS = (
    "## Resumo da aula",
    "## Conteúdo principal",
    "## Do livro",
    "## Pontos sinalizados como difícil",
    "## Pontos de atenção do professor",
    "## Conceitos novos",
    "## Exercícios relacionados",
    "## Ver também",
)

#: cada perfil exige as seções que fazem sentido nele. Exigir "complexidade" numa nota
#: de idioma não é excesso de zelo: obriga o modelo a preencher a seção com alguma coisa,
#: e a alguma coisa é invenção.
SECOES_OBRIGATORIAS_IDIOMA = (
    "## Resumo da aula",
    "## Vocabulário",
    "## Gramática",
    "## Exemplos de uso",
    "## Pronúncia e armadilhas",
    "## Pontos de atenção do professor",
    "## Exercícios relacionados",
    "## Ver também",
)

SECOES_OBRIGATORIAS_REUNIAO = (
    "## Pauta",
    "## Discussão",
    "## Decisões",
    "## Pendências",
    "## Backlog gerado",
    "## Ver também",
)

SECOES_POR_PERFIL = {
    "tecnica": SECOES_OBRIGATORIAS_PREFIXOS,
    "idioma": SECOES_OBRIGATORIAS_IDIOMA,
    "reuniao": SECOES_OBRIGATORIAS_REUNIAO,
}

SECOES_OBRIGATORIAS_CONCEITO = (
    "## Definição formal",
    "## Intuição",
    "## Exemplo",
    "## Aparece em",
)

_RE_WIKILINK_ABRE = re.compile(r"(?<!!)\[\[")
_RE_WIKILINK_FECHA = re.compile(r"\]\]")
_RE_EMBED = re.compile(r"!\[\[([^\]]+)\]\]")


def _erro(onde: str, descricao: str, sugestao: str) -> Problema:
    return Problema(severidade="erro", onde=onde, descricao=descricao, sugestao=sugestao)


def _checar_frontmatter(
    markdown: str, disciplina_esperada: str, data_esperada: str
) -> list[Problema]:
    problemas: list[Problema] = []

    # A POSIÇÃO importa, não só a presença: o Obsidian (e o Dataview, de que o
    # calendário depende) só lê o frontmatter se ele for a primeira coisa do arquivo.
    # Procurar "---" em qualquer lugar deixava passar nota com título antes do bloco,
    # e até uma com o frontmatter dentro de uma cerca ```yaml.
    if not markdown.startswith("---\n"):
        problemas.append(
            _erro(
                "frontmatter",
                "não está no início do arquivo (o Obsidian só lê frontmatter na 1ª linha)",
                "mover o bloco --- ... --- para antes do título, sem cerca de código",
            )
        )
        return problemas

    fim = markdown.find("\n---", 4)
    if fim == -1:
        problemas.append(
            _erro(
                "frontmatter",
                "bloco --- ... --- não foi fechado",
                "fechar com --- numa linha só",
            )
        )
        return problemas

    corpo_frontmatter = markdown[4:fim]

    chaves: dict[str, str] = {}
    for linha in corpo_frontmatter.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        chave, sep, valor = linha.partition(":")
        if sep:
            chaves[chave.strip()] = valor.strip()

    extras = set(chaves) - CAMPOS_TEMPLATE_AULA
    if extras:
        problemas.append(
            _erro(
                "frontmatter",
                f"campo(s) fora do template: {sorted(extras)}",
                "mover metadados de pipeline para o manifesto, não para o frontmatter",
            )
        )

    faltando = CAMPOS_TEMPLATE_AULA - set(chaves)
    if faltando:
        problemas.append(
            _erro(
                "frontmatter",
                f"campo(s) obrigatório(s) ausente(s): {sorted(faltando)}",
                "incluir no frontmatter",
            )
        )

    if chaves.get("disciplina") and chaves["disciplina"] != disciplina_esperada:
        problemas.append(
            _erro(
                "frontmatter.disciplina",
                f"'{chaves['disciplina']}' diverge da disciplina do job ('{disciplina_esperada}')",
                "corrigir o campo disciplina",
            )
        )

    aula = chaves.get("aula", "")
    if aula and not aula.isdigit():
        problemas.append(
            _erro(
                "frontmatter.aula",
                f"'{aula}' não é um número — quebra o cruzamento com o programa e o Dataview",
                "usar o número da aula; se não souber, use o próximo da sequência",
            )
        )

    if chaves.get("data") and chaves["data"] != data_esperada:
        problemas.append(
            _erro(
                "frontmatter.data",
                f"'{chaves['data']}' diverge da data do job ('{data_esperada}')",
                "corrigir o campo data",
            )
        )

    return problemas


def _checar_secoes(
    markdown: str, prefixos: tuple[str, ...] = SECOES_OBRIGATORIAS_PREFIXOS
) -> list[Problema]:
    problemas = []
    for prefixo in prefixos:
        if not any(linha.startswith(prefixo) for linha in markdown.splitlines()):
            problemas.append(
                _erro(
                    "seções",
                    f"seção obrigatória ausente: '{prefixo}'",
                    "incluir a seção no template",
                )
            )
    return problemas


def _checar_frontmatter_conceito(markdown: str, disciplina_esperada: str) -> list[Problema]:
    problemas: list[Problema] = []
    partes = markdown.split("---")
    if len(partes) < 3:
        problemas.append(
            _erro(
                "frontmatter",
                "bloco --- ... --- ausente ou malformado",
                "adicionar frontmatter YAML",
            )
        )
        return problemas

    chaves: dict[str, str] = {}
    for linha in partes[1].splitlines():
        linha = linha.strip()
        if not linha:
            continue
        chave, sep, valor = linha.partition(":")
        if sep:
            chaves[chave.strip()] = valor.strip()

    faltando = CAMPOS_TEMPLATE_CONCEITO - set(chaves)
    if faltando:
        problemas.append(
            _erro(
                "frontmatter",
                f"campo(s) obrigatório(s) ausente(s): {sorted(faltando)}",
                "incluir no frontmatter",
            )
        )

    if chaves.get("tipo") not in (None, "conceito"):
        problemas.append(
            _erro(
                "frontmatter.tipo",
                f"'{chaves['tipo']}' deveria ser 'conceito'",
                "corrigir o campo tipo",
            )
        )

    if chaves.get("disciplina") and chaves["disciplina"] != disciplina_esperada:
        problemas.append(
            _erro(
                "frontmatter.disciplina",
                f"'{chaves['disciplina']}' diverge da disciplina do job ('{disciplina_esperada}')",
                "corrigir o campo disciplina",
            )
        )

    return problemas


def _checar_dollarsigns(markdown: str) -> list[Problema]:
    if markdown.count("$$") % 2 != 0:
        return [
            _erro(
                "latex",
                "número ímpar de '$$' — bloco de fórmula não fechado",
                "balancear os $$",
            )
        ]
    return []


def _checar_wikilinks(markdown: str) -> list[Problema]:
    # remove os embeds primeiro — ![[...]] também termina em ]], e não deve contar
    # como fechamento de wikilink (já que sua abertura ![[ também não conta como abertura).
    sem_embeds = _RE_EMBED.sub("", markdown)
    abre = len(_RE_WIKILINK_ABRE.findall(sem_embeds))
    fecha = len(_RE_WIKILINK_FECHA.findall(sem_embeds))
    if abre != fecha:
        return [_erro("wikilinks", "'[[' e ']]' desbalanceados", "corrigir os wiki links")]
    return []


def _checar_embeds(markdown: str, pasta_crops: Path) -> list[Problema]:
    problemas = []
    for nome_arquivo in _RE_EMBED.findall(markdown):
        if not (pasta_crops / nome_arquivo).exists():
            problemas.append(
                _erro(
                    "embeds",
                    f"![[{nome_arquivo}]] aponta para recorte inexistente",
                    "remover o embed ou gerar o recorte correspondente",
                )
            )
    return problemas


def _checar_blocos_codigo(markdown: str) -> list[Problema]:
    if markdown.count("```") % 2 != 0:
        return [
            _erro(
                "código",
                "bloco de código (```) não fechado",
                "fechar o bloco de código",
            )
        ]
    return []


def validar_nota(
    markdown: str,
    disciplina_esperada: str,
    data_esperada: str,
    pasta_crops: Path,
    perfil: str = "tecnica",
) -> Validacao:
    problemas = [
        *_checar_frontmatter(markdown, disciplina_esperada, data_esperada),
        *_checar_secoes(markdown, SECOES_POR_PERFIL.get(perfil, SECOES_OBRIGATORIAS_PREFIXOS)),
        *_checar_dollarsigns(markdown),
        *_checar_wikilinks(markdown),
        *_checar_embeds(markdown, pasta_crops),
        *_checar_blocos_codigo(markdown),
    ]
    aprovado = not any(p.severidade == "erro" for p in problemas)
    return Validacao(aprovado=aprovado, problemas=problemas)


def validar_pagina_conceito(markdown: str, disciplina_esperada: str) -> Validacao:
    # Página de conceito não tem crops embutidos nem os campos/seções da nota de aula —
    # reaproveita só as checagens de markdown genéricas (latex/wikilinks/código).
    problemas = [
        *_checar_frontmatter_conceito(markdown, disciplina_esperada),
        *_checar_secoes(markdown, SECOES_OBRIGATORIAS_CONCEITO),
        *_checar_dollarsigns(markdown),
        *_checar_wikilinks(markdown),
        *_checar_blocos_codigo(markdown),
    ]
    aprovado = not any(p.severidade == "erro" for p in problemas)
    return Validacao(aprovado=aprovado, problemas=problemas)
