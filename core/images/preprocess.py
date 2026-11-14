import hashlib
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from core.config import get_settings
from core.fileops import escrever, ler
from core.logging import registrar_evento

LADO_MAXIMO = 1568
QUALIDADE_JPEG = 85
AREA_MINIMA_QUADRILATERO = 0.2  # fração da área total da imagem
GAMMA_PROJECAO = 1.6


def _pil_para_cv2(imagem: Image.Image) -> np.ndarray:
    array = np.array(imagem.convert("RGB"))
    return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)


def _cv2_para_pil(imagem_cv: np.ndarray) -> Image.Image:
    rgb = cv2.cvtColor(imagem_cv, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _maior_quadrilatero(imagem_cv: np.ndarray) -> np.ndarray | None:
    cinza = cv2.cvtColor(imagem_cv, cv2.COLOR_BGR2GRAY)
    borrado = cv2.GaussianBlur(cinza, (5, 5), 0)
    bordas = cv2.dilate(cv2.Canny(borrado, 50, 150), None, iterations=2)

    contornos, _ = cv2.findContours(bordas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return None

    maior = max(contornos, key=cv2.contourArea)
    area_imagem = imagem_cv.shape[0] * imagem_cv.shape[1]
    if cv2.contourArea(maior) < AREA_MINIMA_QUADRILATERO * area_imagem:
        return None

    perimetro = cv2.arcLength(maior, True)
    aproximado = cv2.approxPolyDP(maior, 0.02 * perimetro, True)
    if len(aproximado) != 4:
        return None

    return aproximado.reshape(4, 2).astype("float32")


def _ordenar_pontos(pontos: np.ndarray) -> np.ndarray:
    soma = pontos.sum(axis=1)
    diferenca = np.diff(pontos, axis=1).flatten()
    return np.array(
        [
            pontos[np.argmin(soma)],
            pontos[np.argmin(diferenca)],
            pontos[np.argmax(soma)],
            pontos[np.argmax(diferenca)],
        ],
        dtype="float32",
    )


def _corrigir_perspectiva(imagem_cv: np.ndarray, pontos: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = _ordenar_pontos(pontos)
    largura = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    altura = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))

    destino = np.array(
        [[0, 0], [largura - 1, 0], [largura - 1, altura - 1], [0, altura - 1]],
        dtype="float32",
    )
    matriz = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl], dtype="float32"), destino)
    return cv2.warpPerspective(imagem_cv, matriz, (largura, altura))


def _aplicar_clahe(imagem_cv: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(imagem_cv, cv2.COLOR_BGR2LAB)
    luz, a, b = cv2.split(lab)
    luz = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(luz)
    return cv2.cvtColor(cv2.merge((luz, a, b)), cv2.COLOR_LAB2BGR)


def _receita_quadro(imagem: Image.Image) -> Image.Image:
    imagem_cv = _pil_para_cv2(imagem)
    quadrilatero = _maior_quadrilatero(imagem_cv)
    if quadrilatero is None:
        registrar_evento(passo="preprocess.quadro", resultado="fallback_sem_quadrilatero_confiavel")
        return imagem

    corrigido = _corrigir_perspectiva(imagem_cv, quadrilatero)
    realcado = _aplicar_clahe(corrigido)
    return _cv2_para_pil(realcado)


def _crop_margens(imagem_cv: np.ndarray) -> np.ndarray:
    cinza = cv2.cvtColor(imagem_cv, cv2.COLOR_BGR2GRAY)
    _, limiar = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    coords = cv2.findNonZero(limiar)
    if coords is None:
        return imagem_cv

    x, y, w, h = cv2.boundingRect(coords)
    margem = int(0.02 * max(imagem_cv.shape[:2]))
    x0, y0 = max(x - margem, 0), max(y - margem, 0)
    x1 = min(x + w + margem, imagem_cv.shape[1])
    y1 = min(y + h + margem, imagem_cv.shape[0])
    return imagem_cv[y0:y1, x0:x1]


def _binarizacao_suave(imagem_cv: np.ndarray) -> np.ndarray:
    cinza = cv2.cvtColor(imagem_cv, cv2.COLOR_BGR2GRAY)
    limiar = cv2.adaptiveThreshold(
        cinza, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 25, 15
    )
    suavizado = cv2.addWeighted(cinza, 0.4, limiar, 0.6, 0)
    return cv2.cvtColor(suavizado, cv2.COLOR_GRAY2BGR)


def _receita_papel(imagem: Image.Image) -> Image.Image:
    imagem_cv = _pil_para_cv2(imagem)
    cortado = _crop_margens(imagem_cv)
    suavizado = _binarizacao_suave(cortado)
    return _cv2_para_pil(suavizado)


def _corrigir_gamma(imagem_cv: np.ndarray, gamma: float = GAMMA_PROJECAO) -> np.ndarray:
    inv_gamma = 1.0 / gamma
    tabela = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)]).astype("uint8")
    return cv2.LUT(imagem_cv, tabela)


def _receita_projecao(imagem: Image.Image) -> Image.Image:
    imagem_cv = _pil_para_cv2(imagem)
    corrigido = _corrigir_gamma(imagem_cv)
    return _cv2_para_pil(corrigido)


def _redimensionar(imagem: Image.Image, lado_maximo: int = LADO_MAXIMO) -> Image.Image:
    largura, altura = imagem.size
    maior_lado = max(largura, altura)
    if maior_lado <= lado_maximo:
        return imagem
    fator = lado_maximo / maior_lado
    novo_tamanho = (round(largura * fator), round(altura * fator))
    return imagem.resize(novo_tamanho, Image.LANCZOS)


def _receita_nenhuma(imagem: Image.Image) -> Image.Image:
    return imagem


_RECEITAS = {
    "nenhuma": _receita_nenhuma,
    "quadro": _receita_quadro,
    "papel": _receita_papel,
    "projecao": _receita_projecao,
}


def _caminho_cache(hash_conteudo: str, receita: str) -> Path:
    chave = hashlib.sha256(f"{hash_conteudo}:{receita}".encode()).hexdigest()
    return get_settings().cache_dir / "preproc" / f"{chave}.jpg"


def preparar(caminho: Path, receita: str) -> Path:
    if receita not in _RECEITAS:
        raise ValueError(f"receita desconhecida: {receita}")

    conteudo_original = ler(caminho)
    hash_conteudo = hashlib.sha256(conteudo_original).hexdigest()
    destino = _caminho_cache(hash_conteudo, receita)

    if destino.exists():
        return destino

    imagem = Image.open(io.BytesIO(conteudo_original))
    imagem = ImageOps.exif_transpose(imagem)  # robustez; no-op p/ fotos já processadas no P1
    imagem = _redimensionar(imagem)
    imagem = _RECEITAS[receita](imagem)

    buffer = io.BytesIO()
    imagem.convert("RGB").save(buffer, format="JPEG", quality=QUALIDADE_JPEG)
    escrever(destino, buffer.getvalue())

    return destino
