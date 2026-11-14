import hashlib
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

from core.config import get_settings
from core.estado import job_por_id
from core.fileops import escrever_texto, ler_texto
from core.llm.client import MAX_TOKENS_PADRAO, blocos_system, chamar_estruturado
from core.llm.custos import registrar_custo, verificar_orcamento
from core.llm.tiers import Tier, modelo_do_tier
from core.logging import registrar_evento

TEntrada = TypeVar("TEntrada", bound=BaseModel)
TSaida = TypeVar("TSaida", bound=BaseModel)


class Agente(ABC, Generic[TEntrada, TSaida]):
    nome: str
    tier: Tier
    prompt_file: Path
    Entrada: type[TEntrada]
    Saida: type[TSaida]
    max_tokens: int = MAX_TOKENS_PADRAO

    @abstractmethod
    def montar_mensagens(self, entrada: TEntrada) -> list[dict]: ...

    def system_dinamico(self, entrada: TEntrada) -> str | None:
        return None

    def hash_adicional(self, entrada: TEntrada | None = None) -> str:
        """Sobrescrito por agentes como o A5, que incluem o hash do template na chave de cache.

        Recebe a entrada porque o template pode depender dela (o compositor escolhe o
        template pelo perfil da disciplina): sem isso, trocar de perfil não invalidaria
        o cache e a nota sairia com o template do perfil anterior.
        """
        return ""

    def _prompt_version_e_texto(self, entrada: TEntrada | None = None) -> tuple[int, str]:
        # prompt_file é conteúdo do repo (versionado), não dado de usuário — lido direto,
        # fora do core/fileops.py (que existe para proteger a allowlist de staging/dados).
        conteudo = self.prompt_file.read_text(encoding="utf-8")
        primeira_linha, _, resto = conteudo.partition("\n")
        prefixo = "PROMPT_VERSION:"
        if not primeira_linha.startswith(prefixo):
            raise ValueError(f"{self.prompt_file}: primeira linha deve ser '{prefixo} N'")
        return int(primeira_linha.removeprefix(prefixo).strip()), resto.strip()

    def identidade_da_entrada(self, entrada: TEntrada) -> str:
        """Texto que identifica a entrada na chave de cache.

        Agentes de visão sobrescrevem para usar o hash do conteúdo da imagem: o caminho
        muda quando a pasta de dados muda, e o conteúdo não.
        """
        return entrada.model_dump_json()

    def _chave_cache(self, entrada: TEntrada) -> str:
        versao, _ = self._prompt_version_e_texto(entrada)
        modelo = modelo_do_tier(self.tier)
        bruto = (
            f"{self.identidade_da_entrada(entrada)}:{self.nome}:{versao}:{modelo}"
            f":{self.hash_adicional(entrada)}"
        )
        return hashlib.sha256(bruto.encode()).hexdigest()

    def _caminho_cache(self, chave: str) -> Path:
        return get_settings().cache_dir / "agentes" / self.nome / f"{chave}.json"

    def _ler_cache(self, chave: str) -> TSaida | None:
        try:
            conteudo = ler_texto(self._caminho_cache(chave))
        except FileNotFoundError:
            return None
        return self.Saida.model_validate_json(conteudo)

    def _gravar_cache(self, chave: str, saida: TSaida) -> None:
        escrever_texto(self._caminho_cache(chave), saida.model_dump_json())

    def run(self, job_id: str, entrada: TEntrada, sufixo_passo: str | None = None) -> TSaida:
        # sufixo_passo distingue múltiplas invocações do mesmo agente dentro de um job
        # (ex. uma foto por chamada) na tabela `passos`, sem afetar a chave de cache —
        # essa já é única por foto porque `entrada` carrega o caminho/hash da imagem.
        nome_passo = f"{self.nome}:{sufixo_passo}" if sufixo_passo else self.nome
        chave = self._chave_cache(entrada)

        # `reprocessar` marca o job em jobs.forcar_reprocessamento ("*" = todos os passos,
        # ou o nome de um agente específico). Isso só pula a LEITURA do cache — a gravação
        # abaixo continua acontecendo, então o resultado novo já fica disponível pra próxima vez.
        job = job_por_id(job_id)
        marca = job["forcar_reprocessamento"] if job is not None else None
        ignorar_cache = marca is not None and marca in ("*", self.nome)

        do_cache = None if ignorar_cache else self._ler_cache(chave)
        if do_cache is not None:
            registrar_evento(
                job=job_id,
                passo=nome_passo,
                modelo=modelo_do_tier(self.tier),
                cache_hit=True,
                resultado="ok",
            )
            return do_cache

        verificar_orcamento()

        _, prompt_estatico = self._prompt_version_e_texto(entrada)
        system = blocos_system(prompt_estatico, self.system_dinamico(entrada))
        mensagens = self.montar_mensagens(entrada)

        inicio = time.monotonic()
        saida, resposta = chamar_estruturado(
            modelo_do_tier(self.tier),
            system,
            mensagens,
            self.Saida,
            max_tokens=self.max_tokens,
        )
        duracao_ms = int((time.monotonic() - inicio) * 1000)

        registrar_custo(
            job_id,
            nome_passo,
            self.tier,
            tokens_in=resposta.usage.input_tokens,
            tokens_out=resposta.usage.output_tokens,
            tokens_cache_leitura=getattr(resposta.usage, "cache_read_input_tokens", 0) or 0,
            cache_hit=False,
            duracao_ms=duracao_ms,
        )

        self._gravar_cache(chave, saida)
        return saida
