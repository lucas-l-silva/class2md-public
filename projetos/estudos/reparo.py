"""Reparo determinístico das notas já escritas em staging.

Dois defeitos entraram no disco antes de serem corrigidos na origem: parágrafos quebrados
em várias linhas (o modelo imitando o template) e seções "Do livro" duplicadas (uma por
execução de `preencher-lacunas`). Reprocessar tudo com modelo custaria dinheiro para
consertar o que é puro texto.

**Nada é reescrito no lugar sem cópia.** O original vai inteiro para
`estudos/trash/<carimbo>/output/`, então dá para comparar antes e depois — ou desfazer.
"""

import pathlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from core.config import get_settings
from core.estado import conectar, registrar_numero_aula
from core.fileops import escrever_texto, mover
from projetos.estudos.manifesto import (
    ler_entrada_manifesto,
    registrar_nota_manifesto,
)
from projetos.estudos.markdown_fmt import juntar_paragrafos
from projetos.estudos.remendo_nota import colapsar_secoes

_RE_SECAO_LIVRO = re.compile(r"(?m)^## Do livro")


@dataclass
class ResultadoReparo:
    alteradas: list[tuple[Path, str]] = field(default_factory=list)
    backup: Path | None = None


def _pasta_output() -> Path:
    return get_settings().agent_data_dir / "estudos" / "output"


def reparar_markdown(texto: str) -> tuple[str, list[str]]:
    """Devolve (texto reparado, o que mudou). Texto já limpo sai byte-idêntico."""
    mudancas = []

    colapsado = colapsar_secoes(texto, "Do livro")
    if colapsado != texto:
        quantas = len(_RE_SECAO_LIVRO.findall(texto))
        mudancas.append(f"{quantas} seções 'Do livro' → 1")

    juntado = juntar_paragrafos(colapsado)
    if juntado != colapsado:
        antes = len(colapsado.splitlines())
        mudancas.append(f"{antes - len(juntado.splitlines())} quebras de parágrafo desfeitas")

    return juntado, mudancas


def reparar_notas(aplicar_mudancas: bool = False) -> ResultadoReparo:
    """Varre `output/`. Com `aplicar_mudancas=False` só relata — é o modo de ensaio."""
    resultado = ResultadoReparo()
    pendentes: list[tuple[Path, str]] = []

    for nota in sorted(_pasta_output().rglob("*.md")):
        texto = nota.read_text(encoding="utf-8")
        reparado, mudancas = reparar_markdown(texto)
        if reparado != texto:
            resultado.alteradas.append((nota, "; ".join(mudancas)))
            pendentes.append((nota, reparado))

    if not aplicar_mudancas or not pendentes:
        return resultado

    carimbo = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
    backup = get_settings().agent_data_dir / "estudos" / "trash" / carimbo / "output"
    for nota, reparado in pendentes:
        destino = backup / nota.relative_to(_pasta_output())
        escrever_texto(destino, nota.read_text(encoding="utf-8"))
        escrever_texto(nota, reparado)

    resultado.backup = backup
    return resultado


def _frontmatter(texto: str) -> dict[str, str]:
    campos = {}
    for linha in texto.splitlines()[1:]:
        if linha.strip() == "---":
            break
        chave, sep, valor = linha.partition(":")
        if sep:
            campos[chave.strip()] = valor.strip()
    return campos


def renumerar_por_data(disciplina: str, aplicar_mudancas: bool = False) -> list[str]:
    """Renumera as notas de aula de uma disciplina pela ordem das datas.

    Conserta o que "maior número + 1" deixou torto: recompor uma aula antiga a jogava
    para o fim da sequência.

    O número da aula vive em **quatro** lugares que precisam concordar: o `aula:` do
    frontmatter, o nome do arquivo, `jobs.numero_aula` e o `caminho_nota` do manifesto.
    Esquecer o manifesto foi o suficiente para `preencher-lacunas` estourar com
    `FileNotFoundError` apontando para o nome antigo.
    """
    pasta = _pasta_output() / disciplina
    notas = []
    for caminho in sorted(pasta.glob("*.md")):
        campos = _frontmatter(caminho.read_text(encoding="utf-8"))
        if campos.get("data") and campos.get("aula", "").isdigit():
            notas.append((campos["data"], caminho, int(campos["aula"])))

    relato = []
    for posicao, (data, caminho, atual) in enumerate(sorted(notas), start=1):
        if posicao == atual:
            continue
        relato.append(f"{caminho.name[:50]}: aula {atual:02d} → {posicao:02d}")
        if not aplicar_mudancas:
            continue

        texto = caminho.read_text(encoding="utf-8")
        texto = texto.replace(f"aula: {atual}", f"aula: {posicao}", 1)
        texto = texto.replace(f"# Aula {atual} — ", f"# Aula {posicao} — ", 1)
        novo_nome = caminho.name.replace(f"Aula {atual:02d}", f"Aula {posicao:02d}", 1)
        escrever_texto(caminho, texto)
        if novo_nome != caminho.name:
            mover(caminho, caminho.with_name(novo_nome))

        conn = conectar()
        linha = conn.execute(
            "SELECT id, criado_em FROM jobs WHERE disciplina=? AND data=? AND tipo='aula'",
            (disciplina, data),
        ).fetchone()
        if linha:
            registrar_numero_aula(linha["id"], posicao)
            entrada = ler_entrada_manifesto(linha["id"])
            if entrada:
                registrar_nota_manifesto(
                    linha["id"],
                    caminho.with_name(novo_nome),
                    entrada.get("status", "concluido"),
                    entrada.get("fotos", []),
                    entrada.get("criado_em", linha["criado_em"]),
                    conceitos_novos=entrada.get("conceitos_novos"),
                    duvidas=entrada.get("duvidas"),
                    precisa_revisao=entrada.get("precisa_revisao", False),
                    secao_do_livro=entrada.get("secao_do_livro"),
                )

    return relato


def notas_duplicadas(disciplina: str) -> list[tuple[str, list[pathlib.Path]]]:
    """Notas que dizem ser a MESMA aula (mesma data e mesmo número).

    O compositor escolhe o título, e o título entra no nome do arquivo — então uma
    recomposição que muda o título deixa a versão anterior órfã em vez de sobrescrevê-la.
    Já aconteceu três vezes: 15 notas onde deviam existir 10, "Aula 03" e "Aula 04" para
    a mesma aula, e duas "Aula 02" com títulos diferentes. Detectar é barato; escolher
    qual fica é decisão humana, então esta função só relata.
    """
    por_aula: dict[str, list[pathlib.Path]] = {}
    for caminho in sorted((_pasta_output() / disciplina).glob("*.md")):
        campos = _frontmatter(caminho.read_text(encoding="utf-8"))
        if campos.get("data") and campos.get("aula", "").isdigit():
            por_aula.setdefault(f"{campos['data']} aula {campos['aula']}", []).append(caminho)
    return [(chave, arquivos) for chave, arquivos in por_aula.items() if len(arquivos) > 1]
