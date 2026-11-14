"""A ementa da disciplina como dado estruturado, montada de forma incremental.

A informação de ementa não chega de uma vez nem de uma fonte só: parte vem do
manuscrito da primeira aula, parte de um PDF de plano de ensino, parte de um
slide mostrado no meio do semestre. Por isso a ementa é **acumulada**: cada
rodada acrescenta o que é novo e nunca apaga o que já estava lá.

Persistida em `estudos/index/<SIGLA>/ementa.json`.
"""

import json
import re
import unicodedata
from pathlib import Path

from core.config import get_settings
from core.fileops import escrever_texto, ler_texto
from core.logging import registrar_evento
from projetos.estudos.agentes import AgenteEmenta
from projetos.estudos.schemas import Ementa, EntradaEmenta, FonteEmenta

NOME_ARQUIVO = "ementa.json"

# Credencial vista numa foto não vira registro. A senha do WiFi do departamento estava
# numa placa da sala e foi parar nas observações da ementa: não é segredo do usuário, mas
# é material de credencial, e o lugar dele não é um arquivo versionável de estudo. O
# filtro é em código porque é regra de segurança — pedir no prompt não garante.
_RE_CREDENCIAL = re.compile(
    r"\b(senha|password|passwd|ssid|wi-?fi|token|api[_ -]?key|credencia|login\s*:|usu[áa]rio\s*:)\b",
    re.IGNORECASE,
)

_CAMPOS_DE_LISTA = (
    "docentes",
    "partes",
    "avaliacao",
    "pesos",
    "bibliografia_basica",
    "bibliografia_complementar",
    "cronograma",
    "monitoria",
    "links",
    "observacoes",
)


def caminho_ementa(disciplina: str) -> Path:
    return get_settings().agent_data_dir / "estudos" / "index" / disciplina / NOME_ARQUIVO


def carregar(disciplina: str) -> Ementa | None:
    try:
        conteudo = ler_texto(caminho_ementa(disciplina))
    except FileNotFoundError:
        return None
    return Ementa.model_validate(json.loads(conteudo))


def salvar(ementa: Ementa) -> Path:
    caminho = caminho_ementa(ementa.disciplina)
    escrever_texto(
        caminho,
        json.dumps(ementa.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
    )
    return caminho


def parece_credencial(texto: str) -> bool:
    return bool(_RE_CREDENCIAL.search(texto))


def _texto_do_item(item) -> str:
    if hasattr(item, "texto"):
        return item.texto
    if hasattr(item, "titulo"):
        return item.titulo
    return f"{item.periodo} {item.conteudo}"


def sem_credenciais(ementa: Ementa) -> tuple[Ementa, int]:
    """Remove itens que parecem credencial. Devolve (ementa, quantos saíram)."""
    removidos = 0
    atualizacoes = {}
    for campo in _CAMPOS_DE_LISTA:
        itens = getattr(ementa, campo)
        mantidos = [item for item in itens if not parece_credencial(_texto_do_item(item))]
        removidos += len(itens) - len(mantidos)
        atualizacoes[campo] = mantidos
    return ementa.model_copy(update=atualizacoes), removidos


def _chave(item) -> str:
    """Identidade de um item para deduplicação: o texto que o humano leria."""
    if hasattr(item, "texto"):
        bruto = item.texto
    elif hasattr(item, "titulo"):
        bruto = f"{item.numero}|{item.titulo}"
    else:
        bruto = f"{item.periodo}|{item.conteudo}"
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", bruto) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).strip()


def mesclar(antiga: Ementa | None, nova: Ementa) -> Ementa:
    """Acumula `nova` sobre `antiga` sem perder nada do que já estava confirmado.

    Item repetido (mesmo texto, ignorando acento e caixa) não duplica; item novo entra
    no fim, preservando a ordem em que a informação foi aparecendo. Título e código só
    são preenchidos se ainda estiverem vazios — o primeiro valor confirmado vence, para
    que uma extração pior não sobrescreva uma melhor.
    """
    if antiga is None:
        return nova

    atualizacoes: dict = {
        "disciplina": antiga.disciplina or nova.disciplina,
        "titulo_oficial": antiga.titulo_oficial or nova.titulo_oficial,
        "codigo": antiga.codigo or nova.codigo,
        "confianca": min(antiga.confianca, nova.confianca),
    }
    for campo in _CAMPOS_DE_LISTA:
        acumulado = list(getattr(antiga, campo))
        vistos = {_chave(item) for item in acumulado}
        for item in getattr(nova, campo):
            chave = _chave(item)
            if chave and chave not in vistos:
                acumulado.append(item)
                vistos.add(chave)
        atualizacoes[campo] = acumulado

    return antiga.model_copy(update=atualizacoes)


def resumo_textual(ementa: Ementa | None) -> str:
    """O que já se sabe, em texto curto, para o agente não repetir o que já existe."""
    if ementa is None:
        return "(nada extraído ainda)"
    linhas = []
    if ementa.titulo_oficial:
        linhas.append(f"titulo_oficial: {ementa.titulo_oficial}")
    if ementa.codigo:
        linhas.append(f"codigo: {ementa.codigo}")
    for campo in _CAMPOS_DE_LISTA:
        itens = getattr(ementa, campo)
        if not itens:
            continue
        linhas.append(f"{campo}:")
        for item in itens:
            if hasattr(item, "texto"):
                linhas.append(f"  - {item.texto}")
            elif hasattr(item, "titulo"):
                linhas.append(f"  - {item.numero}. {item.titulo}")
            else:
                linhas.append(f"  - {item.periodo}: {item.conteudo}")
    return "\n".join(linhas) or "(nada extraído ainda)"


def atualizar(job_id: str, disciplina: str, fontes: list[FonteEmenta]) -> Ementa | None:
    """Roda o AgenteEmenta sobre as fontes e acumula o resultado. Sem fontes, não gasta API."""
    if not fontes:
        return carregar(disciplina)

    atual = carregar(disciplina)
    extraida = AgenteEmenta().run(
        job_id,
        EntradaEmenta(
            disciplina=disciplina,
            ementa_atual=resumo_textual(atual),
            fontes=fontes,
        ),
    )
    extraida, credenciais = sem_credenciais(extraida)
    if credenciais:
        registrar_evento(
            job=job_id,
            passo="ementa",
            resultado="credencial_descartada",
            aviso=f"{credenciais} item(ns) com aparência de credencial não foram registrados",
        )

    mesclada = mesclar(atual, extraida)
    salvar(mesclada)
    registrar_evento(
        job=job_id,
        passo="ementa",
        resultado=f"{disciplina}: {sum(len(getattr(mesclada, c)) for c in _CAMPOS_DE_LISTA)} itens",
    )
    return mesclada
