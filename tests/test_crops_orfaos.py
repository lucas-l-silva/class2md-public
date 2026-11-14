import pytest

from core.config import get_settings
from projetos.estudos.crops_orfaos import (
    inventariar,
    mover_para_trash,
    nomes_referenciados,
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
    (raiz / "crops" / "MAT1").mkdir(parents=True)
    (raiz / "output" / "MAT1").mkdir(parents=True)
    return raiz


def _crop(estudos, nome, disciplina="MAT1"):
    caminho = estudos / "crops" / disciplina / nome
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"\x89PNG fake")
    return caminho


def _nota(estudos, nome, corpo, pasta="output"):
    caminho = estudos / pasta / "MAT1" / nome
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(corpo, encoding="utf-8")
    return caminho


def test_separa_usados_de_orfaos(estudos):
    _crop(estudos, "usado_crop01.png")
    _crop(estudos, "orfao_crop02.png")
    _nota(estudos, "aula.md", "Texto\n\n![[usado_crop01.png]]\n")

    inventario = inventariar()

    assert [p.name for p in inventario.usados] == ["usado_crop01.png"]
    assert [p.name for p in inventario.orfaos] == ["orfao_crop02.png"]


def test_nota_ja_promovida_protege_o_recorte(estudos):
    """Promovida é nota que já foi para o vault: apagar o recorte dela quebraria
    exatamente as notas que você já revisou."""
    (estudos / "promovidas" / "MAT1").mkdir(parents=True)
    _crop(estudos, "so_na_promovida_crop01.png")
    _nota(estudos, "aula-antiga.md", "![[so_na_promovida_crop01.png]]", pasta="promovidas")

    assert inventariar().orfaos == []


def test_reconhece_as_duas_sintaxes_de_imagem(estudos):
    _crop(estudos, "wiki_crop01.png")
    _crop(estudos, "md_crop02.png")
    _nota(
        estudos,
        "aula.md",
        "![[wiki_crop01.png|300]]\n\n![quadro](crops/MAT1/md_crop02.png)\n",
    )

    assert inventariar().orfaos == []


def test_move_para_trash_sem_apagar(estudos):
    orfao = _crop(estudos, "orfao_crop01.png")

    pasta = mover_para_trash([orfao])

    assert not orfao.exists()
    movido = pasta / "crops" / "MAT1" / "orfao_crop01.png"
    assert movido.exists()
    assert movido.read_bytes() == b"\x89PNG fake"


def test_trash_explica_o_que_foi_movido(estudos):
    """Uma pasta de PNGs com carimbo de data não diz nada meses depois."""
    pasta = mover_para_trash([_crop(estudos, "orfao_crop01.png")])

    readme = (pasta / "README.md").read_text(encoding="utf-8")

    assert "nenhuma nota referencia" in readme
    assert "MAT1/orfao_crop01.png" in readme
    assert "mover de volta" in readme


def test_filtra_por_disciplina(estudos):
    _crop(estudos, "mat1_crop01.png", "MAT1")
    _crop(estudos, "fis1_crop01.png", "FIS1")

    assert [p.name for p in inventariar("FIS1").orfaos] == ["fis1_crop01.png"]


def test_sem_notas_nada_e_considerado_usado(estudos):
    _crop(estudos, "a_crop01.png")

    assert nomes_referenciados() == set()
    assert len(inventariar().orfaos) == 1
