from pathlib import Path

from core.config import get_settings
from core.fileops import escrever_texto

_SECOES_VAZIAS = (
    "## Resumo da aula",
    "## Conteúdo principal",
    "## Do livro",
    "## Pontos sinalizados como difícil",
    "## Conceitos novos — precisam de página própria",
    "## Exercícios relacionados",
    "## Ver também",
)


def nome_stub(data: str) -> str:
    return f"{data} Aula — (a processar).md"


def caminho_stub(data: str, disciplina: str) -> Path:
    output_dir = get_settings().agent_data_dir / "estudos" / "output"
    return output_dir / disciplina / nome_stub(data)


def _conteudo_stub(data: str, disciplina: str) -> str:
    frontmatter = f"---\ndata: {data}\ndisciplina: {disciplina}\naula: null\ntags: []\n---\n"
    titulo = "# Aula — (a processar)\n"
    corpo = "\n\n".join(_SECOES_VAZIAS)
    return f"{frontmatter}\n{titulo}\n{corpo}\n"


def criar_stub(data: str, disciplina: str) -> Path:
    caminho = caminho_stub(data, disciplina)
    escrever_texto(caminho, _conteudo_stub(data, disciplina))
    return caminho


def nome_definitivo(data: str, aula_numero: int | None, titulo: str) -> str:
    if aula_numero is not None:
        return f"{data} Aula {aula_numero:02d} — {titulo}.md"
    return f"{data} Aula — {titulo}.md"


def caminho_nota_final(data: str, disciplina: str, aula_numero: int | None, titulo: str) -> Path:
    output_dir = get_settings().agent_data_dir / "estudos" / "output"
    return output_dir / disciplina / nome_definitivo(data, aula_numero, titulo)
