"""Lógica de cada tela da interface local.

Não importa `anthropic` e não lê `.env` (S11): a chave só entra por `chave_configurada()`,
que devolve verdadeiro ou falso. Nenhuma função daqui recebe um caminho de destino (S9):
tudo o que é gravado fica em `estudos/inbox/` ou `estudos/trash/` da pasta de dados.
"""

import hashlib
import json
import statistics
import threading
import time
import uuid
from pathlib import Path

from core.config import chave_configurada, get_settings
from core.estado import (
    RunnerJaEmExecucao,
    arquivo_por_sha,
    custo_do_mes,
    enfileirar,
    fotos_do_job,
    job_por_id,
    listar_jobs,
    lock_runner,
)
from core.fileops import escrever, ler_texto, mover
from core.logging import registrar_evento
from projetos.estudos import etapas as etapas_mod
from projetos.estudos.ingestao import processar_inbox
from projetos.estudos.manifesto import ler_entrada_manifesto
from projetos.estudos.runner import aprovar_job, drenar_fila, reprocessar_job
from ui.seguranca import (
    MAX_FOTO_BYTES,
    MAX_FOTOS_POR_ENVIO,
    PedidoRecusado,
    dentro_da_pasta,
    disciplina_valida,
    formato_da_imagem,
)

MATERIAIS = ("foto_aula", "pdf_livro", "pdf_capitulos", "pdf_lista")
MATERIAIS_FOTO = ("foto_aula",)
RECURSOS = {"duvidas": False, "economia": False, "pdf": False}
JANELA_HISTORICO = 10
ESTADOS_FINAIS = ("concluido", "parcial", "aguardando_humano", "falhou", "limite")
TIPOS_DE_IMAGEM = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _erro(status: int, codigo: str, mensagem: str) -> PedidoRecusado:
    return PedidoRecusado(status, codigo, mensagem)


def _recurso_desligado() -> PedidoRecusado:
    return _erro(404, "em_desenvolvimento", "Este recurso ainda não está disponível.")


class Servico:
    def __init__(self) -> None:
        self._envios: dict[str, dict] = {}
        self._execucoes: dict[str, dict] = {}
        self._trava = threading.Lock()

    # ------------------------------------------------------------------ estado
    def estado(self) -> dict:
        base = {
            "chave_configurada": chave_configurada(),
            "limites": {
                "max_foto_bytes": MAX_FOTO_BYTES,
                "max_fotos_por_envio": MAX_FOTOS_POR_ENVIO,
            },
            "recursos": dict(RECURSOS),
            "teto_usd": None,
            "gasto_mes_usd": None,
            "tem_registro": False,
            "disciplinas": [],
        }
        if not base["chave_configurada"]:
            return base
        settings = get_settings()
        base["teto_usd"] = settings.teto_mensal_usd
        base["gasto_mes_usd"] = round(custo_do_mes(), 6)
        try:
            from projetos.estudos.disciplinas import disciplinas_ativas

            base["disciplinas"] = sorted(d.nome for d in disciplinas_ativas())
            base["tem_registro"] = True
        except Exception:  # noqa: BLE001 - sem registro, a tela usa campo de texto
            pass
        return base

    def _exigir_chave(self) -> None:
        if not chave_configurada():
            raise _erro(400, "sem_chave", "Falta a chave da API. Veja a tela de primeira execução.")

    # ------------------------------------------------------------------- plano
    def plano(self, material: str) -> dict:
        if material not in MATERIAIS:
            raise _erro(400, "material_invalido", "Material desconhecido.")
        tipo = etapas_mod.FOTO if material in MATERIAIS_FOTO else etapas_mod.PDF
        return {
            "material": material,
            "disponivel": tipo == etapas_mod.FOTO,
            "etapas": [
                {
                    "nome": e.nome,
                    "rotulo": e.rotulo,
                    "descricao": e.descricao,
                    "depende_de": list(e.depende_de),
                    "chama_modelo": e.chama_modelo,
                    "comando_cli": e.comando_cli,
                }
                for e in etapas_mod.etapas_para(tipo)
            ],
        }

    def _validar_etapas(self, pedidas: object) -> list[str]:
        if (
            not isinstance(pedidas, list)
            or not pedidas
            or not all(isinstance(n, str) for n in pedidas)
        ):
            raise _erro(400, "etapas_invalidas", "Marque pelo menos uma etapa.")
        validas = {e.nome for e in etapas_mod.etapas_para(etapas_mod.FOTO)}
        for nome in pedidas:
            if nome not in validas:
                raise _erro(400, "etapa_desconhecida", f"Etapa desconhecida: {nome}.")
        falta = etapas_mod.faltantes(pedidas)
        if falta:
            rotulos = ", ".join(etapas_mod.etapa(n).rotulo for n in falta)
            raise _erro(
                400,
                "dependencia_faltante",
                f"Estas etapas precisam de outras que não foram marcadas: {rotulos}.",
            )
        return pedidas

    # ------------------------------------------------------------------- envio
    def receber(self, campos: dict[str, str], arquivos: list[tuple[str, bytes]]) -> dict:
        self._exigir_chave()
        disciplina = disciplina_valida(campos.get("disciplina", ""))
        envio_id = campos.get("envio_id") or uuid.uuid4().hex
        with self._trava:
            envio = self._envios.setdefault(envio_id, {"disciplina": disciplina, "arquivos": {}})
        if envio["disciplina"] != disciplina:
            raise _erro(400, "disciplina_diferente", "Este envio já pertence a outra disciplina.")
        if len(envio["arquivos"]) + len(arquivos) > MAX_FOTOS_POR_ENVIO:
            raise _erro(
                400,
                "fotos_demais",
                f"Até {MAX_FOTOS_POR_ENVIO} fotos por envio.",
            )
        settings = get_settings()
        inbox = settings.agent_data_dir / "estudos" / "inbox" / disciplina
        saida = []
        for nome, conteudo in arquivos:
            item = {"nome": nome, "tamanho": len(conteudo)}
            try:
                if len(conteudo) > MAX_FOTO_BYTES:
                    raise _erro(
                        400,
                        "foto_grande",
                        f"A foto passa de {MAX_FOTO_BYTES // (1024 * 1024)} MB.",
                    )
                extensao = formato_da_imagem(conteudo)
                sha = hashlib.sha256(conteudo).hexdigest()
                arquivo_id = sha[:16]
                if arquivo_por_sha(sha) is not None:
                    item.update(arquivo_id=arquivo_id, situacao="ja_estava")
                else:
                    destino = dentro_da_pasta(inbox / f"{sha}{extensao}", settings.agent_data_dir)
                    escrever(destino, conteudo)
                    item.update(arquivo_id=arquivo_id, situacao="recebido")
                envio["arquivos"][arquivo_id] = {**item, "sha": sha, "extensao": extensao}
            except PedidoRecusado as recusa:
                item.update(arquivo_id=None, situacao="recusado", motivo=recusa.mensagem)
            saida.append(item)
        return {
            "envio_id": envio_id,
            "arquivos": saida,
            "pasta": f"estudos/inbox/{disciplina}/",
        }

    def remover(self, envio_id: str, arquivo_id: str) -> dict:
        envio = self._envios.get(envio_id)
        item = envio["arquivos"].get(arquivo_id) if envio else None
        if item is None:
            raise _erro(404, "arquivo_desconhecido", "Arquivo não encontrado neste envio.")
        if item["situacao"] == "recebido":
            settings = get_settings()
            origem = (
                settings.agent_data_dir
                / "estudos"
                / "inbox"
                / envio["disciplina"]
                / f"{item['sha']}{item['extensao']}"
            )
            if origem.exists():
                dentro_da_pasta(origem, settings.agent_data_dir)
                lixeira = settings.agent_data_dir / "estudos" / "trash" / origem.name
                mover(origem, lixeira)
        del envio["arquivos"][arquivo_id]
        return {"removido": True}

    # --------------------------------------------------------------- estimativa
    def _envio(self, envio_id: object) -> dict:
        envio = self._envios.get(envio_id) if isinstance(envio_id, str) else None
        if envio is None or not envio["arquivos"]:
            raise _erro(400, "envio_desconhecido", "Envie as fotos antes de continuar.")
        return envio

    def _etapa_guardada(self, envio: dict, nome: str) -> bool:
        """Todas as fotos já foram processadas e a etapa já rodou para o job delas."""
        itens = list(envio["arquivos"].values())
        if not itens or any(i["situacao"] != "ja_estava" for i in itens):
            return False
        for item in itens:
            linha = arquivo_por_sha(item["sha"])
            job = job_por_id(linha["job_id"]) if linha and linha["job_id"] else None
            if job is None:
                return False
            if nome not in _etapas_feitas_do_job(job):
                return False
        return True

    def estimativa(self, corpo: dict) -> dict:
        self._exigir_chave()
        envio = self._envio(corpo.get("envio_id"))
        pedidas = self._validar_etapas(corpo.get("etapas"))
        historico = _historico_por_etapa()
        linhas = []
        total = 0.0
        sem_estimativa = False
        for nome in pedidas:
            etapa = etapas_mod.etapa(nome)
            if self._etapa_guardada(envio, nome):
                linha = {"custo_usd": 0.0, "espera_s": 0, "origem": "guardado", "n": None}
            elif nome in historico:
                custo, espera, n = historico[nome]
                linha = {"custo_usd": custo, "espera_s": espera, "origem": "historico", "n": n}
                total += custo
            else:
                linha = {"custo_usd": None, "espera_s": None, "origem": "sem_historico", "n": None}
                sem_estimativa = True
            linhas.append({"etapa": nome, "rotulo": etapa.rotulo, **linha})
        settings = get_settings()
        gasto = custo_do_mes()
        sobra = max(settings.teto_mensal_usd - gasto, 0.0)
        tudo_guardado = all(linha["origem"] == "guardado" for linha in linhas)
        bloqueado = None
        if not tudo_guardado:
            if gasto >= settings.teto_mensal_usd:
                bloqueado = "limite_atingido"
            elif total > sobra:
                bloqueado = "estimativa_acima_da_sobra"
        return {
            "etapas": linhas,
            "total_usd": round(total, 6),
            "total_incompleto": sem_estimativa,
            "tudo_guardado": tudo_guardado,
            "teto_usd": settings.teto_mensal_usd,
            "gasto_mes_usd": round(gasto, 6),
            "sobra_usd": round(sobra, 6),
            "bloqueado": bloqueado,
        }

    # ----------------------------------------------------------------- processar
    def processar(self, corpo: dict) -> dict:
        self._exigir_chave()
        if corpo.get("confirmado") is not True:
            raise _erro(400, "confirmacao_ausente", "Confirme o custo antes de rodar.")
        envio = self._envio(corpo.get("envio_id"))
        pedidas = self._validar_etapas(corpo.get("etapas"))
        previsto = self.estimativa({"envio_id": corpo["envio_id"], "etapas": pedidas})
        if previsto["bloqueado"]:
            raise _erro(
                402,
                previsto["bloqueado"],
                "O limite de gasto do mês não permite esta execução. "
                "Tire etapas ou aumente TETO_MENSAL_USD no .env.",
            )
        shas = [i["sha"] for i in envio["arquivos"].values()]
        return self._iniciar(shas=shas, pedidas=pedidas)

    def continuar(self, job_id: str, corpo: dict) -> dict:
        self._exigir_chave()
        if corpo.get("confirmado") is not True:
            raise _erro(400, "confirmacao_ausente", "Confirme antes de continuar.")
        job = job_por_id(job_id)
        if job is None:
            raise _erro(404, "job_desconhecido", "Execução não encontrada.")
        pedidas = self._validar_etapas(corpo["etapas"]) if corpo.get("etapas") else None
        gasto = custo_do_mes()
        if gasto >= get_settings().teto_mensal_usd:
            raise _erro(402, "limite_atingido", "O limite de gasto do mês foi atingido.")
        return self._iniciar(job_ids=[job_id], pedidas=pedidas)

    def _iniciar(
        self,
        pedidas: list[str] | None,
        shas: list[str] | None = None,
        job_ids: list[str] | None = None,
    ) -> dict:
        todas = {e.nome for e in etapas_mod.etapas_para(etapas_mod.FOTO)}
        etapas_runner = None if pedidas is None or set(pedidas) == todas else pedidas
        with self._trava:
            if any(not e["fim"] for e in self._execucoes.values()):
                raise _erro(409, "ja_rodando", "Já existe uma execução rodando neste computador.")
            try:
                with lock_runner():
                    pass
            except RunnerJaEmExecucao:
                raise _erro(
                    409, "ja_rodando", "Já existe uma execução rodando neste computador."
                ) from None
            execucao_id = uuid.uuid4().hex
            execucao = {
                "id": execucao_id,
                "shas": shas or [],
                "job_ids": list(job_ids or []),
                "etapas": etapas_runner,
                "pedidas": pedidas,
                "inicio": time.monotonic(),
                "fim": False,
                "duracao_s": None,
                "erro": None,
                "limite": False,
                "sem_job": [],
                "iniciado_em": time.time(),
            }
            self._execucoes[execucao_id] = execucao
        threading.Thread(target=self._rodar, args=(execucao,), daemon=True).start()
        return {"job_id": execucao_id}

    def _rodar(self, execucao: dict) -> None:
        try:
            with lock_runner():
                ids = set(execucao["job_ids"])
                for sha in execucao["shas"]:
                    linha = arquivo_por_sha(sha)
                    if linha and linha["job_id"]:
                        job = job_por_id(linha["job_id"])
                        if job["status"] in ("concluido", "parcial"):
                            reprocessar_job(job["id"], com_cache=True)
                        elif job["status"] == "falhou":
                            enfileirar(job["id"])
                processar_inbox()
                for sha in execucao["shas"]:
                    linha = arquivo_por_sha(sha)
                    if linha and linha["job_id"]:
                        ids.add(linha["job_id"])
                    else:
                        execucao["sem_job"].append(sha)
                for job_id in list(execucao["job_ids"]):
                    job = job_por_id(job_id)
                    if job["status"] == "aguardando_humano":
                        aprovar_job(job_id)
                    elif job["status"] == "falhou":
                        enfileirar(job_id)
                    elif job["status"] in ("parcial", "concluido"):
                        reprocessar_job(job_id, com_cache=True)
                execucao["job_ids"] = sorted(ids)
                for job_id in execucao["job_ids"]:
                    drenar_fila(etapas=execucao["etapas"], somente_job=job_id)
        except RunnerJaEmExecucao:
            execucao["erro"] = "Já existe uma execução rodando neste computador."
        except Exception as erro:  # noqa: BLE001 - a tela mostra a frase, não o rastro
            texto = _sem_segredos(str(erro))
            execucao["limite"] = "orçamento mensal estourado" in texto
            execucao["erro"] = texto or type(erro).__name__
            registrar_evento(passo="ui", resultado="falhou", aviso=execucao["erro"])
        finally:
            execucao["duracao_s"] = round(time.monotonic() - execucao["inicio"], 1)
            execucao["fim"] = True

    # ---------------------------------------------------------------- acompanhar
    def job(self, execucao_id: str) -> dict:
        execucao = self._execucoes.get(execucao_id)
        if execucao is None:
            raise _erro(404, "execucao_desconhecida", "Execução não encontrada.")
        jobs = [job_por_id(j) for j in execucao["job_ids"]]
        jobs = [j for j in jobs if j is not None]
        vistos = _eventos_dos_jobs([j["id"] for j in jobs]) if jobs else []
        agentes = _agrupar_agentes(vistos)
        custo = round(sum(a["custo_usd"] for a in agentes), 6)
        guardados = sum(a["guardados"] for a in agentes)
        estado = self._estado_final(execucao, jobs) if execucao["fim"] else "rodando"
        avisos = []
        if execucao["sem_job"]:
            avisos.append(
                "Algumas fotos não viraram execução: a data da aula ficou ambígua. "
                "Coloque-as numa pasta com a data, AAAA-MM-DD, e envie de novo."
            )
        for job in jobs:
            entrada = ler_entrada_manifesto(job["id"]) or {}
            if entrada.get("precisa_revisao"):
                avisos.append(
                    "A conferência automática apontou problemas. Leia a nota com atenção."
                )
        espera = (
            execucao["duracao_s"]
            if execucao["fim"]
            else round(time.monotonic() - execucao["inicio"], 1)
        )
        return {
            "id": execucao_id,
            "estado": estado,
            "jobs": [
                {
                    "id": j["id"],
                    "status": j["status"],
                    "disciplina": j["disciplina"],
                    "data": j["data"],
                    "pergunta": j["aviso_reprocessamento"]
                    if j["status"] == "aguardando_humano"
                    else None,
                }
                for j in jobs
            ],
            "etapas": self._etapas_da_execucao(execucao, jobs, vistos, estado),
            "custo_usd": custo,
            "espera_s": espera,
            "guardados": guardados,
            "avisos": avisos,
            "erro": execucao["erro"] if estado in ("falhou", "limite") else None,
            "agentes": agentes,
        }

    def _estado_final(self, execucao: dict, jobs: list) -> str:
        if execucao["limite"]:
            return "limite"
        status = {j["status"] for j in jobs}
        if "aguardando_humano" in status:
            return "aguardando_humano"
        if "falhou" in status or execucao["erro"] or not jobs:
            return "falhou"
        if "parcial" in status:
            return "parcial"
        return "concluido"

    def _etapas_da_execucao(
        self, execucao: dict, jobs: list, vistos: list, estado: str
    ) -> list[dict]:
        pedidas = execucao["pedidas"]
        todas = etapas_mod.etapas_para(etapas_mod.FOTO)
        ativas = (
            set(etapas_mod.fechar_dependencias(pedidas)) if pedidas else {e.nome for e in todas}
        )
        feitas_por_job = [set(_etapas_feitas_do_job(j)) for j in jobs]
        resultado = []
        rodando_marcado = False
        for etapa in todas:
            if etapa.nome not in ativas:
                resultado.append({"nome": etapa.nome, "rotulo": etapa.rotulo, "estado": "pulada"})
                continue
            eventos = [
                e for e in vistos if str(e.get("passo", "")).partition(":")[0] in etapa.agentes
            ]
            feita = bool(jobs) and all(etapa.nome in f for f in feitas_por_job)
            if feita:
                guardada = bool(eventos) and all(e.get("cache_hit") for e in eventos)
                situacao = "guardado" if guardada else "feito"
            elif estado == "rodando":
                situacao = "espera" if rodando_marcado else "rodando"
                rodando_marcado = True
            elif estado in ("falhou", "limite") and not rodando_marcado:
                situacao = "falhou"
                rodando_marcado = True
            else:
                situacao = "espera"
            resultado.append({"nome": etapa.nome, "rotulo": etapa.rotulo, "estado": situacao})
        return resultado

    def execucao(self, execucao_id: str) -> dict:
        visao = self.job(execucao_id)
        return {
            "id": execucao_id,
            "custo_usd": visao["custo_usd"],
            "espera_s": visao["espera_s"],
            "agentes": visao["agentes"],
        }

    # --------------------------------------------------------------------- notas
    def notas(self) -> dict:
        saida = []
        for job in listar_jobs(limite=200):
            if job["tipo"] != "aula":
                continue
            entrada = ler_entrada_manifesto(job["id"]) or {}
            avisos = sum(
                bool(entrada.get(chave))
                for chave in ("precisa_revisao", "possivel_injecao", "avisos_conceitos", "pergunta")
            )
            saida.append(
                {
                    "id": job["id"],
                    "disciplina": job["disciplina"],
                    "data": job["data"],
                    "status": job["status"],
                    "avisos": avisos,
                }
            )
        return {"notas": saida}

    def _nota_do_job(self, job_id: str) -> tuple[dict, dict]:
        job = job_por_id(job_id)
        if job is None:
            raise _erro(404, "nota_desconhecida", "Nota não encontrada.")
        return dict(job), ler_entrada_manifesto(job_id) or {}

    def _texto_da_nota(self, entrada: dict) -> tuple[str | None, str | None]:
        caminho = entrada.get("caminho_nota")
        if not caminho:
            return None, None
        staging = get_settings().staging_dir
        resolvido = dentro_da_pasta(Path(caminho), staging)
        try:
            return ler_texto(resolvido), resolvido.name
        except FileNotFoundError:
            return None, None

    def nota(self, job_id: str) -> dict:
        job, entrada = self._nota_do_job(job_id)
        texto, nome = self._texto_da_nota(entrada)
        fotos = [f["nome_final"] for f in fotos_do_job(job_id)]
        return {
            "id": job_id,
            "status": job["status"],
            "disciplina": job["disciplina"],
            "arquivo": nome,
            "texto": texto,
            "duvidas": entrada.get("duvidas") or [],
            "avisos": {
                "precisa_revisao": bool(entrada.get("precisa_revisao")),
                "problemas_validacao": entrada.get("problemas_validacao") or [],
                "possivel_injecao": bool(entrada.get("possivel_injecao")),
                "avisos_conceitos": entrada.get("avisos_conceitos") or [],
                "pergunta": entrada.get("pergunta"),
            },
            "fotos": len(fotos),
            "pasta_de_revisao": "estudos/output/",
            "flashcards": f"estudos/flashcards/{job['disciplina']}/",
        }

    def foto(self, job_id: str, numero: int) -> tuple[bytes, str]:
        job, _ = self._nota_do_job(job_id)
        fotos = sorted(fotos_do_job(job_id), key=lambda f: f["nome_final"])
        if not 1 <= numero <= len(fotos):
            raise _erro(404, "foto_desconhecida", "Foto não encontrada.")
        settings = get_settings()
        base = settings.agent_data_dir / "estudos" / "processed"
        caminho = dentro_da_pasta(base / job["disciplina"] / fotos[numero - 1]["nome_final"], base)
        tipo = TIPOS_DE_IMAGEM.get(caminho.suffix.lower())
        if tipo is None or not caminho.exists():
            raise _erro(404, "foto_desconhecida", "Foto não encontrada.")
        from core.fileops import ler

        return ler(caminho), tipo

    def baixar(self, job_id: str) -> tuple[bytes, str]:
        _, entrada = self._nota_do_job(job_id)
        texto, nome = self._texto_da_nota(entrada)
        if texto is None or nome is None:
            raise _erro(404, "sem_nota", "Esta execução ainda não tem nota.")
        return texto.encode("utf-8"), nome

    # --------------------------------------------------------- em desenvolvimento
    def duvidas(self) -> dict:
        raise _recurso_desligado()

    def economia(self) -> dict:
        raise _recurso_desligado()


# ----------------------------------------------------------------------- auxiliares
def _sem_segredos(texto: str) -> str:
    import os

    chave = os.environ.get("ANTHROPIC_API_KEY")
    return texto.replace(chave, "[chave omitida]") if chave else texto


def _etapas_feitas_do_job(job) -> list[str]:
    """Etapas de foto já concluídas por um job. Vazio em `etapas_feitas` significa tudo."""
    if job["status"] in ("concluido", "promovido"):
        marcadas = job["etapas_feitas"]
        if marcadas:
            return marcadas.split(",")
        return [e.nome for e in etapas_mod.etapas_para(etapas_mod.FOTO)]
    if job["status"] == "parcial" and job["etapas_feitas"]:
        return job["etapas_feitas"].split(",")
    return []


def _ler_eventos() -> list[dict]:
    eventos = []
    for arquivo in sorted(get_settings().logs_dir.glob("*.jsonl")):
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            try:
                eventos.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    return eventos


def _eventos_dos_jobs(job_ids: list[str]) -> list[dict]:
    alvo = set(job_ids)
    return [e for e in _ler_eventos() if e.get("job") in alvo]


def _historico_por_etapa() -> dict[str, tuple[float, float, int]]:
    """Mediana de custo e de tempo por etapa, nas últimas execuções que gastaram de verdade.

    Só conta evento sem `cache_hit`. Sem nenhuma execução, a etapa não aparece: a tela
    mostra "sem estimativa" em vez de inventar um valor.
    """
    por_agente: dict[str, str] = {}
    for etapa in etapas_mod.etapas_para(etapas_mod.FOTO):
        for agente in etapa.agentes:
            por_agente.setdefault(agente, etapa.nome)
    somas: dict[str, dict[str, list[float]]] = {}
    for evento in _ler_eventos():
        job = evento.get("job")
        base = str(evento.get("passo", "")).partition(":")[0]
        etapa = por_agente.get(base)
        if not job or etapa is None or evento.get("cache_hit") or evento.get("custo_usd") is None:
            continue
        atual = somas.setdefault(etapa, {}).setdefault(job, [0.0, 0.0])
        atual[0] += float(evento["custo_usd"])
        atual[1] += float(evento.get("duracao_ms") or 0) / 1000
    resultado = {}
    for etapa, por_job in somas.items():
        recentes = list(por_job.values())[-JANELA_HISTORICO:]
        if recentes:
            resultado[etapa] = (
                round(statistics.median(c for c, _ in recentes), 6),
                round(statistics.median(t for _, t in recentes), 1),
                len(recentes),
            )
    return resultado


def _agrupar_agentes(eventos: list[dict]) -> list[dict]:
    grupos: dict[tuple[str, str | None], dict] = {}
    for e in eventos:
        passo = str(e.get("passo", ""))
        if passo.startswith(("fileops", "runner", "ingestao", "ui")) or not passo:
            continue
        chave = (passo.partition(":")[0], e.get("modelo"))
        g = grupos.setdefault(
            chave,
            {
                "agente": chave[0],
                "modelo": chave[1],
                "tokens_in": 0,
                "tokens_out": 0,
                "custo_usd": 0.0,
                "guardados": 0,
                "duracao_s": None,
            },
        )
        g["tokens_in"] += e.get("tokens_in") or 0
        g["tokens_out"] += e.get("tokens_out") or 0
        g["custo_usd"] += e.get("custo_usd") or 0.0
        if e.get("cache_hit"):
            g["guardados"] += 1
        if e.get("duracao_ms") is not None:
            g["duracao_s"] = (g["duracao_s"] or 0) + e["duracao_ms"] / 1000
    return list(grupos.values())
