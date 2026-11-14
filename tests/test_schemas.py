import pytest
from pydantic import ValidationError

from projetos.estudos.schemas import (
    Bloco,
    Contexto,
    Extracao,
    Flashcards,
    NotaComposta,
    Triagem,
)


def test_triagem_valida_com_campos_corretos():
    triagem = Triagem(
        categoria="lousa",
        receita_preproc="quadro",
        qualidade="boa",
        contem_conteudo_academico=True,
        confianca=0.9,
    )
    assert triagem.categoria == "lousa"


def test_triagem_rejeita_categoria_fora_do_literal():
    with pytest.raises(ValidationError):
        Triagem(
            categoria="foto_de_gato",
            receita_preproc="quadro",
            qualidade="boa",
            contem_conteudo_academico=True,
            confianca=0.9,
        )


def test_extracao_com_blocos_e_flags():
    extracao = Extracao(
        blocos=[
            Bloco(
                tipo="formula",
                conteudo="E=mc^2",
                latex="E=mc^2",
                bbox=(0.1, 0.1, 0.5, 0.3),
                confianca=0.95,
                flags=["importante"],
            )
        ],
        idioma="pt",
        observacoes="",
    )
    assert extracao.blocos[0].flags == ["importante"]


def test_contexto_aceita_aula_numero_nulo():
    contexto = Contexto(
        aula_numero=None,
        titulo_sugerido="Caminhos mínimos: Dijkstra",
        topicos=["grafos"],
        conexoes=[],
        tags=["algoritmos"],
        subnotas_sugeridas=[],
        confianca=0.8,
    )
    assert contexto.aula_numero is None


def test_nota_composta_com_conceitos_e_duvidas():
    nota = NotaComposta(
        markdown="# Aula 1\n...",
        conceitos_novos=["Dijkstra"],
        duvidas=["Por que funciona?"],
    )
    assert nota.conceitos_novos == ["Dijkstra"]


def test_flashcards_aceita_card_basico_e_card_cloze():
    flashcards = Flashcards(
        cards=[
            {
                "tipo": "basico",
                "frente": "Complexidade de Dijkstra?",
                "verso": "O((V+E) log V)",
            },
            {"tipo": "cloze", "texto": "θ ← θ − {{c1::η ∇J(θ)}}"},
        ],
        duvidas=[],
    )

    assert flashcards.cards[0].tipo == "basico"
    assert flashcards.cards[0].frente == "Complexidade de Dijkstra?"
    assert flashcards.cards[1].tipo == "cloze"
    assert flashcards.cards[1].texto == "θ ← θ − {{c1::η ∇J(θ)}}"
    assert flashcards.cards[1].extra == ""


def test_flashcards_rejeita_card_basico_com_campo_de_cloze():
    with pytest.raises(ValidationError):
        Flashcards(cards=[{"tipo": "basico", "texto": "não tem frente/verso"}], duvidas=[])


def test_flashcards_rejeita_tipo_fora_do_literal():
    with pytest.raises(ValidationError):
        Flashcards(cards=[{"tipo": "misto", "frente": "P", "verso": "R"}], duvidas=[])


def test_lista_de_saida_de_agente_tem_default():
    """Mesma armadilha do campo anulável, com coleção: o modelo omite a lista quando ela
    sairia vazia. `SaidaBibliotecario.respostas` sem default derrubou preencher-lacunas
    justamente quando nenhuma lacuna foi resolvida — que é um resultado válido."""
    import typing

    from projetos.estudos import schemas

    saidas_de_agente = (
        schemas.SaidaBibliotecario,
        schemas.Extracao,
        schemas.Flashcards,
        schemas.Ementa,
    )
    listas_obrigatorias = []
    for modelo in saidas_de_agente:
        for nome, campo in modelo.model_fields.items():
            origem = typing.get_origin(campo.annotation)
            if origem in (list, dict) and campo.is_required():
                listas_obrigatorias.append(f"{modelo.__name__}.{nome}")

    assert listas_obrigatorias == []


def test_bibliotecario_aceita_zero_lacunas_resolvidas():
    from projetos.estudos.schemas import SaidaBibliotecario

    saida = SaidaBibliotecario(secao_do_livro="- CLRS, caps. 2-3")

    assert saida.respostas == []
    assert saida.lacunas_nao_resolvidas == []


def test_bloco_aceita_latex_omitido():
    bloco = Bloco(
        tipo="diagrama",
        conteudo="árvore binária",
        bbox=(0, 0, 1, 1),
        confianca=0.9,
        flags=[],
    )

    assert bloco.latex is None


def test_compromisso_aceita_data_e_recorrencia_ausentes():
    from projetos.estudos.schemas import CompromissoExtraido

    c = CompromissoExtraido(tipo="aviso", titulo="Aviso", origem_trecho="trecho", confianca=0.9)

    assert c.data is None
    assert c.hora is None
    assert c.recorrencia is None


def test_compromisso_recusa_tipo_fora_da_lista():
    from pydantic import ValidationError

    from projetos.estudos.schemas import CompromissoExtraido

    with pytest.raises(ValidationError):
        CompromissoExtraido(tipo="festa", titulo="x", origem_trecho="t", confianca=0.5)


def test_compromisso_exige_origem_trecho_e_confianca():
    from pydantic import ValidationError

    from projetos.estudos.schemas import CompromissoExtraido

    with pytest.raises(ValidationError):
        CompromissoExtraido(tipo="prova", titulo="P1")
