"""De que dia é a foto: pasta com data, data escrita na folha, EXIF — nessa ordem.

O EXIF diz quando a foto foi **tirada**, não de que aula ela é. Para a lousa, fotografada em
sala, as duas coisas coincidem. Para a anotação manuscrita, fotografada dias depois, não: as
três folhas de FIS1 fotografadas num domingo, 13/09, eram das aulas de 20/08, 03/09 e 10/09, e
o EXIF sozinho as juntaria numa aula que não existiu.

A decisão importa **antes** da ingestão, porque a ingestão move a foto do inbox e apaga o
EXIF. Por isso tudo aqui é conservador:

1. **Pasta `inbox/<SIGLA>/AAAA-MM-DD/`** vence tudo. É a válvula manual, sem modelo.
2. **EXIF num dia de aula** é aceito sem mais perguntas: é o caso comum, e não custa nada.
3. **EXIF fora de dia de aula** dispara a leitura da data escrita no topo da folha (Sonnet,
   zoom dos dois cantos superiores, cacheada por hash). A data é tirada **em Python** do texto
   que o modelo transcreveu, e não do campo de data que ele preenche: na primeira execução o
   Haiku transcreveu `09.09.26` e devolveu `2026-09-08`, e a folha dizia `02.09.26`.
4. **Data escrita que não é dia de aula** — `02.09.26` numa disciplina de terça e quinta — vai
   para o dia de aula adjacente que tem foto de lousa. Se nenhum ou os dois tiverem, a data é
   **ambígua** e a foto fica no inbox: decidir em silêncio é o que este módulo existe para
   evitar, e deixar a foto onde está é a única decisão que se desfaz.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageOps

from core.config import get_settings
from core.logging import registrar_evento
from projetos.estudos.disciplinas import (
    DisciplinaDesconhecida,
    RegistroAusente,
    RegistroInvalido,
)
from projetos.estudos.disciplinas import (
    disciplina as disciplina_do_registro,
)

DIAS_DA_SEMANA = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6}

#: `inbox/FIS1/2026-08-20/foto.jpg`
RE_PASTA_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: quantos dias para cada lado uma data escrita pode ser deslocada até um dia de aula
JANELA_RECONCILIACAO = 2

#: data escrita mais antiga que isso em relação ao EXIF é leitura errada, não aula antiga
LIMITE_ATRASO_DIAS = 200

#: o canto superior de cada lado, onde se escreve disciplina e data. A faixa inteira reduzida
#: a 1024 px deixava a data com uns 15 px de altura — ilegível para dígito manuscrito.
FRACAO_ALTURA_CANTO = 0.15
FRACAO_LARGURA_CANTO = 0.45
LARGURA_RECORTE = 1024

#: `02.09.26`, `2/9/2026`, `10-09-26`
RE_DATA_ESCRITA = re.compile(r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2}(?:\d{2})?)\b")


@dataclass(frozen=True)
class Datacao:
    """A data escolhida e de onde ela veio. `data=None` significa ambígua: não ingerir."""

    data: date | None
    fonte: str  # pasta | exif | escrita | escrita_reconciliada | ambigua
    aviso: str = ""


def data_da_pasta(caminho: Path) -> date | None:
    if RE_PASTA_DATA.match(caminho.parent.name):
        return date.fromisoformat(caminho.parent.name)
    return None


def dias_de_aula(sigla: str) -> set[int] | None:
    """Dias da semana com aula. None quando não há registro: aí não dá para julgar o EXIF."""
    try:
        item = disciplina_do_registro(sigla)
    except (RegistroAusente, RegistroInvalido, DisciplinaDesconhecida):
        return None
    dias = {DIAS_DA_SEMANA[h.dia] for h in item.horarios if h.tipo == "aula"}
    return dias or None


def reconciliar(escrita: date, dias: set[int], datas_com_foto: set[date]) -> Datacao:
    """Data escrita fora de dia de aula → o dia de aula vizinho que tem foto de lousa."""
    candidatos = [
        escrita + timedelta(days=delta)
        for delta in range(-JANELA_RECONCILIACAO, JANELA_RECONCILIACAO + 1)
        if delta != 0 and (escrita + timedelta(days=delta)).weekday() in dias
    ]
    com_foto = [c for c in candidatos if c in datas_com_foto]
    if len(com_foto) == 1:
        escolhida = com_foto[0]
        return Datacao(
            escolhida,
            "escrita_reconciliada",
            f"a folha diz {escrita:%d/%m}, que não é dia de aula; atribuída a "
            f"{escolhida:%d/%m}, o dia de aula vizinho com fotos da lousa",
        )
    vizinhos = ", ".join(f"{c:%d/%m}" for c in candidatos) or "nenhum"
    return Datacao(
        None,
        "ambigua",
        f"a folha diz {escrita:%d/%m}, que não é dia de aula, e não há um único dia de aula "
        f"vizinho com fotos da lousa (vizinhos: {vizinhos}). Mova a foto para "
        f"inbox/<SIGLA>/AAAA-MM-DD/ com a data certa.",
    )


def datar(
    caminho: Path,
    sigla: str,
    exif: datetime,
    datas_com_foto: set[date],
    ler_escrita: Callable[[Path], date | None],
) -> Datacao:
    """A decisão inteira. `ler_escrita` é injetado para os testes não chamarem modelo."""
    da_pasta = data_da_pasta(caminho)
    if da_pasta is not None:
        return Datacao(da_pasta, "pasta")

    dias = dias_de_aula(sigla)
    if dias is None or exif.weekday() in dias:
        return Datacao(exif.date(), "exif")

    escrita = ler_escrita(caminho)
    if escrita is not None and not (
        timedelta(0) <= exif.date() - escrita <= timedelta(days=LIMITE_ATRASO_DIAS)
    ):
        registrar_evento(
            passo="datacao",
            resultado="data_escrita_implausivel",
            aviso=f"{caminho.name}: leu {escrita}, EXIF {exif.date()}",
        )
        escrita = None

    if escrita is None:
        return Datacao(
            exif.date(),
            "exif",
            f"EXIF de {exif:%d/%m} não é dia de aula e nenhuma data foi lida na folha",
        )
    if escrita.weekday() in dias:
        return Datacao(escrita, "escrita")
    return reconciliar(escrita, dias, datas_com_foto)


def recortar_cantos(caminho: Path, pasta: Path, sha: str) -> list[Path]:
    """Os dois cantos superiores, cada um em resolução de leitura de dígito."""
    imagem = ImageOps.exif_transpose(Image.open(caminho)).convert("RGB")
    largura, altura = imagem.size
    h = max(1, int(altura * FRACAO_ALTURA_CANTO))
    w = max(1, int(largura * FRACAO_LARGURA_CANTO))
    caixas = {"esq": (0, 0, w, h), "dir": (largura - w, 0, largura, h)}
    pasta.mkdir(parents=True, exist_ok=True)
    saidas = []
    for lado, caixa in caixas.items():
        recorte = imagem.crop(caixa)
        if recorte.width > LARGURA_RECORTE:
            proporcao = LARGURA_RECORTE / recorte.width
            recorte = recorte.resize((LARGURA_RECORTE, max(1, int(recorte.height * proporcao))))
        destino = pasta / f"{sha}_{lado}.jpg"
        recorte.save(destino, format="JPEG", quality=90)
        saidas.append(destino)
    return saidas


def data_do_texto_lido(texto: str) -> date | None:
    """Dia, mês, ano no padrão brasileiro, tirado do que o modelo transcreveu."""
    achado = RE_DATA_ESCRITA.search(texto or "")
    if achado is None:
        return None
    dia, mes, ano = (int(g) for g in achado.groups())
    if ano < 100:
        ano += 2000
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def leitor_de_data_escrita(sigla: str, sha256_de: Callable[[Path], str]):
    """O `ler_escrita` de verdade: recorta, chama o agente, converte.

    O job existe só para o custo ter onde ser lançado, e **nunca** passa por `na_fila`: o
    runner pega todo job na fila, não sabe o que fazer com `datacao` e o marca como falho.
    Foi o que aconteceu com os quatro primeiros, criados na conferência manual das datas.
    """

    def ler(caminho: Path) -> date | None:
        from core.estado import criar_job, transicionar
        from projetos.estudos.agentes import AgenteDataEscrita
        from projetos.estudos.schemas import EntradaDataEscrita

        sha = sha256_de(caminho)
        cantos = recortar_cantos(caminho, get_settings().cache_dir / "datacao", sha)
        job_id = criar_job("datacao", disciplina=sigla)
        transicionar(job_id, "rodando")
        try:
            saida = AgenteDataEscrita().run(
                job_id,
                EntradaDataEscrita(sha256=sha, caminhos=[str(c) for c in cantos]),
                sufixo_passo=sha[:8],
            )
        except BaseException:
            transicionar(job_id, "falhou")
            raise
        transicionar(job_id, "concluido")
        lida = data_do_texto_lido(saida.texto_lido)
        if saida.data and lida and saida.data != lida.isoformat():
            registrar_evento(
                passo="datacao",
                resultado="data_escrita_inconsistente",
                aviso=f"{caminho.name}: transcreveu '{saida.texto_lido}', "
                f"mas devolveu {saida.data}; vale o transcrito",
            )
        return lida

    return ler
