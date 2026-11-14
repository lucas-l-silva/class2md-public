"""Registro declarativo das disciplinas do semestre.

Antes deste módulo, "disciplina" era apenas o nome da pasta pai de uma foto
(`ingestao.py`). Isso basta para arquivar, mas não para nada que dependa de
saber *o que* é a disciplina: quem ministra, que horário tem, se tem monitoria,
se o material fica num site, e a que semestre pertence.

O registro vive em `estudos/index/disciplinas.toml` (dado do usuário, fora do
repositório) e é a fonte de verdade para:

- validar o nome de disciplina na ingestão (substitui `disciplinas.txt`);
- saber quais pastas criar no início do semestre e quais arquivar no fim;
- priorizar material autorado por quem ministra a disciplina *hoje*;
- montar a grade horária e a nota-home (MOC) de cada disciplina.

Campos que o pipeline infere mas não pode confirmar sozinho (nome de docente
lido de um manuscrito, horário lido de uma grade) entram em `a_confirmar`, para
que a incerteza fique visível em vez de virar fato silencioso.

**Por que TOML e não JSON:** este arquivo é editado à mão. JSON não aceita
comentário, e na prática o usuário acabou escrevendo as anotações dentro dos
textos de `a_confirmar` — e quebrou a sintaxe. TOML tem comentário nativo, é
lido pela stdlib e perdoa mais a edição humana. O `.json` legado é migrado
automaticamente na primeira leitura.
"""

import re
import tomllib
import unicodedata
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field, ValidationError

from core.config import get_settings
from core.fileops import escrever_texto, ler_texto
from core.logging import registrar_evento

NOME_ARQUIVO = "disciplinas.toml"
NOME_ARQUIVO_LEGADO = "disciplinas.json"

# Sigla é nome de pasta e entra em nome de arquivo gerado: sem espaço, sem acento.
_RE_SIGLA = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")

DIAS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")


class RegistroAusente(Exception):
    """Não existe `estudos/index/disciplinas.toml` (nem o `.json` legado)."""


class RegistroInvalido(Exception):
    """O arquivo existe mas não pôde ser lido — sintaxe ou campo inválido.

    Erro esperado, não excepcional: o registro é escrito à mão. A mensagem tem de
    dizer arquivo, linha e o que corrigir, em vez de vazar um traceback.
    """


class DisciplinaDesconhecida(Exception):
    """Sigla que não está no registro."""


class Docente(BaseModel):
    nome: str
    papel: Literal["titular", "monitor"] = "titular"
    #: de onde veio o nome (foto, PDF, digitado à mão) — para auditoria
    fonte: str | None = None


class Horario(BaseModel):
    dia: Literal["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
    inicio: str
    fim: str
    tipo: Literal["aula", "monitoria", "reuniao"] = "aula"
    local: str | None = None
    #: fim da recorrência (AAAA-MM-DD) — ex.: "monitoria toda sexta até 01/01/2026"
    ate: str | None = None
    #: "semanal" (padrão) ou "quinzenal"
    periodicidade: Literal["semanal", "quinzenal"] = "semanal"


class Coletor(BaseModel):
    """Como buscar o material publicado pelo professor, quando existe."""

    tipo: str
    url: str


class Disciplina(BaseModel):
    """Uma entrada do registro. Nem toda entrada é disciplina: uma reunião recorrente
    (`tipo="reuniao"`) usa os mesmos campos, mas produz ata e backlog em vez de nota
    de aula, e não ganha pastas de livro ou prova."""

    nome: str
    titulo: str
    codigo: str | None = None
    semestre: str
    tipo: Literal["disciplina", "reuniao"] = "disciplina"
    #: qual template/validação a nota usa; derivado de `tipo` quando não informado
    perfil: Literal["tecnica", "idioma", "reuniao"] | None = None
    #: forma da resolução de listas e provas. `algoritmo` (padrão, MAT1): ideia,
    #: pseudocódigo, corretude, complexidade. `calculo` (FIS1): estratégia e passos que se
    #: revelam um de cada vez, com as contas refeitas por sympy. Era propriedade do prompt;
    #: migrou para cá quando a segunda disciplina precisou de outra forma.
    resolucao: Literal["algoritmo", "calculo"] = "algoritmo"
    ativa: bool = True
    monitoria: bool = False
    #: texto livre seu; o pipeline nunca reescreve
    notas: str = ""
    docentes: list[Docente] = Field(default_factory=list)
    horarios: list[Horario] = Field(default_factory=list)
    coletor: Coletor | None = None
    links: dict[str, str] = Field(default_factory=dict)
    #: sobrepõe `Registro.semestre_curso` — para disciplina fora do seu período atual
    #: (uma optativa de outro semestre, uma cadeira que você está repetindo)
    semestre_curso: int | None = None
    #: pontos inferidos que ainda dependem de confirmação humana
    a_confirmar: list[str] = Field(default_factory=list)

    def perfil_efetivo(self) -> str:
        if self.perfil is not None:
            return self.perfil
        return "reuniao" if self.tipo == "reuniao" else "tecnica"


class Registro(BaseModel):
    semestre_atual: str
    #: qual número de semestre do curso você está cursando (o "6" de `MAT1-S6`).
    #: É seu período, não o da grade: as disciplinas que você cursa juntas compartilham
    #: o número, e a exceção se resolve em `Disciplina.semestre_curso`.
    semestre_curso: int | None = None
    disciplinas: list[Disciplina] = Field(default_factory=list)


def nome_do_baralho(disciplina: str) -> str:
    """Nome do deck do Anki: `MAT1-S6`, ou só `MAT1` se o semestre não estiver no registro.

    Agrupa os baralhos por período no Anki, que ordena por nome. Sem o número, cadeiras
    de semestres diferentes com a mesma sigla se misturariam ao longo do curso.
    """
    try:
        registro = carregar_registro()
    except (RegistroAusente, RegistroInvalido):
        return disciplina
    entrada = next((d for d in registro.disciplinas if d.nome == disciplina), None)
    numero = (entrada.semestre_curso if entrada else None) or registro.semestre_curso
    return f"{disciplina}-S{numero}" if numero else disciplina


def _pasta_index():
    return get_settings().agent_data_dir / "estudos" / "index"


def caminho_registro():
    return _pasta_index() / NOME_ARQUIVO


def caminho_registro_legado():
    return _pasta_index() / NOME_ARQUIVO_LEGADO


def sigla_valida(nome: str) -> bool:
    return bool(_RE_SIGLA.match(nome))


def _sem_nulos(valor: Any) -> Any:
    """TOML não representa null: campo vazio é campo ausente."""
    if isinstance(valor, dict):
        return {k: _sem_nulos(v) for k, v in valor.items() if v is not None}
    if isinstance(valor, list):
        return [_sem_nulos(item) for item in valor]
    return valor


def _migrar_do_json() -> Registro | None:
    """Lê o `disciplinas.json` legado e grava o `.toml`, preservando o que existe.

    O JSON antigo fica onde está: se a migração produzir algo estranho, o original
    continua disponível para conferência.
    """
    import json

    legado = caminho_registro_legado()
    try:
        conteudo = ler_texto(legado)
    except FileNotFoundError:
        return None

    try:
        registro = Registro.model_validate(json.loads(conteudo))
    except (json.JSONDecodeError, ValidationError) as erro:
        raise RegistroInvalido(
            f"{legado}: não deu para migrar o registro legado — {erro}. "
            "Corrija o JSON ou apague-o e recrie com 'disciplinas --exemplo'."
        ) from erro

    salvar_registro(registro)
    registrar_evento(
        passo="disciplinas/migrado",
        resultado=f"{legado.name} → {NOME_ARQUIVO}",
    )
    return registro


def carregar_registro() -> Registro:
    caminho = caminho_registro()
    try:
        conteudo = ler_texto(caminho)
    except FileNotFoundError as erro:
        migrado = _migrar_do_json()
        if migrado is not None:
            return migrado
        raise RegistroAusente(
            f"registro de disciplinas não encontrado em {caminho} — "
            "rode 'uv run python scripts/estudos.py disciplinas --exemplo' para criar um modelo"
        ) from erro

    try:
        dados = tomllib.loads(conteudo)
    except tomllib.TOMLDecodeError as erro:
        raise RegistroInvalido(f"{caminho}: TOML inválido — {erro}") from erro

    try:
        return Registro.model_validate(dados)
    except ValidationError as erro:
        problemas = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in erro.errors()[:5]
        )
        raise RegistroInvalido(f"{caminho}: campo inválido — {problemas}") from erro


def salvar_registro(registro: Registro) -> None:
    dados = _sem_nulos(registro.model_dump(mode="json"))
    escrever_texto(caminho_registro(), tomli_w.dumps(dados))


def _registro_ou_none() -> Registro | None:
    """Registro carregado, ou None quando ainda não há um.

    Registro **inválido** não é silenciado: um erro de sintaxe tem de aparecer, não
    virar "validação desligada".
    """
    try:
        return carregar_registro()
    except RegistroAusente:
        return None


def disciplina(nome: str) -> Disciplina:
    registro = carregar_registro()
    for item in registro.disciplinas:
        if item.nome == nome:
            return item
    conhecidas = ", ".join(sorted(d.nome for d in registro.disciplinas)) or "(nenhuma)"
    raise DisciplinaDesconhecida(
        f"disciplina '{nome}' não está no registro. Conhecidas: {conhecidas}"
    )


def disciplinas_ativas(semestre: str | None = None, tipo: str | None = None) -> list[Disciplina]:
    """Entradas ativas do semestre. `tipo` filtra disciplina × reunião."""
    registro = carregar_registro()
    alvo = semestre or registro.semestre_atual
    return [
        d
        for d in registro.disciplinas
        if d.ativa and d.semestre == alvo and (tipo is None or d.tipo == tipo)
    ]


def perfil_de(nome: str) -> str:
    """Perfil de nota da disciplina; `tecnica` para quem não está no registro."""
    try:
        return disciplina(nome).perfil_efetivo()
    except (RegistroAusente, RegistroInvalido, DisciplinaDesconhecida):
        return "tecnica"


def nomes_conhecidos() -> set[str] | None:
    """Siglas registradas, ou None quando não há registro (validação desligada).

    Mesmo contrato de `ingestao._disciplinas_conhecidas`: None significa "não sei",
    não "nenhuma" — é o que mantém o pipeline utilizável antes de configurar nada.
    """
    registro = _registro_ou_none()
    if registro is None:
        return None
    return {d.nome for d in registro.disciplinas}


def docentes_atuais(nome: str) -> list[Docente]:
    """Docentes de uma disciplina ATIVA. Disciplina arquivada devolve lista vazia:
    o objetivo é priorizar material de quem ministra hoje."""
    try:
        item = disciplina(nome)
    except (RegistroAusente, RegistroInvalido, DisciplinaDesconhecida):
        return []
    return item.docentes if item.ativa else []


def registrar_docente(nome_disciplina: str, docente: Docente) -> Disciplina:
    """Acrescenta um docente sem duplicar (comparação por nome normalizado)."""
    registro = carregar_registro()
    for item in registro.disciplinas:
        if item.nome != nome_disciplina:
            continue
        ja_tem = {_normalizar_nome(d.nome) for d in item.docentes}
        if _normalizar_nome(docente.nome) not in ja_tem:
            item.docentes.append(docente)
            salvar_registro(registro)
            registrar_evento(
                passo="disciplinas/docente_registrado",
                resultado=f"{nome_disciplina}: {docente.nome}",
            )
        return item
    raise DisciplinaDesconhecida(f"disciplina '{nome_disciplina}' não está no registro")


def arquivar(nome: str) -> Disciplina:
    registro = carregar_registro()
    for item in registro.disciplinas:
        if item.nome == nome:
            item.ativa = False
            salvar_registro(registro)
            return item
    raise DisciplinaDesconhecida(f"disciplina '{nome}' não está no registro")


def _normalizar_nome(nome: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", nome) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def autoria_de_docente_atual(nome_disciplina: str, autor: str | None) -> bool:
    """O autor do material é um docente atual da disciplina?

    Casamento tolerante: basta que o sobrenome do docente apareça na string de
    autoria, porque `autor` costuma vir de metadados de PDF ou de nome de arquivo,
    em formatos que não controlamos.
    """
    if not autor:
        return False
    autor_norm = _normalizar_nome(autor)
    for docente in docentes_atuais(nome_disciplina):
        partes = [p for p in _normalizar_nome(docente.nome).split(" ") if len(p) > 2]
        if any(parte in autor_norm for parte in partes):
            return True
    return False


REGISTRO_EXEMPLO = Registro(
    semestre_atual="2030.1",
    disciplinas=[
        Disciplina(
            nome="EXEMPLO",
            titulo="Nome completo da disciplina",
            codigo="XX0000",
            semestre="2030.1",
            ativa=True,
            monitoria=False,
            docentes=[Docente(nome="Nome do Professor", papel="titular", fonte="digitado")],
            horarios=[
                Horario(dia="seg", inicio="08:00", fim="10:00"),
                Horario(dia="qua", inicio="08:00", fim="10:00"),
            ],
            coletor=None,
            links={"classroom": "https://..."},
        )
    ],
)


def criar_registro_exemplo(sobrescrever: bool = False) -> tuple[bool, str]:
    """Escreve um registro de exemplo. Devolve (criado, caminho)."""
    caminho = caminho_registro()
    if caminho.exists() and not sobrescrever:
        return False, str(caminho)
    salvar_registro(REGISTRO_EXEMPLO)
    return True, str(caminho)
