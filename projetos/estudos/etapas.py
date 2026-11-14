"""Etapas que o usuário pode pedir, e o que cada uma exige.

Só dados e três funções puras. Quem executa é o runner (fotos) ou os comandos de PDF.
Não há custo nem tempo "típicos" aqui: sem medida, um número fixo no código viraria
número inventado na tela. A estimativa vem do histórico do próprio usuário.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Etapa:
    nome: str
    rotulo: str
    descricao: str
    depende_de: tuple[str, ...]
    materiais: tuple[str, ...]
    agentes: tuple[str, ...]
    chama_modelo: bool
    comando_cli: str | None = None


FOTO = "foto"
PDF = "pdf"

ETAPAS: tuple[Etapa, ...] = (
    Etapa(
        "leitura",
        "Ler as fotos",
        "Classifica cada foto e extrai o conteúdo da lousa ou do caderno.",
        (),
        (FOTO,),
        ("triagem", "extrator"),
        True,
    ),
    Etapa(
        "nota",
        "Escrever a nota",
        "Identifica a aula, compõe a nota no template e confere contra a extração.",
        ("leitura",),
        (FOTO,),
        ("contexto", "compositor", "validador_semantico"),
        True,
    ),
    Etapa(
        "flashcards",
        "Gerar flashcards",
        "Cria os cards Basic e Cloze para o Anki.",
        ("nota",),
        (FOTO,),
        ("flashcards",),
        True,
    ),
    Etapa(
        "conceitos",
        "Criar páginas de conceito",
        "Cria uma página para cada termo novo da nota.",
        ("nota",),
        (FOTO,),
        ("conceito", "validador_semantico"),
        True,
    ),
    Etapa(
        "disciplina",
        "Atualizar a ementa da disciplina",
        "Lê fotos de plano de ensino e atualiza ementa e programa.",
        ("leitura",),
        (FOTO,),
        ("ementa", "compromissos"),
        True,
    ),
    Etapa(
        "registro_pdf",
        "Registrar o PDF",
        "Classifica o PDF e guarda o hash. Não chama modelo.",
        (),
        (PDF,),
        (),
        False,
        "indexar-pdf",
    ),
    Etapa(
        "indice_livro",
        "Montar o índice do livro",
        "Extrai o sumário do livro, capítulo e página, uma vez por hash.",
        ("registro_pdf",),
        (PDF,),
        ("indexador_livro",),
        True,
        "indexar-pdf",
    ),
    Etapa(
        "leitura_visual_pdf",
        "Ler PDF sem texto",
        "Lê por visão as páginas de um PDF sem camada de texto.",
        ("registro_pdf",),
        (PDF,),
        ("extrator",),
        True,
        "ocr-pdf",
    ),
    Etapa(
        "lacunas",
        "Consultar o livro para as dúvidas",
        "Escolhe capítulos e preenche as lacunas de uma nota concluída.",
        ("nota", "indice_livro"),
        (PDF,),
        ("seletor_capitulos", "bibliotecario"),
        True,
        "preencher-lacunas",
    ),
    Etapa(
        "enriquecer",
        "Acrescentar material à nota",
        "Acrescenta à nota da aula o material que chegou depois.",
        ("nota", "registro_pdf"),
        (PDF,),
        ("enriquecedor",),
        True,
        "enriquecer",
    ),
)

_POR_NOME = {e.nome: e for e in ETAPAS}


def etapa(nome: str) -> Etapa:
    try:
        return _POR_NOME[nome]
    except KeyError:
        raise ValueError(f"etapa desconhecida: {nome}. Válidas: {', '.join(_POR_NOME)}") from None


def fechar_dependencias(pedidas: list[str]) -> list[str]:
    """As etapas pedidas mais as dependências, em ordem de execução."""
    ordem: list[str] = []

    def visitar(nome: str) -> None:
        if nome in ordem:
            return
        for dep in etapa(nome).depende_de:
            visitar(dep)
        ordem.append(nome)

    for nome in pedidas:
        visitar(nome)
    return ordem


def etapas_para(material: str) -> list[Etapa]:
    return [e for e in ETAPAS if material in e.materiais]


def faltantes(pedidas: list[str]) -> list[str]:
    """Dependências que o usuário não marcou, para o aviso na tela."""
    return [n for n in fechar_dependencias(pedidas) if n not in pedidas]
