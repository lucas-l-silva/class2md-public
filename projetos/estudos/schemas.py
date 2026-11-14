from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field


def _vazio_para_none(valor):
    """String vazia significa "não se aplica" — é como o modelo costuma dizer isso.

    Sem esta conversão, `""` num campo `int | None` levanta ValidationError e derruba
    a chamada inteira depois das tentativas. É a mesma classe de problema do campo
    anulável sem default: a forma natural de o modelo omitir algo não pode ser fatal.
    """
    if isinstance(valor, str) and not valor.strip():
        return None
    return valor


#: use em TODO campo anulável de saída de agente
IntOpcional = Annotated[int | None, BeforeValidator(_vazio_para_none)]
TextoOpcional = Annotated[str | None, BeforeValidator(_vazio_para_none)]


class Triagem(BaseModel):
    categoria: Literal[
        "lousa", "caderno", "slide_projetado", "lista_exercicios", "documento", "outro"
    ]
    receita_preproc: Literal["quadro", "papel", "projecao", "nenhuma"]
    qualidade: Literal["boa", "borrada", "cortada", "escura"]
    contem_conteudo_academico: bool
    confianca: float


# Campo anulável de saída de agente SEMPRE leva default `= None`. Sem o default, o
# Pydantic o marca como obrigatório no schema da ferramenta, e omitir o campo — que é
# a forma natural do modelo dizer "não se aplica" — derruba a extração inteira. Foi o
# que aconteceu com `latex` num bloco de diagrama: 20 fotos perdidas por um campo que
# só faz sentido em fórmula.
class Bloco(BaseModel):
    tipo: Literal["texto", "formula", "diagrama", "tabela", "lista", "codigo"]
    conteudo: str
    latex: TextoOpcional = None
    bbox: tuple[float, float, float, float]
    confianca: float
    flags: list[
        Literal[
            "duvida",
            "importante",
            "prova",
            "administrativo",
            "possivel_injecao",
            "ilegivel_parcial",
        ]
    ]


class Extracao(BaseModel):
    #: default porque foto sem nada legível é resultado válido, e o modelo omite a
    #: lista quando ela sairia vazia — sem default, esse caso derruba o job inteiro
    blocos: list[Bloco] = Field(default_factory=list)
    idioma: str = ""
    observacoes: str = ""


class EntradaImagem(BaseModel):
    """Entrada comum aos agentes de visão: caminho da imagem a analisar."""

    caminho: str


class Contexto(BaseModel):
    aula_numero: IntOpcional = None
    titulo_sugerido: str
    topicos: list[str]
    conexoes: list[str]
    tags: list[str]
    subnotas_sugeridas: list[str]
    confianca: float


class EntradaContexto(BaseModel):
    """Entrada do A4: disciplina é DADA (não questionada), extração consolidada do dia,
    e a lista de títulos de notas já existentes (para conexões sem alucinação)."""

    disciplina: str
    extracao_consolidada: str
    titulos_existentes: list[str]


class NotaComposta(BaseModel):
    markdown: str
    conceitos_novos: list[str]
    duvidas: list[str]


class EntradaCompositor(BaseModel):
    """Entrada do A5: tudo que o Compositor tem permissão de usar como fonte —
    nada além disso (nunca inventa conteúdo de aula)."""

    disciplina: str
    data: str
    aula_numero: int | None = None
    titulo_sugerido: str
    topicos: list[str]
    tags: list[str]
    extracao_consolidada: str
    mapa_recortes: dict[str, str]  # descrição do bloco -> nome do arquivo do crop
    do_livro: str = ""  # preenchido pelo bibliotecário (preencher-lacunas); persistido no manifesto
    materiais_da_aula: str = ""  # PDFs pequenos da aula (ementa, lista, notas), já envelopados
    #: escolhe o template e as seções obrigatórias (tecnica | idioma | reuniao)
    perfil: str = "tecnica"
    problemas_anteriores: list[str] = []  # do ciclo de correção do A10, se houver


class Problema(BaseModel):
    severidade: Literal["erro", "aviso"]
    onde: str
    descricao: str
    sugestao: str


class Validacao(BaseModel):
    aprovado: bool
    problemas: list[Problema]


class EntradaValidadorSemantico(BaseModel):
    markdown: str


class FlashcardBasico(BaseModel):
    tipo: Literal["basico"]
    frente: str
    verso: str


class FlashcardCloze(BaseModel):
    tipo: Literal["cloze"]
    texto: str
    extra: str = ""


Flashcard = Annotated[FlashcardBasico | FlashcardCloze, Field(discriminator="tipo")]


class Flashcards(BaseModel):
    cards: list[Flashcard] = Field(default_factory=list)
    duvidas: list[str] = Field(default_factory=list)


class EntradaFlashcards(BaseModel):
    """Entrada do A7: a nota já validada (fonte dos cards) e as dúvidas brutas
    sinalizadas até aqui (do A5), para o A7 consolidar (dedup/fusão)."""

    disciplina: str
    markdown: str
    duvidas_brutas: list[str]
    perfil: str = "tecnica"


class PaginaConceito(BaseModel):
    definicao_formal: str
    intuicao: str
    exemplo: str
    tags: list[str]
    definicao_a_completar: bool


class EntradaConceito(BaseModel):
    """Entrada do A6: nome do conceito (de conceitos_novos do A5) e a nota já composta,
    única fonte permitida — RAG ao livro só chega na Iteração 4 (A8)."""

    disciplina: str
    nome_conceito: str
    markdown_nota: str
    perfil: str = "tecnica"


class CapituloIndice(BaseModel):
    numero: int
    titulo: str
    pagina_inicio: int
    pagina_fim: IntOpcional = None  # None = até o próximo capítulo / fim do PDF


class IndiceLivro(BaseModel):
    titulo_livro: str
    autor: str
    capitulos: list[CapituloIndice]
    fonte_indice: Literal["toc_nativo", "paginas_iniciais", "fallback_paginas"]
    confianca: float


class EntradaIndexadorLivro(BaseModel):
    """Entrada do indexador de livro: TOC nativo se houver, senão texto das primeiras
    páginas (onde mora o sumário impresso)."""

    nome_arquivo: str
    total_paginas: int
    toc_bruto: str  # "" se não houver TOC nativo
    texto_paginas_iniciais: str  # só preenchido quando toc_bruto == ""


class SugestaoCapitulos(BaseModel):
    capitulos: list[int]
    justificativa: str
    confianca: float


class EntradaSeletorCapitulos(BaseModel):
    disciplina: str
    titulo_nota: str
    topicos: list[str]
    lacunas: list[str]
    indice_resumido: str  # "3 — Limites (p. 87-120)\n4 — ..."


class TrechoFonte(BaseModel):
    arquivo: str
    tipo: Literal["livro", "aula", "slides", "exercicios", "prova", "ementa", "manuscrito"]
    capitulo: TextoOpcional = None
    pagina_inicio: int
    pagina_fim: int
    texto: str


class RespostaLacuna(BaseModel):
    lacuna: str
    resolvida: bool
    resposta: str = ""
    citacao: str = ""  # "Stewart, cap. 3, p. 91" — obrigatória se resolvida
    #: título da seção da nota (`##`/`###`) que esta resposta completa. É o que permite
    #: pôr o trecho do livro ONDE ele responde, em vez de num apanhado no fim da nota.
    secao_alvo: str = ""


class SaidaBibliotecario(BaseModel):
    """`respostas` e `lacunas_nao_resolvidas` têm default: lista vazia é uma resposta
    legítima ("nenhuma lacuna foi resolvida"), e o modelo omite listas vazias."""

    #: A procedência é **estruturada de propósito**. Quando era um campo de texto livre
    #: (`secao_do_livro`), o modelo despejava nele toda a matéria e deixava `respostas`
    #: vazia — reconstruindo exatamente o apanhado monolítico que a seção deveria deixar
    #: de ser. Sem campo de prosa longa, não há onde despejar.
    obras_consultadas: list[str] = Field(default_factory=list)
    divergencias: list[str] = Field(default_factory=list)
    nao_coberto: list[str] = Field(default_factory=list)
    #: a saída principal: é aqui que a matéria entra, cada item na seção que ele responde
    respostas: list[RespostaLacuna] = Field(default_factory=list)
    lacunas_nao_resolvidas: list[str] = Field(default_factory=list)


class EntradaBibliotecario(BaseModel):
    disciplina: str
    titulo_nota: str
    markdown_nota: str
    lacunas: list[str]
    trechos: list[TrechoFonte]


class ItemEmenta(BaseModel):
    """Um fato sobre a disciplina, sempre com a fonte de onde saiu.

    `fonte` não é decorativa: é validada em código contra os nomes realmente
    fornecidos ao agente, e item sem fonte válida é descartado.
    """

    texto: str
    fonte: str


class ParteEmenta(BaseModel):
    numero: IntOpcional = None
    titulo: str
    fonte: str


class EntradaCronograma(BaseModel):
    periodo: str  # "31/08", "08/09–12/09", "última semana"
    conteudo: str
    fonte: str


class Ementa(BaseModel):
    disciplina: str = ""
    titulo_oficial: str = ""
    codigo: str | None = None
    docentes: list[ItemEmenta] = Field(default_factory=list)
    partes: list[ParteEmenta] = Field(default_factory=list)
    avaliacao: list[ItemEmenta] = Field(default_factory=list)
    pesos: list[ItemEmenta] = Field(default_factory=list)
    bibliografia_basica: list[ItemEmenta] = Field(default_factory=list)
    bibliografia_complementar: list[ItemEmenta] = Field(default_factory=list)
    cronograma: list[EntradaCronograma] = Field(default_factory=list)
    monitoria: list[ItemEmenta] = Field(default_factory=list)
    links: list[ItemEmenta] = Field(default_factory=list)
    observacoes: list[ItemEmenta] = Field(default_factory=list)
    confianca: float = 1.0


class FonteEmenta(BaseModel):
    nome: str
    tipo: Literal["manuscrito", "pdf", "slides"]
    texto: str


class EntradaEmenta(BaseModel):
    disciplina: str
    #: o que já está confirmado, para o agente acrescentar em vez de repetir
    ementa_atual: str
    fontes: list[FonteEmenta]


class CompromissoExtraido(BaseModel):
    tipo: Literal["prova", "entrega", "lista", "monitoria", "aviso"]
    titulo: str
    #: AAAA-MM-DD já resolvido contra a data da aula; None quando só há recorrência
    data: TextoOpcional = None
    hora: TextoOpcional = None
    #: "semanal-sexta", "quinzenal-sabado"; None quando é evento único
    recorrencia: TextoOpcional = None
    #: citação literal do material — validada como substring em código
    origem_trecho: str
    confianca: float


class SaidaCompromissos(BaseModel):
    compromissos: list[CompromissoExtraido]
    confianca: float


class EntradaCompromissos(BaseModel):
    disciplina: str
    #: data da aula, âncora para resolver "amanhã", "próxima quarta"
    data_ancora: str
    texto: str


class MaterialPrograma(BaseModel):
    nome: str
    tipo: Literal["notas", "listas", "slides", "outro"]
    url: str
    caminho_local: str | None = None


class AulaPrograma(BaseModel):
    numero: int
    titulo: str
    topicos: list[str] = Field(default_factory=list)
    parte: str | None = None
    #: data da aula, preenchida quando um job de aula é casado com este número
    data: str | None = None
    url: str | None = None
    materiais: list[MaterialPrograma] = Field(default_factory=list)


class Programa(BaseModel):
    disciplina: str
    titulo_oficial: str = ""
    fonte_url: str | None = None
    coletado_em: str | None = None
    aulas: list[AulaPrograma] = Field(default_factory=list)


class SaidaEnriquecedor(BaseModel):
    """Só os corpos das seções que o enriquecimento pode reescrever.

    O agente não devolve a nota inteira de propósito: reescrever tudo arriscaria
    perder conteúdo que já estava certo, e o remendo cirúrgico não permite isso.
    """

    secao_exercicios: str = ""
    secao_do_livro: str = ""
    secao_pontos_dificeis: str = ""
    secao_pontos_atencao: str = ""
    #: nomes dos arquivos realmente usados — validados contra os fornecidos
    fontes_usadas: list[str] = Field(default_factory=list)


class EntradaEnriquecedor(BaseModel):
    disciplina: str
    titulo_nota: str
    markdown_nota: str
    trechos: list[TrechoFonte]


# ------------------------------------------------------------------- A9: truques
#
# Um "truque" é a técnica reutilizável por trás de uma questão — o contador exponencial,
# o ponteiro que anda de trás para frente, a partição por paridade. A resolução ensina
# *aquela* questão; o truque é o que sobra dela para a próxima, e é o que se decora.


# --------------------------------------------------------------------------- datação


class EntradaDataEscrita(BaseModel):
    """A faixa superior de uma foto de anotação. O sha entra na chave de cache: o recorte
    tem nome derivado dele, mas é o conteúdo que define a resposta."""

    sha256: str
    #: os recortes dos dois cantos superiores
    caminhos: list[str]


class DataEscrita(BaseModel):
    #: AAAA-MM-DD, ou None quando não há data legível no recorte
    data: str | None = None
    #: o que foi lido, literal, para o evento e para quem for conferir
    texto_lido: str = ""


# --------------------------------------------------------------------------- passo a passo


class Passo(BaseModel):
    titulo: str
    #: LaTeX sem cifrões; o renderizador põe o bloco `$$`
    calculo: str
    #: o "por quê" — só quando a transição não é óbvia para quem está aprendendo
    explicacao: str = ""


def _cifroes_balanceados(texto: str) -> bool:
    return texto.replace("\\$", "").count("$") % 2 == 0


# --------------------------------------------------------------------------- resposta de prova
