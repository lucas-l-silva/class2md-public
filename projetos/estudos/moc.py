"""Geração das notas-home (MOC) de cada disciplina e do hub central.

Renderização **determinística**: nenhum modelo é chamado. Tudo vem de dados que já
foram apurados e conferidos — registro, ementa, programa e notas existentes.
Isso torna o comando idempotente, de graça, e impossível
de alucinar: um MOC nunca vai afirmar algo que não esteja em algum desses lugares.


Tudo o que o usuário escreve **fora** dos marcadores `<!-- moc:inicio X -->` é
preservado byte a byte — é para isso que `remendo_nota.substituir_bloco` existe.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from core.config import get_settings
from core.fileops import escrever_texto, ler_texto, listar
from core.logging import registrar_evento
from projetos.estudos import ementa as modulo_ementa
from projetos.estudos import programa as modulo_programa
from projetos.estudos.disciplinas import (
    Disciplina,
    DisciplinaDesconhecida,
    RegistroAusente,
    RegistroInvalido,
    carregar_registro,
    disciplinas_ativas,
)
from projetos.estudos.disciplinas import (
    disciplina as buscar_disciplina,
)
from projetos.estudos.pdf_ingestao import registros_por_disciplina
from projetos.estudos.remendo_nota import aplicar_blocos

NOME_CENTRAL = "Ciência de Dados - MOC.md"
SECAO_PONTOS = "## Pontos de atenção do professor"
_SEM_PONTOS = "(nada sinalizado nesta aula)"

_RE_FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_RE_TITULO = re.compile(r"^# (.+)$", re.MULTILINE)
_DIAS = {
    "seg": "Segunda",
    "ter": "Terça",
    "qua": "Quarta",
    "qui": "Quinta",
    "sex": "Sexta",
    "sab": "Sábado",
    "dom": "Domingo",
}
_FAIXAS = ("08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00")


@dataclass
class NotaDeAula:
    caminho: Path
    titulo: str
    data: str | None = None
    numero: int | None = None
    pontos_de_atencao: list[str] = field(default_factory=list)


def _estudos_dir() -> Path:
    return get_settings().agent_data_dir / "estudos"


def caminho_moc(sigla: str) -> Path:
    return _estudos_dir() / "output" / sigla / f"{sigla} - MOC.md"


def caminho_moc_central() -> Path:
    return _estudos_dir() / "output" / NOME_CENTRAL


def _campo_frontmatter(conteudo: str, campo: str) -> str | None:
    match = _RE_FRONTMATTER.search(conteudo)
    if not match:
        return None
    for linha in match.group(1).splitlines():
        chave, _, valor = linha.partition(":")
        if chave.strip() == campo:
            return valor.strip() or None
    return None


def _pontos_de_atencao(conteudo: str) -> list[str]:
    inicio = conteudo.find(SECAO_PONTOS)
    if inicio == -1:
        return []
    corpo = conteudo[inicio + len(SECAO_PONTOS) :]
    fim = corpo.find("\n## ")
    corpo = corpo[:fim] if fim != -1 else corpo

    itens = []
    for linha in corpo.splitlines():
        texto = linha.strip()
        if not texto.startswith("- "):
            continue
        texto = texto[2:].strip()
        if texto and _SEM_PONTOS not in texto:
            itens.append(texto)
    return itens


def notas_da_disciplina(sigla: str) -> list[NotaDeAula]:
    """Notas de aula já concluídas, ignorando stubs e o próprio MOC."""
    pasta = _estudos_dir() / "output" / sigla
    if not pasta.exists():
        return []

    notas = []
    for caminho in listar(pasta, "*.md"):
        if caminho.name.endswith(" - MOC.md") or "(a processar)" in caminho.name:
            continue
        conteudo = ler_texto(caminho)
        titulo_match = _RE_TITULO.search(conteudo)
        numero = _campo_frontmatter(conteudo, "aula")
        notas.append(
            NotaDeAula(
                caminho=caminho,
                titulo=titulo_match.group(1).strip() if titulo_match else caminho.stem,
                data=_campo_frontmatter(conteudo, "data"),
                numero=int(numero) if numero and numero.isdigit() else None,
                pontos_de_atencao=_pontos_de_atencao(conteudo),
            )
        )
    notas.sort(key=lambda nota: (nota.data or "9999", nota.titulo))
    return notas


# --------------------------------------------------------------------- blocos


def bloco_identificacao(item: Disciplina) -> str:
    linhas = ["## Identificação", "", "| | |", "|---|---|"]
    linhas.append(f"| **Disciplina** | {item.titulo} |")
    linhas.append(f"| **Código** | {item.codigo or '❓ a confirmar'} |")
    linhas.append(f"| **Semestre** | {item.semestre} |")

    aulas = [h for h in item.horarios if h.tipo == "aula"]
    if aulas:
        linhas.append(f"| **Horário** | {', '.join(_horario_texto(h) for h in aulas)} |")
    outros = [h for h in item.horarios if h.tipo != "aula"]
    for horario in outros:
        linhas.append(f"| **{horario.tipo.capitalize()}** | {_horario_texto(horario)} |")

    docentes = ", ".join(d.nome for d in item.docentes) or "❓ a confirmar"
    linhas.append(f"| **Docente** | {docentes} |")
    if item.coletor:
        linhas.append(f"| **Site** | {item.coletor.url} |")

    if item.a_confirmar:
        linhas += ["", "> [!warning] A confirmar", ">"]
        linhas += [f"> - {pendencia}" for pendencia in item.a_confirmar]
    return "\n".join(linhas)


def _horario_texto(horario) -> str:
    texto = f"{_DIAS.get(horario.dia, horario.dia)}, {horario.inicio}–{horario.fim}"
    if horario.periodicidade != "semanal":
        texto += f" ({horario.periodicidade})"
    if horario.local:
        texto += f" · {horario.local}"
    if horario.ate:
        texto += f" · até {horario.ate}"
    return texto


def _rodape_de_fontes(*grupos) -> list[str]:
    """Uma linha de fonte por bloco, não por item.

    Repetir a mesma origem em toda linha polui a leitura sem acrescentar nada: o que
    importa é saber de onde o bloco veio, e quando há mais de uma origem, quais são.
    """
    fontes = {item.fonte.split(" | ")[0].strip() for grupo in grupos for item in grupo}
    fontes.discard("")
    if not fontes:
        return []
    return ["", f"<sub>Fonte: {'; '.join(sorted(fontes))}</sub>"]


def _lista(itens, prefixo: str = "- ") -> list[str]:
    return [f"{prefixo}{item.texto}" for item in itens]


def bloco_ementa(ementa) -> str:
    if ementa is None or not ementa.partes:
        return "## Ementa\n\n_(ainda não extraída — processe a aula que apresenta a ementa)_"
    linhas = ["## Ementa", ""]
    for parte in ementa.partes:
        numero = f"{parte.numero}. " if parte.numero is not None else "- "
        linhas.append(f"{numero}**{parte.titulo}**")
    linhas += _rodape_de_fontes(ementa.partes)
    return "\n".join(linhas)


def bloco_avaliacao(ementa) -> str:
    if ementa is None or (not ementa.avaliacao and not ementa.pesos):
        return "## Avaliação\n\n_(ainda não extraída)_"
    linhas = ["## Avaliação", ""]
    linhas += _lista(ementa.avaliacao)
    if ementa.pesos:
        linhas += ["", "**Pesos**", ""]
        linhas += _lista(ementa.pesos)
    linhas += _rodape_de_fontes(ementa.avaliacao, ementa.pesos)
    return "\n".join(linhas)


def bloco_bibliografia(ementa) -> str:
    if ementa is None or not (ementa.bibliografia_basica or ementa.bibliografia_complementar):
        return "## Bibliografia\n\n_(ainda não extraída)_"
    linhas = ["## Bibliografia", ""]
    if ementa.bibliografia_basica:
        linhas += ["**Básica**", ""] + _lista(ementa.bibliografia_basica) + [""]
    if ementa.bibliografia_complementar:
        linhas += ["**Complementar**", ""] + _lista(ementa.bibliografia_complementar)
    linhas += _rodape_de_fontes(ementa.bibliografia_basica, ementa.bibliografia_complementar)
    return "\n".join(linhas)


def bloco_aulas(sigla: str) -> str:
    programa = modulo_programa.carregar(sigla)
    notas = notas_da_disciplina(sigla)
    por_numero = {nota.numero: nota for nota in notas if nota.numero is not None}

    linhas = ["## Aulas", "", "| Nº | Título | Data | Nota |", "|---|---|---|---|"]

    if programa is not None and programa.aulas:
        for aula in programa.aulas:
            nota = por_numero.pop(aula.numero, None)
            data = (nota.data if nota else None) or aula.data or "—"
            link = f"[[{nota.caminho.stem}]]" if nota else "—"
            linhas.append(f"| {aula.numero:02d} | {aula.titulo} | {data} | {link} |")

    # notas sem correspondência no programa (ou disciplina sem programa) continuam visíveis
    for nota in sorted(por_numero.values(), key=lambda n: n.data or "9999"):
        numero = f"{nota.numero:02d}" if nota.numero is not None else "—"
        linhas.append(
            f"| {numero} | {nota.titulo} | {nota.data or '—'} | [[{nota.caminho.stem}]] |"
        )
    for nota in notas:
        if nota.numero is None:
            linhas.append(f"| — | {nota.titulo} | {nota.data or '—'} | [[{nota.caminho.stem}]] |")

    if len(linhas) == 4:
        return "## Aulas\n\n_(nenhuma nota concluída ainda)_"
    return "\n".join(linhas)


def bloco_pontos_de_atencao(sigla: str) -> str:
    linhas = ["## Pontos de atenção do professor", ""]
    achou = False
    for nota in notas_da_disciplina(sigla):
        for ponto in nota.pontos_de_atencao:
            linhas.append(f"- {ponto}  — [[{nota.caminho.stem}]]")
            achou = True
    if not achou:
        linhas.append("_(nada sinalizado até agora)_")
    return "\n".join(linhas)


def bloco_materiais(sigla: str) -> str:
    registros = registros_por_disciplina(sigla)
    if not registros:
        return "## Materiais\n\n_(nenhum PDF registrado)_"

    linhas = [
        "## Materiais",
        "",
        "| Arquivo | Tipo | Vigência | Aula | Origem |",
        "|---|---|---|---|---|",
    ]
    for registro in sorted(registros, key=lambda r: (r.tipo, r.nome_arquivo)):
        aula = f"{registro.numero_aula:02d}" if registro.numero_aula else "—"
        origem = registro.vinculo_fonte or "local"
        marca = "" if registro.tem_texto_nativo else " ⚠️ sem texto"
        linhas.append(
            f"| `{registro.nome_arquivo}`{marca} | {registro.tipo} | {registro.vigencia} "
            f"| {aula} | {origem} |"
        )
    linhas += [
        "",
        "<sub>Material com vigência `antiga` nunca entra na composição de uma nota nova — "
        "só é consultado para preencher lacunas. Gabarito nunca vira fonte: a nota aponta "
        "onde conferir a solução.</sub>",
    ]
    return "\n".join(linhas)


def bloco_conceitos(sigla: str) -> str:
    pasta = _estudos_dir() / "output" / sigla / "conceitos"
    if not pasta.exists():
        return "## Conceitos\n\n_(nenhum ainda)_"
    conceitos = sorted(caminho.stem for caminho in listar(pasta, "*.md"))
    if not conceitos:
        return "## Conceitos\n\n_(nenhum ainda)_"
    return "\n".join(["## Conceitos", ""] + [f"- [[{nome}]]" for nome in conceitos])


# ------------------------------------------------------------------ geradores

_CABECALHO = """---
tipo: moc
disciplina: {sigla}
semestre: {semestre}
---

#estudos{tag_codigo}

"""


def gerar_moc_disciplina(sigla: str) -> Path:
    item = buscar_disciplina(sigla)
    ementa = modulo_ementa.carregar(sigla)
    caminho = caminho_moc(sigla)

    try:
        atual = ler_texto(caminho)
    except FileNotFoundError:
        atual = _CABECALHO.format(
            sigla=sigla,
            semestre=item.semestre,
            tag_codigo=f" #{item.codigo}" if item.codigo else "",
        )

    blocos = {
        "identificacao": bloco_identificacao(item),
        "ementa": bloco_ementa(ementa),
        "avaliacao": bloco_avaliacao(ementa),
        "bibliografia": bloco_bibliografia(ementa),
        "aulas": bloco_aulas(sigla),
        "pontos_de_atencao": bloco_pontos_de_atencao(sigla),
        "materiais": bloco_materiais(sigla),
        "conceitos": bloco_conceitos(sigla),
    }
    escrever_texto(caminho, aplicar_blocos(atual, blocos))
    registrar_evento(passo="moc", resultado=f"{sigla}: {len(blocos)} blocos")
    return caminho


def bloco_grade(semestre: str) -> str:
    disciplinas = disciplinas_ativas(semestre, tipo="disciplina")
    reunioes = disciplinas_ativas(semestre, tipo="reuniao")

    cabecalho = (
        "| | " + " | ".join(_DIAS[d] for d in ("seg", "ter", "qua", "qui", "sex", "sab")) + " |"
    )
    separador = "|---" * 8 + "|"
    linhas = [f"## {semestre}", "", cabecalho, separador]

    for inicio, fim in zip(_FAIXAS, _FAIXAS[1:], strict=False):
        celulas = []
        for dia in ("seg", "ter", "qua", "qui", "sex", "sab"):
            ocupantes = [
                f"[[{item.nome} - MOC\\|{item.nome}]]"
                + ("" if horario.tipo == "aula" else f" ({horario.tipo})")
                for item in disciplinas + reunioes
                for horario in item.horarios
                if horario.dia == dia and horario.inicio <= inicio < horario.fim
            ]
            celulas.append(" · ".join(ocupantes))
        if any(celulas):
            linhas.append(f"| {inicio}–{fim} | " + " | ".join(celulas) + " |")

    linhas += [
        "",
        "### Disciplinas ativas",
        "",
        "| Sigla | Disciplina | Código | Monitoria |",
        "|---|---|---|---|",
    ]
    for item in disciplinas:
        linhas.append(
            f"| [[{item.nome} - MOC\\|{item.nome}]] | {item.titulo} | {item.codigo or '—'} "
            f"| {'sim' if item.monitoria else '—'} |"
        )
    if reunioes:
        linhas += ["", "### Reuniões", ""]
        linhas += [f"- [[{item.nome} - MOC\\|{item.nome}]] — {item.titulo}" for item in reunioes]
    return "\n".join(linhas)


def gerar_moc_central(semestre: str | None = None) -> Path:
    registro = carregar_registro()
    alvo = semestre or registro.semestre_atual
    caminho = caminho_moc_central()

    try:
        atual = ler_texto(caminho)
    except FileNotFoundError:
        atual = "#estudos\n\n"

    escrever_texto(
        caminho,
        aplicar_blocos(
            atual,
            {"grade_semestre": bloco_grade(alvo)},
        ),
    )
    registrar_evento(passo="moc", resultado=f"central {alvo}")
    return caminho


def atualizar_apos_job(sigla: str) -> Path | None:
    """Chamado ao concluir um job. Falhar aqui não pode derrubar o job."""
    try:
        return gerar_moc_disciplina(sigla)
    except (RegistroAusente, RegistroInvalido, DisciplinaDesconhecida) as erro:
        registrar_evento(passo="moc", resultado="pulado", aviso=str(erro))
        return None
