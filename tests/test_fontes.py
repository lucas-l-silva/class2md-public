import pytest

from core.config import get_settings
from projetos.estudos.disciplinas import Disciplina, Docente, Registro, salvar_registro
from projetos.estudos.fontes import (
    PRIORIDADE_ANTIGO_DOCENTE,
    PRIORIDADE_ANTIGO_OUTRO,
    PRIORIDADE_LIVRO,
    PRIORIDADE_MANUSCRITO,
    PRIORIDADE_MATERIAL_ATUAL,
    PRIORIDADE_MATERIAL_ATUAL_DOCENTE,
    FonteOrdenada,
    ordenar,
    prioridade_do_registro,
    resumo,
    truncar,
)
from projetos.estudos.pdf_ingestao import RegistroPdf
from projetos.estudos.schemas import TrechoFonte


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
    salvar_registro(
        Registro(
            semestre_atual="2030.2",
            disciplinas=[
                Disciplina(
                    nome="MAT1",
                    titulo="Construção e Análise",
                    semestre="2030.2",
                    docentes=[Docente(nome="Docente Exemplo")],
                )
            ],
        )
    )
    yield
    get_settings.cache_clear()


def _registro(nome="x.pdf", tipo="aula", vigencia="atual", autor=None) -> RegistroPdf:
    return RegistroPdf(
        sha256=nome,
        caminho=f"/tmp/{nome}",
        nome_arquivo=nome,
        disciplina="MAT1",
        tipo=tipo,
        modo="direto",
        paginas=1,
        chars_total=10,
        data_aula=None,
        tem_texto_nativo=True,
        vigencia=vigencia,
        autor=autor,
    )


def _fonte(nome: str, prioridade: int, texto: str = "conteúdo") -> FonteOrdenada:
    return FonteOrdenada(
        trecho=TrechoFonte(
            arquivo=nome,
            tipo="aula",
            capitulo=None,
            pagina_inicio=1,
            pagina_fim=1,
            texto=texto,
        ),
        prioridade=prioridade,
    )


def test_material_atual_do_docente_atual_vence_material_atual_anonimo():
    assert prioridade_do_registro("MAT1", _registro(autor="D. Exemplo")) == (
        PRIORIDADE_MATERIAL_ATUAL_DOCENTE
    )
    assert prioridade_do_registro("MAT1", _registro(autor=None)) == PRIORIDADE_MATERIAL_ATUAL


def test_livro_fica_abaixo_do_material_do_semestre():
    assert prioridade_do_registro("MAT1", _registro(tipo="livro")) == PRIORIDADE_LIVRO
    assert PRIORIDADE_LIVRO > PRIORIDADE_MATERIAL_ATUAL


def test_material_antigo_do_docente_atual_vence_antigo_de_outro_autor():
    """Mesmo autor carrega o mesmo recorte e o mesmo estilo de prova."""
    do_professor = _registro(vigencia="antiga", autor="Docente Exemplo")
    de_outro = _registro(vigencia="antiga", autor="Cormen")

    assert prioridade_do_registro("MAT1", do_professor) == PRIORIDADE_ANTIGO_DOCENTE
    assert prioridade_do_registro("MAT1", de_outro) == PRIORIDADE_ANTIGO_OUTRO
    assert PRIORIDADE_ANTIGO_DOCENTE < PRIORIDADE_ANTIGO_OUTRO


def test_antigo_nunca_passa_na_frente_de_atual():
    antigo_do_professor = prioridade_do_registro(
        "MAT1", _registro(vigencia="antiga", autor="Docente Exemplo")
    )
    atual_anonimo = prioridade_do_registro("MAT1", _registro())

    assert atual_anonimo < antigo_do_professor


def test_ordenar_e_estavel_dentro_da_mesma_prioridade():
    fontes = [
        _fonte("livro.pdf", PRIORIDADE_LIVRO),
        _fonte("segundo-slide.pdf", PRIORIDADE_MATERIAL_ATUAL),
        _fonte("manuscrito", PRIORIDADE_MANUSCRITO),
        _fonte("primeiro-slide.pdf", PRIORIDADE_MATERIAL_ATUAL),
    ]

    nomes = [f.trecho.arquivo for f in ordenar(fontes)]

    assert nomes == [
        "manuscrito",
        "segundo-slide.pdf",
        "primeiro-slide.pdf",
        "livro.pdf",
    ]


def test_truncar_corta_de_baixo_para_cima():
    fontes = [
        _fonte("livro.pdf", PRIORIDADE_LIVRO, "L" * 60),
        _fonte("manuscrito", PRIORIDADE_MANUSCRITO, "M" * 60),
    ]

    mantidas, avisos = truncar(fontes, limite_chars=100)

    assert [f.trecho.arquivo for f in mantidas] == ["manuscrito"]
    assert "livro.pdf" in avisos[0]
    assert "livro-texto" in avisos[0]


def test_fonte_nunca_entra_pela_metade():
    """Trecho cortado no meio de um raciocínio é pior que trecho ausente."""
    fontes = [_fonte("grande.pdf", PRIORIDADE_MANUSCRITO, "X" * 500)]

    mantidas, avisos = truncar(fontes, limite_chars=100)

    assert mantidas == []
    assert avisos


def test_tudo_cabendo_nao_gera_aviso():
    fontes = [_fonte("a.pdf", PRIORIDADE_MANUSCRITO, "a" * 10)]

    mantidas, avisos = truncar(fontes, limite_chars=1000)

    assert len(mantidas) == 1
    assert avisos == []


def test_resumo_mostra_a_ordem_que_o_modelo_vai_ver():
    fontes = [
        _fonte("livro.pdf", PRIORIDADE_LIVRO),
        _fonte("manuscrito", PRIORIDADE_MANUSCRITO),
    ]

    texto = resumo(fontes)

    assert texto.splitlines()[0].startswith("1. [manuscrito da aula]")
    assert texto.splitlines()[1].startswith("2. [livro-texto]")


def test_disciplina_fora_do_registro_nao_quebra():
    assert prioridade_do_registro("NAOEXISTE", _registro(autor="alguém")) == (
        PRIORIDADE_MATERIAL_ATUAL
    )


def test_fonte_garantida_entra_mesmo_estourando_o_teto():
    """Em preencher-lacunas o capítulo do livro foi escolhido para aquela consulta:
    cortá-lo por prioridade derrotaria o próprio comando."""
    fontes = [
        _fonte("livro.pdf", PRIORIDADE_LIVRO, "L" * 500),
        _fonte("manuscrito", PRIORIDADE_MANUSCRITO, "M" * 60),
    ]

    mantidas, avisos = truncar(fontes, limite_chars=100, garantidas={"livro.pdf"})

    assert "livro.pdf" in [f.trecho.arquivo for f in mantidas]
    assert any("não são descartadas" in a for a in avisos)


def test_garantida_nao_rouba_o_orcamento_das_fontes_melhores():
    """Garantir é "não pode ser descartada", não "passa na frente". Dois capítulos do
    CLRS chegaram a expulsar o manuscrito da aula — a fonte mais valiosa que existe."""
    fontes = [
        _fonte("livro.pdf", PRIORIDADE_LIVRO, "L" * 5000),
        _fonte("manuscrito", PRIORIDADE_MANUSCRITO, "M" * 90),
        _fonte("slide.pdf", PRIORIDADE_MATERIAL_ATUAL, "S" * 90),
    ]

    mantidas, avisos = truncar(fontes, limite_chars=100, garantidas={"livro.pdf"})
    nomes = [f.trecho.arquivo for f in mantidas]

    assert "manuscrito" in nomes and "livro.pdf" in nomes
    # o teto continua valendo para quem não foi pedido
    assert "slide.pdf" not in nomes
    assert any("slide.pdf" in a for a in avisos)


def test_resultado_sai_na_ordem_de_prioridade_mesmo_com_garantida():
    fontes = [
        _fonte("livro.pdf", PRIORIDADE_LIVRO, "L" * 10),
        _fonte("manuscrito", PRIORIDADE_MANUSCRITO, "M" * 10),
    ]

    mantidas, _ = truncar(fontes, limite_chars=1000, garantidas={"livro.pdf"})

    assert [f.trecho.arquivo for f in mantidas] == ["manuscrito", "livro.pdf"]
