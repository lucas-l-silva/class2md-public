"""Enriquecer uma nota já pronta com material que chegou depois.

A lista de exercícios sai depois da aula, os slides do professor são publicados na
semana seguinte, a foto da monitoria é de sexta. A nota já está escrita, validada e
possivelmente já promovida — reprocessá-la do zero jogaria fora trabalho bom e
gastaria visão de novo em todas as fotos.

O enriquecimento reescreve **apenas** as seções que o material novo pode melhorar,
pelo mesmo mecanismo cirúrgico do `preencher-lacunas` (`remendo_nota`). Tudo o mais
sai byte a byte igual.

Idempotente por hash das fontes: rodar de novo com o mesmo material não gasta API.
Material novo muda o hash, e aí sim vale reescrever — é o "processar novamente
quando tratar do mesmo tópico".
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from core.fileops import escrever_texto, ler_texto
from core.logging import registrar_evento
from projetos.estudos.agentes import AgenteEnriquecedor
from projetos.estudos.biblioteca import (
    LIMITE_CHARS_MATERIAIS,
    fontes_antigas_por_topico,
    fontes_da_aula,
)
from projetos.estudos.fontes import resumo, truncar
from projetos.estudos.manifesto import ler_entrada_manifesto, registrar_nota_manifesto
from projetos.estudos.programa import aula_por_numero
from projetos.estudos.programa import carregar as carregar_programa
from projetos.estudos.remendo_nota import SecaoAusente, substituir_secao
from projetos.estudos.schemas import EntradaEnriquecedor, SaidaEnriquecedor

#: seção da nota ← campo da saída do agente
SECOES = (
    ("Exercícios relacionados", "secao_exercicios"),
    ("Do livro", "secao_do_livro"),
    ("Pontos sinalizados como difícil", "secao_pontos_dificeis"),
    ("Pontos de atenção do professor", "secao_pontos_atencao"),
)


class SemMaterialNovo(Exception):
    pass


class NotaNaoEncontrada(Exception):
    pass


@dataclass
class ResultadoEnriquecimento:
    caminho_nota: Path
    secoes_alteradas: list[str] = field(default_factory=list)
    fontes_usadas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    ja_estava_em_dia: bool = False


def hash_das_fontes(nomes: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(nomes)).encode("utf-8")).hexdigest()[:16]


def montar_fontes(disciplina: str, numero_aula: int, titulo_nota: str):
    """Material da aula + material antigo do mesmo assunto, na ordem de prioridade."""
    programa = carregar_programa(disciplina)
    aula = aula_por_numero(programa, numero_aula) if programa else None
    topicos = aula.topicos if aula else []

    fontes = fontes_da_aula(disciplina, numero_aula)
    fontes += fontes_antigas_por_topico(disciplina, titulo_nota, topicos)
    return truncar(fontes, LIMITE_CHARS_MATERIAIS)


def aplicar(markdown: str, saida: SaidaEnriquecedor) -> tuple[str, list[str]]:
    """Reescreve só as seções que vieram preenchidas. Devolve (markdown, alteradas)."""
    resultado = markdown
    alteradas = []
    for prefixo, campo in SECOES:
        corpo = getattr(saida, campo).strip()
        if not corpo:
            continue  # seção vazia = "não tenho o que melhorar", e não é tocada
        try:
            resultado = substituir_secao(resultado, prefixo, f"\n{corpo}\n\n")
        except SecaoAusente:
            continue
        alteradas.append(prefixo)
    return resultado, alteradas


def enriquecer(job_id: str, job, forcar: bool = False) -> ResultadoEnriquecimento:
    """Enriquece a nota de um job concluído com o material disponível hoje."""
    entrada_manifesto = ler_entrada_manifesto(job["id"])
    if entrada_manifesto is None:
        raise NotaNaoEncontrada(f"job {job['id'][:8]} não tem entrada no manifesto")

    caminho_nota = Path(entrada_manifesto["caminho_nota"])
    markdown = ler_texto(caminho_nota)
    titulo_nota = next(
        (linha[2:].strip() for linha in markdown.splitlines() if linha.startswith("# ")),
        caminho_nota.stem,
    )

    numero_aula = job["numero_aula"]
    if numero_aula is None:
        raise SemMaterialNovo(
            f"job {job['id'][:8]} não está vinculado a uma aula — "
            "a nota precisa ter sido gerada com a aula identificada"
        )

    fontes, avisos = montar_fontes(job["disciplina"], numero_aula, titulo_nota)
    if not fontes:
        raise SemMaterialNovo(
            f"nenhum material novo para a aula {numero_aula:02d} de {job['disciplina']}"
        )

    nomes = [fonte.trecho.arquivo for fonte in fontes]
    hash_atual = hash_das_fontes(nomes)
    if not forcar and entrada_manifesto.get("hash_enriquecimento") == hash_atual:
        return ResultadoEnriquecimento(
            caminho_nota=caminho_nota,
            fontes_usadas=nomes,
            avisos=avisos,
            ja_estava_em_dia=True,
        )

    saida = AgenteEnriquecedor().run(
        job_id,
        EntradaEnriquecedor(
            disciplina=job["disciplina"],
            titulo_nota=titulo_nota,
            markdown_nota=markdown,
            trechos=[fonte.trecho for fonte in fontes],
        ),
    )

    novo_markdown, alteradas = aplicar(markdown, saida)
    if alteradas:
        escrever_texto(caminho_nota, novo_markdown)

    registrar_nota_manifesto(
        job["id"],
        caminho_nota,
        entrada_manifesto.get("status", "concluido"),
        entrada_manifesto.get("fotos", []),
        entrada_manifesto.get("criado_em", ""),
        conceitos_novos=entrada_manifesto.get("conceitos_novos"),
        duvidas=entrada_manifesto.get("duvidas"),
        secao_do_livro=saida.secao_do_livro or entrada_manifesto.get("secao_do_livro"),
        hash_enriquecimento=hash_atual,
    )
    registrar_evento(
        job=job_id,
        passo="enriquecedor",
        resultado=f"{caminho_nota.name}: {len(alteradas)} seção(ões)",
    )

    return ResultadoEnriquecimento(
        caminho_nota=caminho_nota,
        secoes_alteradas=alteradas,
        fontes_usadas=saida.fontes_usadas or nomes,
        avisos=avisos + ([f"ordem das fontes:\n{resumo(fontes)}"] if fontes else []),
    )
