from pathlib import Path

import pytest
from PIL import Image

from core.config import get_settings
from core.estado import criar_job, registrar_arquivo, transicionar
from projetos.estudos.ingestao import (
    fotos_ja_processadas,
    mover_fotos_processadas,
    sha256_de,
)


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
def estudos(tmp_path):
    raiz = tmp_path / "estudos"
    (raiz / "inbox" / "MAT1").mkdir(parents=True)
    (raiz / "processed" / "MAT1").mkdir(parents=True)
    return raiz


def _foto(caminho: Path, cor="blue") -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), color=cor).save(caminho)
    return caminho


def _processada(estudos, nome="IMG_1.JPG", status="concluido", com_copia=True):
    """Foto no inbox, registrada, com job concluído e cópia normalizada em processed/."""
    origem = _foto(estudos / "inbox" / "MAT1" / nome)
    job_id = criar_job("aula", disciplina="MAT1", data="2026-08-10")
    transicionar(job_id, "rodando")
    transicionar(job_id, status if status != "rodando" else "concluido")
    registrar_arquivo(sha256_de(origem), "2026-08-10_mat1_001.jpg", "MAT1", "2026-08-10", job_id)
    if com_copia:
        _foto(estudos / "processed" / "MAT1" / "2026-08-10_mat1_001.jpg", cor="red")
    return origem


def test_foto_processada_e_detectada(estudos):
    origem = _processada(estudos)

    prontas = fotos_ja_processadas()

    assert [c for c, _ in prontas] == [origem]


def test_foto_sem_copia_em_processed_nao_e_movida(estudos):
    """O inbox pode ser a única cópia que resta — tirá-la cedo é irrecuperável."""
    _processada(estudos, com_copia=False)

    assert fotos_ja_processadas() == []


def test_foto_de_job_nao_concluido_fica(estudos):
    origem = _foto(estudos / "inbox" / "MAT1" / "IMG_2.JPG")
    job_id = criar_job("aula", disciplina="MAT1", data="2026-08-11")
    registrar_arquivo(sha256_de(origem), "2026-08-11_mat1_001.jpg", "MAT1", "2026-08-11", job_id)
    _foto(estudos / "processed" / "MAT1" / "2026-08-11_mat1_001.jpg")

    assert fotos_ja_processadas() == []  # job ainda em na_fila


def test_foto_nunca_ingerida_fica(estudos):
    _foto(estudos / "inbox" / "MAT1" / "IMG_NOVA.JPG")

    assert fotos_ja_processadas() == []


def test_pdf_nunca_entra_na_limpeza(estudos):
    """Para o PDF o inbox é o lugar definitivo: o registro aponta para lá."""
    (estudos / "inbox" / "MAT1" / "pdfs").mkdir(parents=True)
    (estudos / "inbox" / "MAT1" / "pdfs" / "aula01.pdf").write_bytes(b"%PDF-1.4")

    assert fotos_ja_processadas() == []


def test_mover_preserva_a_arvore_e_explica(estudos):
    origem = _processada(estudos)

    pasta = mover_fotos_processadas([origem])

    assert not origem.exists()
    assert (pasta / "inbox" / "MAT1" / "IMG_1.JPG").exists()
    readme = (pasta / "README.md").read_text(encoding="utf-8")
    assert "MAT1/IMG_1.JPG" in readme
    assert "não apagadas" in readme


def test_foto_de_job_parcial_fica_no_inbox(estudos):
    """Job que parou antes da nota ainda vai ser retomado: a foto não pode sair."""
    _processada(estudos, status="parcial")

    assert fotos_ja_processadas() == []
