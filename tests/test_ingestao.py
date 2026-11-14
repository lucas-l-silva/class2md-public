import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from core.config import get_settings
from core.estado import conectar
from core.fileops import escrever_texto
from projetos.estudos.disciplinas import Disciplina, Registro, salvar_registro
from projetos.estudos.ingestao import ingerir_imagem, varrer_inbox


@pytest.fixture(autouse=True)
def settings_isolado(monkeypatch, tmp_path):
    (tmp_path / "logs").mkdir()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def inbox(tmp_path) -> Path:
    caminho = tmp_path / "estudos" / "inbox"
    caminho.mkdir(parents=True)
    return caminho


def _criar_foto(
    caminho: Path,
    cor: str = "blue",
    orientation: int | None = None,
    data_exif: str | None = None,
) -> None:
    imagem = Image.new("RGB", (80, 60), color=cor)
    exif = imagem.getexif()
    if orientation is not None:
        exif[0x0112] = orientation
    if data_exif is not None:
        exif[0x9003] = data_exif
    caminho.parent.mkdir(parents=True, exist_ok=True)
    imagem.save(caminho, exif=exif)


def test_ingerir_mesma_foto_duas_vezes_nao_duplica(inbox):
    origem1 = inbox / "Calculo" / "foto1.jpg"
    _criar_foto(origem1, data_exif="2026:07:15 10:00:00")
    origem2 = inbox / "Calculo" / "foto2.jpg"
    _criar_foto(origem2, data_exif="2026:07:15 10:00:00")

    nome1 = ingerir_imagem(origem1)
    nome2 = ingerir_imagem(origem2)

    assert nome1 == "2026-07-15_calculo_001.jpg"
    assert nome2 is None

    processed = list(
        (get_settings().agent_data_dir / "estudos" / "processed" / "Calculo").glob("*.jpg")
    )
    assert len(processed) == 1


def test_exif_removido_do_arquivo_final(inbox):
    origem = inbox / "Calculo" / "foto.jpg"
    _criar_foto(origem, data_exif="2026:07:15 10:00:00")

    nome = ingerir_imagem(origem)

    destino = get_settings().agent_data_dir / "estudos" / "processed" / "Calculo" / nome
    assert Image.open(destino).getexif().get(0x9003) is None


def test_orientacao_preservada(inbox):
    origem = inbox / "Calculo" / "foto.jpg"
    _criar_foto(origem, orientation=6, data_exif="2026:07:15 10:00:00")

    nome = ingerir_imagem(origem)

    destino = get_settings().agent_data_dir / "estudos" / "processed" / "Calculo" / nome
    assert Image.open(destino).size == (60, 80)


def test_nome_usa_slug_da_disciplina_e_sequencia_incrementa(inbox):
    origem1 = inbox / "Cálculo III" / "a.jpg"
    _criar_foto(origem1, cor="red", data_exif="2026:07:15 10:00:00")
    origem2 = inbox / "Cálculo III" / "b.jpg"
    _criar_foto(origem2, cor="green", data_exif="2026:07:15 11:00:00")

    nome1 = ingerir_imagem(origem1)
    nome2 = ingerir_imagem(origem2)

    assert nome1 == "2026-07-15_calculo_iii_001.jpg"
    assert nome2 == "2026-07-15_calculo_iii_002.jpg"


def test_arquivo_movido_para_processed_por_disciplina_e_removido_do_inbox(inbox):
    origem = inbox / "Calculo" / "foto.jpg"
    _criar_foto(origem, data_exif="2026:07:15 10:00:00")

    nome = ingerir_imagem(origem)

    assert not origem.exists()
    destino = get_settings().agent_data_dir / "estudos" / "processed" / "Calculo" / nome
    assert destino.exists()


def test_arquivo_solto_na_raiz_do_inbox_e_ignorado(inbox):
    solto = inbox / "solto.jpg"
    _criar_foto(solto, data_exif="2026:07:15 10:00:00")

    resultado = varrer_inbox()

    assert resultado == []
    assert solto.exists()


def test_disciplina_extraida_do_nome_da_subpasta(inbox):
    origem = inbox / "Fisica II" / "foto.jpg"
    _criar_foto(origem, data_exif="2026:07:15 10:00:00")

    nome = ingerir_imagem(origem)

    conn = conectar()
    row = conn.execute("SELECT disciplina FROM arquivos WHERE nome_final=?", (nome,)).fetchone()
    assert row["disciplina"] == "Fisica II"


def test_varrer_inbox_aceita_extensao_maiuscula_e_png(inbox):
    origem_jpg_maiuscula = inbox / "Historia" / "IMG_1710.JPG"
    _criar_foto(origem_jpg_maiuscula, data_exif="2026:07:15 10:00:00")

    origem_png = inbox / "Historia" / "foto.png"
    origem_png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 60), color="green").save(origem_png, format="PNG")

    resultado = varrer_inbox()

    assert len(resultado) == 2
    assert not origem_jpg_maiuscula.exists()
    assert not origem_png.exists()


def test_disciplina_fora_da_lista_gera_aviso_mas_ingere(inbox):
    settings = get_settings()
    escrever_texto(settings.agent_data_dir / "estudos" / "disciplinas.txt", "Calculo\n")

    origem = inbox / "Fisica II" / "foto.jpg"
    _criar_foto(origem, data_exif="2026:07:15 10:00:00")

    nome = ingerir_imagem(origem)

    assert nome is not None

    hoje = datetime.now(UTC).strftime("%Y-%m-%d")
    log = settings.logs_dir / f"{hoje}.jsonl"
    eventos = [json.loads(linha) for linha in log.read_text().splitlines()]
    assert any(e.get("resultado") == "disciplina_nao_cadastrada" for e in eventos)


def test_registro_de_disciplinas_vence_o_disciplinas_txt(inbox):
    """O registro é a fonte de verdade; o .txt só vale quando não há registro."""
    settings = get_settings()
    escrever_texto(settings.agent_data_dir / "estudos" / "disciplinas.txt", "Calculo\n")
    salvar_registro(
        Registro(
            semestre_atual="2030.2",
            disciplinas=[Disciplina(nome="MAT1", titulo="Construção e Análise", semestre="2030.2")],
        )
    )

    origem = inbox / "MAT1" / "foto.jpg"
    _criar_foto(origem, data_exif="2026:08:10 10:00:00")

    assert ingerir_imagem(origem) is not None

    hoje = datetime.now(UTC).strftime("%Y-%m-%d")
    eventos = [
        json.loads(linha)
        for linha in (settings.logs_dir / f"{hoje}.jsonl").read_text().splitlines()
    ]
    # MAT1 não está no .txt, mas está no registro: nenhum aviso
    assert not any(e.get("resultado") == "disciplina_nao_cadastrada" for e in eventos)


def test_foto_de_monitoria_e_ingerida_com_origem_propria(inbox):
    """Misturá-la no job do dia faria a nota da aula afirmar o que o professor não disse."""
    origem = inbox / "MAT1" / "monitoria" / "quadro.jpg"
    _criar_foto(origem, data_exif="2026:08:14 09:00:00")

    nome = ingerir_imagem(origem)

    assert nome == "2026-08-14_mat1_monitoria_001.jpg"
    conn = conectar()
    linha = conn.execute("SELECT disciplina, origem FROM arquivos").fetchone()
    assert linha["disciplina"] == "MAT1"
    assert linha["origem"] == "monitoria"


def test_monitoria_nao_entra_na_fila_de_fotos_de_aula(inbox):
    _criar_foto(inbox / "MAT1" / "aula.jpg", data_exif="2026:08:14 08:00:00")
    _criar_foto(inbox / "MAT1" / "monitoria" / "quadro.jpg", data_exif="2026:08:14 09:00:00")

    varrer_inbox()

    from core.estado import fotos_pendentes

    assert [f["origem"] for f in fotos_pendentes()] == ["aula"]
    assert len(fotos_pendentes("monitoria")) == 1


def test_varrer_inbox_pega_as_duas_pastas(inbox):
    _criar_foto(inbox / "MAT1" / "aula.jpg", data_exif="2026:08:14 08:00:00")
    _criar_foto(inbox / "MAT1" / "monitoria" / "quadro.jpg", data_exif="2026:08:14 09:00:00")

    assert len(varrer_inbox()) == 2


def test_foto_na_pasta_de_ementa_e_ingerida_como_administrativa(inbox):
    """Quatro fotos de plano de ensino ficaram paradas em `pdfs/ementa/` porque o
    varredor só olhava a raiz e `monitoria/`."""
    from projetos.estudos.ingestao import _origem_e_disciplina, varrer_inbox

    destino = inbox / "FIS1" / "pdfs" / "ementa"
    destino.mkdir(parents=True)
    _criar_foto(destino / "plano.jpg")

    assert _origem_e_disciplina(destino / "plano.jpg") == ("ementa", "FIS1")
    assert len(varrer_inbox()) == 1


def test_imagem_em_pasta_nao_varrida_e_relatada(inbox):
    """Pular em silêncio é o pior modo de falha: não dá para distinguir "olhei e não
    achei" de "nunca olhei"."""
    from projetos.estudos.ingestao import imagens_fora_das_pastas_conhecidas

    pasta = inbox / "MAT1"
    pasta.mkdir(parents=True, exist_ok=True)
    perdida = pasta / "pdfs" / "antigas" / "notas"
    perdida.mkdir(parents=True)
    _criar_foto(perdida / "esquecida.jpg")
    _criar_foto(pasta / "normal.jpg")

    esquecidas = imagens_fora_das_pastas_conhecidas(pasta)

    assert [c.name for c in esquecidas] == ["esquecida.jpg"]
