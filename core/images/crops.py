import io
from pathlib import Path

from PIL import Image

from core.fileops import ler


def recortar(
    imagem: Path,
    bbox_normalizado: tuple[float, float, float, float],
    margem: float = 0.03,
) -> bytes:
    conteudo = ler(imagem)
    pil_imagem = Image.open(io.BytesIO(conteudo))
    largura, altura = pil_imagem.size

    x0, y0, x1, y1 = bbox_normalizado
    largura_bbox = x1 - x0
    altura_bbox = y1 - y0

    x0 = max(0.0, x0 - largura_bbox * margem)
    y0 = max(0.0, y0 - altura_bbox * margem)
    x1 = min(1.0, x1 + largura_bbox * margem)
    y1 = min(1.0, y1 + altura_bbox * margem)

    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"bbox inválido após aplicar margem: {(x0, y0, x1, y1)}")

    caixa_pixels = (
        round(x0 * largura),
        round(y0 * altura),
        round(x1 * largura),
        round(y1 * altura),
    )
    recorte = pil_imagem.crop(caixa_pixels)

    buffer = io.BytesIO()
    recorte.save(buffer, format="PNG")
    return buffer.getvalue()
