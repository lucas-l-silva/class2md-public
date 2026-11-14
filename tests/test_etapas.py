import pytest

from core.agents.base import Agente
from projetos.estudos import agentes as modulo_agentes
from projetos.estudos.etapas import (
    ETAPAS,
    etapa,
    etapas_para,
    faltantes,
    fechar_dependencias,
)


def test_toda_dependencia_existe_e_nao_ha_ciclo():
    nomes = {e.nome for e in ETAPAS}
    for e in ETAPAS:
        assert set(e.depende_de) <= nomes
    for e in ETAPAS:
        fechar_dependencias([e.nome])  # um ciclo estouraria a recursão


def test_fechar_dependencias_de_flashcards_inclui_leitura_e_nota_em_ordem():
    assert fechar_dependencias(["flashcards"]) == ["leitura", "nota", "flashcards"]


def test_fechar_dependencias_nao_repete():
    assert fechar_dependencias(["nota", "flashcards", "conceitos"]) == [
        "leitura",
        "nota",
        "flashcards",
        "conceitos",
    ]


def test_faltantes_so_lista_o_que_o_usuario_nao_marcou():
    assert faltantes(["nota"]) == ["leitura"]
    assert faltantes(["leitura", "nota"]) == []


def test_etapas_de_foto_nao_incluem_etapas_de_pdf():
    nomes = {e.nome for e in etapas_para("foto")}

    assert {"leitura", "nota", "flashcards"} <= nomes
    assert not nomes & {"registro_pdf", "indice_livro", "lacunas"}


def test_etapa_desconhecida_lista_as_validas():
    with pytest.raises(ValueError, match="Válidas: leitura"):
        etapa("inexistente")


def test_todo_agente_citado_existe():
    existentes = {
        obj.nome
        for obj in vars(modulo_agentes).values()
        if isinstance(obj, type) and issubclass(obj, Agente) and obj is not Agente
    }
    for e in ETAPAS:
        assert set(e.agentes) <= existentes, e.nome


def test_todo_comando_cli_citado_existe():
    from scripts.estudos import app

    comandos = {c.name or c.callback.__name__.replace("_", "-") for c in app.registered_commands}
    for e in ETAPAS:
        if e.comando_cli:
            assert e.comando_cli in comandos, e.nome
