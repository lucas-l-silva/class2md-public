from dataclasses import dataclass
from datetime import datetime

from core.estado import (
    TransicaoInvalida,
    criar_job,
    enfileirar,
    fotos_do_job,
    fotos_pendentes,
    job_por_data_disciplina,
    registrar_aviso_job,
    vincular_arquivo_a_job,
)
from core.logging import registrar_evento
from projetos.estudos.manifesto import registrar_nota_manifesto
from projetos.estudos.nota import caminho_stub, criar_stub


@dataclass(frozen=True)
class FotoParaAgrupar:
    sha256: str
    disciplina: str
    tirada_em: datetime


def agrupar_por_data_disciplina(
    fotos: list[FotoParaAgrupar],
) -> dict[tuple[str, str], list[FotoParaAgrupar]]:
    grupos: dict[tuple[str, str], list[FotoParaAgrupar]] = {}
    for foto in fotos:
        chave = (foto.tirada_em.strftime("%Y-%m-%d"), foto.disciplina)
        grupos.setdefault(chave, []).append(foto)
    return grupos


def criar_ou_atualizar_job(data: str, disciplina: str, fotos: list[FotoParaAgrupar]) -> str:
    existente = job_por_data_disciplina("aula", data, disciplina)

    if existente is None:
        job_id = criar_job("aula", disciplina=disciplina, data=data)
    else:
        job_id = existente["id"]
        # concluido é tratado à parte (mesmo sendo uma transição válida hoje, via o comando
        # `reprocessar`): a chegada automática de uma foto nova nunca deve reabrir sozinha
        # um job já dado como pronto — só avisa, e o humano decide com `estudos reprocessar`.
        if existente["status"] == "concluido":
            aviso = (
                f"fotos novas chegaram em {data}/{disciplina} mas o job já está 'concluido' — "
                "use 'estudos reprocessar' se quiser incluí-las."
            )
            registrar_aviso_job(job_id, aviso)
            registrar_evento(passo="agrupamento", resultado="reprocessamento_pendente", aviso=aviso)
        else:
            try:
                enfileirar(job_id)
                registrar_aviso_job(job_id, None)
            except TransicaoInvalida:
                aviso = (
                    f"fotos novas chegaram em {data}/{disciplina} mas o job já está "
                    f"'{existente['status']}' e não pôde voltar à fila automaticamente"
                )
                registrar_aviso_job(job_id, aviso)
                registrar_evento(
                    passo="agrupamento",
                    resultado="reprocessamento_pendente",
                    aviso=aviso,
                )

    for foto in fotos:
        vincular_arquivo_a_job(foto.sha256, job_id)

    if not caminho_stub(data, disciplina).exists():
        criar_stub(data, disciplina)

    job = job_por_data_disciplina("aula", data, disciplina)
    nomes_fotos = [foto["nome_final"] for foto in fotos_do_job(job_id)]
    registrar_nota_manifesto(
        job_id,
        caminho_stub(data, disciplina),
        "a_processar",
        nomes_fotos,
        job["criado_em"],
    )

    return job_id


def agrupar_pendentes_ementa() -> dict:
    """Foto de plano de ensino vira job próprio, que **não** produz nota de aula.

    Ela documenta a disciplina (avaliações, bibliografia, datas), não um dia de aula.
    Enfiá-la num job de aula faria o compositor escrever uma nota sobre um documento
    administrativo; deixá-la sem job, que era o comportamento antigo, faz a ementa
    nunca chegar ao MOC.
    """
    fotos = [
        FotoParaAgrupar(row["sha256"], row["disciplina"], datetime.fromisoformat(row["tirada_em"]))
        for row in fotos_pendentes(origem="ementa")
    ]

    job_ids = []
    for (data, disciplina), membros in agrupar_por_data_disciplina(fotos).items():
        existente = job_por_data_disciplina("ementa", data, disciplina)
        if existente is None:
            job_id = criar_job("ementa", disciplina=disciplina, data=data)
        else:
            job_id = existente["id"]
            if existente["status"] != "na_fila":
                try:
                    enfileirar(job_id)
                except TransicaoInvalida:
                    pass
        for foto in membros:
            vincular_arquivo_a_job(foto.sha256, job_id)
        job_ids.append(job_id)

    return {"job_ids": job_ids, "jobs_criados": len(job_ids)}


def agrupar_pendentes() -> dict:
    fotos = [
        FotoParaAgrupar(row["sha256"], row["disciplina"], datetime.fromisoformat(row["tirada_em"]))
        for row in fotos_pendentes()
    ]
    grupos = agrupar_por_data_disciplina(fotos)

    job_ids = []
    jobs_criados = 0
    jobs_reaproveitados = 0
    for (data, disciplina), membros in grupos.items():
        ja_existia = job_por_data_disciplina("aula", data, disciplina) is not None
        job_ids.append(criar_ou_atualizar_job(data, disciplina, membros))
        if ja_existia:
            jobs_reaproveitados += 1
        else:
            jobs_criados += 1

    return {
        "job_ids": job_ids,
        "jobs_criados": jobs_criados,
        "jobs_reaproveitados": jobs_reaproveitados,
    }
