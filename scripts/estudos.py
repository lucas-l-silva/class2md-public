import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import typer  # noqa: E402

from core.config import get_settings  # noqa: E402
from core.estado import (
    RunnerJaEmExecucao,
    criar_job,
    job_por_prefixo_id,
    listar_jobs,
    lock_runner,
    pdfs_por_disciplina,
    registrar_passo,
    transicionar,
)
from core.fileops import escrever_texto, ler_texto  # noqa: E402
from core.llm.custos import reconciliar_do_log, relatorio_mensal  # noqa: E402
from projetos.estudos.agentes import (  # noqa: E402
    validar_completo,
)
from projetos.estudos.biblioteca import (  # noqa: E402
    LIMITE_CHARS_MATERIAIS as LIMITE_CHARS_FONTES,
)
from projetos.estudos.biblioteca import (
    LivroNaoEncontrado,
    consultar,
    fontes_antigas_por_topico,
    fontes_da_aula,
    indice_do_livro,
    livro_da_disciplina,
    resolver_capitulos,
    trechos_dos_capitulos,
)
from projetos.estudos.crops_orfaos import inventariar, mover_para_trash  # noqa: E402
from projetos.estudos.disciplinas import (  # noqa: E402
    DisciplinaDesconhecida,
    RegistroAusente,
    RegistroInvalido,
    carregar_registro,
    criar_registro_exemplo,
)
from projetos.estudos.enriquecimento import (  # noqa: E402
    NotaNaoEncontrada,
    SemMaterialNovo,
    enriquecer,
)
from projetos.estudos.etapas import (  # noqa: E402
    etapa as etapa_por_nome,
)
from projetos.estudos.etapas import (
    etapas_para,
    fechar_dependencias,
)
from projetos.estudos.fontes import (  # noqa: E402
    PRIORIDADE_LIVRO,
    FonteOrdenada,
    resumo,
    truncar,
)
from projetos.estudos.gabarito import localizar_capitulos, secao_onde_conferir  # noqa: E402
from projetos.estudos.ingestao import (  # noqa: E402
    fotos_ja_processadas,
    mover_fotos_processadas,
    processar_inbox,
)
from projetos.estudos.manifesto import ler_entrada_manifesto, registrar_nota_manifesto  # noqa: E402
from projetos.estudos.moc import gerar_moc_central, gerar_moc_disciplina  # noqa: E402
from projetos.estudos.pdf_ingestao import (  # noqa: E402
    obter_registro,
    registros_por_disciplina,
    registros_por_tipo,
    varrer_pdfs,
)
from projetos.estudos.pdf_ocr import (  # noqa: E402
    OcrRecusado,
    custo_estimado,
    extrair_por_visao,
    precisa_de_visao,
)
from projetos.estudos.programa import aula_por_numero  # noqa: E402
from projetos.estudos.programa import carregar as carregar_programa  # noqa: E402
from projetos.estudos.remendo_nota import (  # noqa: E402
    SecaoAusente,
    aplicar,
    renderizar_procedencia,
)
from projetos.estudos.reparo import (  # noqa: E402
    notas_duplicadas,
    renumerar_por_data,
    reparar_notas,
)
from projetos.estudos.runner import (
    aprovar_job,
    drenar_fila,
    promover_job,
    reprocessar_job,
)  # noqa: E402

app = typer.Typer()


def _horario_legivel(disciplina) -> str:
    if not disciplina.horarios:
        return "—"
    partes = []
    for h in disciplina.horarios:
        texto = f"{h.dia} {h.inicio}-{h.fim}"
        if h.tipo != "aula":
            texto += f" ({h.tipo})"
        if h.periodicidade != "semanal":
            texto += f" {h.periodicidade}"
        if h.local:
            texto += f" @{h.local}"
        if h.ate:
            texto += f" até {h.ate}"
        partes.append(texto)
    return ", ".join(partes)


@app.command()
def disciplinas(
    todas: bool = typer.Option(False, "--todas", help="Inclui disciplinas arquivadas."),
    exemplo: bool = typer.Option(
        False, "--exemplo", help="Cria um registro de exemplo se ainda não existir."
    ),
) -> None:
    """Lista o registro de disciplinas (siglas, docentes, horários)."""
    if exemplo:
        criado, caminho = criar_registro_exemplo()
        if criado:
            typer.echo(f"registro de exemplo criado em {caminho} — edite antes de usar")
        else:
            typer.echo(f"registro já existe em {caminho} (nada foi sobrescrito)")
        return

    try:
        registro = carregar_registro()
    except (RegistroAusente, RegistroInvalido) as erro:
        typer.echo(str(erro))
        raise typer.Exit(code=1) from erro

    typer.echo(f"Semestre atual: {registro.semestre_atual}")
    for item in registro.disciplinas:
        if not item.ativa and not todas:
            continue
        marca = " " if item.ativa else "(arquivada) "
        docentes = ", ".join(d.nome for d in item.docentes) or "—"
        codigo = f" {item.codigo}" if item.codigo else ""
        typer.echo(f"\n{marca}{item.nome}{codigo} — {item.titulo}  [{item.semestre}]")
        typer.echo(f"    tipo: {item.tipo} · perfil: {item.perfil_efetivo()}")
        typer.echo(f"    horário: {_horario_legivel(item)}")
        typer.echo(f"    docentes: {docentes}")
        if item.tipo == "disciplina":
            typer.echo(f"    monitoria: {'sim' if item.monitoria else 'não'}")
        if item.notas:
            typer.echo(f"    notas: {item.notas}")
        if item.coletor:
            typer.echo(f"    coletor: {item.coletor.tipo} → {item.coletor.url}")
        for pendencia in item.a_confirmar:
            typer.echo(f"    ⚠ a confirmar: {pendencia}")


@app.command()
def programa(
    disciplina: str = typer.Argument(..., help="Sigla da disciplina."),
) -> None:
    """Mostra o programa (aulas, títulos, tópicos e material) registrado."""
    atual = carregar_programa(disciplina)
    if atual is None:
        typer.echo(f"nenhum programa para {disciplina}")
        raise typer.Exit(code=1)

    typer.echo(f"{disciplina} — {atual.titulo_oficial or '(sem título oficial)'}")
    if atual.fonte_url:
        typer.echo(f"fonte: {atual.fonte_url}  (registrado em {atual.coletado_em})")
    for aula in atual.aulas:
        data = f"  [{aula.data}]" if aula.data else ""
        parte = f"  ({aula.parte})" if aula.parte else ""
        typer.echo(f"\n  {aula.numero:02d} — {aula.titulo}{data}{parte}")
        for topico in aula.topicos:
            typer.echo(f"       · {topico}")
        for material in aula.materiais:
            marca = "✓" if material.caminho_local else " "
            typer.echo(f"       {marca} {material.nome} ({material.tipo})")


@app.command()
def moc(
    disciplina: str = typer.Argument(None, help="Sigla. Sem argumento, use --todos."),
    todos: bool = typer.Option(False, "--todos", help="Todas as ativas + o MOC central."),
) -> None:
    """Gera as notas-home (MOC) em staging. Determinístico: não chama modelo nenhum.

    Só os blocos entre <!-- moc:inicio X --> e <!-- moc:fim X --> são reescritos;
    tudo que você escreveu fora deles sai byte a byte igual.
    """
    try:
        if todos:
            registro = carregar_registro()
            alvos = [d.nome for d in registro.disciplinas if d.ativa]
        elif disciplina:
            alvos = [disciplina]
        else:
            typer.echo("informe uma disciplina ou use --todos")
            raise typer.Exit(code=1)

        for sigla in alvos:
            typer.echo(f"  {gerar_moc_disciplina(sigla)}")
        if todos:
            typer.echo(f"  {gerar_moc_central()}")
    except (RegistroAusente, RegistroInvalido, DisciplinaDesconhecida) as erro:
        typer.echo(str(erro))
        raise typer.Exit(code=1) from erro


@app.command("enriquecer")
def enriquecer_cmd(
    disciplina: str = typer.Argument(..., help="Sigla da disciplina."),
    aula: int = typer.Option(..., "--aula", help="Número da aula no programa."),
    sim: bool = typer.Option(False, "--sim", help="Não pedir confirmação."),
    force: bool = typer.Option(False, "--force", help="Reescreve mesmo sem material novo."),
) -> None:
    """Acrescenta à nota de uma aula o material que chegou depois (lista, slides, monitoria).

    Reescreve só as seções que o material novo pode melhorar; o resto da nota sai
    byte a byte igual. Idempotente: sem material novo, não gasta API.
    """
    alvo = next(
        (
            j
            for j in listar_jobs(limite=200)
            if j["disciplina"] == disciplina
            and j["tipo"] == "aula"
            and j["status"] in ("concluido", "promovido")
            and j["numero_aula"] == aula
        ),
        None,
    )
    if alvo is None:
        typer.echo(f"nenhuma nota concluída da aula {aula:02d} de {disciplina}")
        raise typer.Exit(code=1)

    job_id = criar_job("enriquecimento", disciplina=disciplina)
    transicionar(job_id, "rodando")
    try:
        with lock_runner():
            resultado = enriquecer(job_id, alvo, forcar=force)
    except (SemMaterialNovo, NotaNaoEncontrada) as erro:
        transicionar(job_id, "falhou")
        typer.echo(str(erro))
        raise typer.Exit(code=1) from erro

    transicionar(job_id, "concluido")
    registrar_passo(job_id, "enriquecedor", "ok")

    if resultado.ja_estava_em_dia:
        typer.echo("nota já está em dia com o material disponível — nada a fazer")
        return
    if not resultado.secoes_alteradas:
        typer.echo("o material novo não acrescentou nada às seções enriquecíveis")
        return

    typer.echo(f"{resultado.caminho_nota.name}")
    for secao in resultado.secoes_alteradas:
        typer.echo(f"  reescrita: ## {secao}")
    typer.echo(f"  fontes: {', '.join(resultado.fontes_usadas) or '—'}")


@app.command("ocr-pdf")
def ocr_pdf_cmd(
    disciplina: str = typer.Argument(..., help="Sigla da disciplina."),
    sim: bool = typer.Option(False, "--sim", help="Não pedir confirmação."),
    force: bool = typer.Option(False, "--force", help="Refaz mesmo com texto já disponível."),
) -> None:
    """Lê por visão os PDFs sem camada de texto. Custa dinheiro — sempre pede confirmação.

    O pipeline nunca faz isso sozinho: extrair páginas por visão é caro e a qualidade
    depende do material. Use quando o PDF for manuscrito ou digitalização que valha a pena.
    """
    pendentes = [r for r in registros_por_disciplina(disciplina) if precisa_de_visao(r)]
    if not pendentes:
        typer.echo(f"nenhum PDF de {disciplina} precisa de leitura por visão")
        return

    paginas, custo = custo_estimado(pendentes)
    typer.echo(f"{len(pendentes)} PDF(s) sem texto, {paginas} página(s):")
    for registro in pendentes:
        typer.echo(f"  {registro.paginas:4}p  {registro.tipo:10} {registro.nome_arquivo}")
    typer.echo(f"\nCusto estimado: ~US$ {custo:.2f} (média do seu histórico)")

    if not sim and not typer.confirm("Ler esses PDFs por visão?"):
        typer.echo("cancelado")
        raise typer.Exit(code=1)

    job_id = criar_job("ocr", disciplina=disciplina)
    transicionar(job_id, "rodando")
    lidos = 0
    for registro in pendentes:
        try:
            resultado = extrair_por_visao(job_id, registro, force=force)
        except OcrRecusado as erro:
            typer.echo(f"  ⚠ {erro}")
            continue
        lidos += 1
        typer.echo(
            f"  ✓ {registro.nome_arquivo}: {resultado.paginas_lidas} páginas, "
            f"{resultado.chars} chars"
        )
    transicionar(job_id, "concluido")
    registrar_passo(job_id, "ocr", "ok")
    typer.echo(f"\n{lidos} PDF(s) lidos.")


@app.command()
def status() -> None:
    """Mostra a fila de jobs, pendências e os últimos jobs processados."""
    fila = listar_jobs(status="na_fila")
    typer.echo(f"Fila ({len(fila)}):")
    for job in fila:
        typer.echo(
            f"  {job['id'][:8]}  {job['disciplina']}  {job['data']}  criado {job['criado_em']}"
        )

    aguardando = listar_jobs(status="aguardando_humano")
    if aguardando:
        typer.echo(f"\nAguardando humano ({len(aguardando)}):")
        for job in aguardando:
            motivo = job["aviso_reprocessamento"] or job["erro"] or ""
            typer.echo(f"  {job['id'][:8]}  {job['disciplina']}  {job['data']}  {motivo}")

    parciais = listar_jobs(status="parcial")
    if parciais:
        typer.echo(f"\nParciais ({len(parciais)}), pararam antes da nota:")
        for job in parciais:
            feitas = job["etapas_feitas"] or "nenhuma"
            typer.echo(
                f"  {job['id'][:8]}  {job['disciplina']}  {job['data']}  etapas feitas: {feitas}"
                f"  (continuar: reprocessar {job['id'][:8]} --com-cache)"
            )

    recentes = listar_jobs(limite=5)
    typer.echo("\nÚltimos jobs:")
    for job in recentes:
        typer.echo(f"  {job['id'][:8]}  {job['status']:<18}  {job['disciplina']}  {job['data']}")


def _validar_etapas(texto: str, sem_flashcards: bool) -> list[str]:
    """Valida `--etapas` antes de qualquer custo e devolve o conjunto com dependências."""
    nomes = [n.strip() for n in texto.split(",") if n.strip()]
    validas_de_foto = [e.nome for e in etapas_para("foto")]
    for nome in nomes:
        try:
            alvo = etapa_por_nome(nome)
        except ValueError:
            typer.echo(f"Etapa desconhecida: {nome}. Etapas de foto: {', '.join(validas_de_foto)}.")
            raise typer.Exit(code=1) from None
        if "foto" not in alvo.materiais:
            typer.echo(
                f"A etapa '{nome}' é de PDF e não roda no `processar`. "
                f"Use o comando `{alvo.comando_cli}`."
            )
            raise typer.Exit(code=1)
    if sem_flashcards and "flashcards" in nomes:
        typer.echo(
            "--sem-flashcards e --etapas com 'flashcards' se contradizem. Escolha um dos dois."
        )
        raise typer.Exit(code=1)
    fechadas = fechar_dependencias(nomes)
    for nome in fechadas:
        if nome not in nomes:
            dependente = next(n for n in nomes if nome in fechar_dependencias([n]))
            typer.echo(f"Incluí '{nome}' porque '{dependente}' depende dela.")
    return fechadas


@app.command()
def processar(
    sem_flashcards: bool = typer.Option(
        False,
        "--sem-flashcards",
        help="Conclui as notas sem gerar cards (as dúvidas continuam). "
        "Gere depois com `reprocessar <job> --passo flashcards`.",
    ),
    etapas: str = typer.Option(
        None,
        "--etapas",
        help="Roda só estas etapas de foto, separadas por vírgula: "
        "leitura, nota, flashcards, conceitos, disciplina. As dependências entram sozinhas. "
        "Sem a opção, roda tudo.",
    ),
) -> None:
    """Roda a ingestão do inbox e agrupa fotos pendentes em jobs de aula."""
    pedidas = _validar_etapas(etapas, sem_flashcards) if etapas else None
    # Ingestão+agrupamento e drenar_fila rodam juntos, sob o mesmo lock, só porque nesta
    # iteração nenhum passo tem trabalho real (é tudo quase instantâneo). Quando P2+
    # adicionar passos de verdade (ex. chamada de API de visão), segurar o lock por toda
    # a duração de "ingerir tudo + processar tudo" vai impedir um watcher de só enfileirar
    # fotos novas enquanto o runner ainda processa jobs antigos. Nessa hora, separar em
    # dois comandos/processos (watcher enfileira rápido; runner drena como serviço,
    # como a doc de arquitetura §9 já prevê) deixa de ser opcional.
    try:
        with lock_runner():
            resultado_ingestao = processar_inbox()
            pdfs_registrados = varrer_pdfs()
            resultado_runner = drenar_fila(flashcards=not sem_flashcards, etapas=pedidas)
    except RunnerJaEmExecucao:
        typer.echo("Já existe um processamento em andamento — tente novamente em instantes.")
        return

    typer.echo(f"Fotos ingeridas: {resultado_ingestao['fotos_ingeridas']}")
    for foto, aviso in resultado_ingestao.get("datas", []):
        typer.echo(f"  data: {foto} — {aviso}")
    typer.echo(f"Jobs criados: {resultado_ingestao['jobs_criados']}")
    typer.echo(f"Jobs reaproveitados: {resultado_ingestao['jobs_reaproveitados']}")
    typer.echo(f"PDFs registrados: {len(pdfs_registrados)}")
    typer.echo(f"Jobs processados: {resultado_runner['processados']}")
    if resultado_runner["falhados"]:
        typer.echo(f"Jobs com falha: {resultado_runner['falhados']}")
    if resultado_runner["pausados"]:
        typer.echo(f"Jobs aguardando humano: {resultado_runner['pausados']}")
    if resultado_runner.get("parciais"):
        typer.echo(
            f"Jobs parciais: {resultado_runner['parciais']}. Para continuar: "
            "`reprocessar <job> --com-cache` e depois `processar`."
        )


@app.command()
def custos(
    mes: str = typer.Option(None, "--mes", help="Mês no formato AAAA-MM; padrão: mês corrente."),
    reconciliar: bool = typer.Option(
        False,
        "--reconciliar",
        help="Completa o livro-caixa com o que o log de eventos tem.",
    ),
) -> None:
    """Telemetria de custo do mês: total, projeção e detalhamento por passo/modelo.

    Só leitura, exceto com --reconciliar, que acrescenta ao livro-caixa o gasto que o
    log de eventos registra e ele não. Nunca reduz o total.
    """
    if reconciliar:
        ano_r, mes_r = (int(x) for x in mes.split("-")) if mes else (None, None)
        antes, depois, lancamentos = reconciliar_do_log(ano_r, mes_r)
        if depois > antes:
            typer.echo(
                f"livro-caixa ajustado: ${antes:.2f} → ${depois:.2f} "
                f"(log tem {lancamentos} chamadas)"
            )
        else:
            typer.echo(f"livro-caixa já está de acordo com o log (${antes:.2f})")

    if mes:
        ano_str, mes_str = mes.split("-")
        relatorio = relatorio_mensal(int(ano_str), int(mes_str))
    else:
        relatorio = relatorio_mensal()

    typer.echo(f"Custo de {relatorio['ano']:04d}-{relatorio['mes']:02d}: ${relatorio['total']:.2f}")
    typer.echo(
        f"Projeção do mês: ${relatorio['projecao']:.2f}  "
        f"(dia {relatorio['dias_decorridos']}/{relatorio['dias_no_mes']}, "
        f"teto ${relatorio['teto']:.2f})"
    )
    if relatorio["estoura_teto"]:
        typer.echo("AVISO: a projeção do mês ultrapassa o teto mensal.")
    if relatorio.get("detalhamento_parcial"):
        typer.echo(
            f"(o detalhamento abaixo soma ${relatorio['total_linhas']:.2f}: mostra só a última "
            "tentativa de cada passo, enquanto o total inclui as reprocessadas)"
        )
    if relatorio["diverge_muito"]:
        typer.echo(
            f"AVISO: soma por passo (${relatorio['total_linhas']:.2f}) diverge "
            f"do total oficial (${relatorio['total']:.2f})."
        )

    if not relatorio["linhas"]:
        typer.echo("\nNenhum passo registrado neste mês.")
        return

    typer.echo(
        f"\n{'Passo':<15} {'Modelo':<25} {'Chamadas':>8}  {'Tok.in':>9}  {'Tok.out':>9}  "
        f"{'Custo':>8}  {'%Cache':>7}"
    )
    for linha in relatorio["linhas"]:
        typer.echo(
            f"{linha['passo']:<15} {linha['modelo']:<25} {linha['chamadas']:>8}  "
            f"{linha['tokens_in']:>9}  {linha['tokens_out']:>9}  "
            f"${linha['custo']:>7.2f}  {linha['pct_cache_hit']:>6.0f}%"
        )


@app.command("pdfs")
def listar_pdfs(
    disciplina: str = typer.Argument(
        ..., help="Disciplina a listar (nome da subpasta em estudos/pdfs/)."
    ),
) -> None:
    """Lista os PDFs registrados de uma disciplina: tipo, modo e se já foi indexado."""
    registros = pdfs_por_disciplina(disciplina)
    if not registros:
        typer.echo(
            f"Nenhum PDF registrado para '{disciplina}'. Rode 'processar' para varrer estudos/pdfs/."
        )
        return

    for row in registros:
        indexado = "indexado" if row["indexado_em"] else "não indexado"
        aula = f"  aula={row['data_aula']}" if row["data_aula"] else ""
        typer.echo(
            f"  {row['nome_arquivo']:<40} {row['tipo']:<11} {row['modo']:<9} "
            f"{row['paginas']:>4}p  {indexado}{aula}"
        )


def _rodar_indexacao(registro, force: bool) -> None:
    job_id = criar_job("indexacao", disciplina=registro.disciplina)
    transicionar(job_id, "rodando")
    try:
        indice = indice_do_livro(job_id, registro, force=force)
    except Exception:
        transicionar(job_id, "falhou")
        raise
    transicionar(job_id, "concluido")
    typer.echo(
        f"  {registro.nome_arquivo}: {len(indice.capitulos)} capítulo(s) "
        f"(fonte: {indice.fonte_indice}, confiança {indice.confianca:.2f})"
    )


@app.command("indexar-pdf")
def indexar_pdf(
    caminho: Path = typer.Argument(
        None,
        help="PDF específico a registrar/indexar. Omitido: indexa todos os livros já registrados.",
    ),
    tipo: str = typer.Option(
        None,
        "--tipo",
        help="livro|aula|slides|exercicios — sobrepõe a detecção automática.",
    ),
    disciplina: str = typer.Option(
        None, "--disciplina", help="Sobrepõe a disciplina inferida da pasta."
    ),
    data_aula: str = typer.Option(
        None,
        "--data-aula",
        help="AAAA-MM-DD: liga o PDF à aula desse dia (relevante p/ PDFs pequenos).",
    ),
    aula: int = typer.Option(
        None,
        "--aula",
        help="Número da aula no programa: liga o PDF a essa aula (usado por `enriquecer`).",
    ),
    force: bool = typer.Option(False, "--force", help="Reextrai o índice mesmo se já indexado."),
) -> None:
    """Registra PDF(s) e extrai o índice de capítulos dos livros (uma vez por hash, cacheado).

    PDFs pequenos (aula/slides/exercícios) só são registrados — não têm índice de capítulo,
    entram direto na composição da nota quando a data casar com a aula.
    """
    with lock_runner():
        if caminho is not None:
            registro = obter_registro(
                caminho,
                tipo=tipo,
                disciplina=disciplina,
                data_aula=data_aula,
                force=force,
                numero_aula=aula,
                vinculo_fonte="manual" if aula is not None else None,
            )
            if registro.tipo != "livro":
                typer.echo(
                    f"{registro.nome_arquivo} é do tipo '{registro.tipo}', não 'livro' — "
                    "registrado, mas nada a indexar (PDFs pequenos entram direto na composição)."
                )
                return
            registros = [registro]
        else:
            varrer_pdfs()
            registros = registros_por_tipo("livro")

        if not registros:
            typer.echo("Nenhum livro para indexar.")
            return

        typer.echo(f"Indexando {len(registros)} livro(s)...")
        for registro in registros:
            _rodar_indexacao(registro, force)


def _titulo_da_nota(markdown: str, default: str) -> str:
    for linha in markdown.splitlines():
        if linha.startswith("# "):
            return linha[2:].strip()
    return default


@app.command("preencher-lacunas")
def preencher_lacunas(
    job_id: str = typer.Argument(
        ..., help="ID (ou prefixo) do job concluido cuja nota tem lacunas."
    ),
    capitulo: list[int] = typer.Option(
        None,
        "--capitulo",
        help="Capítulo do livro a consultar; repetível. Sem isso, a sugestão é automática.",
    ),
    livro: str = typer.Option(
        None,
        "--livro",
        help="Nome do arquivo do livro, quando a disciplina tem mais de um.",
    ),
    sim: bool = typer.Option(
        False, "--sim", help="Não pedir confirmação antes de reescrever a nota."
    ),
) -> None:
    """Consulta o livro-texto e preenche as lacunas (dúvidas/conceitos incompletos) de uma
    nota já concluída — sem tocar nas fotos nem reingerir nada, sempre com revisão humana
    antes de escrever (a menos que --sim)."""
    job = job_por_prefixo_id(job_id)
    if job is None:
        typer.echo(f"job não encontrado: {job_id}")
        raise typer.Exit(code=1)
    if job["status"] != "concluido":
        typer.echo(f"job {job['id'][:8]} não está concluido (status atual: {job['status']})")
        raise typer.Exit(code=1)

    entrada_manifesto = ler_entrada_manifesto(job["id"])
    if entrada_manifesto is None:
        typer.echo(f"job {job['id'][:8]} não tem entrada no manifesto de staging")
        raise typer.Exit(code=1)

    lacunas = list(entrada_manifesto.get("duvidas") or []) + list(
        entrada_manifesto.get("avisos_conceitos") or []
    )
    if not lacunas:
        typer.echo("Nenhuma lacuna registrada nesta nota — nada a preencher.")
        return

    caminho_nota = Path(entrada_manifesto["caminho_nota"])
    markdown = ler_texto(caminho_nota)
    titulo_nota = _titulo_da_nota(markdown, job["disciplina"])

    try:
        registro = livro_da_disciplina(job["disciplina"], livro)
    except LivroNaoEncontrado as erro:
        typer.echo(str(erro))
        raise typer.Exit(code=1) from erro

    with lock_runner():
        indice = indice_do_livro(job["id"], registro)
        try:
            capitulos, origem = resolver_capitulos(
                job["id"],
                indice,
                job["disciplina"],
                titulo_nota,
                [],
                lacunas,
                override=list(capitulo) if capitulo else None,
            )
        except ValueError as erro:
            typer.echo(str(erro))
            raise typer.Exit(code=1) from erro

        if not capitulos:
            typer.echo("Nenhum capítulo identificado (manual ou sugerido) — nada a consultar.")
            return

        # As fontes são montadas e ORDENADAS em Python antes de qualquer chamada de
        # modelo (ver projetos/estudos/fontes.py): manuscrito e material do professor
        # atual vêm antes do livro, e o corte por teto acontece de baixo para cima.
        trechos_do_livro = trechos_dos_capitulos(registro, indice, capitulos)
        fontes = [
            FonteOrdenada(trecho=trecho, prioridade=PRIORIDADE_LIVRO) for trecho in trechos_do_livro
        ]
        numero_aula = job["numero_aula"]
        fontes += fontes_da_aula(job["disciplina"], numero_aula)

        programa_atual = carregar_programa(job["disciplina"])
        aula_no_programa = (
            aula_por_numero(programa_atual, numero_aula)
            if programa_atual is not None and numero_aula is not None
            else None
        )
        fontes += fontes_antigas_por_topico(
            job["disciplina"],
            titulo_nota,
            aula_no_programa.topicos if aula_no_programa else [],
        )

        # os capítulos foram escolhidos para ESTA consulta: entram garantidos, senão a
        # prioridade (que põe o livro abaixo do material do semestre) cortaria justamente
        # o que o comando existe para consultar
        mantidas, avisos_fonte = truncar(
            fontes,
            LIMITE_CHARS_FONTES,
            garantidas={trecho.arquivo for trecho in trechos_do_livro},
        )
        for aviso in avisos_fonte:
            typer.echo(f"  ⚠ {aviso}")
        typer.echo("Fontes, na ordem em que o modelo vai lê-las:")
        typer.echo(resumo(mantidas))

        trechos = [fonte.trecho for fonte in mantidas]
        saida = consultar(job["id"], job["disciplina"], titulo_nota, markdown, lacunas, trechos)

        # Gabarito nunca entra como fonte: entra como ponteiro. Copiar a solução
        # tiraria justamente o trabalho que ensina.
        onde_conferir = secao_onde_conferir(localizar_capitulos(job["disciplina"], capitulos))
        if onde_conferir:
            saida = saida.model_copy(
                update={"secao_do_livro": f"{renderizar_procedencia(saida)}\n\n{onde_conferir}\n"}
            )

        resolvidas = sum(1 for resposta in saida.respostas if resposta.resolvida)
        typer.echo(f"Capítulo(s) consultado(s) ({origem}): {capitulos}")
        typer.echo(f"Lacunas resolvidas: {resolvidas}/{len(lacunas)}")
        if onde_conferir:
            typer.echo("Gabarito: adicionada a lista de onde conferir (sem copiar a solução).")

        if not sim and not typer.confirm("Reescrever a nota com o resultado acima?", default=False):
            typer.echo("Cancelado — nota não foi alterada.")
            return

        try:
            novo_markdown = aplicar(markdown, saida)
        except SecaoAusente as erro:
            typer.echo(str(erro))
            raise typer.Exit(code=1) from erro

        escrever_texto(caminho_nota, novo_markdown)

        pasta_crops = get_settings().agent_data_dir / "estudos" / "crops" / job["disciplina"]
        validacao = validar_completo(
            job["id"], novo_markdown, job["disciplina"], job["data"], pasta_crops
        )
        problemas_texto = (
            [f"{p.onde}: {p.descricao}" for p in validacao.problemas]
            if not validacao.aprovado
            else None
        )

        registrar_passo(job["id"], "bibliotecario", "ok")
        registrar_nota_manifesto(
            job["id"],
            caminho_nota,
            "concluido",
            entrada_manifesto.get("fotos", []),
            entrada_manifesto.get("criado_em"),
            conceitos_novos=entrada_manifesto.get("conceitos_novos"),
            duvidas=saida.lacunas_nao_resolvidas,
            precisa_revisao=True,
            problemas_validacao=problemas_texto,
            avisos_conceitos=entrada_manifesto.get("avisos_conceitos"),
            secao_do_livro=renderizar_procedencia(saida),
        )

    typer.echo(f"Nota atualizada: {caminho_nota}")


@app.command()
def aprovar(
    job_id: str = typer.Argument(..., help="ID (ou prefixo) do job em aguardando_humano."),
) -> None:
    """Resolve um job aguardando_humano, devolvendo-o à fila para reprocessar."""
    try:
        job_id_completo = aprovar_job(job_id)
    except ValueError as erro:
        typer.echo(str(erro))
        raise typer.Exit(code=1) from erro

    typer.echo(f"Job {job_id_completo[:8]} aprovado — voltou para na_fila.")


@app.command()
def reprocessar(
    job_id: str = typer.Argument(
        ..., help="ID (ou prefixo) do job concluido/falhou a reprocessar."
    ),
    passo: str = typer.Option(
        None,
        "--passo",
        help="Restringe a invalidação de cache a este passo (ex.: extrator).",
    ),
    com_cache: bool = typer.Option(
        False,
        "--com-cache",
        help="Refaz a nota aproveitando o cache: só é cobrado o que mudou desde a última execução.",
    ),
) -> None:
    """Re-enfileira um job concluido/falhou. Por padrão ignora o cache no próximo processar."""
    try:
        job_id_completo = reprocessar_job(job_id, passo, com_cache=com_cache)
    except ValueError as erro:
        typer.echo(str(erro))
        raise typer.Exit(code=1) from erro

    if com_cache:
        typer.echo(
            f"Job {job_id_completo[:8]} voltou para a fila. O cache será usado: "
            "só é cobrado o que mudou desde a última execução."
        )
        return

    alvo = f"passo '{passo}'" if passo else "todos os passos"
    typer.echo(
        f"Job {job_id_completo[:8]} marcado para reprocessar ({alvo}) — voltou para na_fila."
    )


@app.command(hidden=True)
def promover_finalizar(
    job_id: str = typer.Argument(
        ..., help="ID (ou prefixo) do job cuja nota já foi copiada ao vault."
    ),
    nota: int = typer.Option(
        ..., "--nota", help="Nota de qualidade 1-5, dada pelo promotor na máquina do vault."
    ),
) -> None:
    """Chamado via SSH pelo promotor: arquiva a nota em promovidas/ e registra a avaliação.

    Nunca escreve no vault — só o promotor na máquina do vault faz isso. Este comando só é seguro de
    rodar DEPOIS da cópia ter dado certo do lado de lá.
    """
    try:
        job_id_completo = promover_job(job_id, nota)
    except ValueError as erro:
        typer.echo(str(erro))
        raise typer.Exit(code=1) from erro

    typer.echo(f"Job {job_id_completo[:8]} promovido — nota {nota}, arquivado em promovidas/.")


@app.command()
def crops(
    disciplina: str = typer.Argument(None, help="Sigla; sem isso, todas."),
    mover_orfaos: bool = typer.Option(
        False, "--mover", help="Move os órfãos para estudos/trash/<carimbo>/."
    ),
    sim: bool = typer.Option(False, "--sim", help="Não pedir confirmação."),
) -> None:
    """Lista os recortes e separa os que nenhuma nota usa.

    Órfão é recorte que o extrator gerou mas o compositor não usou, ou que sobrou de um
    job reprocessado. Com --mover, vai para a lixeira — nunca é apagado.
    """
    inventario = inventariar(disciplina)
    if inventario.total == 0:
        typer.echo("nenhum recorte encontrado")
        return

    typer.echo(
        f"{len(inventario.usados)} em uso, {len(inventario.orfaos)} órfãos (de {inventario.total})"
    )
    if not inventario.orfaos:
        return

    por_disciplina: dict[str, int] = {}
    for caminho in inventario.orfaos:
        por_disciplina[caminho.parent.name] = por_disciplina.get(caminho.parent.name, 0) + 1
    for sigla, quantos in sorted(por_disciplina.items()):
        typer.echo(f"  {sigla:18s} {quantos:4d}")

    if not mover_orfaos:
        typer.echo("\nuse --mover para enviá-los à lixeira")
        return

    if not sim and not typer.confirm(f"Mover {len(inventario.orfaos)} recortes para a lixeira?"):
        typer.echo("cancelado")
        raise typer.Exit(code=1)

    destino = mover_para_trash(inventario.orfaos)
    typer.echo(f"movidos para {destino}")


@app.command()
def inbox(
    limpar: bool = typer.Option(
        False, "--limpar", help="Move para a lixeira as fotos que já viraram nota."
    ),
    sim: bool = typer.Option(False, "--sim", help="Não pedir confirmação."),
) -> None:
    """Mostra o que ainda está no inbox e drena as fotos já processadas.

    Só sai foto que passou nas três condições: está registrada, o job dela concluiu e a
    versão normalizada está em processed/. PDF nunca sai — para ele o inbox é o lugar
    definitivo, e o registro aponta para lá.
    """
    prontas = fotos_ja_processadas()
    if not prontas:
        typer.echo("nenhuma foto processada sobrando no inbox")
        return

    typer.echo(f"{len(prontas)} foto(s) já processada(s):")
    for caminho, motivo in prontas:
        typer.echo(f"  {caminho.name:22s} → {motivo}")

    if not limpar:
        typer.echo("\nuse --limpar para movê-las à lixeira")
        return

    if not sim and not typer.confirm(f"Mover {len(prontas)} foto(s) para a lixeira?"):
        typer.echo("cancelado")
        raise typer.Exit(code=1)

    destino = mover_fotos_processadas([caminho for caminho, _ in prontas])
    typer.echo(f"movidas para {destino}")


@app.command("reparar-notas")
def reparar_notas_cmd(
    sim: bool = typer.Option(False, "--sim", help="Não pedir confirmação."),
    renumerar: str = typer.Option(
        None,
        "--renumerar",
        help="Sigla cujas notas devem ser renumeradas pela ordem das datas.",
    ),
) -> None:
    """Conserta formatação das notas já geradas. Determinístico: não chama modelo nenhum.

    Junta parágrafos que vieram quebrados em várias linhas e funde as seções "Do livro"
    que se duplicaram a cada execução de preencher-lacunas. Faz backup antes.

    Com --renumerar <SIGLA>, corrige também o número da aula pela ordem das datas —
    reescreve frontmatter, nome do arquivo e o job, que precisam concordar.
    """
    if renumerar:
        relato = renumerar_por_data(renumerar, aplicar_mudancas=False)
        if not relato:
            typer.echo(f"{renumerar}: numeração já está na ordem das datas")
        else:
            for linha in relato:
                typer.echo(f"  {linha}")
            if sim or typer.confirm(f"Renumerar {len(relato)} nota(s)?"):
                renumerar_por_data(renumerar, aplicar_mudancas=True)
                typer.echo("renumeradas")
            else:
                typer.echo("cancelado")
                raise typer.Exit(code=1)
        return

    for sigla in {
        c.parent.name for c in (get_settings().agent_data_dir / "estudos" / "output").glob("*/*.md")
    }:
        for chave, arquivos in notas_duplicadas(sigla):
            typer.echo(f"⚠ {sigla}: {len(arquivos)} notas para {chave} — só uma pode ficar:")
            for caminho in arquivos:
                typer.echo(f"    {caminho.name}")

    resultado = reparar_notas(aplicar_mudancas=False)
    if not resultado.alteradas:
        typer.echo("nada a reparar — todas as notas já estão limpas")
        return

    typer.echo(f"{len(resultado.alteradas)} nota(s) a reparar:")
    for caminho, o_que in resultado.alteradas:
        typer.echo(f"  {caminho.name[:56]:58s} {o_que}")

    if not sim and not typer.confirm("Aplicar? (o original vai para a lixeira)"):
        typer.echo("cancelado")
        raise typer.Exit(code=1)

    resultado = reparar_notas(aplicar_mudancas=True)
    typer.echo(f"reparadas {len(resultado.alteradas)}; backup em {resultado.backup}")


@app.command()
def ui(
    porta: int = typer.Option(8765, "--porta", help="Porta local da interface."),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Só 127.0.0.1 é aceito: a página usa a sua chave e não pode ficar na rede.",
    ),
) -> None:
    """Abre a interface local no navegador, em http://127.0.0.1:8765."""
    from ui.servidor import servir

    try:
        servir(host=host, porta=porta)
    except ValueError as erro:
        typer.echo(str(erro))
        raise typer.Exit(1) from None
    except OSError as erro:
        typer.echo(f"Não consegui abrir a porta {porta}: {erro}. Tente outra com --porta.")
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
