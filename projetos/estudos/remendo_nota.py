import re

from projetos.estudos.markdown_fmt import juntar_paragrafos
from projetos.estudos.schemas import SaidaBibliotecario

_RE_SECAO = re.compile(r"^## (.+)$", re.MULTILINE)

# Blocos gerenciados: a parte do arquivo que o pipeline pode reescrever. Tudo que
# estiver fora dos marcadores é do usuário e sai byte-idêntico. Casar por título de
# seção não serviria aqui, porque um MOC mistura seções geradas com seções escritas
# à mão — e às vezes com o mesmo título.
_MARCA_INICIO = "<!-- moc:inicio {chave} -->"
_MARCA_FIM = "<!-- moc:fim {chave} -->"
_RE_BLOCO = re.compile(
    r"<!-- moc:inicio (?P<chave>[a-z0-9_]+) -->\n(?P<corpo>.*?)<!-- moc:fim (?P=chave) -->",
    re.DOTALL,
)
_RE_CHAVE = re.compile(r"^[a-z0-9_]+$")


class SecaoAusente(Exception):
    pass


class ChaveInvalida(Exception):
    """Chave de bloco fora de `[a-z0-9_]+` — entraria no marcador e quebraria o casamento."""


def secoes(markdown: str) -> list[tuple[str, str]]:
    """Devolve [(linha do título "## ...", corpo até a próxima "## " ou fim)], na ordem."""
    matches = list(_RE_SECAO.finditer(markdown))
    resultado = []
    for indice, match in enumerate(matches):
        inicio_corpo = match.end()
        fim_corpo = matches[indice + 1].start() if indice + 1 < len(matches) else len(markdown)
        resultado.append((match.group(0), markdown[inicio_corpo:fim_corpo]))
    return resultado


def substituir_secao(markdown: str, prefixo_titulo: str, novo_corpo: str) -> str:
    """Troca só o corpo da seção cujo título (depois de '## ') começa com `prefixo_titulo`.
    Todo o resto do markdown sai byte-idêntico. `## Do livro — Autor, ano, cap.` casa com
    prefixo "Do livro" (o template permite completar o título com a citação)."""
    matches = list(_RE_SECAO.finditer(markdown))
    for indice, match in enumerate(matches):
        if not match.group(1).startswith(prefixo_titulo):
            continue
        inicio_corpo = match.end()
        fim_corpo = matches[indice + 1].start() if indice + 1 < len(matches) else len(markdown)
        return markdown[:inicio_corpo] + novo_corpo + markdown[fim_corpo:]

    raise SecaoAusente(f"nota não tem seção '## {prefixo_titulo}...'")


def colapsar_secoes(markdown: str, prefixo_titulo: str) -> str:
    """Funde em uma só as seções repetidas cujo título começa com `prefixo_titulo`.

    Conserta um estrago acumulado: `substituir_secao` troca o *corpo* da primeira seção
    "Do livro", mas o bibliotecário emitia o próprio cabeçalho `## Do livro — CLRS…`
    dentro desse corpo. O cabeçalho novo virava a fronteira da seção, e a execução
    seguinte inseria antes dele — uma seção a mais por rodada. A nota da MAT1 aula 1
    chegou a quatro.

    Mantém o título da **última** (é a que traz a citação completa) e o corpo de todas,
    na ordem em que aparecem.
    """
    todos = list(_RE_SECAO.finditer(markdown))
    alvos = [i for i, m in enumerate(todos) if m.group(1).startswith(prefixo_titulo)]
    if len(alvos) < 2:
        return markdown

    corpos = []
    for indice in alvos:
        fim = todos[indice + 1].start() if indice + 1 < len(todos) else len(markdown)
        corpo = markdown[todos[indice].end() : fim].strip("\n")
        if corpo:
            corpos.append(corpo)

    primeiro, ultimo = alvos[0], alvos[-1]
    fim_ultimo = todos[ultimo + 1].start() if ultimo + 1 < len(todos) else len(markdown)
    miolo = ("\n\n".join(corpos) + "\n\n") if corpos else "\n"
    fundido = f"{todos[ultimo].group(0)}\n\n{miolo}"

    return markdown[: todos[primeiro].start()] + fundido + markdown[fim_ultimo:]


def inserir_no_fim_da_secao(markdown: str, titulo: str, bloco: str) -> str:
    """Acrescenta `bloco` no fim da seção de título `titulo` (`##` ou `###`).

    É o que põe a resposta do livro **onde ela responde**, em vez de num apanhado no fim
    da nota. Seção inexistente devolve o markdown intacto: o alvo vem do modelo e pode
    citar uma seção que não existe — perder o texto seria pior que ignorar o destino.
    """
    padrao = re.compile(r"^#{2,3} " + re.escape(titulo.strip()) + r"\s*$", re.MULTILINE)
    match = padrao.search(markdown)
    if match is None:
        return markdown

    proximo = re.compile(r"^#{2,3} ", re.MULTILINE).search(markdown, match.end())
    fim = proximo.start() if proximo else len(markdown)
    corpo = markdown[match.end() : fim].rstrip("\n")

    return markdown[: match.end()] + corpo + f"\n\n{bloco.strip()}\n\n" + markdown[fim:]


def _remover_citacoes_do_livro(markdown: str) -> str:
    """Tira os callouts `> [!quote] Do livro` já inseridos.

    É o que torna `preencher-lacunas` idempotente: sem isso, cada execução acrescentaria
    outra citação do mesmo trecho dentro da mesma seção.
    """
    return re.sub(
        r"\n*^> \[!quote\] Do livro.*?(?=\n(?!>)|\Z)",
        "",
        markdown,
        flags=re.MULTILINE | re.DOTALL,
    )


def _callout_do_livro(resposta) -> str:
    corpo = "\n".join(f"> {linha}" for linha in resposta.resposta.strip().split("\n"))
    return f"> [!quote] Do livro — {resposta.citacao}\n>\n{corpo}"


def renderizar_procedencia(saida: SaidaBibliotecario) -> str:
    """Monta a seção "Do livro" a partir dos campos estruturados, em Python.

    Renderizar aqui em vez de aceitar markdown do modelo é o que impede a seção de voltar
    a crescer: o agente não tem campo de prosa livre para preencher.
    """
    partes = []
    if saida.obras_consultadas:
        partes.append(
            "**Consultado:**\n" + "\n".join(f"- {obra}" for obra in saida.obras_consultadas)
        )
    if saida.divergencias:
        partes.append(
            "**Divergências entre a aula e o livro:**\n"
            + "\n".join(f"- {item}" for item in saida.divergencias)
        )
    if saida.nao_coberto:
        partes.append(
            "**Não coberto pelos trechos consultados:**\n"
            + "\n".join(f"- {item}" for item in saida.nao_coberto)
        )
    return "\n\n".join(partes) if partes else "(nenhuma fonte consultada ainda)"


def aplicar(markdown: str, saida: SaidaBibliotecario) -> str:
    """Integra o livro na nota: cada resposta entra na seção que ela responde.

    A seção "Do livro" fica só com a procedência — o que foi consultado e onde conferir.
    O conteúdo em si vai para o corpo, porque uma seção monolítica no fim da nota é lida
    como apêndice e não como parte da matéria.
    """
    novo = colapsar_secoes(markdown, "Do livro")
    novo = _remover_citacoes_do_livro(novo)

    for resposta in saida.respostas:
        if resposta.resolvida and resposta.secao_alvo and resposta.citacao:
            novo = inserir_no_fim_da_secao(novo, resposta.secao_alvo, _callout_do_livro(resposta))

    novo = substituir_secao(novo, "Do livro", f"\n{renderizar_procedencia(saida)}\n\n")

    resolvidas = {resposta.lacuna for resposta in saida.respostas if resposta.resolvida}

    corpo_atual = next(
        (
            corpo
            for titulo, corpo in secoes(novo)
            if titulo.startswith("## Pontos sinalizados como difícil")
        ),
        None,
    )
    if corpo_atual is None:
        raise SecaoAusente("nota não tem seção '## Pontos sinalizados como difícil...'")

    linhas_mantidas = []
    for linha in corpo_atual.splitlines():
        texto_item = linha.lstrip("-* ").strip()
        foi_resolvida = any(
            texto_item == lacuna or texto_item.startswith(lacuna) for lacuna in resolvidas
        )
        if not foi_resolvida:
            linhas_mantidas.append(linha)

    corpo_novo = "\n".join(linhas_mantidas).strip("\n")
    corpo_novo = f"\n{corpo_novo}\n\n" if corpo_novo else "\n(nenhum ponto pendente)\n\n"

    return juntar_paragrafos(substituir_secao(novo, "Pontos sinalizados como difícil", corpo_novo))


def blocos(markdown: str) -> dict[str, str]:
    """Blocos gerenciados presentes no documento: {chave: corpo}.

    Bloco duplicado (mesma chave duas vezes) fica com a primeira ocorrência, que é
    a que `substituir_bloco` reescreve — assim ler e escrever concordam.
    """
    encontrados: dict[str, str] = {}
    for match in _RE_BLOCO.finditer(markdown):
        encontrados.setdefault(match.group("chave"), match.group("corpo"))
    return encontrados


def _validar_chave(chave: str) -> None:
    if not _RE_CHAVE.match(chave):
        raise ChaveInvalida(f"chave de bloco inválida: {chave!r} (use [a-z0-9_]+)")


def envolver_bloco(chave: str, corpo: str) -> str:
    """Corpo com os marcadores em volta, pronto para ser concatenado."""
    _validar_chave(chave)
    corpo = corpo.strip("\n")
    return (
        _MARCA_INICIO.format(chave=chave)
        + "\n"
        + (f"{corpo}\n" if corpo else "")
        + _MARCA_FIM.format(chave=chave)
    )


def substituir_bloco(markdown: str, chave: str, novo_corpo: str) -> str:
    """Reescreve só o bloco `chave`, preservando o resto byte a byte.

    Bloco ausente é **acrescentado no fim** em vez de erro: um MOC que você começou
    à mão não deve ser rejeitado só porque ainda não tem a marcação, e acrescentar
    nunca sobrescreve texto seu.
    """
    _validar_chave(chave)
    bloco_novo = envolver_bloco(chave, novo_corpo)

    match = _RE_BLOCO.search(markdown)
    while match is not None and match.group("chave") != chave:
        match = _RE_BLOCO.search(markdown, match.end())

    if match is None:
        if not markdown or markdown.endswith("\n\n"):
            separador = ""
        elif markdown.endswith("\n"):
            separador = "\n"
        else:
            separador = "\n\n"
        return markdown + separador + bloco_novo + "\n"

    return markdown[: match.start()] + bloco_novo + markdown[match.end() :]


def aplicar_blocos(markdown: str, novos: dict[str, str]) -> str:
    """`substituir_bloco` para vários blocos, na ordem dada."""
    resultado = markdown
    for chave, corpo in novos.items():
        resultado = substituir_bloco(resultado, chave, corpo)
    return resultado
