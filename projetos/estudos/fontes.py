"""Hierarquia de fontes: o que o modelo lê primeiro, e o que é cortado quando não cabe.

O manuscrito é a fonte mais valiosa que existe aqui — é onde o professor diz o que é
relevante e o que cai na prova. O livro-texto é canônico, mas não é o recorte do
professor. Material de semestre passado só vale se for do mesmo docente, porque aí
carrega o mesmo recorte e o mesmo estilo de prova.

**A ordenação e o corte acontecem em Python, não no prompt.** Um prompt pode pedir
"priorize o manuscrito" e ser ignorado; uma lista já ordenada e já truncada não pode.
Quando o teto de caracteres é atingido, o que sai é sempre o fim da lista — a fonte de
menor prioridade —, nunca um pedaço do meio.
"""

from dataclasses import dataclass

from projetos.estudos.disciplinas import autoria_de_docente_atual
from projetos.estudos.pdf_ingestao import RegistroPdf
from projetos.estudos.schemas import TrechoFonte

#: menor número = maior prioridade
PRIORIDADE_MANUSCRITO = 1
PRIORIDADE_MATERIAL_ATUAL_DOCENTE = 2
PRIORIDADE_MATERIAL_ATUAL = 3
PRIORIDADE_LIVRO = 4
PRIORIDADE_ANTIGO_DOCENTE = 5
PRIORIDADE_ANTIGO_OUTRO = 6

_ROTULOS = {
    PRIORIDADE_MANUSCRITO: "manuscrito da aula",
    PRIORIDADE_MATERIAL_ATUAL_DOCENTE: "material do professor atual",
    PRIORIDADE_MATERIAL_ATUAL: "material deste semestre",
    PRIORIDADE_LIVRO: "livro-texto",
    PRIORIDADE_ANTIGO_DOCENTE: "material antigo do professor atual",
    PRIORIDADE_ANTIGO_OUTRO: "material antigo de outro autor",
}


@dataclass(frozen=True)
class FonteOrdenada:
    trecho: TrechoFonte
    prioridade: int

    @property
    def rotulo(self) -> str:
        return _ROTULOS[self.prioridade]


def prioridade_do_registro(disciplina: str, registro: RegistroPdf) -> int:
    """Onde este PDF entra na fila. Gabarito não aparece aqui: ele nunca é fonte."""
    do_docente = autoria_de_docente_atual(disciplina, registro.autor)

    if registro.vigencia == "antiga":
        return PRIORIDADE_ANTIGO_DOCENTE if do_docente else PRIORIDADE_ANTIGO_OUTRO
    if registro.tipo == "livro":
        return PRIORIDADE_LIVRO
    return PRIORIDADE_MATERIAL_ATUAL_DOCENTE if do_docente else PRIORIDADE_MATERIAL_ATUAL


def ordenar(fontes: list[FonteOrdenada]) -> list[FonteOrdenada]:
    """Estável: dentro da mesma prioridade, preserva a ordem em que as fontes chegaram."""
    return sorted(fontes, key=lambda fonte: fonte.prioridade)


def truncar(
    fontes: list[FonteOrdenada],
    limite_chars: int,
    garantidas: set[str] | None = None,
) -> tuple[list[FonteOrdenada], list[str]]:
    """Corta de baixo para cima até caber. Devolve (mantidas, avisos).

    Uma fonte nunca entra pela metade: ou cabe inteira, ou fica de fora. Trecho cortado
    no meio de um raciocínio é pior que trecho ausente — o modelo completa a lacuna.

    `garantidas` (nomes de arquivo) **nunca são descartadas**: o teto vale para as
    outras, e elas entram por cima. Existe por um caso concreto: em `preencher-lacunas`,
    o capítulo do livro foi escolhido de propósito para aquela consulta, e a prioridade —
    que o coloca abaixo do material do semestre — o cortava inteiro. O comando existe
    para consultar o livro; cortá-lo derrota o próprio comando.

    Garantir é "não pode ser descartada", não "passa na frente". A primeira tentativa
    deste código reservava o orçamento para as garantidas antes de tudo, e dois capítulos
    do CLRS (124 mil caracteres) expulsaram o **manuscrito da aula** — a fonte de maior
    prioridade que existe aqui. Trocar a fonte mais valiosa pela que foi pedida é o mesmo
    defeito de antes, invertido.
    """
    garantidas = garantidas or set()
    mantidas: list[FonteOrdenada] = []
    avisos: list[str] = []
    total = 0

    for fonte in ordenar(fontes):
        if fonte.trecho.arquivo in garantidas:
            continue
        tamanho = len(fonte.trecho.texto)
        if total + tamanho > limite_chars:
            avisos.append(
                f"{fonte.trecho.arquivo} ({fonte.rotulo}) ficou de fora: "
                f"não cabe no teto de {limite_chars} caracteres"
            )
            continue
        mantidas.append(fonte)
        total += tamanho

    reservadas = [f for f in ordenar(fontes) if f.trecho.arquivo in garantidas]
    excedente = sum(len(f.trecho.texto) for f in reservadas)
    if excedente:
        mantidas.extend(reservadas)
        avisos.append(
            f"{len(reservadas)} fonte(s) pedida(s) para esta consulta somam {excedente} "
            f"caracteres e entraram acima do teto de {limite_chars} — foram escolhidas "
            "de propósito, então não são descartadas"
        )

    return ordenar(mantidas), avisos


def resumo(fontes: list[FonteOrdenada]) -> str:
    """Uma linha por fonte, na ordem em que o modelo vai vê-las — para o log e para o CLI."""
    return "\n".join(
        f"{indice + 1}. [{fonte.rotulo}] {fonte.trecho.arquivo}"
        for indice, fonte in enumerate(ordenar(fontes))
    )
