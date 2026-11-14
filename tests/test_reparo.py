from pathlib import Path

import pytest

from core.config import get_settings
from projetos.estudos.reparo import reparar_markdown, reparar_notas


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "estudos" / "output" / "MAT1").mkdir(parents=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _nota(tmp_path, nome, corpo):
    caminho = tmp_path / "estudos" / "output" / "MAT1" / nome
    caminho.write_text(corpo, encoding="utf-8")
    return caminho


ESTRAGADA = """# Aula 01

## Resumo da aula

A aula introduz os algoritmos clássicos de ordenação
e chega à análise de complexidade.

## Do livro
## Do livro — CLRS, caps. 2–3

Primeiro resumo.

## Do livro — CLRS, caps. 2–3

Segundo resumo.

## Ver também
"""

LIMPA = """# Aula 01

## Resumo da aula

Um parágrafo inteiro numa linha só.

## Do livro

- CLRS, caps. 2–3

## Ver também
"""


def test_relata_os_dois_defeitos():
    _, mudancas = reparar_markdown(ESTRAGADA)

    assert any("Do livro" in m for m in mudancas)
    assert any("quebras de parágrafo" in m for m in mudancas)


def test_conserta_sem_perder_conteudo():
    reparado, _ = reparar_markdown(ESTRAGADA)

    assert reparado.count("## Do livro") == 1
    assert "Primeiro resumo." in reparado and "Segundo resumo." in reparado
    assert "ordenação e chega à análise" in reparado


def test_nota_limpa_sai_byte_identica():
    """As 9 notas das outras disciplinas já estavam corretas."""
    reparado, mudancas = reparar_markdown(LIMPA)

    assert reparado == LIMPA
    assert mudancas == []


def test_e_idempotente():
    uma, _ = reparar_markdown(ESTRAGADA)
    duas, mudancas = reparar_markdown(uma)

    assert duas == uma
    assert mudancas == []


def test_ensaio_nao_escreve_nada(tmp_path):
    caminho = _nota(tmp_path, "aula.md", ESTRAGADA)

    resultado = reparar_notas(aplicar_mudancas=False)

    assert len(resultado.alteradas) == 1
    assert caminho.read_text(encoding="utf-8") == ESTRAGADA
    assert resultado.backup is None


def test_aplicar_guarda_o_original_na_lixeira(tmp_path):
    caminho = _nota(tmp_path, "aula.md", ESTRAGADA)

    resultado = reparar_notas(aplicar_mudancas=True)

    assert caminho.read_text(encoding="utf-8").count("## Do livro") == 1
    original = resultado.backup / "MAT1" / "aula.md"
    assert original.read_text(encoding="utf-8") == ESTRAGADA


def test_nao_toca_no_que_ja_esta_limpo(tmp_path):
    limpa = _nota(tmp_path, "outra.md", LIMPA)
    _nota(tmp_path, "aula.md", ESTRAGADA)

    resultado = reparar_notas(aplicar_mudancas=True)

    assert [c.name for c, _ in resultado.alteradas] == ["aula.md"]
    assert limpa.read_text(encoding="utf-8") == LIMPA
    assert not (resultado.backup / "MAT1" / "outra.md").exists()


def _nota_de_aula(tmp_path, data, numero, titulo):
    caminho = tmp_path / "estudos" / "output" / "MAT1" / f"{data} Aula {numero:02d} — {titulo}.md"
    caminho.write_text(
        f"---\ndata: {data}\ndisciplina: MAT1\naula: {numero}\ntags: []\n---\n\n"
        f"# Aula {numero} — {titulo}\n",
        encoding="utf-8",
    )
    return caminho


def test_renumera_pela_ordem_das_datas(tmp_path):
    """Recompor a aula de 10/08 com a aula 02 no disco a jogou para "Aula 03"."""
    from projetos.estudos.reparo import renumerar_por_data

    _nota_de_aula(tmp_path, "2026-08-10", 3, "Ordenação")
    _nota_de_aula(tmp_path, "2026-08-12", 2, "Shell Sort")

    relato = renumerar_por_data("MAT1", aplicar_mudancas=True)

    pasta = tmp_path / "estudos" / "output" / "MAT1"
    nomes = sorted(p.name for p in pasta.glob("*.md"))
    assert nomes == [
        "2026-08-10 Aula 01 — Ordenação.md",
        "2026-08-12 Aula 02 — Shell Sort.md",
    ]
    assert "aula: 1" in (pasta / nomes[0]).read_text(encoding="utf-8")
    assert "# Aula 1 — " in (pasta / nomes[0]).read_text(encoding="utf-8")
    assert len(relato) == 1


def test_sequencia_certa_nao_e_mexida(tmp_path):
    from projetos.estudos.reparo import renumerar_por_data

    _nota_de_aula(tmp_path, "2026-08-10", 1, "Ordenação")
    _nota_de_aula(tmp_path, "2026-08-12", 2, "Shell Sort")

    assert renumerar_por_data("MAT1", aplicar_mudancas=True) == []


def test_detecta_duas_notas_para_a_mesma_aula(tmp_path):
    """O compositor escolhe o título e o título vira nome de arquivo: recompor com outro
    título deixa a versão anterior órfã em vez de sobrescrevê-la."""
    from projetos.estudos.reparo import notas_duplicadas

    _nota_de_aula(tmp_path, "2026-08-12", 2, "Shell Sort")
    _nota_de_aula(tmp_path, "2026-08-12", 2, "Otimizando Bubble Sort")
    _nota_de_aula(tmp_path, "2026-08-10", 1, "Ordenação")

    duplicadas = notas_duplicadas("MAT1")

    assert len(duplicadas) == 1
    chave, arquivos = duplicadas[0]
    assert chave == "2026-08-12 aula 2"
    assert len(arquivos) == 2


def test_sem_duplicatas_nao_relata_nada(tmp_path):
    from projetos.estudos.reparo import notas_duplicadas

    _nota_de_aula(tmp_path, "2026-08-10", 1, "Ordenação")
    _nota_de_aula(tmp_path, "2026-08-12", 2, "Shell Sort")

    assert notas_duplicadas("MAT1") == []


def test_renumerar_atualiza_tambem_o_manifesto(tmp_path):
    """O número vive em quatro lugares. Esquecer o manifesto fez preencher-lacunas
    estourar com FileNotFoundError apontando para o nome antigo."""
    from core.estado import criar_job
    from projetos.estudos.manifesto import (
        ler_entrada_manifesto,
        registrar_nota_manifesto,
    )
    from projetos.estudos.reparo import renumerar_por_data

    caminho = _nota_de_aula(tmp_path, "2026-08-10", 3, "Ordenação")
    job_id = criar_job("aula", disciplina="MAT1", data="2026-08-10")
    registrar_nota_manifesto(job_id, caminho, "concluido", [], "2026-08-10T00:00:00Z")
    _nota_de_aula(tmp_path, "2026-08-12", 2, "Shell Sort")

    renumerar_por_data("MAT1", aplicar_mudancas=True)

    apontado = Path(ler_entrada_manifesto(job_id)["caminho_nota"])
    assert apontado.name == "2026-08-10 Aula 01 — Ordenação.md"
    assert apontado.exists()
