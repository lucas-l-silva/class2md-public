from unittest.mock import patch

import pytest

from core.config import get_settings
from projetos.estudos.agentes import AgenteEnriquecedor
from projetos.estudos.enriquecimento import (
    NotaNaoEncontrada,
    SemMaterialNovo,
    aplicar,
    enriquecer,
    hash_das_fontes,
)
from projetos.estudos.manifesto import _ler_manifesto, registrar_nota_manifesto
from projetos.estudos.pdf_ingestao import registrar_pdf
from projetos.estudos.programa import salvar as salvar_programa
from projetos.estudos.schemas import (
    AulaPrograma,
    EntradaEnriquecedor,
    Programa,
    SaidaEnriquecedor,
    TrechoFonte,
)
from tests.pdf_fabrica import criar_pdf

NOTA = """---
data: 2026-08-10
disciplina: MAT1
aula: 1
tags: []
---

# Aula 1 — Ordenação

## Resumo da aula
Resumo original.

## Conteúdo principal
Conteúdo original que não pode ser tocado.

## Do livro
(ainda não disponível)

## Pontos sinalizados como difícil
- por que a inserção é mais rápida na prática?

## Pontos de atenção do professor
- (nada sinalizado nesta aula)

## Conceitos novos — precisam de página própria
- [[Ordenação por Bolha]]

## Exercícios relacionados
(nenhum ainda)

## Ver também
- [[Aula 2]]
"""


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "estudos" / "index").mkdir(parents=True)
    (tmp_path / "estudos" / "output" / "MAT1").mkdir(parents=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def nota(tmp_path):
    caminho = tmp_path / "estudos" / "output" / "MAT1" / "2026-08-10 Aula 01 — Ordenação.md"
    caminho.write_text(NOTA, encoding="utf-8")
    registrar_nota_manifesto("job-1", caminho, "concluido", ["f.jpg"], "2026-08-10T00:00:00")
    return caminho


@pytest.fixture
def material(tmp_path):
    salvar_programa(
        Programa(
            disciplina="MAT1",
            aulas=[AulaPrograma(numero=1, titulo="Algoritmos básicos de ordenação")],
        )
    )
    caminho = tmp_path / "estudos" / "pdfs" / "MAT1" / "lista01.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="1. Ordene a lista. 2. Prove a corretude.")
    return registrar_pdf(caminho, disciplina="MAT1", numero_aula=1)


def _job():
    return {"id": "job-1", "disciplina": "MAT1", "data": "2026-08-10", "numero_aula": 1}


def _saida(**campos):
    padrao = dict(
        secao_exercicios="- Lista 01, questão 1 — treina ordenação por inserção. (lista01.pdf)",
        fontes_usadas=["lista01.pdf"],
    )
    padrao.update(campos)
    return SaidaEnriquecedor(**padrao)


def test_secao_vazia_nao_e_tocada():
    novo, alteradas = aplicar(NOTA, SaidaEnriquecedor(secao_exercicios="- item novo"))

    assert alteradas == ["Exercícios relacionados"]
    assert "- item novo" in novo
    assert "(ainda não disponível)" in novo  # "Do livro" veio vazia e ficou como estava


def test_resto_da_nota_sai_byte_a_byte_igual():
    novo, _ = aplicar(NOTA, SaidaEnriquecedor(secao_exercicios="- item novo"))

    assert "Conteúdo original que não pode ser tocado." in novo
    assert novo.split("## Conteúdo principal")[0] == NOTA.split("## Conteúdo principal")[0]


def test_enriquece_a_nota_e_registra_o_hash(nota, material):
    with patch.object(AgenteEnriquecedor, "run", return_value=_saida()):
        resultado = enriquecer("job-x", _job())

    assert resultado.secoes_alteradas == ["Exercícios relacionados"]
    assert "Lista 01, questão 1" in nota.read_text(encoding="utf-8")
    assert _ler_manifesto()["job-1"]["hash_enriquecimento"] == hash_das_fontes(["lista01.pdf"])


def test_rodar_de_novo_sem_material_novo_nao_gasta_api(nota, material):
    with patch.object(AgenteEnriquecedor, "run", return_value=_saida()):
        enriquecer("job-x", _job())

    with patch.object(AgenteEnriquecedor, "run") as mock:
        resultado = enriquecer("job-x", _job())

    mock.assert_not_called()
    assert resultado.ja_estava_em_dia


def test_material_novo_muda_o_hash_e_reescreve(nota, material, tmp_path):
    with patch.object(AgenteEnriquecedor, "run", return_value=_saida()):
        enriquecer("job-x", _job())

    outro = tmp_path / "estudos" / "pdfs" / "MAT1" / "aula01-sec02.pdf"
    criar_pdf(outro, paginas=1, texto_por_pagina="slide da seção 2")
    registrar_pdf(outro, disciplina="MAT1", numero_aula=1)

    with patch.object(AgenteEnriquecedor, "run", return_value=_saida()) as mock:
        enriquecer("job-x", _job())

    mock.assert_called_once()


def test_sem_material_da_aula_nao_chama_api(nota):
    with (
        patch.object(AgenteEnriquecedor, "run") as mock,
        pytest.raises(SemMaterialNovo),
    ):
        enriquecer("job-x", _job())

    mock.assert_not_called()


def test_nota_sem_vinculo_de_aula_e_recusada(nota, material):
    job = _job() | {"numero_aula": None}

    with pytest.raises(SemMaterialNovo, match="não está vinculado a uma aula"):
        enriquecer("job-x", job)


def test_job_sem_manifesto_falha_claro(material):
    with pytest.raises(NotaNaoEncontrada):
        enriquecer(
            "job-x",
            {
                "id": "inexistente",
                "disciplina": "MAT1",
                "data": "2026-08-10",
                "numero_aula": 1,
            },
        )


def test_guardrail_descarta_fonte_inventada():
    entrada = EntradaEnriquecedor(
        disciplina="MAT1",
        titulo_nota="Aula 1",
        markdown_nota=NOTA,
        trechos=[
            TrechoFonte(
                arquivo="lista01.pdf",
                tipo="exercicios",
                capitulo=None,
                pagina_inicio=1,
                pagina_fim=2,
                texto="x",
            )
        ],
    )
    bruto = SaidaEnriquecedor(
        secao_exercicios="- item",
        fontes_usadas=["lista01.pdf", "livro_que_nao_foi_dado.pdf"],
    )

    with patch("core.agents.base.Agente.run", return_value=bruto):
        resultado = AgenteEnriquecedor().run("job-x", entrada)

    assert resultado.fontes_usadas == ["lista01.pdf"]
