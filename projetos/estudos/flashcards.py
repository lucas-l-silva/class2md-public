import csv
import hashlib
import io
import re

from projetos.estudos.schemas import FlashcardBasico, FlashcardCloze

_PADRAO_BLOCO = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_PADRAO_INLINE = re.compile(r"\$(.+?)\$", re.DOTALL)


def _converter_latex(texto: str) -> str:
    # Ordem importa: bloco ($$...$$) primeiro, senão o padrão inline consome os $$ como
    # dois delimitadores de $...$ vazios/errados.
    texto = _PADRAO_BLOCO.sub(lambda m: f"\\[{m.group(1)}\\]", texto)
    return _PADRAO_INLINE.sub(lambda m: f"\\({m.group(1)}\\)", texto)


def _preparar_campo(texto: str) -> str:
    return _converter_latex(texto).replace("\n", "<br>")


def _guid(disciplina: str, data: str, tipo: str, chave: str) -> str:
    """Chaveado pela SIGLA, nunca pelo nome do baralho.

    O guid é o que o Anki usa para saber que já viu este card. Se ele dependesse do
    baralho, renomear `MAT1` para `MAT1-S6` recriaria todos os cards como novos e você
    perderia o histórico de revisão de cada um.
    """
    bruto = f"{disciplina}{data}{tipo}{chave}"
    return hashlib.sha256(bruto.encode()).hexdigest()[:16]


def _csv_anki(diretivas: list[str], linhas: list[list[str]]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(linhas)
    return "\n".join(diretivas) + "\n" + buffer.getvalue()


def gera_csv_basico(
    cards: list[FlashcardBasico],
    disciplina: str,
    data: str,
    baralho: str | None = None,
) -> str:
    diretivas = [
        "#separator:Comma",
        "#html:true",
        f"#deck:{baralho or disciplina}",
        "#notetype:Basic",
        "#guid column:1",
        "#tags column:4",
    ]
    linhas = [
        [
            _guid(disciplina, data, "basico", card.frente),
            _preparar_campo(card.frente),
            _preparar_campo(card.verso),
            data,
        ]
        for card in cards
    ]
    return _csv_anki(diretivas, linhas)


def gera_csv_cloze(
    cards: list[FlashcardCloze],
    disciplina: str,
    data: str,
    baralho: str | None = None,
) -> str:
    diretivas = [
        "#separator:Comma",
        "#html:true",
        f"#deck:{baralho or disciplina}",
        "#notetype:Cloze",
        "#guid column:1",
        "#tags column:4",
    ]
    linhas = [
        [
            _guid(disciplina, data, "cloze", card.texto),
            _preparar_campo(card.texto),
            _preparar_campo(card.extra),
            data,
        ]
        for card in cards
    ]
    return _csv_anki(diretivas, linhas)
