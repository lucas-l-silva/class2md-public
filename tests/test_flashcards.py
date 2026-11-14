import csv
import io

from projetos.estudos.flashcards import (
    _converter_latex,
    gera_csv_basico,
    gera_csv_cloze,
)
from projetos.estudos.schemas import FlashcardBasico, FlashcardCloze


def _linhas_de_dados(csv_texto: str) -> list[list[str]]:
    # As primeiras 6 linhas são diretivas #-prefixadas; o resto é CSV de verdade.
    corpo = "\n".join(csv_texto.splitlines()[6:])
    return list(csv.reader(io.StringIO(corpo)))


def test_converter_latex_bloco_e_inline():
    assert _converter_latex("Fórmula: $$E=mc^2$$") == "Fórmula: \\[E=mc^2\\]"
    assert _converter_latex("A área é $A$.") == "A área é \\(A\\)."


def test_gera_csv_basico_tem_diretivas_do_anki():
    cards = [FlashcardBasico(tipo="basico", frente="P1", verso="R1")]
    csv_texto = gera_csv_basico(cards, "Algoritmos", "2026-07-15")

    linhas = csv_texto.splitlines()
    assert linhas[0] == "#separator:Comma"
    assert linhas[1] == "#html:true"
    assert linhas[2] == "#deck:Algoritmos"
    assert linhas[3] == "#notetype:Basic"
    assert linhas[4] == "#guid column:1"
    assert linhas[5] == "#tags column:4"


def test_gera_csv_basico_uma_linha_por_card_com_tag_da_data():
    cards = [
        FlashcardBasico(tipo="basico", frente="P1", verso="R1"),
        FlashcardBasico(tipo="basico", frente="P2", verso="R2"),
    ]
    csv_texto = gera_csv_basico(cards, "Algoritmos", "2026-07-15")

    dados = _linhas_de_dados(csv_texto)
    assert len(dados) == 2
    assert dados[0][1:] == ["P1", "R1", "2026-07-15"]
    assert dados[1][1:] == ["P2", "R2", "2026-07-15"]


def test_gera_csv_cloze_tem_notetype_cloze_e_colunas_texto_extra():
    cards = [FlashcardCloze(tipo="cloze", texto="{{c1::x}}", extra="contexto")]
    csv_texto = gera_csv_cloze(cards, "Historia", "2026-07-15")

    assert "#notetype:Cloze" in csv_texto.splitlines()
    dados = _linhas_de_dados(csv_texto)
    assert dados[0][1:] == ["{{c1::x}}", "contexto", "2026-07-15"]


def test_csv_usa_aspas_quando_ha_virgula_ou_quebra_de_linha():
    cards = [FlashcardBasico(tipo="basico", frente="P, com vírgula", verso="linha1\nlinha2")]
    csv_texto = gera_csv_basico(cards, "Algoritmos", "2026-07-15")

    dados = _linhas_de_dados(csv_texto)
    # a quebra de linha do conteúdo virou <br> (html:true) — não é mais quebra física de linha
    assert dados[0][1] == "P, com vírgula"
    assert dados[0][2] == "linha1<br>linha2"
    assert len(dados) == 1  # o <br> garante que o parser não veja uma 2ª linha


def test_csv_converte_latex_no_conteudo_dos_campos():
    cards = [FlashcardBasico(tipo="basico", frente="Qual a fórmula?", verso="$$E=mc^2$$")]
    csv_texto = gera_csv_basico(cards, "Fisica", "2026-07-15")

    dados = _linhas_de_dados(csv_texto)
    assert dados[0][2] == "\\[E=mc^2\\]"


def test_guid_estavel_para_o_mesmo_card_reprocessado():
    card = FlashcardBasico(tipo="basico", frente="P1", verso="R1")
    primeira = gera_csv_basico([card], "Algoritmos", "2026-07-15")
    segunda = gera_csv_basico([card], "Algoritmos", "2026-07-15")

    guid1 = _linhas_de_dados(primeira)[0][0]
    guid2 = _linhas_de_dados(segunda)[0][0]
    assert guid1 == guid2


def test_guid_difere_entre_cards_diferentes():
    cards = [
        FlashcardBasico(tipo="basico", frente="P1", verso="R1"),
        FlashcardBasico(tipo="basico", frente="P2", verso="R2"),
    ]
    csv_texto = gera_csv_basico(cards, "Algoritmos", "2026-07-15")

    dados = _linhas_de_dados(csv_texto)
    assert dados[0][0] != dados[1][0]


def test_deck_leva_o_semestre_do_curso(tmp_path, monkeypatch):
    """`MAT1-S6` agrupa os baralhos por período no Anki, que ordena por nome."""
    from projetos.estudos.disciplinas import (
        Disciplina,
        Registro,
        nome_do_baralho,
        salvar_registro,
    )

    salvar_registro(
        Registro(
            semestre_atual="2030.2",
            semestre_curso=6,
            disciplinas=[
                Disciplina(nome="MAT1", titulo="Construção", semestre="2030.2"),
                Disciplina(
                    nome="OPTATIVA",
                    titulo="Optativa de outro período",
                    semestre="2030.2",
                    semestre_curso=4,
                ),
            ],
        )
    )

    assert nome_do_baralho("MAT1") == "MAT1-S6"
    # o override por disciplina vence o número do registro
    assert nome_do_baralho("OPTATIVA") == "OPTATIVA-S4"
    # sigla fora do registro não inventa número
    assert nome_do_baralho("DESCONHECIDA") == "DESCONHECIDA-S6"


def test_sem_semestre_no_registro_o_deck_e_so_a_sigla():
    from projetos.estudos.disciplinas import Registro, nome_do_baralho, salvar_registro

    salvar_registro(Registro(semestre_atual="2030.2"))

    assert nome_do_baralho("ALEMAO-A1.1") == "ALEMAO-A1.1"


def test_renomear_o_baralho_nao_recria_os_cards():
    """O guid é chaveado pela sigla: mudar o deck no Anki não pode custar o histórico
    de revisão de cada card."""
    cards = [FlashcardBasico(tipo="basico", frente="O que é O(n)?", verso="linear")]

    sem_baralho = gera_csv_basico(cards, "MAT1", "2026-08-10")
    com_baralho = gera_csv_basico(cards, "MAT1", "2026-08-10", "MAT1-S6")

    assert "#deck:MAT1-S6" in com_baralho
    assert "#deck:MAT1\n" in sem_baralho
    guid = lambda csv: csv.splitlines()[6].split(",")[0]  # noqa: E731
    assert guid(sem_baralho) == guid(com_baralho)
