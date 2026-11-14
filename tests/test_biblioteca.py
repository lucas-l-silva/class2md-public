from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.config import get_settings
from core.estado import criar_job, pdf_por_sha
from projetos.estudos.biblioteca import (
    fontes_antigas_por_topico,
    fontes_da_aula,
    indice_do_livro,
    materiais_da_aula,
    resolver_capitulos,
    trecho_de_pdf,
    trechos_dos_capitulos,
)
from projetos.estudos.pdf_ingestao import registrar_pdf
from projetos.estudos.schemas import CapituloIndice, IndiceLivro, SugestaoCapitulos
from tests.pdf_fabrica import criar_pdf


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "logs").mkdir()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def pdfs_dir(tmp_path):
    caminho = tmp_path / "estudos" / "pdfs"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


@pytest.fixture
def registro_livro(tmp_path):
    caminho = tmp_path / "estudos" / "pdfs" / "Calculo" / "livro.pdf"
    criar_pdf(
        caminho,
        paginas=100,
        texto_por_pagina="conteúdo " * 10,
        toc=[("Capítulo 1", 0, 1), ("Capítulo 2", 0, 40), ("Capítulo 3", 0, 70)],
    )
    return registrar_pdf(caminho)


def _resposta_mock():
    usage = SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0)
    return SimpleNamespace(usage=usage)


def _indice_valido() -> IndiceLivro:
    return IndiceLivro(
        titulo_livro="Cálculo",
        autor="Stewart",
        capitulos=[
            CapituloIndice(numero=1, titulo="Capítulo 1", pagina_inicio=1, pagina_fim=39),
            CapituloIndice(numero=2, titulo="Capítulo 2", pagina_inicio=40, pagina_fim=69),
            CapituloIndice(numero=3, titulo="Capítulo 3", pagina_inicio=70, pagina_fim=100),
        ],
        fonte_indice="toc_nativo",
        confianca=0.9,
    )


def test_indice_do_livro_usa_toc_nativo_e_cacheia(registro_livro):
    job_id = criar_job("indexacao")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_indice_valido(), _resposta_mock())
        primeiro = indice_do_livro(job_id, registro_livro)
        segundo = indice_do_livro(job_id, registro_livro)

    assert len(primeiro.capitulos) == 3
    assert segundo == primeiro
    assert mock_chamar.call_count == 1  # segunda chamada veio do cache de indice.json


def test_indice_do_livro_marca_pdf_como_indexado(registro_livro):
    job_id = criar_job("indexacao")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_indice_valido(), _resposta_mock())
        indice_do_livro(job_id, registro_livro)

    assert pdf_por_sha(registro_livro.sha256)["indexado_em"] is not None


def test_indice_com_pagina_fora_do_range_cai_em_fallback(registro_livro):
    job_id = criar_job("indexacao")
    indice_invalido = IndiceLivro(
        titulo_livro="Cálculo",
        autor="Stewart",
        capitulos=[CapituloIndice(numero=1, titulo="Cap 1", pagina_inicio=9999, pagina_fim=None)],
        fonte_indice="toc_nativo",
        confianca=0.9,
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (indice_invalido, _resposta_mock())
        resultado = indice_do_livro(job_id, registro_livro)

    assert resultado.fonte_indice == "fallback_paginas"
    assert len(resultado.capitulos) > 0


def test_indice_com_paginas_nao_crescentes_cai_em_fallback(registro_livro):
    job_id = criar_job("indexacao")
    indice_invalido = IndiceLivro(
        titulo_livro="Cálculo",
        autor="Stewart",
        capitulos=[
            CapituloIndice(numero=1, titulo="Cap 1", pagina_inicio=50, pagina_fim=None),
            CapituloIndice(numero=2, titulo="Cap 2", pagina_inicio=10, pagina_fim=None),
        ],
        fonte_indice="toc_nativo",
        confianca=0.9,
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (indice_invalido, _resposta_mock())
        resultado = indice_do_livro(job_id, registro_livro)

    assert resultado.fonte_indice == "fallback_paginas"


def test_indice_vazio_cai_em_fallback(registro_livro):
    job_id = criar_job("indexacao")
    indice_vazio = IndiceLivro(
        titulo_livro="",
        autor="",
        capitulos=[],
        fonte_indice="paginas_iniciais",
        confianca=0.3,
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (indice_vazio, _resposta_mock())
        resultado = indice_do_livro(job_id, registro_livro)

    assert resultado.fonte_indice == "fallback_paginas"
    assert len(resultado.capitulos) > 0


def test_indice_do_livro_force_reextrai_mesmo_com_cache(registro_livro):
    job_id = criar_job("indexacao")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_indice_valido(), _resposta_mock())
        indice_do_livro(job_id, registro_livro)
        indice_do_livro(job_id, registro_livro, force=True)

    assert mock_chamar.call_count == 2


def test_indice_sem_toc_usa_texto_das_paginas_iniciais(tmp_path):
    caminho = tmp_path / "estudos" / "pdfs" / "Calculo" / "sem_toc.pdf"
    criar_pdf(
        caminho,
        paginas=50,
        texto_por_pagina=[f"sumário linha {i}" for i in range(1, 51)],
    )
    registro = registrar_pdf(caminho)
    job_id = criar_job("indexacao")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_indice_valido(), _resposta_mock())
        indice_do_livro(job_id, registro)

    mensagens = mock_chamar.call_args_list[0].args[2]
    assert "sumário linha 1" in mensagens[0]["content"]
    assert "sumário linha 50" not in mensagens[0]["content"]  # só as ~12 primeiras páginas


def test_resolver_capitulos_com_override_nao_chama_llm():
    job_id = criar_job("indexacao")
    indice = _indice_valido()

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        capitulos, origem = resolver_capitulos(
            job_id, indice, "Calculo", "Aula 5", ["limites"], ["dúvida"], override=[2]
        )

    assert capitulos == [2]
    assert origem == "manual"
    mock_chamar.assert_not_called()


def test_resolver_capitulos_override_invalido_leva_a_erro_sem_chamar_llm():
    job_id = criar_job("indexacao")
    indice = _indice_valido()

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        with pytest.raises(ValueError, match="inválido"):
            resolver_capitulos(job_id, indice, "Calculo", "Aula 5", [], [], override=[99])

    mock_chamar.assert_not_called()


def test_resolver_capitulos_sem_override_usa_sugestao_do_agente():
    job_id = criar_job("indexacao")
    indice = _indice_valido()
    sugestao = SugestaoCapitulos(
        capitulos=[1], justificativa="Introdução cobre isso.", confianca=0.9
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (sugestao, _resposta_mock())
        capitulos, origem = resolver_capitulos(
            job_id, indice, "Calculo", "Aula 5", ["limites"], ["dúvida"], override=None
        )

    assert capitulos == [1]
    assert origem == "sugerido"


def test_resolver_capitulos_descarta_numeros_que_nao_existem_no_indice():
    job_id = criar_job("indexacao")
    indice = _indice_valido()
    sugestao = SugestaoCapitulos(capitulos=[1, 99, 2], justificativa="x", confianca=0.9)

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (sugestao, _resposta_mock())
        capitulos, _ = resolver_capitulos(
            job_id, indice, "Calculo", "Aula 5", [], [], override=None
        )

    assert capitulos == [1, 2]  # 99 descartado, nunca existiu no índice


def test_trechos_dos_capitulos_extrai_e_cacheia(registro_livro):
    job_id = criar_job("indexacao")
    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_indice_valido(), _resposta_mock())
        indice = indice_do_livro(job_id, registro_livro)

    trechos = trechos_dos_capitulos(registro_livro, indice, [1])

    assert len(trechos) == 1
    assert trechos[0].capitulo == "1 — Capítulo 1"
    assert trechos[0].pagina_inicio == 1
    assert trechos[0].pagina_fim == 39
    assert trechos[0].tipo == "livro"


def test_trechos_dos_capitulos_e_cacheado_sem_reler_o_pdf(registro_livro, monkeypatch):
    job_id = criar_job("indexacao")
    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_indice_valido(), _resposta_mock())
        indice = indice_do_livro(job_id, registro_livro)

    trechos_dos_capitulos(registro_livro, indice, [1])

    chamadas = {"n": 0}
    import projetos.estudos.biblioteca as mod

    original = mod.texto_paginas

    def _contando(*args, **kwargs):
        chamadas["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(mod, "texto_paginas", _contando)
    trechos_dos_capitulos(registro_livro, indice, [1])

    assert chamadas["n"] == 0


def test_trechos_dos_capitulos_capitulo_nao_existente_no_indice_da_erro(registro_livro):
    job_id = criar_job("indexacao")
    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_indice_valido(), _resposta_mock())
        indice = indice_do_livro(job_id, registro_livro)

    with pytest.raises(ValueError):
        trechos_dos_capitulos(registro_livro, indice, [999])


def test_materiais_da_aula_vazio_quando_nenhum_pdf_casa_com_a_data(tmp_path):
    assert materiais_da_aula("Calculo", "2026-07-15") == ""


def test_materiais_da_aula_inclui_pdf_direto_com_data_casando(tmp_path):
    caminho = tmp_path / "estudos" / "pdfs" / "Calculo" / "lista.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="1. Questão de exemplo sobre limites.")
    registro = registrar_pdf(caminho, data_aula="2026-07-15")
    assert registro.modo == "direto"

    resultado = materiais_da_aula("Calculo", "2026-07-15")

    assert "Questão de exemplo sobre limites" in resultado
    assert '<dados fonte="lista.pdf' in resultado


def test_materiais_da_aula_ignora_pdf_com_data_diferente(tmp_path):
    caminho = tmp_path / "estudos" / "pdfs" / "Calculo" / "lista.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="1. Questão de exemplo.")
    registrar_pdf(caminho, data_aula="2026-07-22")

    assert materiais_da_aula("Calculo", "2026-07-15") == ""


def test_materiais_da_aula_ignora_livro_mesmo_com_data_marcada(tmp_path):
    caminho = tmp_path / "estudos" / "pdfs" / "Calculo" / "livro.pdf"
    criar_pdf(caminho, paginas=60, texto_por_pagina="conteúdo " * 10)
    registro = registrar_pdf(caminho, data_aula="2026-07-15")
    assert registro.tipo == "livro"
    assert registro.modo == "indexado"

    assert materiais_da_aula("Calculo", "2026-07-15") == ""


def test_materiais_da_aula_trunca_no_limite_e_avisa(tmp_path, monkeypatch):
    monkeypatch.setattr("projetos.estudos.biblioteca.LIMITE_CHARS_MATERIAIS", 100)
    caminho = tmp_path / "estudos" / "pdfs" / "Calculo" / "lista.pdf"
    criar_pdf(caminho, paginas=2, texto_por_pagina="x" * 60)
    registrar_pdf(caminho, data_aula="2026-07-15")

    resultado = materiais_da_aula("Calculo", "2026-07-15")

    assert len(resultado) < 60 * 2 + 200  # não incluiu o texto inteiro sem limite


def _pdf_registrado(pdfs_dir, nome, texto, vigencia="atual", numero_aula=None, tipo=None):
    from projetos.estudos.pdf_ingestao import registrar_pdf

    caminho = pdfs_dir / "MAT1" / nome
    criar_pdf(caminho, paginas=2, texto_por_pagina=texto)
    return registrar_pdf(
        caminho,
        disciplina="MAT1",
        vigencia=vigencia,
        numero_aula=numero_aula,
        tipo=tipo,
    )


def test_fontes_da_aula_pega_so_material_atual_da_aula(pdfs_dir):
    _pdf_registrado(pdfs_dir, "lista01.pdf", "exercícios da aula 1", numero_aula=1)
    _pdf_registrado(pdfs_dir, "lista02.pdf", "exercícios da aula 2", numero_aula=2)
    _pdf_registrado(pdfs_dir, "antiga.pdf", "material velho", vigencia="antiga", numero_aula=1)

    fontes = fontes_da_aula("MAT1", 1)

    assert [f.trecho.arquivo for f in fontes] == ["lista01.pdf"]
    assert fontes_da_aula("MAT1", None) == []


def test_gabarito_nunca_vira_trecho_de_fonte(pdfs_dir):
    registro = _pdf_registrado(pdfs_dir, "Solutions Manual.pdf", "resposta pronta", numero_aula=1)

    assert registro.tipo == "gabarito"
    assert trecho_de_pdf(registro) is None
    assert fontes_da_aula("MAT1", 1) == []


def test_material_antigo_casa_por_topico_e_nao_pelo_numero_do_arquivo(pdfs_dir):
    """ "Aula 5" de outro semestre não é a aula 5 deste — a numeração é de outra oferta."""
    _pdf_registrado(pdfs_dir, "Alg - Aula 5 Mergesort.pdf", "intercalação", vigencia="antiga")
    _pdf_registrado(pdfs_dir, "Alg - Aula 8 Quicksort.pdf", "partição", vigencia="antiga")

    fontes = fontes_antigas_por_topico("MAT1", "Aula 2 — Mergesort e intercalação", [])

    assert [f.trecho.arquivo for f in fontes] == ["Alg - Aula 5 Mergesort.pdf"]


def test_material_antigo_sem_relacao_de_topico_fica_de_fora(pdfs_dir):
    _pdf_registrado(
        pdfs_dir,
        "Alg - Aula 21 Gulosos.pdf",
        "seleção de atividades",
        vigencia="antiga",
    )

    assert fontes_antigas_por_topico("MAT1", "Ordenação por inserção", []) == []
