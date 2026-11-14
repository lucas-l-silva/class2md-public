import pytest

from core.agents.base import Agente


@pytest.fixture
def sem_cache_llm(monkeypatch):
    """Força cache-MISS em toda chamada de Agente.run() durante o teste.

    Testes de integração/ciclo mockam o cliente LLM (`core.agents.base.chamar_estruturado`)
    com uma fila de `side_effect`, mas o cache do Agente fica acima do cliente: um cache-hit
    (por conteúdo repetido entre passos do pipeline) pula a chamada e desalinha a fila de
    mocks silenciosamente. Esta fixture elimina essa classe de confound sem exigir que cada
    teste arme entradas artificialmente distintas. A gravação do cache não é afetada.
    """
    monkeypatch.setattr(Agente, "_ler_cache", lambda self, chave: None)


@pytest.fixture(autouse=True)
def _dados_isolados(monkeypatch, tmp_path):
    """Nenhum teste escreve no ~/agent-data real.

    Sem isto, um teste que só sobrescreve AGENT_DATA_DIR deixa LOGS_DIR e CACHE_DIR
    apontando para os diretórios de verdade — e a suíte acaba gravando eventos no log
    do usuário. Roda antes das fixtures de cada arquivo, que continuam podendo apontar
    para onde quiserem.
    """
    padrao = tmp_path / "_isolado"
    for variavel in ("AGENT_DATA_DIR", "STAGING_DIR", "CACHE_DIR", "LOGS_DIR"):
        destino = padrao if variavel == "AGENT_DATA_DIR" else padrao / variavel.lower()
        destino.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(variavel, str(destino))
