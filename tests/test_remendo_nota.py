import pytest

from projetos.estudos.remendo_nota import (
    ChaveInvalida,
    SecaoAusente,
    aplicar,
    aplicar_blocos,
    blocos,
    colapsar_secoes,
    secoes,
    substituir_bloco,
    substituir_secao,
)
from projetos.estudos.schemas import RespostaLacuna, SaidaBibliotecario

NOTA = """---
data: 2026-07-15
disciplina: Calculo
aula: 5
tags: []
---

# Aula 5 — Limites

## Resumo da aula
Resumo qualquer.

## Conteúdo principal
Conteúdo qualquer.

## Do livro — (ainda não disponível)
(ainda não disponível — Iteração 4)

## Pontos sinalizados como difícil
- por que o limite lateral pode não existir?
- diferença entre continuidade e derivabilidade

## Conceitos novos — precisam de página própria
- [[Limite]]

## Ver também
- [[Aula 4]]
"""


def test_secoes_extrai_titulo_e_corpo_na_ordem():
    resultado = secoes(NOTA)

    titulos = [titulo for titulo, _ in resultado]
    assert titulos[0] == "## Resumo da aula"
    assert titulos[2].startswith("## Do livro")
    assert "por que o limite lateral" in dict(resultado)["## Pontos sinalizados como difícil"]


def test_substituir_secao_troca_so_a_secao_alvo():
    novo = substituir_secao(NOTA, "Do livro", "\nConteúdo novo do livro.\n\n")

    assert "Conteúdo novo do livro." in novo
    assert "(ainda não disponível — Iteração 4)" not in novo
    # o resto sai byte-idêntico
    assert "## Resumo da aula\nResumo qualquer.\n\n" in novo
    assert "## Pontos sinalizados como difícil\n- por que o limite lateral" in novo


def test_substituir_secao_casa_por_prefixo():
    # "Do livro" casa com "## Do livro — (ainda não disponível)" (título completo)
    novo = substituir_secao(NOTA, "Do livro", "\nx\n\n")
    assert "\nx\n\n## Pontos sinalizados" in novo


def test_substituir_secao_ausente_leva_a_erro():
    with pytest.raises(SecaoAusente):
        substituir_secao(NOTA, "Seção Inexistente", "x")


def test_aplicar_duas_vezes_com_mesma_entrada_da_o_mesmo_resultado():
    saida = SaidaBibliotecario(
        obras_consultadas=["Stewart, cap. 3"],
        respostas=[
            RespostaLacuna(
                lacuna="por que o limite lateral pode não existir?",
                resolvida=True,
                resposta="porque os limites laterais divergem",
                citacao="Stewart, cap. 2, p. 90",
            )
        ],
        lacunas_nao_resolvidas=["diferença entre continuidade e derivabilidade"],
    )

    primeiro = aplicar(NOTA, saida)
    segundo = aplicar(NOTA, saida)

    assert primeiro == segundo


def test_aplicar_remove_lacuna_resolvida_e_mantem_a_nao_resolvida():
    saida = SaidaBibliotecario(
        obras_consultadas=["Stewart, cap. 3"],
        respostas=[
            RespostaLacuna(
                lacuna="por que o limite lateral pode não existir?",
                resolvida=True,
                resposta="porque os limites laterais divergem",
                citacao="Stewart, cap. 2, p. 90",
            )
        ],
        lacunas_nao_resolvidas=["diferença entre continuidade e derivabilidade"],
    )

    resultado = aplicar(NOTA, saida)

    assert "por que o limite lateral pode não existir?" not in resultado
    assert "diferença entre continuidade e derivabilidade" in resultado
    assert "- Stewart, cap. 3" in resultado
    # seções não afetadas continuam intactas
    assert "## Conceitos novos — precisam de página própria\n- [[Limite]]" in resultado
    assert "## Ver também\n- [[Aula 4]]" in resultado


def test_aplicar_sem_nenhuma_lacuna_resolvida_preserva_todos_os_itens():
    saida = SaidaBibliotecario(
        nao_coberto=["o trecho fornecido não cobre o assunto"],
        respostas=[
            RespostaLacuna(
                lacuna="por que o limite lateral pode não existir?",
                resolvida=False,
                resposta="",
                citacao="",
            )
        ],
        lacunas_nao_resolvidas=["por que o limite lateral pode não existir?"],
    )

    resultado = aplicar(NOTA, saida)

    assert "por que o limite lateral pode não existir?" in resultado
    assert "diferença entre continuidade e derivabilidade" in resultado


def test_aplicar_todas_resolvidas_deixa_secao_de_pontos_com_marcador_vazio():
    saida = SaidaBibliotecario(
        obras_consultadas=["x"],
        respostas=[
            RespostaLacuna(
                lacuna="por que o limite lateral pode não existir?",
                resolvida=True,
                resposta="r1",
                citacao="Stewart, p. 1",
            ),
            RespostaLacuna(
                lacuna="diferença entre continuidade e derivabilidade",
                resolvida=True,
                resposta="r2",
                citacao="Stewart, p. 2",
            ),
        ],
        lacunas_nao_resolvidas=[],
    )

    resultado = aplicar(NOTA, saida)

    assert "(nenhum ponto pendente)" in resultado
    assert "por que o limite lateral pode não existir?" not in resultado
    assert "diferença entre continuidade e derivabilidade" not in resultado


def test_aplicar_nota_sem_secao_do_livro_da_erro():
    nota_sem_secao = NOTA.replace(
        "## Do livro — (ainda não disponível)\n(ainda não disponível — Iteração 4)\n\n",
        "",
    )
    saida = SaidaBibliotecario(obras_consultadas=["x"], respostas=[], lacunas_nao_resolvidas=[])

    with pytest.raises(SecaoAusente):
        aplicar(nota_sem_secao, saida)


MOC = """#estudos #MAT1

<!-- moc:inicio identificacao -->
| Docente | Maria Lima |
<!-- moc:fim identificacao -->

Nota minha, escrita à mão, que não pode ser tocada.

<!-- moc:inicio aulas -->
- Aula 01
<!-- moc:fim aulas -->

## Minhas anotações

Texto livre com `<!-- comentário qualquer -->` no meio.
"""


def test_blocos_lista_as_chaves_gerenciadas():
    assert set(blocos(MOC)) == {"identificacao", "aulas"}
    assert blocos(MOC)["aulas"] == "- Aula 01\n"


def test_substituir_bloco_preserva_tudo_fora_dos_marcadores():
    novo = substituir_bloco(MOC, "aulas", "- Aula 01\n- Aula 02")

    assert "- Aula 02" in novo
    assert "Nota minha, escrita à mão, que não pode ser tocada." in novo
    assert "Texto livre com `<!-- comentário qualquer -->` no meio." in novo
    # o outro bloco não é tocado
    assert blocos(novo)["identificacao"] == "| Docente | Maria Lima |\n"


def test_substituir_bloco_e_idempotente():
    uma_vez = substituir_bloco(MOC, "aulas", "- Aula 01")
    duas_vezes = substituir_bloco(uma_vez, "aulas", "- Aula 01")

    assert uma_vez == duas_vezes


def test_bloco_ausente_e_acrescentado_no_fim_sem_apagar_nada():
    novo = substituir_bloco(MOC, "cronograma", "| 31/08 | AP1 |")

    assert MOC in novo
    assert novo.rstrip().endswith("<!-- moc:fim cronograma -->")
    assert blocos(novo)["cronograma"] == "| 31/08 | AP1 |\n"


def test_bloco_vazio_nao_deixa_linha_em_branco_solta():
    novo = substituir_bloco(MOC, "aulas", "")

    assert "<!-- moc:inicio aulas -->\n<!-- moc:fim aulas -->" in novo
    assert blocos(novo)["aulas"] == ""


def test_chave_invalida_e_recusada_antes_de_escrever():
    with pytest.raises(ChaveInvalida):
        substituir_bloco(MOC, "Aulas Da Disciplina", "x")


def test_aplicar_blocos_atualiza_varios_de_uma_vez():
    novo = aplicar_blocos(MOC, {"aulas": "- Aula 02", "cronograma": "| 31/08 | AP1 |"})

    assert blocos(novo)["aulas"] == "- Aula 02\n"
    assert blocos(novo)["cronograma"] == "| 31/08 | AP1 |\n"
    assert blocos(novo)["identificacao"] == "| Docente | Maria Lima |\n"


def test_documento_sem_nenhum_bloco_ganha_o_primeiro():
    novo = substituir_bloco("Só o meu texto.", "ementa", "1. Ordenação")

    assert novo.startswith("Só o meu texto.\n\n<!-- moc:inicio ementa -->")


_NOTA_COM_SECOES = """# Aula 01

## Conteúdo principal

### Algoritmo de Inserção

Pseudocódigo da aula.

### Comparação de eficiência

Texto da aula.

## Do livro

## Pontos sinalizados como difícil

- Caso médio da Inserção
"""


def _saida(secao_alvo="Algoritmo de Inserção", obras=("CLRS, caps. 2–3",)):
    return SaidaBibliotecario(
        obras_consultadas=list(obras),
        respostas=[
            RespostaLacuna(
                lacuna="Caso médio da Inserção",
                resolvida=True,
                resposta="O CLRS soma `t_i` e chega a Θ(n²).",
                citacao="CLRS, cap. 2",
                secao_alvo=secao_alvo,
            )
        ],
        lacunas_nao_resolvidas=[],
    )


def test_resposta_entra_na_secao_que_ela_responde():
    """Uma seção monolítica no fim da nota é lida como apêndice, não como matéria."""
    resultado = aplicar(_NOTA_COM_SECOES, _saida())

    corpo_insercao = resultado.split("### Algoritmo de Inserção")[1].split("###")[0]
    assert "[!quote] Do livro — CLRS, cap. 2" in corpo_insercao
    assert "Θ(n²)" in corpo_insercao
    # a seção "Do livro" fica só com a procedência
    assert "Θ(n²)" not in resultado.split("## Do livro")[1]


def test_secao_alvo_inexistente_nao_perde_a_nota():
    """O alvo vem do modelo: ignorar o destino é melhor que estourar ou perder texto."""
    resultado = aplicar(_NOTA_COM_SECOES, _saida(secao_alvo="Seção Que Não Existe"))

    assert "## Conteúdo principal" in resultado
    assert "## Do livro" in resultado


def test_aplicar_e_idempotente():
    """Três execuções de preencher-lacunas tinham de dar o mesmo arquivo que uma."""
    uma = aplicar(_NOTA_COM_SECOES, _saida())
    tres = aplicar(aplicar(uma, _saida()), _saida())

    assert tres == uma
    assert tres.count("[!quote] Do livro") == 1
    assert tres.count("## Do livro") == 1


def test_procedencia_e_renderizada_em_python():
    """Quando era um campo de texto livre, o modelo despejava nele toda a matéria e
    deixava `respostas` vazia — reconstruindo o apanhado monolítico."""
    from projetos.estudos.remendo_nota import renderizar_procedencia

    saida = SaidaBibliotecario(
        obras_consultadas=["CLRS (MIT Press, 2022), caps. 2–3"],
        divergencias=["a aula usa `Para i <- N Até 2`; o livro usa `for i = 2 to n`"],
        nao_coberto=["a condição de parada do laço da Inserção"],
    )

    texto = renderizar_procedencia(saida)

    assert texto.startswith("**Consultado:**")
    assert "- CLRS (MIT Press, 2022), caps. 2–3" in texto
    assert "**Divergências entre a aula e o livro:**" in texto
    assert "**Não coberto pelos trechos consultados:**" in texto
    # e não existe campo de prosa livre onde despejar a matéria
    assert not hasattr(saida, "secao_do_livro")


def test_colapsar_funde_secoes_ja_duplicadas_no_disco():
    """Reparo dos dados: a MAT1 aula 1 acumulou quatro seções 'Do livro'."""
    estragada = (
        "## Do livro\n"
        "## Do livro — CLRS, caps. 2–3\n\nPrimeiro resumo.\n\n"
        "## Do livro — CLRS, caps. 2–3\n\nSegundo resumo.\n\n"
        "## Pontos sinalizados como difícil\n\n- item\n"
    )

    resultado = colapsar_secoes(estragada, "Do livro")

    assert resultado.count("## Do livro") == 1
    assert "Primeiro resumo." in resultado and "Segundo resumo." in resultado
    assert "## Pontos sinalizados como difícil" in resultado
