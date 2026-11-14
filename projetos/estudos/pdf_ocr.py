"""Leitura por visão de PDF que não tem camada de texto.

O pipeline nunca cai em visão sozinho — extrair 100 páginas custa dinheiro de
verdade e a qualidade depende do material. Este caminho é sempre **pedido
explicitamente**, com o custo estimado antes.

Quando vale a pena: as notas de aula antigas da MAT1 são **manuscrito vetorial**
exportado de tablet. Não têm texto nem imagem embutida — só traços — mas são o
material do professor, o topo da hierarquia de fontes. Rasterizar e ler com o
mesmo `AgenteExtrator` que lê foto de lousa recupera exatamente esse conteúdo.

O resultado é gravado no cache padrão (`cache_dir/pdf/<sha>/texto.txt`), então
todo o resto do pipeline consome o texto sem saber que ele veio de visão.
"""

from dataclasses import dataclass, field
from pathlib import Path

from core.config import get_settings
from core.estado import marcar_pdf_ocr
from core.fileops import escrever_texto
from core.images.preprocess import preparar
from core.logging import registrar_evento
from core.pdf import renderizar_paginas
from projetos.estudos.agentes import AgenteExtrator
from projetos.estudos.pdf_ingestao import RegistroPdf, _caminho_texto_direto
from projetos.estudos.schemas import EntradaImagem

#: abaixo disto, por página, a camada de texto é ruído de OCR e não conteúdo
PISO_CHARS_POR_PAGINA = 400

#: acima disso, o custo deixa de ser trivial e a decisão passa a ser sua
LIMITE_PAGINAS_SEM_CONFIRMACAO = 40

#: média observada no histórico deste projeto, por página de manuscrito
CUSTO_ESTIMADO_POR_PAGINA_USD = 0.022


class OcrRecusado(Exception):
    pass


@dataclass
class ResultadoOcr:
    registro: RegistroPdf
    paginas_lidas: int = 0
    chars: int = 0
    caminho_texto: Path | None = None
    avisos: list[str] = field(default_factory=list)


def _cache_tem_texto(sha256: str) -> bool:
    """Existe cache COM conteúdo — arquivo vazio não conta como texto recuperado."""
    caminho = _caminho_texto_direto(sha256)
    return caminho.exists() and bool(caminho.read_text(encoding="utf-8").strip())


def precisa_de_visao(registro: RegistroPdf) -> bool:
    """PDF sem texto nativo e sem texto já recuperado por visão."""
    return not registro.tem_texto_nativo and not _cache_tem_texto(registro.sha256)


def texto_suspeito(registro: RegistroPdf) -> bool:
    """Tem camada de texto, mas rala demais para ser um documento de verdade.

    `precisa_de_visao` responde "não" para todo PDF com camada de texto, e há um caso em
    que isso erra feio: `Copy of simulado Ap1.pdf` são seis páginas manuscritas com 1.816
    caracteres de OCR embutido — texto suficiente para o PDF passar por legível e
    ilegível o bastante para não servir para nada ("quest4. sortA=S nloghHeap Sort"). O
    resultado é o pipeline pular por visão exatamente o arquivo que mais precisa dela.

    Isto não decide nada sozinho: só levanta a mão para o comando avisar e oferecer
    `--visao`. Leitura por visão custa dinheiro e continua sendo escolha humana.
    """
    if registro.paginas <= 0:
        return False
    return registro.chars_total / registro.paginas < PISO_CHARS_POR_PAGINA


def custo_estimado(registros: list[RegistroPdf]) -> tuple[int, float]:
    paginas = sum(r.paginas for r in registros)
    return paginas, paginas * CUSTO_ESTIMADO_POR_PAGINA_USD


def _texto_da_extracao(extracao, numero_pagina: int) -> str:
    linhas = [f"--- página {numero_pagina} ---"]
    for bloco in extracao.blocos:
        texto = bloco.latex if bloco.tipo == "formula" and bloco.latex else bloco.conteudo
        flags = f" [{', '.join(bloco.flags)}]" if bloco.flags else ""
        linhas.append(f"- ({bloco.tipo}) {texto}{flags}")
    return "\n".join(linhas)


def extrair_por_visao(job_id: str, registro: RegistroPdf, force: bool = False) -> ResultadoOcr:
    """Rasteriza e lê cada página com o extrator de visão. Cacheado por hash do PDF."""
    resultado = ResultadoOcr(registro=registro)
    destino_texto = _caminho_texto_direto(registro.sha256)

    if _cache_tem_texto(registro.sha256) and not force:
        resultado.caminho_texto = destino_texto
        resultado.avisos.append("texto já disponível — nada a fazer")
        return resultado

    if registro.paginas > LIMITE_PAGINAS_SEM_CONFIRMACAO and not force:
        raise OcrRecusado(
            f"{registro.nome_arquivo} tem {registro.paginas} páginas "
            f"(acima de {LIMITE_PAGINAS_SEM_CONFIRMACAO}) — use --force se for mesmo isso"
        )

    pasta_imagens = get_settings().cache_dir / "pdf" / registro.sha256 / "render"
    imagens = renderizar_paginas(Path(registro.caminho), 1, registro.paginas, pasta_imagens)

    partes = []
    for numero, imagem in enumerate(imagens, start=1):
        preparada = preparar(imagem, "papel")
        extracao = AgenteExtrator().run(
            job_id,
            EntradaImagem(caminho=str(preparada)),
            sufixo_passo=f"{registro.sha256[:12]}_p{numero:04d}",
        )
        partes.append(_texto_da_extracao(extracao, numero))
        resultado.paginas_lidas += 1

    texto = "\n\n".join(partes) + "\n"
    escrever_texto(destino_texto, texto)
    marcar_pdf_ocr(registro.sha256)

    resultado.caminho_texto = destino_texto
    resultado.chars = len(texto)
    registrar_evento(
        job=job_id,
        passo="pdf_ocr",
        resultado=f"{registro.nome_arquivo}: {resultado.paginas_lidas} páginas, {len(texto)} chars",
    )
    return resultado
