"""Compromissos com data, extraídos das aulas e confirmados pelo humano.

Uma data lida errado num manuscrito ("31/08" que na verdade era "3/08") polui o
calendário de forma difícil de perceber — o erro só aparece no dia da prova. Por
isso todo compromisso nasce `proposto` e só entra no calendário depois de
`agenda confirmar`, com o trecho de origem citado para você conferir.

Os guardrails ficam aqui, em código, não no prompt:

1. **Citação literal**: `origem_trecho` tem de aparecer no texto-fonte. Se o modelo
   parafraseou, não dá para você auditar a proposta — então ela é descartada.
2. **Janela de data**: uma data resolvida muito longe da aula é quase sempre erro de
   leitura ou de resolução de referência relativa.
3. **Deduplicação por chave**: a mesma aula reprocessada não gera linhas novas, e o
   status que você já decidiu nunca é sobrescrito.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core.estado import (
    listar_compromissos,
    mudar_status_compromisso,
    registrar_compromisso,
)
from core.logging import registrar_evento
from projetos.estudos.agentes import AgenteCompromissos
from projetos.estudos.schemas import CompromissoExtraido, EntradaCompromissos

#: quanto antes/depois da aula uma data ainda é plausível. Prova marcada para antes
#: da aula em que foi anunciada é erro; mais de um ano depois, também.
DIAS_ANTES_MAX = 60
DIAS_DEPOIS_MAX = 365

_RE_ESPACO = re.compile(r"\s+")


class DataImplausivel(Exception):
    pass


@dataclass
class ResultadoExtracao:
    propostos: list[str]
    descartados: list[tuple[str, str]]  # (titulo, motivo)


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return _RE_ESPACO.sub(" ", sem_acento.lower()).strip()


def chave_de(disciplina: str, tipo: str, data: str | None, titulo: str) -> str:
    bruto = f"{disciplina}|{tipo}|{data or ''}|{_normalizar(titulo)}"
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:16]


def trecho_e_literal(trecho: str, texto_fonte: str) -> bool:
    """O trecho citado aparece mesmo no material?

    Comparação tolerante a espaçamento e acentuação (a extração normaliza o texto),
    mas não a reescrita: o objetivo é garantir que você consiga achar a frase no
    material original ao conferir a proposta.
    """
    if not trecho.strip():
        return False
    return _normalizar(trecho) in _normalizar(texto_fonte)


def data_plausivel(data_iso: str | None, ancora: str) -> bool:
    if data_iso is None:
        return True  # compromisso só recorrente, sem data única
    try:
        alvo = date.fromisoformat(data_iso)
        base = date.fromisoformat(ancora)
    except ValueError:
        return False
    return -DIAS_ANTES_MAX <= (alvo - base).days <= DIAS_DEPOIS_MAX


def _validar(compromisso: CompromissoExtraido, ancora: str, texto_fonte: str) -> str | None:
    """Motivo de descarte, ou None se o compromisso passa."""
    if not trecho_e_literal(compromisso.origem_trecho, texto_fonte):
        return "origem_trecho não aparece literalmente no material"
    if not data_plausivel(compromisso.data, ancora):
        return f"data {compromisso.data} fora da janela plausível em torno de {ancora}"
    if compromisso.data is None and not compromisso.recorrencia:
        return "sem data e sem recorrência"
    return None


def extrair(job_id: str, disciplina: str, data_ancora: str, texto_fonte: str) -> ResultadoExtracao:
    """Propõe compromissos a partir do material administrativo de uma aula.

    Texto vazio não gasta API. Nenhum compromisso é confirmado aqui.
    """
    resultado = ResultadoExtracao(propostos=[], descartados=[])
    if not texto_fonte.strip():
        return resultado

    saida = AgenteCompromissos().run(
        job_id,
        EntradaCompromissos(disciplina=disciplina, data_ancora=data_ancora, texto=texto_fonte),
    )

    for compromisso in saida.compromissos:
        motivo = _validar(compromisso, data_ancora, texto_fonte)
        if motivo:
            resultado.descartados.append((compromisso.titulo, motivo))
            registrar_evento(
                job=job_id,
                passo="compromissos",
                resultado="descartado",
                aviso=f"{compromisso.titulo}: {motivo}",
            )
            continue

        id_compromisso = registrar_compromisso(
            chave=chave_de(disciplina, compromisso.tipo, compromisso.data, compromisso.titulo),
            disciplina=disciplina,
            tipo=compromisso.tipo,
            titulo=compromisso.titulo,
            data=compromisso.data,
            hora=compromisso.hora,
            recorrencia=compromisso.recorrencia,
            origem_job=job_id,
            origem_trecho=compromisso.origem_trecho,
            confianca=compromisso.confianca,
        )
        resultado.propostos.append(id_compromisso)

    return resultado


def adicionar_manual(
    disciplina: str,
    tipo: str,
    titulo: str,
    data: str | None = None,
    hora: str | None = None,
    recorrencia: str | None = None,
) -> str:
    """Compromisso digitado por você — já nasce confirmado, porque a fonte é você."""
    if data is not None:
        try:
            date.fromisoformat(data)
        except ValueError as erro:
            raise DataImplausivel(f"data inválida: {data} (use AAAA-MM-DD)") from erro

    id_compromisso = registrar_compromisso(
        chave=chave_de(disciplina, tipo, data, titulo),
        disciplina=disciplina,
        tipo=tipo,
        titulo=titulo,
        data=data,
        hora=hora,
        recorrencia=recorrencia,
        origem_trecho="digitado à mão",
        confianca=1.0,
    )
    mudar_status_compromisso(id_compromisso, "confirmado")
    return id_compromisso


def confirmar(id_compromisso: str) -> None:
    mudar_status_compromisso(id_compromisso, "confirmado")


def descartar(id_compromisso: str) -> None:
    mudar_status_compromisso(id_compromisso, "descartado")


def listar(disciplina: str | None = None, status: str | None = None):
    return listar_compromissos(disciplina=disciplina, status=status)


#: aceita a abreviação e o nome por extenso, com e sem acento. O agente grava
#: "semanal-sexta" tanto quanto "semanal-sex", e exigir uma das formas fazia a
#: recorrência silenciosamente não expandir — uma monitoria passou dias assim.
DIAS_DA_SEMANA = {
    "seg": 0,
    "segunda": 0,
    "segunda-feira": 0,
    "ter": 1,
    "terca": 1,
    "terça": 1,
    "terca-feira": 1,
    "terça-feira": 1,
    "qua": 2,
    "quarta": 2,
    "quarta-feira": 2,
    "qui": 3,
    "quinta": 3,
    "quinta-feira": 3,
    "sex": 4,
    "sexta": 4,
    "sexta-feira": 4,
    "sab": 5,
    "sabado": 5,
    "sábado": 5,
    "dom": 6,
    "domingo": 6,
}


def dia_da_semana(texto: str) -> int | None:
    return DIAS_DA_SEMANA.get(texto.strip().lower())


def proximas_ocorrencias(recorrencia: str, inicio: str, quantas: int = 4) -> list[str]:
    """Datas de um compromisso recorrente.

    Formato: "semanal-<dia>" ou "quinzenal-<dia>", com `<dia>` abreviado ou por extenso.
    Recorrência não reconhecida devolve lista vazia em vez de erro — o compromisso
    continua válido, só não se expande sozinho. Quem chama deve **relatar** esse caso:
    degradar em silêncio foi como a monitoria da MAT1 ficou sem aparecer no calendário.
    """
    partes = recorrencia.split("-", 1)
    if len(partes) != 2 or partes[0] not in ("semanal", "quinzenal"):
        return []
    indice_dia = dia_da_semana(partes[1])
    if indice_dia is None:
        return []

    passo = 7 if partes[0] == "semanal" else 14
    try:
        atual = date.fromisoformat(inicio)
    except ValueError:
        return []

    avanco = (indice_dia - atual.weekday()) % 7
    atual = atual + timedelta(days=avanco)
    return [(atual + timedelta(days=passo * i)).isoformat() for i in range(quantas)]


def hoje_iso() -> str:
    return datetime.now().date().isoformat()
