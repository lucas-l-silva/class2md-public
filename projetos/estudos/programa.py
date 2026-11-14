"""O programa da disciplina: a lista canônica de aulas, com número, título e tópicos.

É a chave de organização de todo o resto. Uma foto, um PDF do site e uma prova
antiga não têm nada em comum além do assunto — o que os liga é o **número da
aula** do programa. Sem esse eixo, "organizar o material por aula" não tem a que
se referir.

O programa pode nascer de três lugares: da coleta do site do professor, da ementa
extraída do manuscrito, ou escrito à mão. Persistido em
`estudos/index/<SIGLA>/programa.json`.
"""

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from core.config import get_settings
from core.fileops import escrever_texto, ler_texto
from projetos.estudos.schemas import AulaPrograma, Programa

NOME_ARQUIVO = "programa.json"

_STOPWORDS = {
    "a",
    "o",
    "as",
    "os",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "um",
    "uma",
    "para",
    "por",
    "com",
    "ao",
    "aos",
    "que",
}

#: palavras que aparecem em quase todo nome de arquivo ou título de aula e por isso não
#: são evidência de assunto. "mais" está aqui por um caso real: o tópico "Quem é o mais
#: rápido?" casou com "Subsequência comum mais longa" por essa única palavra.
RUIDO_DE_ASSUNTO = {
    "aula",
    "aulas",
    "pdf",
    "nota",
    "notas",
    "lista",
    "listas",
    "prova",
    "provas",
    "slide",
    "slides",
    "parte",
    "cap",
    "capitulo",
    "capitulos",
    "exercicio",
    "exercicios",
    "copy",
    "mais",
    "menos",
    "outro",
    "outros",
    "geral",
    "introducao",
    "problema",
    "problemas",
    "exemplo",
    "exemplos",
}

#: quantos tokens de assunto em comum bastam para afirmar que é o mesmo assunto.
#: Um só não basta — é sempre uma palavra genérica que escapou da lista acima.
MINIMO_TOKENS_ASSUNTO = 2


def tokens_de_assunto(texto: str, disciplina: str, titulo_oficial: str = "") -> set[str]:
    """Tokens que carregam assunto, sem o ruído e sem as palavras da própria disciplina.

    "algoritmos" não distingue nada dentro de "Matemática Discreta".
    """
    ruido = RUIDO_DE_ASSUNTO | normalizar_titulo(disciplina) | normalizar_titulo(titulo_oficial)
    return normalizar_titulo(texto) - ruido


def caminho_programa(disciplina: str) -> Path:
    return get_settings().agent_data_dir / "estudos" / "index" / disciplina / NOME_ARQUIVO


def carregar(disciplina: str) -> Programa | None:
    try:
        conteudo = ler_texto(caminho_programa(disciplina))
    except FileNotFoundError:
        return None
    return Programa.model_validate(json.loads(conteudo))


def salvar(programa: Programa) -> Path:
    caminho = caminho_programa(programa.disciplina)
    escrever_texto(
        caminho,
        json.dumps(programa.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
    )
    return caminho


def aula_por_numero(programa: Programa, numero: int) -> AulaPrograma | None:
    return next((aula for aula in programa.aulas if aula.numero == numero), None)


def titulos(programa: Programa) -> dict[int, str]:
    return {aula.numero: aula.titulo for aula in programa.aulas}


def indice_resumido(programa: Programa) -> str:
    """Uma linha por aula, para entrar num prompt sem custar o programa inteiro."""
    linhas = []
    for aula in programa.aulas:
        topicos = "; ".join(aula.topicos[:4])
        linhas.append(f"{aula.numero:02d} — {aula.titulo}" + (f" ({topicos})" if topicos else ""))
    return "\n".join(linhas)


def mesclar(antigo: Programa | None, novo: Programa) -> Programa:
    """Recoleta atualiza título/tópicos/materiais, mas nunca perde o que você anotou.

    `data` é o caso que importa: é preenchida quando um job de aula é casado com o
    número, não vem do site, e sumiria a cada recoleta se a mesclagem fosse cega.
    """
    if antigo is None:
        return novo

    datas_conhecidas = {aula.numero: aula.data for aula in antigo.aulas if aula.data}
    aulas_antigas = {aula.numero: aula for aula in antigo.aulas}

    mescladas: list[AulaPrograma] = []
    for aula in novo.aulas:
        aulas_antigas.pop(aula.numero, None)
        mescladas.append(
            aula.model_copy(update={"data": aula.data or datas_conhecidas.get(aula.numero)})
        )
    # aula que existia só no programa antigo (anotada à mão) continua existindo
    mescladas.extend(aulas_antigas.values())
    mescladas.sort(key=lambda aula: aula.numero)

    return novo.model_copy(
        update={
            "titulo_oficial": novo.titulo_oficial or antigo.titulo_oficial,
            "fonte_url": novo.fonte_url or antigo.fonte_url,
            "aulas": mescladas,
        }
    )


def registrar_data(disciplina: str, numero: int, data: str) -> Programa | None:
    """Liga uma data de aula ao número do programa. É o que amarra nota ↔ material."""
    programa = carregar(disciplina)
    if programa is None:
        return None
    aula = aula_por_numero(programa, numero)
    if aula is None:
        return programa
    atualizadas = [
        item.model_copy(update={"data": data}) if item.numero == numero else item
        for item in programa.aulas
    ]
    programa = programa.model_copy(
        update={"aulas": atualizadas, "coletado_em": programa.coletado_em}
    )
    salvar(programa)
    return programa


def normalizar_titulo(texto: str) -> set[str]:
    """Tokens significativos de um título, para casamento por similaridade."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    palavras = re.findall(r"[a-z0-9]+", sem_acento.lower())
    return {p for p in palavras if p not in _STOPWORDS and len(p) > 2}


def agora_iso() -> str:
    return datetime.now(UTC).isoformat()
