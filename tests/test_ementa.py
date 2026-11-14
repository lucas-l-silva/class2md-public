from unittest.mock import patch

import pytest

from core.config import get_settings
from projetos.estudos.agentes import AgenteEmenta
from projetos.estudos.ementa import (
    atualizar,
    carregar,
    mesclar,
    parece_credencial,
    resumo_textual,
    salvar,
    sem_credenciais,
)
from projetos.estudos.schemas import (
    Ementa,
    EntradaCronograma,
    EntradaEmenta,
    FonteEmenta,
    ItemEmenta,
    ParteEmenta,
)


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "estudos" / "index").mkdir(parents=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


FONTE_013 = "2026-08-10_mat1_013.jpg"
FONTE_014 = "2026-08-10_mat1_014.jpg"


def _fontes():
    return [
        FonteEmenta(nome=FONTE_013, tipo="manuscrito", texto="5 grandes partes... AP1 31/08"),
        FonteEmenta(nome=FONTE_014, tipo="manuscrito", texto="livros: Cormen e Papadimitriou"),
    ]


def _ementa_da_013():
    return Ementa(
        disciplina="MAT1",
        partes=[
            ParteEmenta(numero=1, titulo="Ordenação", fonte=FONTE_013),
            ParteEmenta(numero=2, titulo="Divisão e Conquista", fonte=FONTE_013),
        ],
        pesos=[ItemEmenta(texto="1ª prova: 15%", fonte=FONTE_013)],
        cronograma=[EntradaCronograma(periodo="31/08", conteudo="AP1", fonte=FONTE_013)],
        confianca=0.9,
    )


def test_round_trip_no_index_da_disciplina():
    salvar(_ementa_da_013())
    lida = carregar("MAT1")

    assert lida is not None
    assert [p.titulo for p in lida.partes] == ["Ordenação", "Divisão e Conquista"]
    assert carregar("FIS1") is None


def test_mesclar_acumula_sem_duplicar_variacao_de_acento_e_caixa():
    antiga = _ementa_da_013()
    nova = Ementa(
        disciplina="MAT1",
        partes=[
            ParteEmenta(numero=1, titulo="ORDENACAO", fonte=FONTE_014),  # mesma parte
            ParteEmenta(numero=3, titulo="Programação Dinâmica", fonte=FONTE_014),
        ],
        bibliografia_basica=[ItemEmenta(texto="Cormen", fonte=FONTE_014)],
        confianca=0.8,
    )

    resultado = mesclar(antiga, nova)

    assert [p.titulo for p in resultado.partes] == [
        "Ordenação",
        "Divisão e Conquista",
        "Programação Dinâmica",
    ]
    assert [b.texto for b in resultado.bibliografia_basica] == ["Cormen"]
    # nada do que já existia se perde
    assert [c.conteudo for c in resultado.cronograma] == ["AP1"]
    assert resultado.confianca == 0.8


def test_mesclar_preserva_o_primeiro_titulo_confirmado():
    antiga = _ementa_da_013().model_copy(update={"titulo_oficial": "Construção e Análise"})
    nova = Ementa(disciplina="MAT1", titulo_oficial="MAT1 (abreviado)", codigo="ALG0001")

    resultado = mesclar(antiga, nova)

    assert resultado.titulo_oficial == "Construção e Análise"
    assert resultado.codigo == "ALG0001"  # vazio antes, então o novo entra


def test_mesclar_sem_ementa_anterior_devolve_a_nova():
    nova = _ementa_da_013()
    assert mesclar(None, nova) is nova


def test_resumo_textual_lista_o_que_ja_existe():
    resumo = resumo_textual(_ementa_da_013())

    assert "1. Ordenação" in resumo
    assert "31/08: AP1" in resumo
    assert resumo_textual(None) == "(nada extraído ainda)"


def test_atualizar_sem_fontes_nao_chama_llm():
    salvar(_ementa_da_013())

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        resultado = atualizar("job-1", "MAT1", [])

    mock_chamar.assert_not_called()
    assert resultado is not None
    assert len(resultado.partes) == 2


def test_atualizar_acumula_sobre_o_que_ja_estava_salvo(sem_cache_llm):
    salvar(_ementa_da_013())
    nova = Ementa(
        disciplina="MAT1",
        bibliografia_basica=[ItemEmenta(texto="Cormen", fonte=FONTE_014)],
    )

    with patch.object(AgenteEmenta, "run", return_value=nova):
        resultado = atualizar("job-1", "MAT1", _fontes())

    assert [b.texto for b in resultado.bibliografia_basica] == ["Cormen"]
    assert len(resultado.partes) == 2
    assert len(carregar("MAT1").partes) == 2


def test_guardrail_descarta_item_com_fonte_inventada(sem_cache_llm):
    entrada = EntradaEmenta(disciplina="MAT1", ementa_atual="", fontes=_fontes())
    bruto = Ementa(
        disciplina="INVENTADA",
        partes=[
            ParteEmenta(numero=1, titulo="Ordenação", fonte=FONTE_013),
            ParteEmenta(numero=9, titulo="Teoria dos Jogos", fonte="livro_que_nao_foi_dado.pdf"),
        ],
        bibliografia_basica=[ItemEmenta(texto="Knuth", fonte="")],
    )

    with patch("core.agents.base.Agente.run", return_value=bruto):
        resultado = AgenteEmenta().run("job-1", entrada)

    assert [p.titulo for p in resultado.partes] == ["Ordenação"]
    assert resultado.bibliografia_basica == []
    # a disciplina é dada, nunca aceita do modelo
    assert resultado.disciplina == "MAT1"


def test_montar_mensagens_envelopa_cada_fonte():
    entrada = EntradaEmenta(disciplina="MAT1", ementa_atual="(nada)", fontes=_fontes())

    mensagens = AgenteEmenta().montar_mensagens(entrada)
    conteudo = mensagens[0]["content"]

    assert f'<dados fonte="{FONTE_013} | manuscrito">' in conteudo
    assert f'<dados fonte="{FONTE_014} | manuscrito">' in conteudo
    assert "Disciplina: MAT1" in conteudo


def test_credencial_vista_numa_foto_nao_vira_registro():
    """A senha do WiFi da sala estava numa placa e foi parar nas observações."""
    bruta = Ementa(
        disciplina="MAT1",
        observacoes=[
            ItemEmenta(
                texto="Informação de WiFi (SSID: REDE-EXEMPLO, Senha: exemplo123)",
                fonte=FONTE_013,
            ),
            ItemEmenta(texto="Data do manuscrito: 10.08.26", fonte=FONTE_013),
        ],
        bibliografia_basica=[ItemEmenta(texto="Cormen", fonte=FONTE_014)],
    )

    limpa, removidos = sem_credenciais(bruta)

    assert removidos == 1
    assert [o.texto for o in limpa.observacoes] == ["Data do manuscrito: 10.08.26"]
    assert [b.texto for b in limpa.bibliografia_basica] == ["Cormen"]


def test_parece_credencial_reconhece_as_formas_comuns():
    assert parece_credencial("Senha: abc123")
    assert parece_credencial("rede wifi REDE-EXEMPLO")
    assert parece_credencial("API_KEY = sk-...")
    assert not parece_credencial("Cormen, Introduction to Algorithms")
    assert not parece_credencial("1ª prova: 15%")


def test_atualizar_nao_salva_credencial(sem_cache_llm):
    nova = Ementa(
        disciplina="MAT1",
        observacoes=[ItemEmenta(texto="Senha do wifi: 12345", fonte=FONTE_013)],
    )

    with patch.object(AgenteEmenta, "run", return_value=nova):
        resultado = atualizar("job-1", "MAT1", _fontes())

    assert resultado.observacoes == []
    assert carregar("MAT1").observacoes == []
