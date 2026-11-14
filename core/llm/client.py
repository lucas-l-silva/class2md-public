import anthropic
from pydantic import BaseModel, ValidationError

from core.config import get_settings

MAX_RETRIES_TRANSITORIOS = 5  # 429/5xx: o SDK já faz backoff exponencial internamente
MAX_TOKENS_PADRAO = 4096


class SaidaInvalida(Exception):
    pass


class SaidaTruncada(Exception):
    pass


def criar_cliente() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=get_settings().anthropic_api_key,
        max_retries=MAX_RETRIES_TRANSITORIOS,
    )


def envelopar_dados(texto: str, fonte: str) -> str:
    """Envolve conteúdo de terceiros (PDF, foto, web) em <dados>, marcando-o como DADO,
    nunca instrução — neutraliza tentativas de fechar a tag cedo (prompt injection)."""
    fonte_segura = fonte.replace('"', "'")
    texto_seguro = texto.replace("</dados", "<\\/dados")
    return f'<dados fonte="{fonte_segura}">\n{texto_seguro}\n</dados>'


def blocos_system(estatico: str, dinamico: str | None = None) -> list[dict]:
    blocos = [{"type": "text", "text": estatico, "cache_control": {"type": "ephemeral"}}]
    if dinamico:
        blocos.append({"type": "text", "text": dinamico})
    return blocos


def chamar_estruturado(
    modelo: str,
    system_blocks: list[dict],
    messages: list[dict],
    saida_model: type[BaseModel],
    cliente: anthropic.Anthropic | None = None,
    max_tentativas: int = 2,
    max_tokens: int = MAX_TOKENS_PADRAO,
) -> tuple[BaseModel, anthropic.types.Message]:
    cliente = cliente or criar_cliente()
    tool = {
        "name": "emitir_resultado",
        "description": f"Emite o resultado estruturado no formato {saida_model.__name__}.",
        "input_schema": saida_model.model_json_schema(),
    }

    mensagens = list(messages)
    ultimo_erro: ValidationError | None = None

    for tentativa in range(1, max_tentativas + 1):
        resposta = cliente.messages.create(
            model=modelo,
            system=system_blocks,
            messages=mensagens,
            tools=[tool],
            tool_choice={"type": "tool", "name": "emitir_resultado"},
            max_tokens=max_tokens,
        )

        if resposta.stop_reason == "max_tokens":
            raise SaidaTruncada(
                f"saída truncada: max_tokens={max_tokens} atingido — aumente o limite deste agente"
            )

        bloco_tool = next((b for b in resposta.content if b.type == "tool_use"), None)
        if bloco_tool is None:
            raise SaidaInvalida("resposta não contém bloco tool_use")

        try:
            saida = saida_model.model_validate(bloco_tool.input)
            return saida, resposta
        except ValidationError as erro:
            ultimo_erro = erro
            if tentativa == max_tentativas:
                break
            # Um tool_result para CADA tool_use da resposta, não só para o que falhou
            # na validação. A API recusa a mensagem seguinte se sobrar qualquer
            # tool_use sem par ("tool_use ids were found without tool_result blocks"),
            # e o modelo às vezes emite mais de um bloco — a retentativa morria em 400
            # justamente quando era mais necessária.
            resultados = [
                {
                    "type": "tool_result",
                    "tool_use_id": bloco.id,
                    "content": (
                        f"Saída inválida, corrija e reenvie: {erro}"
                        if bloco.id == bloco_tool.id
                        else "Ignorado: emita um único resultado."
                    ),
                    "is_error": True,
                }
                for bloco in resposta.content
                if bloco.type == "tool_use"
            ]
            mensagens = [
                *mensagens,
                {"role": "assistant", "content": resposta.content},
                {"role": "user", "content": resultados},
            ]

    raise SaidaInvalida(f"saída inválida após {max_tentativas} tentativa(s): {ultimo_erro}")
