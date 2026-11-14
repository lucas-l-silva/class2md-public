"""Garante que a documentação só cita comandos e arquivos que existem."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import typer.main

RAIZ = Path(__file__).resolve().parent.parent
DOCUMENTOS = [
    RAIZ / "README.md",
    RAIZ / "MANUAL_DE_USO.md",
    RAIZ / "AGENTS.md",
    RAIZ / "SECURITY.md",
]
DOCUMENTOS += sorted((RAIZ / "docs").glob("*.md"))
RE_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
RE_COMANDO = re.compile(r"scripts/(estudos|promover|bootstrap)\.py((?:[ \t]+[^\s`|]+)?)")


def _carregar_comandos(nome: str) -> set[str]:
    caminho = RAIZ / "scripts" / f"{nome}.py"
    sys.path.insert(0, str(RAIZ))
    try:
        spec = importlib.util.spec_from_file_location(f"_doc_{nome}", caminho)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
    finally:
        sys.path.remove(str(RAIZ))
    comando = typer.main.get_command(modulo.app)
    return set(getattr(comando, "commands", {}))


def _textos():
    for doc in DOCUMENTOS:
        if doc.exists():
            yield doc, doc.read_text(encoding="utf-8")


def test_documentos_esperados_existem():
    for nome in ("README.md", "MANUAL_DE_USO.md", "AGENTS.md"):
        assert (RAIZ / nome).exists(), nome


@pytest.mark.parametrize(
    "doc,texto", list(_textos()), ids=lambda v: v.name if isinstance(v, Path) else ""
)
def test_links_relativos_apontam_para_arquivos_que_existem(doc, texto):
    for alvo in RE_LINK.findall(texto):
        if alvo.startswith(("http", "mailto:")):
            continue
        assert (doc.parent / alvo).exists(), f"{doc.name}: link quebrado {alvo}"


def test_comandos_citados_existem():
    por_script = {nome: _carregar_comandos(nome) for nome in ("estudos", "promover", "bootstrap")}
    problemas = []
    for doc, texto in _textos():
        for script, resto in RE_COMANDO.findall(texto):
            comandos = por_script[script]
            palavra = resto.strip()
            if not palavra or palavra.startswith("-") or palavra.startswith(("[", "<", "...")):
                continue
            if script == "estudos" and palavra not in comandos:
                problemas.append(f"{doc.name}: estudos.py {palavra}")
            if script in ("promover", "bootstrap") and comandos:
                problemas.append(
                    f"{doc.name}: {script}.py {palavra} (comando único: sem subcomando)"
                )
    assert not problemas, "\n".join(problemas)


def test_nenhum_documento_cita_comandos_obsoletos():
    for doc, texto in _textos():
        assert "class2md ui" not in texto, f"{doc.name}: o comando é scripts/estudos.py ui"
        assert "COMO_USAR" not in texto, f"{doc.name}: COMO_USAR.md foi substituído pelo manual"
