from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas


def criar_pdf(
    caminho: Path,
    paginas: int,
    texto_por_pagina: str | list[str] = "",
    toc: list[tuple[str, int, int]] | None = None,
    landscape_: bool = False,
    so_imagem: bool = False,
) -> None:
    """Gera um PDF real (via reportlab) para testes, sem versionar binário nenhum.

    - `texto_por_pagina`: string única repetida em todas as páginas, ou lista (1 por página).
    - `toc`: lista de (titulo, nivel, pagina_1_based) — vira outline nativo (bookmarks).
    - `so_imagem`: desenha só um retângulo, sem texto (simula PDF escaneado sem texto nativo).
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tamanho = landscape(A4) if landscape_ else A4
    c = canvas.Canvas(str(caminho), pagesize=tamanho)

    textos = (
        texto_por_pagina if isinstance(texto_por_pagina, list) else [texto_por_pagina] * paginas
    )

    for pagina_1based in range(1, paginas + 1):
        if so_imagem:
            c.rect(50, 50, 100, 100, fill=1)
        else:
            texto = textos[pagina_1based - 1] if pagina_1based - 1 < len(textos) else ""
            y = tamanho[1] - 60
            for linha in texto.splitlines() or [""]:
                c.drawString(50, y, linha[:110])
                y -= 14
        c.showPage()

    c.save()

    if toc:
        # reportlab escreve bookmarks só via addOutlineEntry durante a geração; para não
        # duplicar a geração de conteúdo, usamos pypdf para adicionar o outline depois.
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(str(caminho))
        writer = PdfWriter()
        for pagina in reader.pages:
            writer.add_page(pagina)

        pilha: list[tuple[int, object]] = []
        for titulo, nivel, pagina_1based in toc:
            while pilha and pilha[-1][0] >= nivel:
                pilha.pop()
            pai = pilha[-1][1] if pilha else None
            item = writer.add_outline_item(titulo, pagina_1based - 1, parent=pai)
            pilha.append((nivel, item))

        with open(caminho, "wb") as arquivo:
            writer.write(arquivo)
