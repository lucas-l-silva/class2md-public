from enum import Enum

from core.config import get_settings


class Tier(str, Enum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


def modelo_do_tier(tier: Tier) -> str:
    return get_settings().modelos[tier.value]


def precos_do_tier(tier: Tier) -> dict[str, float]:
    return get_settings().precos_por_milhao[tier.value]
