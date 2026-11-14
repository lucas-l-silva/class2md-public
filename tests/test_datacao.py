from datetime import date, datetime
from pathlib import Path

import pytest
from PIL import Image

from core.config import get_settings
from core.estado import conectar
from projetos.estudos.datacao import datar, reconciliar
from projetos.estudos.disciplinas import Disciplina, Horario, Registro, salvar_registro
from projetos.estudos.ingestao import varrer_inbox

TER, QUI = 1, 3


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
def fis1_terca_quinta():
    salvar_registro(
        Registro(
            semestre_atual="2030.2",
            disciplinas=[
                Disciplina(
                    nome="FIS1",
                    titulo="Física Geral",
                    semestre="2030.2",
                    horarios=[
                        Horario(dia="ter", inicio="08:00", fim="10:00"),
                        Horario(dia="qui", inicio="08:00", fim="10:00"),
                    ],
                )
            ],
        )
    )


def _foto(caminho: Path, data_exif: str, cor: str = "blue") -> Path:
    imagem = Image.new("RGB", (80, 60), color=cor)
    exif = imagem.getexif()
    exif[0x9003] = data_exif
    caminho.parent.mkdir(parents=True, exist_ok=True)
    imagem.save(caminho, exif=exif)
    return caminho


def _leitor_que_falha(_caminho):
    raise AssertionError("não devia ler a data escrita")


# ----------------------------------------------------------------- decisão pura


def test_pasta_com_data_vence_exif_e_folha(fis1_terca_quinta, tmp_path):
    caminho = tmp_path / "inbox" / "FIS1" / "2026-08-20" / "f.jpg"
    d = datar(caminho, "FIS1", datetime(2026, 9, 13, 16, 0), set(), _leitor_que_falha)

    assert (d.data, d.fonte) == (date(2026, 8, 20), "pasta")


def test_exif_em_dia_de_aula_nao_chama_modelo(fis1_terca_quinta, tmp_path):
    """O caso comum, a lousa fotografada em sala, não pode custar uma chamada."""
    d = datar(tmp_path / "f.jpg", "FIS1", datetime(2026, 9, 3, 9, 0), set(), _leitor_que_falha)

    assert (d.data, d.fonte) == (date(2026, 9, 3), "exif")


def test_manuscrita_fotografada_no_domingo_usa_a_data_da_folha(fis1_terca_quinta, tmp_path):
    """IMG_3047: EXIF 13/09 (domingo), a folha diz 10.09.26 (quinta)."""
    d = datar(
        tmp_path / "f.jpg",
        "FIS1",
        datetime(2026, 9, 13, 16, 56),
        set(),
        lambda _: date(2026, 9, 10),
    )

    assert (d.data, d.fonte) == (date(2026, 9, 10), "escrita")


def test_data_escrita_fora_de_dia_de_aula_vai_para_o_vizinho_com_lousa():
    """IMG_3049: a folha diz 02.09.26, uma quarta; só 03/09 tem foto da lousa."""
    d = reconciliar(date(2026, 9, 2), {TER, QUI}, {date(2026, 9, 3), date(2026, 8, 27)})

    assert (d.data, d.fonte) == (date(2026, 9, 3), "escrita_reconciliada")
    assert "02/09" in d.aviso and "03/09" in d.aviso


def test_vizinhos_com_lousa_dos_dois_lados_e_ambiguo():
    d = reconciliar(date(2026, 9, 2), {TER, QUI}, {date(2026, 9, 1), date(2026, 9, 3)})

    assert d.data is None and d.fonte == "ambigua"
    assert "AAAA-MM-DD" in d.aviso


def test_nenhum_vizinho_com_lousa_tambem_e_ambiguo():
    assert reconciliar(date(2026, 9, 2), {TER, QUI}, set()).data is None


def test_folha_sem_data_legivel_cai_no_exif_com_aviso(fis1_terca_quinta, tmp_path):
    d = datar(tmp_path / "f.jpg", "FIS1", datetime(2026, 9, 13), set(), lambda _: None)

    assert (d.data, d.fonte) == (date(2026, 9, 13), "exif")
    assert "nenhuma data" in d.aviso


def test_data_escrita_depois_do_exif_e_descartada(fis1_terca_quinta, tmp_path):
    """Ninguém fotografa hoje a anotação de uma aula que ainda não aconteceu."""
    d = datar(
        tmp_path / "f.jpg",
        "FIS1",
        datetime(2026, 9, 13),
        set(),
        lambda _: date(2026, 10, 1),
    )

    assert d.fonte == "exif"


def test_sem_horario_no_registro_o_exif_vale(tmp_path):
    d = datar(tmp_path / "f.jpg", "SEMREGISTRO", datetime(2026, 9, 13), set(), _leitor_que_falha)

    assert d.fonte == "exif"


# ----------------------------------------------------------------- na ingestão


def test_as_tres_manuscritas_de_fis1_vao_para_as_aulas_certas(fis1_terca_quinta, tmp_path):
    """O lote real: lousa em 03/09 e 10/09, três folhas fotografadas no domingo 13/09."""
    inbox = tmp_path / "estudos" / "inbox" / "FIS1"
    _foto(inbox / "IMG_2879.jpeg", "2026:09:03 09:14:18", "red")
    _foto(inbox / "IMG_2991.jpeg", "2026:09:10 09:26:09", "green")
    folhas = {
        _foto(inbox / "IMG_3047.jpg", "2026:09:13 13:56:45", "white"): date(2026, 9, 10),
        _foto(inbox / "IMG_3048.jpg", "2026:09:13 13:56:55", "yellow"): date(2026, 8, 20),
        _foto(inbox / "IMG_3049.jpg", "2026:09:13 13:57:10", "gray"): date(2026, 9, 2),
    }
    lidas = {p.name: d for p, d in folhas.items()}

    ingeridas = varrer_inbox(ler_escrita=lambda caminho: lidas[caminho.name])

    assert sorted(ingeridas) == [
        "2026-08-20_fis1_001.jpg",
        "2026-09-03_fis1_001.jpg",
        "2026-09-03_fis1_002.jpg",
        "2026-09-10_fis1_001.jpg",
        "2026-09-10_fis1_002.jpg",
    ]
    fontes = dict(conectar().execute("SELECT nome_final, data_fonte FROM arquivos").fetchall())
    assert fontes["2026-09-03_fis1_002.jpg"] == "escrita_reconciliada"
    assert fontes["2026-08-20_fis1_001.jpg"] == "escrita"
    assert not any(n.startswith("2026-09-13") for n in ingeridas)


def test_foto_com_data_ambigua_fica_no_inbox(fis1_terca_quinta, tmp_path):
    """Depois de movida e sem EXIF não há como decidir: a foto não sai do lugar."""
    inbox = tmp_path / "estudos" / "inbox" / "FIS1"
    folha = _foto(inbox / "folha.jpg", "2026:09:13 13:57:10")

    ingeridas = varrer_inbox(ler_escrita=lambda _: date(2026, 9, 2))

    assert ingeridas == []
    assert folha.exists()


def test_pasta_de_data_e_varrida_e_nao_e_denunciada_como_esquecida(fis1_terca_quinta, tmp_path):
    inbox = tmp_path / "estudos" / "inbox" / "FIS1"
    _foto(inbox / "2026-08-20" / "folha.jpg", "2026:09:13 13:56:55")

    ingeridas = varrer_inbox(ler_escrita=_leitor_que_falha)

    assert ingeridas == ["2026-08-20_fis1_001.jpg"]


def test_data_vem_do_texto_transcrito_e_nao_do_campo_do_modelo():
    """O Haiku transcreveu `09.09.26` e devolveu `2026-09-08`. Vale o que foi transcrito."""
    from projetos.estudos.datacao import data_do_texto_lido

    assert data_do_texto_lido("09.09.26") == date(2026, 9, 9)
    assert data_do_texto_lido("FIS1 02.09.26") == date(2026, 9, 2)
    assert data_do_texto_lido("10/9/2026") == date(2026, 9, 10)
    assert data_do_texto_lido("sem data") is None
    assert data_do_texto_lido("31.02.26") is None
