from projetos.estudos.markdown_fmt import juntar_paragrafos


def test_junta_paragrafo_quebrado():
    """O caso real: o resumo da MAT1 aula 1 veio partido em 12 linhas de ~100 caracteres."""
    entrada = (
        "## Resumo da aula\n"
        "\n"
        "A aula introduz os algoritmos clássicos de ordenação — Seleção, Bolha\n"
        "e Inserção — como primeiro exemplo prático de eficiência.\n"
    )

    assert juntar_paragrafos(entrada) == (
        "## Resumo da aula\n"
        "\n"
        "A aula introduz os algoritmos clássicos de ordenação — Seleção, Bolha "
        "e Inserção — como primeiro exemplo prático de eficiência.\n"
    )


def test_linha_em_branco_separa_paragrafos():
    entrada = "Primeiro parágrafo\ncontinua aqui.\n\nSegundo parágrafo.\n"

    assert juntar_paragrafos(entrada) == "Primeiro parágrafo continua aqui.\n\nSegundo parágrafo.\n"


def test_nao_toca_em_bloco_de_codigo():
    """Juntar linhas de pseudocódigo destruiria o algoritmo."""
    entrada = "```\npara i <- 1 até N\n    se A[i] > A[i+1]\n        troca\n```\n"

    assert juntar_paragrafos(entrada) == entrada


def test_nao_junta_itens_de_lista():
    entrada = "- Seleção: O(N²)\n- Bolha: O(N²)\n- Inserção: O(N²)\n"

    assert juntar_paragrafos(entrada) == entrada


def test_nao_junta_linhas_de_tabela():
    entrada = "| Algoritmo | Custo |\n|---|---|\n| Bolha | O(N²) |\n"

    assert juntar_paragrafos(entrada) == entrada


def test_nao_junta_callout():
    entrada = "> [!tip] Onde conferir\n> - Solutions Manual, 2.1-1, p. 3\n"

    assert juntar_paragrafos(entrada) == entrada


def test_nao_junta_titulo_com_o_paragrafo_seguinte():
    entrada = "### Algoritmo de Seleção\nO algoritmo percorre o vetor.\n"

    assert juntar_paragrafos(entrada) == entrada


def test_preserva_frontmatter():
    entrada = "---\ndata: 2026-08-10\ndisciplina: MAT1\naula: 1\n---\n\nTexto\nda nota.\n"

    assert juntar_paragrafos(entrada) == (
        "---\ndata: 2026-08-10\ndisciplina: MAT1\naula: 1\n---\n\nTexto da nota.\n"
    )


def test_respeita_quebra_explicita_de_markdown():
    """Dois espaços no fim da linha são quebra intencional — juntar mudaria o render."""
    entrada = "Primeira linha do endereço  \nSegunda linha.\n"

    assert juntar_paragrafos(entrada) == entrada


def test_nao_junta_imagem_com_a_legenda():
    entrada = "![[2026-08-10_mat1_001_crop02.png]]\nO quadro mostra a troca de elementos.\n"

    assert juntar_paragrafos(entrada) == entrada


def test_nao_junta_marcador_de_bloco_gerenciado():
    entrada = "<!-- moc:inicio ementa -->\nConteúdo da ementa.\n<!-- moc:fim ementa -->\n"

    assert juntar_paragrafos(entrada) == entrada


def test_e_idempotente():
    entrada = "Uma prosa\nquebrada em duas.\n\n- lista\n- intacta\n"

    uma_vez = juntar_paragrafos(entrada)

    assert juntar_paragrafos(uma_vez) == uma_vez


def test_nota_ja_limpa_sai_byte_identica():
    """As 9 notas das outras disciplinas já estavam corretas: o reparo não pode mexer."""
    entrada = (
        "---\ndata: 2026-08-15\n---\n\n"
        "# Aula 01\n\n"
        "## Resumo da aula\n\n"
        "Um parágrafo inteiro numa linha só, como deve ser.\n\n"
        "## Conteúdo principal\n\n"
        "- item\n- outro item\n"
    )

    assert juntar_paragrafos(entrada) == entrada
