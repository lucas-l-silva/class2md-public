import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from core.config import get_settings
from core.estado import criar_job
from core.llm.tiers import Tier, modelo_do_tier
from projetos.estudos.agentes import (
    AgenteBibliotecario,
    AgenteCompositor,
    AgenteConceito,
    AgenteContexto,
    AgenteExtrator,
    AgenteFlashcards,
    AgenteIndexadorLivro,
    AgenteSeletorCapitulos,
    AgenteTriagem,
    AgenteValidadorSemantico,
    validar_completo,
    validar_conceito_completo,
)
from projetos.estudos.schemas import (
    Bloco,
    CapituloIndice,
    Contexto,
    EntradaBibliotecario,
    EntradaCompositor,
    EntradaConceito,
    EntradaContexto,
    EntradaFlashcards,
    EntradaImagem,
    EntradaIndexadorLivro,
    EntradaSeletorCapitulos,
    EntradaValidadorSemantico,
    Extracao,
    FlashcardBasico,
    Flashcards,
    IndiceLivro,
    NotaComposta,
    PaginaConceito,
    Problema,
    RespostaLacuna,
    SaidaBibliotecario,
    SugestaoCapitulos,
    TrechoFonte,
    Triagem,
    Validacao,
)


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
def foto(tmp_path) -> Path:
    caminho = tmp_path / "estudos" / "processed" / "Historia" / "foto.jpg"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), color="blue").save(caminho, format="JPEG")
    return caminho


def _resposta_mock(tokens_in=100, tokens_out=50, cache_read=0):
    usage = SimpleNamespace(
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cache_read_input_tokens=cache_read,
    )
    return SimpleNamespace(usage=usage)


def _triagem(confianca: float, contem_academico: bool = True) -> Triagem:
    return Triagem(
        categoria="lousa",
        receita_preproc="quadro",
        qualidade="boa",
        contem_conteudo_academico=contem_academico,
        confianca=confianca,
    )


def test_triagem_confianca_alta_nao_escalona(foto):
    job_id = criar_job("aula")
    entrada = EntradaImagem(caminho=str(foto))

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_triagem(0.9), _resposta_mock())
        resultado = AgenteTriagem().run(job_id, entrada)

    assert resultado.confianca == 0.9
    assert mock_chamar.call_count == 1
    assert mock_chamar.call_args_list[0].args[0] == modelo_do_tier(Tier.HAIKU)


def test_triagem_confianca_baixa_escalona_para_sonnet(foto):
    job_id = criar_job("aula")
    entrada = EntradaImagem(caminho=str(foto))

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.side_effect = [
            (_triagem(0.5), _resposta_mock()),
            (_triagem(0.95), _resposta_mock()),
        ]
        resultado = AgenteTriagem().run(job_id, entrada)

    assert resultado.confianca == 0.95
    assert mock_chamar.call_count == 2
    assert mock_chamar.call_args_list[0].args[0] == modelo_do_tier(Tier.HAIKU)
    assert mock_chamar.call_args_list[1].args[0] == modelo_do_tier(Tier.SONNET)


def test_extrator_retorna_extracao_com_blocos(foto):
    job_id = criar_job("aula")
    entrada = EntradaImagem(caminho=str(foto))

    extracao_mock = Extracao(
        blocos=[
            Bloco(
                tipo="texto",
                conteudo="Teorema de Pitágoras",
                latex=None,
                bbox=(0.1, 0.1, 0.5, 0.2),
                confianca=0.9,
                flags=[],
            )
        ],
        idioma="pt",
        observacoes="",
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (extracao_mock, _resposta_mock())
        resultado = AgenteExtrator().run(job_id, entrada)

    assert len(resultado.blocos) == 1
    assert resultado.blocos[0].conteudo == "Teorema de Pitágoras"


def _contexto(**overrides) -> Contexto:
    base = dict(
        aula_numero=3,
        titulo_sugerido="Caminhos mínimos: Dijkstra",
        topicos=["grafos", "algoritmos gulosos"],
        conexoes=[],
        tags=["algoritmos"],
        subnotas_sugeridas=[],
        confianca=0.9,
    )
    base.update(overrides)
    return Contexto(**base)


def test_contexto_disciplina_dada_e_preservada_e_enviada_na_mensagem():
    job_id = criar_job("aula")
    entrada = EntradaContexto(
        disciplina="Cálculo III",
        extracao_consolidada="conteúdo do dia",
        titulos_existentes=[],
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_contexto(), _resposta_mock())
        AgenteContexto().run(job_id, entrada)

    assert entrada.disciplina == "Cálculo III"  # nunca alterado
    mensagens = mock_chamar.call_args_list[0].args[2]
    assert "Cálculo III" in mensagens[0]["content"]


def test_contexto_filtra_conexoes_alucinadas():
    job_id = criar_job("aula")
    entrada = EntradaContexto(
        disciplina="Historia",
        extracao_consolidada="x",
        titulos_existentes=["Revolução Francesa"],
    )
    contexto_com_alucinacao = _contexto(conexoes=["Revolução Francesa", "Título Que Não Existe"])

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (contexto_com_alucinacao, _resposta_mock())
        resultado = AgenteContexto().run(job_id, entrada)

    assert resultado.conexoes == ["Revolução Francesa"]


def test_contexto_lista_vazia_de_titulos_gera_conexoes_vazias():
    job_id = criar_job("aula")
    entrada = EntradaContexto(
        disciplina="Historia", extracao_consolidada="x", titulos_existentes=[]
    )
    contexto_com_alucinacao = _contexto(conexoes=["Algo Inventado"])

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (contexto_com_alucinacao, _resposta_mock())
        resultado = AgenteContexto().run(job_id, entrada)

    assert resultado.conexoes == []


def test_contexto_retorna_subnotas_sugeridas():
    job_id = criar_job("aula")
    entrada = EntradaContexto(
        disciplina="Historia", extracao_consolidada="x", titulos_existentes=[]
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            _contexto(subnotas_sugeridas=["Revolução Industrial", "Iluminismo"]),
            _resposta_mock(),
        )
        resultado = AgenteContexto().run(job_id, entrada)

    assert resultado.subnotas_sugeridas == ["Revolução Industrial", "Iluminismo"]


def test_contexto_confianca_baixa_escalona_para_sonnet():
    job_id = criar_job("aula")
    entrada = EntradaContexto(
        disciplina="Historia", extracao_consolidada="x", titulos_existentes=[]
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.side_effect = [
            (_contexto(confianca=0.5), _resposta_mock()),
            (_contexto(confianca=0.95), _resposta_mock()),
        ]
        resultado = AgenteContexto().run(job_id, entrada)

    assert resultado.confianca == 0.95
    assert mock_chamar.call_count == 2
    assert mock_chamar.call_args_list[0].args[0] == modelo_do_tier(Tier.HAIKU)
    assert mock_chamar.call_args_list[1].args[0] == modelo_do_tier(Tier.SONNET)


def _entrada_compositor(**overrides) -> EntradaCompositor:
    base = dict(
        disciplina="Historia",
        data="2026-07-15",
        aula_numero=1,
        titulo_sugerido="Revolução Francesa",
        topicos=["causas", "consequências"],
        tags=["historia"],
        extracao_consolidada="conteúdo x",
        mapa_recortes={},
        do_livro="",
    )
    base.update(overrides)
    return EntradaCompositor(**base)


def _nota_composta(**overrides) -> NotaComposta:
    base = dict(markdown="# Aula\n...", conceitos_novos=[], duvidas=[])
    base.update(overrides)
    return NotaComposta(**base)


def test_compositor_inclui_template_no_bloco_system_estatico():
    job_id = criar_job("aula")
    entrada = _entrada_compositor()

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_nota_composta(), _resposta_mock())
        AgenteCompositor().run(job_id, entrada)

    system_blocks = mock_chamar.call_args_list[0].args[1]
    assert "<template>" in system_blocks[0]["text"]
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_compositor_lista_recortes_na_mensagem_quando_ha_mapa():
    job_id = criar_job("aula")
    entrada = _entrada_compositor(mapa_recortes={"grafo de estados": "crop01.png"})

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_nota_composta(), _resposta_mock())
        AgenteCompositor().run(job_id, entrada)

    mensagens = mock_chamar.call_args_list[0].args[2]
    assert "crop01.png" in mensagens[0]["content"]


def test_compositor_sem_recortes_indica_nenhum_disponivel():
    job_id = criar_job("aula")
    entrada = _entrada_compositor(mapa_recortes={})

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_nota_composta(), _resposta_mock())
        AgenteCompositor().run(job_id, entrada)

    mensagens = mock_chamar.call_args_list[0].args[2]
    assert "nenhum recorte disponível" in mensagens[0]["content"]


def test_compositor_cache_muda_quando_template_muda(monkeypatch):
    job_id = criar_job("aula")
    entrada = _entrada_compositor()

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_nota_composta(), _resposta_mock())
        AgenteCompositor().run(job_id, entrada)
        assert mock_chamar.call_count == 1

        import projetos.estudos.agentes as agentes_mod

        monkeypatch.setattr(agentes_mod, "_template", lambda perfil="tecnica": "TEMPLATE DIFERENTE")

        AgenteCompositor().run(job_id, entrada)
        assert mock_chamar.call_count == 2  # não veio do cache


def test_compositor_retorna_conceitos_novos_e_duvidas():
    job_id = criar_job("aula")
    entrada = _entrada_compositor()

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            _nota_composta(conceitos_novos=["Bastilha"], duvidas=["Por que caiu em 1789?"]),
            _resposta_mock(),
        )
        resultado = AgenteCompositor().run(job_id, entrada)

    assert resultado.conceitos_novos == ["Bastilha"]
    assert resultado.duvidas == ["Por que caiu em 1789?"]


def test_flashcards_envia_nota_e_duvidas_brutas_na_mensagem():
    job_id = criar_job("aula")
    entrada = EntradaFlashcards(
        disciplina="Algoritmos",
        markdown="# Aula\nconteúdo",
        duvidas_brutas=["Por que log V?"],
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            Flashcards(
                cards=[FlashcardBasico(tipo="basico", frente="P", verso="R")],
                duvidas=["Por que log V?"],
            ),
            _resposta_mock(),
        )
        resultado = AgenteFlashcards().run(job_id, entrada)

    mensagens = mock_chamar.call_args_list[0].args[2]
    assert "conteúdo" in mensagens[0]["content"]
    assert "Por que log V?" in mensagens[0]["content"]
    assert resultado.cards[0].frente == "P"
    assert resultado.duvidas == ["Por que log V?"]
    assert mock_chamar.call_args_list[0].args[0] == modelo_do_tier(Tier.SONNET)


def test_flashcards_sem_duvidas_indica_nenhuma_na_mensagem():
    job_id = criar_job("aula")
    entrada = EntradaFlashcards(disciplina="Algoritmos", markdown="# Aula", duvidas_brutas=[])

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (Flashcards(cards=[], duvidas=[]), _resposta_mock())
        AgenteFlashcards().run(job_id, entrada)

    mensagens = mock_chamar.call_args_list[0].args[2]
    assert "(nenhuma)" in mensagens[0]["content"]


def test_validador_semantico_retorna_validacao():
    job_id = criar_job("aula")
    entrada = EntradaValidadorSemantico(markdown="# Aula\nconteúdo normal")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            Validacao(aprovado=True, problemas=[]),
            _resposta_mock(),
        )
        resultado = AgenteValidadorSemantico().run(job_id, entrada)

    assert resultado.aprovado is True


def test_validar_completo_combina_deterministico_e_semantico(tmp_path):
    job_id = criar_job("aula")
    pasta_crops = tmp_path / "crops"
    pasta_crops.mkdir()

    markdown_sem_frontmatter = "sem frontmatter algum"

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            Validacao(
                aprovado=False,
                problemas=[
                    Problema(
                        severidade="aviso",
                        onde="idioma",
                        descricao="mistura idiomas",
                        sugestao="revisar",
                    )
                ],
            ),
            _resposta_mock(),
        )
        resultado = validar_completo(
            job_id, markdown_sem_frontmatter, "Historia", "2026-07-15", pasta_crops
        )

    assert resultado.aprovado is False
    assert len(resultado.problemas) >= 2  # >=1 do determinístico + 1 do semântico


def test_validar_completo_aprova_quando_ambos_aprovam():
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            Validacao(aprovado=True, problemas=[]),
            _resposta_mock(),
        )
        resultado = validar_completo(
            job_id,
            (
                "---\ndata: 2026-07-15\ndisciplina: Historia\naula: 1\ntags: []\n---\n\n"
                "# Aula\n\n## Resumo da aula\nx\n\n## Conteúdo principal\nx\n\n"
                "## Do livro\nx\n\n## Pontos sinalizados como difícil\nx\n\n"
                "## Pontos de atenção do professor\nx\n\n"
                "## Conceitos novos — precisam de página própria\nx\n\n"
                "## Exercícios relacionados\nx\n\n## Ver também\nx\n"
            ),
            "Historia",
            "2026-07-15",
            get_settings().cache_dir,  # pasta qualquer sem embeds a checar
        )

    assert resultado.aprovado is True


def test_agente_conceito_retorna_pagina():
    job_id = criar_job("aula")
    entrada = EntradaConceito(
        disciplina="Historia",
        nome_conceito="Bastilha",
        markdown_nota="# Aula\nA Bastilha caiu em 1789.",
    )
    pagina = PaginaConceito(
        definicao_formal="Fortaleza-prisão de Paris.",
        intuicao="Símbolo do poder real.",
        exemplo="Sua queda em 14/07/1789.",
        tags=["revolucao-francesa"],
        definicao_a_completar=False,
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (pagina, _resposta_mock())
        resultado = AgenteConceito().run(job_id, entrada)

    assert resultado.definicao_a_completar is False
    assert mock_chamar.call_args_list[0].args[0] == modelo_do_tier(Tier.SONNET)
    mensagens = mock_chamar.call_args_list[0].args[2]
    assert "Bastilha" in mensagens[0]["content"]


def test_validar_conceito_completo_checa_frontmatter_tipo_conceito():
    job_id = criar_job("aula")
    markdown = (
        "---\ntipo: nota\ndisciplina: Historia\ntags: []\n---\n\n"
        "# Bastilha\n\n## Definição formal\nx\n\n## Intuição\nx\n\n"
        "## Exemplo\nx\n\n## Aparece em\n- [[Aula 01]]\n"
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            Validacao(aprovado=True, problemas=[]),
            _resposta_mock(),
        )
        resultado = validar_conceito_completo(job_id, markdown, "Historia")

    assert resultado.aprovado is False
    assert any(p.onde == "frontmatter.tipo" for p in resultado.problemas)


def test_validar_conceito_completo_aprova_pagina_bem_formada():
    job_id = criar_job("aula")
    markdown = (
        "---\ntipo: conceito\ndisciplina: Historia\ntags: [revolucao-francesa]\n---\n\n"
        "# Bastilha\n\n## Definição formal\nx\n\n## Intuição\nx\n\n"
        "## Exemplo\nx\n\n## Aparece em\n- [[Aula 01]]\n"
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (
            Validacao(aprovado=True, problemas=[]),
            _resposta_mock(),
        )
        resultado = validar_conceito_completo(job_id, markdown, "Historia")

    assert resultado.aprovado is True


def _indice(confianca: float, capitulos=None, fonte_indice="toc_nativo") -> IndiceLivro:
    return IndiceLivro(
        titulo_livro="Cálculo",
        autor="Stewart",
        capitulos=capitulos
        if capitulos is not None
        else [
            CapituloIndice(numero=1, titulo="Limites", pagina_inicio=1, pagina_fim=50),
        ],
        fonte_indice=fonte_indice,
        confianca=confianca,
    )


def test_indexador_livro_usa_toc_bruto_quando_disponivel():
    job_id = criar_job("indexacao")
    entrada = EntradaIndexadorLivro(
        nome_arquivo="livro.pdf",
        total_paginas=300,
        toc_bruto="Capítulo 1 — p.1",
        texto_paginas_iniciais="",
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_indice(0.9), _resposta_mock())
        resultado = AgenteIndexadorLivro().run(job_id, entrada)

    assert resultado.confianca == 0.9
    mensagens = mock_chamar.call_args_list[0].args[2]
    assert "Capítulo 1 — p.1" in mensagens[0]["content"]
    assert mock_chamar.call_count == 1


def test_indexador_livro_confianca_baixa_escalona_para_sonnet():
    job_id = criar_job("indexacao")
    entrada = EntradaIndexadorLivro(
        nome_arquivo="livro.pdf",
        total_paginas=300,
        toc_bruto="",
        texto_paginas_iniciais="sumário confuso",
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.side_effect = [
            (_indice(0.4), _resposta_mock()),
            (_indice(0.9), _resposta_mock()),
        ]
        resultado = AgenteIndexadorLivro().run(job_id, entrada)

    assert resultado.confianca == 0.9
    assert mock_chamar.call_count == 2
    assert mock_chamar.call_args_list[0].args[0] == modelo_do_tier(Tier.HAIKU)
    assert mock_chamar.call_args_list[1].args[0] == modelo_do_tier(Tier.SONNET)


def _sugestao(confianca: float, capitulos=None) -> SugestaoCapitulos:
    return SugestaoCapitulos(
        capitulos=capitulos if capitulos is not None else [3],
        justificativa="Capítulo 3 trata de limites.",
        confianca=confianca,
    )


def test_seletor_capitulos_envia_indice_e_lacunas_na_mensagem():
    job_id = criar_job("indexacao")
    entrada = EntradaSeletorCapitulos(
        disciplina="Calculo",
        titulo_nota="Aula 5 — Limites",
        topicos=["limites"],
        lacunas=["por que o limite lateral pode não existir?"],
        indice_resumido="3 — Limites (p. 80-120)",
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_sugestao(0.9), _resposta_mock())
        resultado = AgenteSeletorCapitulos().run(job_id, entrada)

    assert resultado.capitulos == [3]
    mensagens = mock_chamar.call_args_list[0].args[2]
    assert "3 — Limites (p. 80-120)" in mensagens[0]["content"]
    assert "limite lateral" in mensagens[0]["content"]


def test_seletor_capitulos_confianca_baixa_escalona_para_sonnet():
    job_id = criar_job("indexacao")
    entrada = EntradaSeletorCapitulos(
        disciplina="Calculo",
        titulo_nota="Aula 5",
        topicos=[],
        lacunas=["dúvida vaga"],
        indice_resumido="1 — Introdução (p. 1-20)",
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.side_effect = [
            (_sugestao(0.4), _resposta_mock()),
            (_sugestao(0.9), _resposta_mock()),
        ]
        resultado = AgenteSeletorCapitulos().run(job_id, entrada)

    assert resultado.confianca == 0.9
    assert mock_chamar.call_count == 2


def _trecho(arquivo="livro.pdf", texto="conteúdo do capítulo") -> TrechoFonte:
    return TrechoFonte(
        arquivo=arquivo,
        tipo="livro",
        capitulo="1 — Limites",
        pagina_inicio=1,
        pagina_fim=20,
        texto=texto,
    )


def test_bibliotecario_envelopa_cada_trecho_como_dados():
    job_id = criar_job("indexacao")
    entrada = EntradaBibliotecario(
        disciplina="Calculo",
        titulo_nota="Aula 5",
        markdown_nota="# Aula 5\n...",
        lacunas=["por que o limite lateral pode não existir?"],
        trechos=[_trecho()],
    )
    saida = SaidaBibliotecario(
        secao_do_livro="O livro confirma...",
        respostas=[
            RespostaLacuna(
                lacuna="por que o limite lateral pode não existir?",
                resolvida=True,
                resposta="porque os limites laterais divergem",
                citacao="livro.pdf, cap. 1, p. 5",
            )
        ],
        lacunas_nao_resolvidas=[],
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (saida, _resposta_mock())
        resultado = AgenteBibliotecario().run(job_id, entrada)

    mensagens = mock_chamar.call_args_list[0].args[2]
    assert '<dados fonte="livro.pdf | 1 — Limites | p.1-20">' in mensagens[0]["content"]
    assert resultado.respostas[0].resolvida is True


def test_bibliotecario_rebaixa_resposta_sem_citacao():
    job_id = criar_job("indexacao")
    entrada = EntradaBibliotecario(
        disciplina="Calculo",
        titulo_nota="Aula 5",
        markdown_nota="# Aula 5",
        lacunas=["dúvida sem fonte"],
        trechos=[_trecho()],
    )
    saida = SaidaBibliotecario(
        secao_do_livro="x",
        respostas=[
            RespostaLacuna(
                lacuna="dúvida sem fonte",
                resolvida=True,
                resposta="resposta qualquer",
                citacao="",
            )
        ],
        lacunas_nao_resolvidas=[],
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (saida, _resposta_mock())
        resultado = AgenteBibliotecario().run(job_id, entrada)

    assert resultado.respostas[0].resolvida is False
    assert "dúvida sem fonte" in resultado.lacunas_nao_resolvidas


def test_bibliotecario_rebaixa_resposta_citando_fonte_que_nao_foi_fornecida():
    job_id = criar_job("indexacao")
    entrada = EntradaBibliotecario(
        disciplina="Calculo",
        titulo_nota="Aula 5",
        markdown_nota="# Aula 5",
        lacunas=["dúvida"],
        trechos=[_trecho(arquivo="livro.pdf")],
    )
    saida = SaidaBibliotecario(
        secao_do_livro="x",
        respostas=[
            RespostaLacuna(
                lacuna="dúvida",
                resolvida=True,
                resposta="resposta",
                citacao="outro-livro-inventado.pdf, p. 1",
            )
        ],
        lacunas_nao_resolvidas=[],
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (saida, _resposta_mock())
        resultado = AgenteBibliotecario().run(job_id, entrada)

    assert resultado.respostas[0].resolvida is False


def test_bibliotecario_preserva_resposta_com_citacao_valida():
    job_id = criar_job("indexacao")
    entrada = EntradaBibliotecario(
        disciplina="Calculo",
        titulo_nota="Aula 5",
        markdown_nota="# Aula 5",
        lacunas=["dúvida"],
        trechos=[_trecho(arquivo="livro.pdf")],
    )
    saida = SaidaBibliotecario(
        secao_do_livro="x",
        respostas=[
            RespostaLacuna(
                lacuna="dúvida",
                resolvida=True,
                resposta="resposta",
                citacao="livro.pdf, cap. 1, p. 5",
            )
        ],
        lacunas_nao_resolvidas=[],
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (saida, _resposta_mock())
        resultado = AgenteBibliotecario().run(job_id, entrada)

    assert resultado.respostas[0].resolvida is True
    assert resultado.lacunas_nao_resolvidas == []


def test_compositor_usa_o_template_do_perfil():
    tecnica = AgenteCompositor()._prompt_version_e_texto(_entrada_compositor())[1]
    idioma = AgenteCompositor()._prompt_version_e_texto(
        _entrada_compositor().model_copy(update={"perfil": "idioma"})
    )[1]

    assert "Vocabulário" in idioma
    assert "complexidade" not in idioma.lower().split("<template>")[1][:2000]
    assert idioma != tecnica


def test_trocar_de_perfil_invalida_o_cache():
    """Sem isso, mudar o perfil da disciplina deixaria a nota com o template anterior."""
    job_id = criar_job("aula")
    entrada = _entrada_compositor()
    outra = entrada.model_copy(update={"perfil": "idioma"})

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_nota_composta(), _resposta_mock())
        AgenteCompositor().run(job_id, entrada)
        AgenteCompositor().run(job_id, outra)

    assert mock_chamar.call_count == 2


def test_perfil_desconhecido_cai_no_tecnico():
    from projetos.estudos.agentes import _template

    assert _template("nao-existe") == _template("tecnica")


def test_flashcards_recebem_o_perfil_da_disciplina():
    from projetos.estudos.schemas import EntradaFlashcards

    entrada = EntradaFlashcards(
        disciplina="ALEMAO-A1.1",
        markdown="# Aula 1",
        duvidas_brutas=[],
        perfil="idioma",
    )

    conteudo = AgenteFlashcards().montar_mensagens(entrada)[0]["content"]

    assert "Perfil: idioma" in conteudo


def test_conceito_recebe_o_perfil_da_disciplina():
    from projetos.estudos.schemas import EntradaConceito

    entrada = EntradaConceito(
        disciplina="ALEMAO-A1.1",
        nome_conceito="Caso acusativo",
        markdown_nota="# Aula 1",
        perfil="idioma",
    )

    conteudo = AgenteConceito().montar_mensagens(entrada)[0]["content"]

    assert "Perfil: idioma" in conteudo
    assert "Caso acusativo" in conteudo


# --- chave de cache dos agentes de visão: conteúdo da imagem, não o caminho -----------------


def _extracao_simples(texto: str = "x") -> Extracao:
    return Extracao(
        blocos=[
            Bloco(
                tipo="texto",
                conteudo=texto,
                latex=None,
                bbox=(0.1, 0.1, 0.5, 0.2),
                confianca=0.9,
                flags=[],
            )
        ],
        idioma="pt",
        observacoes="",
    )


def _imagem(caminho: Path, cor: str) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), color=cor).save(caminho, format="JPEG")
    return caminho


def test_cache_de_visao_sobrevive_a_mudanca_de_pasta(tmp_path):
    original = _imagem(tmp_path / "estudos" / "inbox" / "A" / "foto.jpg", "blue")
    copia = tmp_path / "estudos" / "inbox" / "B" / "outro_nome.jpg"
    copia.parent.mkdir(parents=True)
    copia.write_bytes(original.read_bytes())
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_extracao_simples(), _resposta_mock())
        AgenteExtrator().run(job_id, EntradaImagem(caminho=str(original)))
        AgenteExtrator().run(job_id, EntradaImagem(caminho=str(copia)))

    assert mock_chamar.call_count == 1


def test_cache_de_visao_distingue_conteudo_no_mesmo_caminho(tmp_path):
    caminho = tmp_path / "estudos" / "inbox" / "A" / "foto.jpg"
    job_id = criar_job("aula")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_extracao_simples(), _resposta_mock())
        _imagem(caminho, "blue")
        AgenteExtrator().run(job_id, EntradaImagem(caminho=str(caminho)))
        _imagem(caminho, "red")
        AgenteExtrator().run(job_id, EntradaImagem(caminho=str(caminho)))

    assert mock_chamar.call_count == 2


def test_triagem_e_extrator_nao_compartilham_chave(foto):
    entrada = EntradaImagem(caminho=str(foto))

    assert AgenteTriagem()._chave_cache(entrada) != AgenteExtrator()._chave_cache(entrada)


def test_chave_de_agente_de_texto_nao_mudou():
    """Trava a chave de um agente sem imagem: mudar o jeito de calcular invalidaria o
    cache de texto de quem já usa."""
    entrada = EntradaFlashcards(
        disciplina="MAT1", markdown="# Aula\n\nO(n) é linear.", duvidas_brutas=[]
    )
    chave = AgenteFlashcards()._chave_cache(entrada)

    bruto = (
        f"{entrada.model_dump_json()}:flashcards:"
        f"{AgenteFlashcards()._prompt_version_e_texto(entrada)[0]}:"
        f"{modelo_do_tier(Tier.SONNET)}:"
    )
    assert chave == hashlib.sha256(bruto.encode()).hexdigest()
