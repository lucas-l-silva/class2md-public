import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image
from typer.testing import CliRunner

from core.config import get_settings
from core.estado import conectar, lock_runner
from projetos.estudos.disciplinas import (
    Disciplina,
    Docente,
    Horario,
    Registro,
    salvar_registro,
)
from projetos.estudos.schemas import (
    Contexto,
    Extracao,
    FlashcardBasico,
    Flashcards,
    NotaComposta,
    Triagem,
    Validacao,
)
from scripts.estudos import app

runner = CliRunner()


def _resposta_mock():
    usage = SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0)
    return SimpleNamespace(usage=usage)


def _mock_llm():
    triagem = Triagem(
        categoria="lousa",
        receita_preproc="nenhuma",
        qualidade="boa",
        contem_conteudo_academico=True,
        confianca=0.9,
    )
    extracao = Extracao(blocos=[], idioma="pt", observacoes="")
    contexto = Contexto(
        aula_numero=1,
        titulo_sugerido="Aula de teste",
        topicos=[],
        conexoes=[],
        tags=[],
        subnotas_sugeridas=[],
        confianca=0.9,
    )
    nota = NotaComposta(
        markdown=(
            "---\ndata: 2026-07-15\ndisciplina: Historia\naula: 1\ntags: []\n---\n\n"
            "# Aula de teste\n\n"
            "## Resumo da aula\nx\n\n"
            "## Conteúdo principal\nx\n\n"
            "## Do livro\nx\n\n"
            "## Pontos sinalizados como difícil\nx\n\n"
            "## Pontos de atenção do professor\nx\n\n"
            "## Conceitos novos — precisam de página própria\nx\n\n"
            "## Exercícios relacionados\nx\n\n"
            "## Ver também\nx\n"
        ),
        conceitos_novos=[],
        duvidas=[],
    )
    validacao = Validacao(aprovado=True, problemas=[])
    flashcards = Flashcards(
        cards=[FlashcardBasico(tipo="basico", frente="P", verso="R")], duvidas=[]
    )
    return patch(
        "core.agents.base.chamar_estruturado",
        side_effect=[
            (triagem, _resposta_mock()),
            (extracao, _resposta_mock()),
            (contexto, _resposta_mock()),
            (nota, _resposta_mock()),
            (validacao, _resposta_mock()),
            (flashcards, _resposta_mock()),
        ],
    )


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "cache").mkdir()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def inbox(tmp_path) -> Path:
    caminho = tmp_path / "estudos" / "inbox"
    caminho.mkdir(parents=True)
    return caminho


def _criar_foto(caminho: Path, cor: str = "blue", data_exif: str | None = None) -> None:
    imagem = Image.new("RGB", (80, 60), color=cor)
    exif = imagem.getexif()
    if data_exif is not None:
        exif[0x9003] = data_exif
    caminho.parent.mkdir(parents=True, exist_ok=True)
    imagem.save(caminho, exif=exif)


def test_processar_cria_job_stub_manifesto_e_conclui(inbox):
    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")

    with _mock_llm():
        resultado = runner.invoke(app, ["processar"])

    assert resultado.exit_code == 0
    assert "Fotos ingeridas: 1" in resultado.stdout
    assert "Jobs criados: 1" in resultado.stdout
    assert "Jobs processados: 1" in resultado.stdout

    settings = get_settings()
    conn = conectar()
    job = conn.execute("SELECT * FROM jobs WHERE disciplina='Historia'").fetchone()
    assert job["status"] == "concluido"

    stub = (
        settings.agent_data_dir
        / "estudos"
        / "output"
        / "Historia"
        / "2026-07-15 Aula — (a processar).md"
    )
    assert not stub.exists()  # substituído pela nota definitiva

    nota_final = (
        settings.agent_data_dir
        / "estudos"
        / "output"
        / "Historia"
        / "2026-07-15 Aula 01 — Aula de teste.md"
    )
    assert nota_final.exists()

    manifesto_path = settings.agent_data_dir / "estudos" / "output" / "_manifest.json"
    manifesto = json.loads(manifesto_path.read_text())
    assert job["id"] in manifesto
    assert manifesto[job["id"]]["status"] == "concluido"


def test_processar_remove_exif_da_foto_final(inbox):
    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")

    with _mock_llm():
        runner.invoke(app, ["processar"])

    settings = get_settings()
    processed = list((settings.agent_data_dir / "estudos" / "processed" / "Historia").glob("*.jpg"))
    assert len(processed) == 1
    assert Image.open(processed[0]).getexif().get(0x9003) is None


def test_rodar_processar_duas_vezes_nao_duplica_nada(inbox):
    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")

    with _mock_llm():
        runner.invoke(app, ["processar"])
        segunda = runner.invoke(app, ["processar"])

    assert "Fotos ingeridas: 0" in segunda.stdout
    assert "Jobs criados: 0" in segunda.stdout

    conn = conectar()
    total_jobs = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
    assert total_jobs == 1


def test_status_mostra_job_processado(inbox):
    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")
    with _mock_llm():
        runner.invoke(app, ["processar"])

    resultado = runner.invoke(app, ["status"])

    assert resultado.exit_code == 0
    assert "Historia" in resultado.stdout
    assert "concluido" in resultado.stdout


def test_segundo_processar_concorrente_e_barrado_pelo_lock(inbox):
    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")

    with lock_runner():
        resultado = runner.invoke(app, ["processar"])

    assert resultado.exit_code == 0
    assert "em andamento" in resultado.stdout

    conn = conectar()
    total_jobs = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
    assert total_jobs == 0


def test_aprovar_resolve_job_aguardando_humano(inbox):
    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")

    triagem_ruim = Triagem(
        categoria="outro",
        receita_preproc="nenhuma",
        qualidade="boa",
        contem_conteudo_academico=False,
        confianca=0.9,
    )
    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (triagem_ruim, _resposta_mock())
        runner.invoke(app, ["processar"])

    conn = conectar()
    job = conn.execute("SELECT id, status FROM jobs WHERE disciplina='Historia'").fetchone()
    assert job["status"] == "aguardando_humano"

    resultado = runner.invoke(app, ["aprovar", job["id"][:8]])

    assert resultado.exit_code == 0
    assert "aprovado" in resultado.stdout

    job_depois = conn.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()
    assert job_depois["status"] == "na_fila"


def test_aprovar_job_inexistente_sai_com_erro():
    resultado = runner.invoke(app, ["aprovar", "nao-existe"])

    assert resultado.exit_code == 1


def test_reprocessar_reenfileira_job_falhou(inbox):
    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.side_effect = RuntimeError("erro técnico simulado")
        runner.invoke(app, ["processar"])

    conn = conectar()
    job = conn.execute("SELECT id, status FROM jobs WHERE disciplina='Historia'").fetchone()
    assert job["status"] == "falhou"

    resultado = runner.invoke(app, ["reprocessar", job["id"][:8]])

    assert resultado.exit_code == 0
    assert "na_fila" in resultado.stdout

    job_depois = conn.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()
    assert job_depois["status"] == "na_fila"


def test_reprocessar_job_inexistente_sai_com_erro():
    resultado = runner.invoke(app, ["reprocessar", "nao-existe"])

    assert resultado.exit_code == 1


def test_processar_registra_pdfs_encontrados_em_pdfs(inbox, tmp_path):
    from tests.pdf_fabrica import criar_pdf

    caminho_pdf = tmp_path / "estudos" / "pdfs" / "Historia" / "lista.pdf"
    criar_pdf(caminho_pdf, paginas=2, texto_por_pagina="1. Questão de teste.")

    resultado = runner.invoke(app, ["processar"])

    assert resultado.exit_code == 0
    assert "PDFs registrados: 1" in resultado.stdout


def test_comando_pdfs_lista_registros_da_disciplina(tmp_path):
    from tests.pdf_fabrica import criar_pdf

    caminho_pdf = tmp_path / "estudos" / "pdfs" / "Historia" / "livro.pdf"
    criar_pdf(caminho_pdf, paginas=50, texto_por_pagina="conteúdo " * 10)
    runner.invoke(app, ["processar"])

    resultado = runner.invoke(app, ["pdfs", "Historia"])

    assert resultado.exit_code == 0
    assert "livro.pdf" in resultado.stdout
    assert "livro" in resultado.stdout


def test_comando_pdfs_sem_registros_avisa(tmp_path):
    resultado = runner.invoke(app, ["pdfs", "Historia"])

    assert resultado.exit_code == 0
    assert "Nenhum PDF registrado" in resultado.stdout


def _indice_mock():
    from projetos.estudos.schemas import CapituloIndice, IndiceLivro

    return IndiceLivro(
        titulo_livro="Cálculo",
        autor="Stewart",
        capitulos=[CapituloIndice(numero=1, titulo="Limites", pagina_inicio=1, pagina_fim=None)],
        fonte_indice="toc_nativo",
        confianca=0.9,
    )


def test_indexar_pdf_com_caminho_indexa_o_livro(tmp_path):
    from tests.pdf_fabrica import criar_pdf

    caminho_pdf = tmp_path / "estudos" / "pdfs" / "Historia" / "livro.pdf"
    criar_pdf(caminho_pdf, paginas=50, texto_por_pagina="conteúdo " * 10)

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_indice_mock(), _resposta_mock())
        resultado = runner.invoke(app, ["indexar-pdf", str(caminho_pdf)])

    assert resultado.exit_code == 0
    assert "capítulo" in resultado.stdout


def test_indexar_pdf_pdf_pequeno_nao_indexa(tmp_path):
    from tests.pdf_fabrica import criar_pdf

    caminho_pdf = tmp_path / "estudos" / "pdfs" / "Historia" / "lista.pdf"
    criar_pdf(caminho_pdf, paginas=2, texto_por_pagina="1. Questão de teste.")

    resultado = runner.invoke(app, ["indexar-pdf", str(caminho_pdf)])

    assert resultado.exit_code == 0
    assert "nada a indexar" in resultado.stdout


def test_indexar_pdf_com_aula_liga_o_pdf_ao_numero_da_aula(tmp_path):
    from core.estado import pdf_por_sha
    from projetos.estudos.pdf_ingestao import sha256_pdf
    from tests.pdf_fabrica import criar_pdf

    caminho_pdf = tmp_path / "estudos" / "pdfs" / "Historia" / "lista.pdf"
    criar_pdf(caminho_pdf, paginas=2, texto_por_pagina="1. Questão de teste.")

    resultado = runner.invoke(app, ["indexar-pdf", str(caminho_pdf), "--aula", "7"])

    assert resultado.exit_code == 0
    registro = pdf_por_sha(sha256_pdf(caminho_pdf))
    assert registro["numero_aula"] == 7
    assert registro["vinculo_fonte"] == "manual"


def test_indexar_pdf_sem_caminho_indexa_todos_os_livros_registrados(tmp_path):
    from tests.pdf_fabrica import criar_pdf

    criar_pdf(
        tmp_path / "estudos" / "pdfs" / "Historia" / "livro1.pdf",
        paginas=50,
        texto_por_pagina="x " * 10,
    )
    criar_pdf(
        tmp_path / "estudos" / "pdfs" / "Calculo" / "livro2.pdf",
        paginas=60,
        texto_por_pagina="y " * 10,
    )

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.return_value = (_indice_mock(), _resposta_mock())
        resultado = runner.invoke(app, ["indexar-pdf"])

    assert resultado.exit_code == 0
    assert "Indexando 2 livro(s)" in resultado.stdout


def _mock_llm_com_duvida():
    from projetos.estudos.schemas import Bloco

    triagem = Triagem(
        categoria="lousa",
        receita_preproc="nenhuma",
        qualidade="boa",
        contem_conteudo_academico=True,
        confianca=0.9,
    )
    extracao = Extracao(
        blocos=[
            Bloco(
                tipo="texto",
                conteudo="limite de uma função",
                latex=None,
                bbox=(0, 0, 1, 1),
                confianca=0.9,
                flags=[],
            )
        ],
        idioma="pt",
        observacoes="",
    )
    contexto = Contexto(
        aula_numero=5,
        titulo_sugerido="Limites",
        topicos=["limites"],
        conexoes=[],
        tags=[],
        subnotas_sugeridas=[],
        confianca=0.9,
    )
    nota = NotaComposta(
        markdown=(
            "---\ndata: 2026-07-15\ndisciplina: Historia\naula: 5\ntags: []\n---\n\n"
            "# Aula 5 — Limites\n\n"
            "## Resumo da aula\nx\n\n"
            "## Conteúdo principal\nx\n\n"
            "## Do livro\n(ainda não disponível)\n\n"
            "## Pontos sinalizados como difícil\n"
            "- por que o limite lateral pode não existir?\n\n"
            "## Pontos de atenção do professor\nx\n\n"
            "## Conceitos novos — precisam de página própria\nx\n\n"
            "## Exercícios relacionados\nx\n\n"
            "## Ver também\nx\n"
        ),
        conceitos_novos=[],
        duvidas=["por que o limite lateral pode não existir?"],
    )
    validacao = Validacao(aprovado=True, problemas=[])
    flashcards = Flashcards(
        cards=[FlashcardBasico(tipo="basico", frente="P", verso="R")],
        duvidas=["por que o limite lateral pode não existir?"],
    )
    return patch(
        "core.agents.base.chamar_estruturado",
        side_effect=[
            (triagem, _resposta_mock()),
            (extracao, _resposta_mock()),
            (contexto, _resposta_mock()),
            (nota, _resposta_mock()),
            (validacao, _resposta_mock()),
            (flashcards, _resposta_mock()),
        ],
    )


def test_preencher_lacunas_com_capitulo_manual_reescreve_a_nota(inbox, tmp_path):
    from projetos.estudos.schemas import (
        CapituloIndice,
        IndiceLivro,
        RespostaLacuna,
        SaidaBibliotecario,
    )
    from tests.pdf_fabrica import criar_pdf

    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")
    with _mock_llm_com_duvida():
        runner.invoke(app, ["processar"])

    criar_pdf(
        tmp_path / "estudos" / "pdfs" / "Historia" / "stewart.pdf",
        paginas=100,
        texto_por_pagina="conteúdo " * 10,
    )
    runner.invoke(app, ["processar"])  # registra o PDF (varrer_pdfs roda dentro de processar)

    conn = conectar()
    job = conn.execute("SELECT id FROM jobs WHERE disciplina='Historia'").fetchone()

    indice = IndiceLivro(
        titulo_livro="Cálculo",
        autor="Stewart",
        capitulos=[CapituloIndice(numero=2, titulo="Limites", pagina_inicio=40, pagina_fim=70)],
        fonte_indice="toc_nativo",
        confianca=0.9,
    )
    saida = SaidaBibliotecario(
        secao_do_livro="Stewart confirma a definição via épsilon-delta.",
        respostas=[
            RespostaLacuna(
                lacuna="por que o limite lateral pode não existir?",
                resolvida=True,
                resposta="porque os limites laterais divergem",
                citacao="stewart.pdf, cap. 2, p. 45",
            )
        ],
        lacunas_nao_resolvidas=[],
    )
    validacao = Validacao(aprovado=True, problemas=[])

    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.side_effect = [
            (indice, _resposta_mock()),
            (saida, _resposta_mock()),
            (validacao, _resposta_mock()),
        ]
        resultado = runner.invoke(
            app, ["preencher-lacunas", job["id"][:8], "--capitulo", "2", "--sim"]
        )

    assert resultado.exit_code == 0, resultado.stdout
    assert "Lacunas resolvidas: 1/1" in resultado.stdout

    manifesto = json.loads(
        (get_settings().agent_data_dir / "estudos" / "output" / "_manifest.json").read_text()
    )
    assert manifesto[job["id"]]["duvidas"] == []


def test_preencher_lacunas_job_nao_concluido_sai_com_erro():
    resultado = runner.invoke(app, ["preencher-lacunas", "0" * 8])

    assert resultado.exit_code == 1


def test_preencher_lacunas_sem_lacunas_nao_faz_nada(inbox):
    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")
    with _mock_llm():
        runner.invoke(app, ["processar"])

    conn = conectar()
    job = conn.execute("SELECT id FROM jobs WHERE disciplina='Historia'").fetchone()

    resultado = runner.invoke(app, ["preencher-lacunas", job["id"][:8]])

    assert resultado.exit_code == 0
    assert "nada a preencher" in resultado.stdout


def _registro_2026_2():
    salvar_registro(
        Registro(
            semestre_atual="2030.2",
            disciplinas=[
                Disciplina(
                    nome="MAT1",
                    titulo="Matemática Discreta",
                    semestre="2030.2",
                    monitoria=True,
                    docentes=[Docente(nome="Maria Lima", fonte="foto 013")],
                    horarios=[Horario(dia="seg", inicio="08:00", fim="10:00")],
                    a_confirmar=["horário do sábado"],
                ),
                Disciplina(nome="FIS1", titulo="Física Geral", semestre="2030.2"),
            ],
        )
    )


def test_disciplinas_sem_registro_orienta_e_sai_com_erro():
    resultado = runner.invoke(app, ["disciplinas"])

    assert resultado.exit_code == 1
    assert "disciplinas --exemplo" in resultado.output


def test_disciplinas_exemplo_cria_modelo_e_nao_sobrescreve():
    primeiro = runner.invoke(app, ["disciplinas", "--exemplo"])
    assert primeiro.exit_code == 0
    assert "criado" in primeiro.output

    segundo = runner.invoke(app, ["disciplinas", "--exemplo"])
    assert "nada foi sobrescrito" in segundo.output


def test_disciplinas_lista_docentes_horarios_e_pendencias():
    _registro_2026_2()

    resultado = runner.invoke(app, ["disciplinas"])

    assert resultado.exit_code == 0
    assert "MAT1 — Matemática Discreta" in resultado.output
    assert "Maria Lima" in resultado.output
    assert "seg 08:00-10:00" in resultado.output
    assert "a confirmar: horário do sábado" in resultado.output


def test_cli_reprocessar_recusa_passo_com_cache(inbox):
    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")
    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.side_effect = RuntimeError("erro técnico simulado")
        runner.invoke(app, ["processar"])
    job = conectar().execute("SELECT id FROM jobs WHERE disciplina='Historia'").fetchone()

    resultado = runner.invoke(
        app, ["reprocessar", job["id"][:8], "--com-cache", "--passo", "extrator"]
    )

    assert resultado.exit_code == 1
    assert "Os dois juntos" in resultado.stdout


def test_cli_reprocessar_com_cache_informa_que_o_cache_sera_usado(inbox):
    _criar_foto(inbox / "Historia" / "foto.jpg", data_exif="2026:07:15 10:00:00")
    with patch("core.agents.base.chamar_estruturado") as mock_chamar:
        mock_chamar.side_effect = RuntimeError("erro técnico simulado")
        runner.invoke(app, ["processar"])
    job = conectar().execute("SELECT id FROM jobs WHERE disciplina='Historia'").fetchone()

    resultado = runner.invoke(app, ["reprocessar", job["id"][:8], "--com-cache"])

    assert resultado.exit_code == 0
    assert "O cache será usado" in resultado.stdout


def test_ajuda_nao_lista_grupo_vazio():
    resultado = runner.invoke(app, ["--help"])

    assert resultado.exit_code == 0
    assert "agenda" not in resultado.stdout


def test_processar_nao_aceita_force():
    resultado = runner.invoke(app, ["processar", "--force"])

    assert resultado.exit_code != 0


def test_processar_etapas_desconhecida_lista_as_validas():
    resultado = runner.invoke(app, ["processar", "--etapas", "inexistente"])

    assert resultado.exit_code == 1
    assert "Etapa desconhecida: inexistente" in resultado.stdout
    assert "leitura, nota, flashcards" in resultado.stdout


def test_processar_etapas_completa_dependencia_e_avisa():
    resultado = runner.invoke(app, ["processar", "--etapas", "nota"])

    assert resultado.exit_code == 0
    assert "Incluí 'leitura' porque 'nota' depende dela." in resultado.stdout


def test_processar_etapas_de_pdf_aponta_o_comando():
    resultado = runner.invoke(app, ["processar", "--etapas", "lacunas"])

    assert resultado.exit_code == 1
    assert "preencher-lacunas" in resultado.stdout


def test_sem_flashcards_com_etapas_flashcards_e_erro():
    resultado = runner.invoke(
        app, ["processar", "--sem-flashcards", "--etapas", "leitura,flashcards"]
    )

    assert resultado.exit_code == 1
    assert "se contradizem" in resultado.stdout


def test_status_mostra_jobs_parciais():
    from core.estado import criar_job, transicionar

    job_id = criar_job("aula", disciplina="Historia", data="2026-07-15")
    transicionar(job_id, "rodando")
    transicionar(job_id, "parcial")

    resultado = runner.invoke(app, ["status"])

    assert "Parciais (1)" in resultado.stdout
    assert f"reprocessar {job_id[:8]} --com-cache" in resultado.stdout
