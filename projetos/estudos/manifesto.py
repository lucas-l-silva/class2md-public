import json
from pathlib import Path

from core.config import get_settings
from core.fileops import escrever_texto, ler_texto


def _caminho_manifesto() -> Path:
    return get_settings().agent_data_dir / "estudos" / "output" / "_manifest.json"


def _ler_manifesto() -> dict:
    try:
        conteudo = ler_texto(_caminho_manifesto())
    except FileNotFoundError:
        return {}
    return json.loads(conteudo)


def ler_entrada_manifesto(job_id: str) -> dict | None:
    return _ler_manifesto().get(job_id)


def registrar_nota_manifesto(
    job_id: str,
    caminho_nota: Path,
    status: str,
    fotos: list[str],
    criado_em: str,
    pergunta: str | None = None,
    conceitos_novos: list[str] | None = None,
    duvidas: list[str] | None = None,
    precisa_revisao: bool = False,
    problemas_validacao: list[str] | None = None,
    avisos_conceitos: list[str] | None = None,
    possivel_injecao: bool = False,
    secao_do_livro: str | None = None,
    hash_enriquecimento: str | None = None,
) -> None:
    # Padrão ler-modificar-escrever, sem lock próprio: duas chamadas concorrentes podem
    # se sobrescrever (lost update — não corrompe o JSON, mas uma das duas some em
    # silêncio). Só é seguro porque o P0.4 já garante um único escritor via
    # core.estado.lock_runner() — esta função nunca deve ser chamada fora dele.
    manifesto = _ler_manifesto()
    entrada = {
        "caminho_nota": str(caminho_nota),
        "status": status,
        "fotos": fotos,
        "criado_em": criado_em,
    }
    if pergunta is not None:
        entrada["pergunta"] = pergunta
    if conceitos_novos is not None:
        entrada["conceitos_novos"] = conceitos_novos
    if duvidas is not None:
        entrada["duvidas"] = duvidas
    if precisa_revisao:
        entrada["precisa_revisao"] = True
    if problemas_validacao is not None:
        entrada["problemas_validacao"] = problemas_validacao
    if avisos_conceitos:
        entrada["avisos_conceitos"] = avisos_conceitos
    if possivel_injecao:
        entrada["possivel_injecao"] = True
    if secao_do_livro:
        entrada["secao_do_livro"] = secao_do_livro
    if hash_enriquecimento:
        # o que já foi enriquecido não é reescrito de graça: material novo muda o hash
        entrada["hash_enriquecimento"] = hash_enriquecimento
    manifesto[job_id] = entrada
    escrever_texto(_caminho_manifesto(), json.dumps(manifesto, ensure_ascii=False, indent=2))
