from pathlib import Path

from core.config import get_settings
from core.estado import job_por_id
from core.fileops import escrever_texto, ler_texto
from core.logging import registrar_evento
from projetos.estudos.agentes import AgenteConceito
from projetos.estudos.disciplinas import perfil_de
from projetos.estudos.schemas import EntradaConceito, PaginaConceito

MAX_CONCEITOS_POR_AULA = 5

_MARCADOR_APARECE_EM = "## Aparece em"


def caminho_conceito(disciplina: str, nome_conceito: str) -> Path:
    output_dir = get_settings().agent_data_dir / "estudos" / "output"
    return output_dir / disciplina / "conceitos" / f"{nome_conceito}.md"


def _renderizar(
    pagina: PaginaConceito, nome_conceito: str, disciplina: str, aparece_em: list[str]
) -> str:
    tags = ", ".join(pagina.tags)
    links = "\n".join(f"- [[{nota}]]" for nota in aparece_em)
    return (
        "---\n"
        "tipo: conceito\n"
        f"disciplina: {disciplina}\n"
        f"tags: [{tags}]\n"
        "---\n\n"
        f"# {nome_conceito}\n\n"
        "## Definição formal\n"
        f"{pagina.definicao_formal}\n\n"
        "## Intuição\n"
        f"{pagina.intuicao}\n\n"
        "## Exemplo\n"
        f"{pagina.exemplo}\n\n"
        f"{_MARCADOR_APARECE_EM}\n"
        f"{links}\n"
    )


def _extrair_aparece_em(markdown: str) -> list[str]:
    indice = markdown.find(_MARCADOR_APARECE_EM)
    if indice == -1:
        return []
    bloco = markdown[indice + len(_MARCADOR_APARECE_EM) :]
    notas = []
    for linha in bloco.splitlines():
        linha = linha.strip()
        if linha.startswith("- [[") and linha.endswith("]]"):
            notas.append(linha[4:-2])
    return notas


def _extrair_origem(markdown: str) -> str | None:
    # Decisão 9: metadado de pipeline não vai pro frontmatter (a página fica 100% template
    # ao ser promovida ao vault). A nota de origem nunca precisa de campo próprio: ela é
    # sempre a 1ª entrada de "Aparece em" — só se acrescenta no fim, nunca se reordena.
    aparece_em = _extrair_aparece_em(markdown)
    return aparece_em[0] if aparece_em else None


def _deve_forcar(job_id: str) -> bool:
    job = job_por_id(job_id)
    marca = job["forcar_reprocessamento"] if job is not None else None
    return marca is not None and marca in ("*", AgenteConceito.nome)


def gerar_paginas_conceito(
    job_id: str,
    disciplina: str,
    conceitos_novos: list[str],
    markdown_nota: str,
    nome_nota: str,
) -> list[str]:
    """Cria (ou atualiza o 'Aparece em' de) as páginas de conceito de `conceitos_novos`.

    Teto de MAX_CONCEITOS_POR_AULA chamadas por aula — acima disso o Compositor está
    exagerando; o excesso vira aviso, não é processado. Idempotente por ARQUIVO (não por
    cache do agente): o mesmo conceito citado em notas diferentes teria entradas de cache
    distintas e chamaria o LLM de novo — aqui, se a página já existe, só atualizamos o
    'Aparece em' sem gastar uma chamada nova.

    Sob forcar_reprocessamento (mesma marca que Agente.run já respeita), a página SÓ é
    regerada se `nome_nota` for a ORIGEM registrada nela — uma nota que apenas cita o
    conceito continua só atualizando 'Aparece em', mesmo em force, senão a definição
    flip-flopa a cada nota que cita o mesmo conceito num reprocessamento em lote.
    """
    forcar = _deve_forcar(job_id)
    avisos: list[str] = []
    conceitos = conceitos_novos[:MAX_CONCEITOS_POR_AULA]
    if len(conceitos_novos) > MAX_CONCEITOS_POR_AULA:
        registrar_evento(
            job=job_id,
            passo="conceito",
            resultado="aviso_excesso_conceitos",
            aviso=(
                f"{len(conceitos_novos)} conceitos_novos (> {MAX_CONCEITOS_POR_AULA}) — "
                "Compositor pode estar exagerando; processando só os primeiros "
                f"{MAX_CONCEITOS_POR_AULA}."
            ),
        )

    for nome_conceito in conceitos:
        caminho = caminho_conceito(disciplina, nome_conceito)
        if caminho.exists():
            conteudo = ler_texto(caminho)
            regenerar = forcar and _extrair_origem(conteudo) == nome_nota
            if not regenerar:
                aparece_em = _extrair_aparece_em(conteudo)
                if nome_nota not in aparece_em:
                    aparece_em.append(nome_nota)
                    indice = conteudo.find(_MARCADOR_APARECE_EM)
                    base = conteudo[:indice].rstrip()
                    links = "\n".join(f"- [[{nota}]]" for nota in aparece_em)
                    escrever_texto(caminho, f"{base}\n\n{_MARCADOR_APARECE_EM}\n{links}\n")
                continue
            aparece_em = _extrair_aparece_em(conteudo)
            if nome_nota not in aparece_em:
                aparece_em.append(nome_nota)
        else:
            aparece_em = [nome_nota]

        pagina = AgenteConceito().run(
            job_id,
            EntradaConceito(
                disciplina=disciplina,
                nome_conceito=nome_conceito,
                markdown_nota=markdown_nota,
                perfil=perfil_de(disciplina),
            ),
        )
        if pagina.definicao_a_completar:
            avisos.append(
                f"conceito '{nome_conceito}': definição a completar (fontes insuficientes na nota)"
            )

        escrever_texto(caminho, _renderizar(pagina, nome_conceito, disciplina, aparece_em))

    return avisos
