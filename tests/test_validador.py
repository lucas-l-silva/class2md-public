from pathlib import Path

import pytest

from projetos.estudos.validador import validar_nota

NOTA_BOA = """---
data: 2026-07-15
disciplina: Historia
aula: 1
tags: [historia]
---

# Aula 1 — Revolução Francesa

## Resumo da aula
Texto do resumo.

## Conteúdo principal
Conteúdo com $$E=mc^2$$ e um wikilink [[Conceito X]].

## Do livro — Autor, 2020, cap. 1
Texto do livro.

## Pontos sinalizados como difícil
- Ponto difícil.

## Pontos de atenção do professor
- (nada sinalizado nesta aula)

## Conceitos novos — precisam de página própria
- [[Conceito X]]

## Exercícios relacionados
- Nenhum.

## Ver também
- [[Outra nota]]
"""


@pytest.fixture
def pasta_crops(tmp_path) -> Path:
    pasta = tmp_path / "crops"
    pasta.mkdir()
    return pasta


def test_nota_boa_aprova(pasta_crops):
    validacao = validar_nota(NOTA_BOA, "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is True
    assert validacao.problemas == []


def test_frontmatter_com_campo_extra_reprova(pasta_crops):
    nota = NOTA_BOA.replace("tags: [historia]", "tags: [historia]\njob_id: abc123")

    validacao = validar_nota(nota, "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("job_id" in p.descricao for p in validacao.problemas)


def test_secao_faltando_reprova(pasta_crops):
    nota = NOTA_BOA.replace("## Ver também\n- [[Outra nota]]\n", "")

    validacao = validar_nota(nota, "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("Ver também" in p.descricao for p in validacao.problemas)


def test_dollarsigns_desbalanceados_reprova(pasta_crops):
    nota = NOTA_BOA.replace("$$E=mc^2$$", "$$E=mc^2")

    validacao = validar_nota(nota, "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("$$" in p.descricao for p in validacao.problemas)


def test_embed_para_arquivo_inexistente_reprova(pasta_crops):
    nota = NOTA_BOA + "\n![[crop_que_nao_existe.png]]\n"

    validacao = validar_nota(nota, "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("crop_que_nao_existe.png" in p.descricao for p in validacao.problemas)


def test_embed_para_arquivo_existente_nao_reprova(pasta_crops):
    (pasta_crops / "crop01.png").write_bytes(b"fake")
    nota = NOTA_BOA + "\n![[crop01.png]]\n"

    validacao = validar_nota(nota, "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is True


def test_bloco_de_codigo_aberto_reprova(pasta_crops):
    nota = NOTA_BOA + "\n```python\nprint(1)\n"

    validacao = validar_nota(nota, "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("código" in p.descricao for p in validacao.problemas)


def test_disciplina_divergente_reprova(pasta_crops):
    validacao = validar_nota(NOTA_BOA, "Fisica", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("disciplina" in p.onde for p in validacao.problemas)


def test_nota_sem_pontos_de_atencao_do_professor_reprova(pasta_crops):
    markdown = NOTA_BOA.replace(
        "## Pontos de atenção do professor\n- (nada sinalizado nesta aula)\n", ""
    )
    validacao = validar_nota(markdown, "Cálculo", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("Pontos de atenção do professor" in p.descricao for p in validacao.problemas)


def test_frontmatter_depois_do_titulo_reprova(pasta_crops):
    """O Obsidian só lê frontmatter na 1ª linha; o Dataview do calendário depende disso."""
    invertida = "# Aula 1 — Revolução Francesa\n\n" + NOTA_BOA

    validacao = validar_nota(invertida, "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("início do arquivo" in p.descricao for p in validacao.problemas)


def test_frontmatter_dentro_de_cerca_de_codigo_reprova(pasta_crops):
    dentro_da_cerca = "# Aula 1\n\n```yaml\n" + NOTA_BOA + "```\n"

    validacao = validar_nota(dentro_da_cerca, "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("início do arquivo" in p.descricao for p in validacao.problemas)


def test_aula_nao_numerica_reprova(pasta_crops):
    quebrada = NOTA_BOA.replace("aula: 1", "aula: desconhecido")

    validacao = validar_nota(quebrada, "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any(p.onde == "frontmatter.aula" for p in validacao.problemas)


def test_frontmatter_nao_fechado_reprova(pasta_crops):
    validacao = validar_nota("---\ndata: 2026-07-15\n", "Historia", "2026-07-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("não foi fechado" in p.descricao for p in validacao.problemas)


NOTA_IDIOMA = """---
data: 2026-08-15
disciplina: ALEMAO-A1.1
aula: 1
tags: [alemao]
---

# Aula 1 — Apresentar-se

## Resumo da aula
Cumprimentos e o verbo heißen.

## Vocabulário
| Palavra | Gênero / plural | Tradução | Exemplo |
|---|---|---|---|
| Tisch | der / die Tische | mesa | Der Tisch ist groß. |

## Gramática
Presente dos verbos regulares.

## Exemplos de uso
- **Wie heißt du?** — Como você se chama?

## Pronúncia e armadilhas
- (nada sinalizado nesta aula)

## Pontos de atenção do professor
- (nada sinalizado nesta aula)

## Exercícios relacionados
x

## Ver também
- [[Aula 2]]
"""


def test_nota_de_idioma_e_validada_pelo_perfil_dela(pasta_crops):
    validacao = validar_nota(NOTA_IDIOMA, "ALEMAO-A1.1", "2026-08-15", pasta_crops, perfil="idioma")

    assert validacao.aprovado is True


def test_nota_de_idioma_reprova_no_perfil_tecnico(pasta_crops):
    """As seções de uma são irrelevantes na outra — o perfil precisa ser respeitado."""
    validacao = validar_nota(NOTA_IDIOMA, "ALEMAO-A1.1", "2026-08-15", pasta_crops)

    assert validacao.aprovado is False
    assert any("Conteúdo principal" in p.descricao for p in validacao.problemas)


def test_nota_de_idioma_sem_vocabulario_reprova(pasta_crops):
    sem_vocab = NOTA_IDIOMA.replace("## Vocabulário", "## Palavras")

    validacao = validar_nota(sem_vocab, "ALEMAO-A1.1", "2026-08-15", pasta_crops, perfil="idioma")

    assert validacao.aprovado is False
    assert any("Vocabulário" in p.descricao for p in validacao.problemas)
