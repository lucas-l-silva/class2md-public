import pytest
from apoio_interface import CHAVE_DE_TESTE, PORTA, TOKEN, chamar, foto, multipart  # noqa: F401

from core.config import Settings, get_settings
from ui.app import criar_app


@pytest.fixture(autouse=True)
def _ambiente_da_ui(monkeypatch, tmp_path):
    dados = tmp_path / "dados"
    dados.mkdir()
    monkeypatch.setenv("AGENT_DATA_DIR", str(dados))
    monkeypatch.setenv("ANTHROPIC_API_KEY", CHAVE_DE_TESTE)
    monkeypatch.delenv("CLASS2MD_API_TOKEN", raising=False)
    monkeypatch.delenv("STAGING_DIR", raising=False)  # staging real: estudos/output
    monkeypatch.setitem(Settings.model_config, "env_file", ())
    get_settings.cache_clear()
    yield dados
    get_settings.cache_clear()


@pytest.fixture
def dados(_ambiente_da_ui):
    return _ambiente_da_ui


@pytest.fixture
def app():
    return criar_app(porta=PORTA, token=TOKEN)


@pytest.fixture
def enviar(app):
    def _enviar(disciplina="ABC1", fotos=None, envio_id=None):
        fotos = fotos if fotos is not None else [("a.jpg", foto())]
        campos = {"disciplina": disciplina}
        if envio_id:
            campos["envio_id"] = envio_id
        tipo, corpo = multipart(campos, fotos)
        return chamar(app, "POST", "/api/materiais", corpo, tipo)

    return _enviar
