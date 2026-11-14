import pytest

from core.config import get_settings
from core.fileops import (
    CaminhoForaDaAllowlist,
    _validar,
    escrever,
    escrever_texto,
    ler,
    ler_texto,
    listar,
    mover,
    remover,
)


@pytest.fixture
def settings_isolado(monkeypatch, tmp_path):
    agent_data_dir = tmp_path / "agent-data"
    staging_dir = agent_data_dir / "estudos" / "output"
    cache_dir = tmp_path / "cache"
    logs_dir = tmp_path / "logs"

    for base in (agent_data_dir, staging_dir, cache_dir, logs_dir):
        base.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-para-teste")
    monkeypatch.setenv("AGENT_DATA_DIR", str(agent_data_dir))
    monkeypatch.setenv("STAGING_DIR", str(staging_dir))
    monkeypatch.setenv("CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("LOGS_DIR", str(logs_dir))

    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def fora(tmp_path_factory):
    return tmp_path_factory.mktemp("fora-da-allowlist")


# --- caso base: escrever + ler dentro da allowlist ---


def test_escrever_e_ler_dentro_da_allowlist(settings_isolado):
    caminho = settings_isolado.allowlist_dirs[0] / "nota.txt"

    escrever(caminho, b"conteudo binario", settings=settings_isolado)
    assert ler(caminho, settings=settings_isolado) == b"conteudo binario"


def test_escrever_texto_e_ler_texto_dentro_da_allowlist(settings_isolado):
    caminho = settings_isolado.allowlist_dirs[0] / "nota.md"

    escrever_texto(caminho, "olá, mundo", settings=settings_isolado)
    assert ler_texto(caminho, settings=settings_isolado) == "olá, mundo"


# --- as 4 operações, fora da allowlist ---


def test_ler_fora_da_allowlist_levanta(settings_isolado, fora):
    with pytest.raises(CaminhoForaDaAllowlist):
        ler(fora / "segredo.bin", settings=settings_isolado)


def test_ler_texto_fora_da_allowlist_levanta(settings_isolado, fora):
    with pytest.raises(CaminhoForaDaAllowlist):
        ler_texto(fora / "segredo.txt", settings=settings_isolado)


def test_escrever_fora_da_allowlist_levanta_e_nao_cria_arquivo(settings_isolado, fora):
    alvo = fora / "vazamento.bin"

    with pytest.raises(CaminhoForaDaAllowlist):
        escrever(alvo, b"dado", settings=settings_isolado)

    assert not alvo.exists()


def test_escrever_texto_fora_da_allowlist_levanta_e_nao_cria_arquivo(settings_isolado, fora):
    alvo = fora / "vazamento.md"

    with pytest.raises(CaminhoForaDaAllowlist):
        escrever_texto(alvo, "dado", settings=settings_isolado)

    assert not alvo.exists()


# --- mover ---


def test_mover_dentro_da_allowlist(settings_isolado):
    origem = settings_isolado.allowlist_dirs[0] / "origem.md"
    destino = settings_isolado.allowlist_dirs[1] / "destino.md"

    escrever_texto(origem, "conteudo", settings=settings_isolado)
    mover(origem, destino, settings=settings_isolado)

    assert not origem.exists()
    assert ler_texto(destino, settings=settings_isolado) == "conteudo"


def test_mover_com_destino_fora_da_allowlist_levanta(settings_isolado, fora):
    origem = settings_isolado.allowlist_dirs[0] / "origem.md"
    escrever_texto(origem, "conteudo", settings=settings_isolado)

    with pytest.raises(CaminhoForaDaAllowlist):
        mover(origem, fora / "exfiltrado.md", settings=settings_isolado)

    assert origem.exists()


def test_mover_com_origem_fora_da_allowlist_levanta(settings_isolado, fora):
    origem = fora / "origem.md"
    origem.write_text("conteudo", encoding="utf-8")
    destino = settings_isolado.allowlist_dirs[0] / "destino.md"

    with pytest.raises(CaminhoForaDaAllowlist):
        mover(origem, destino, settings=settings_isolado)

    assert not destino.exists()


# --- listar ---


def test_listar_dentro_da_allowlist(settings_isolado):
    base = settings_isolado.allowlist_dirs[0]
    escrever_texto(base / "a.md", "1", settings=settings_isolado)
    escrever_texto(base / "b.md", "2", settings=settings_isolado)

    resultado = listar(base, "*.md", settings=settings_isolado)

    assert {p.name for p in resultado} == {"a.md", "b.md"}


def test_listar_fora_da_allowlist_levanta(settings_isolado, fora):
    with pytest.raises(CaminhoForaDaAllowlist):
        listar(fora, settings=settings_isolado)


def test_remover_dentro_da_allowlist(settings_isolado):
    base = settings_isolado.allowlist_dirs[0]
    caminho = base / "descartavel.md"
    escrever_texto(caminho, "x", settings=settings_isolado)

    remover(caminho, settings=settings_isolado)

    assert not caminho.exists()


def test_remover_arquivo_inexistente_nao_levanta(settings_isolado):
    base = settings_isolado.allowlist_dirs[0]
    remover(base / "nao_existe.md", settings=settings_isolado)  # não levanta


def test_remover_fora_da_allowlist_levanta_e_nao_apaga(settings_isolado, fora):
    caminho = fora / "protegido.md"
    caminho.write_text("importante")

    with pytest.raises(CaminhoForaDaAllowlist):
        remover(caminho, settings=settings_isolado)

    assert caminho.exists()


# --- os dois casos de aprendizado: por que resolve() é essencial ---


def test_path_traversal_com_dotdot_e_bloqueado(settings_isolado, fora):
    base = settings_isolado.allowlist_dirs[0]
    alvo_real = fora / "etc" / "passwd"
    alvo_real.parent.mkdir(parents=True, exist_ok=True)
    alvo_real.write_text("root:x:0:0", encoding="utf-8")

    # calcula quantos ".." levam de `base` até a raiz de `fora`, e monta um
    # caminho cuja STRING começa com o prefixo da allowlist (um startswith
    # ingênuo passaria), mas que na verdade escapa via "..".
    partes_ate_raiz = [".."] * len(base.parts[1:])
    caminho_com_traversal = base.joinpath(*partes_ate_raiz, *alvo_real.parts[1:])

    assert str(caminho_com_traversal).startswith(str(base))  # prova: startswith enganaria

    with pytest.raises(CaminhoForaDaAllowlist):
        _validar(caminho_com_traversal, settings_isolado)


def test_symlink_apontando_para_fora_e_bloqueado(settings_isolado, fora):
    alvo_real = fora / "chaves_privadas"
    alvo_real.mkdir()

    atalho = settings_isolado.allowlist_dirs[0] / "atalho"
    atalho.parent.mkdir(parents=True, exist_ok=True)
    atalho.symlink_to(alvo_real, target_is_directory=True)

    assert str(atalho).startswith(str(settings_isolado.allowlist_dirs[0]))  # nominalmente "dentro"

    with pytest.raises(CaminhoForaDaAllowlist):
        _validar(atalho, settings_isolado)
