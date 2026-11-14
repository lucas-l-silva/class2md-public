# Ingestão de PDF — livros, notas de aula, slides, listas de exercícios


Este documento registra **o que foi construído** (sem RAG vetorial; índice de capítulos cacheado, com override manual):
módulos, funções, comandos, formato de cache, e como testar.

## Visão geral do fluxo

```
PDF em estudos/pdfs/<Disciplina>/[livros|aulas|slides|exercicios/]
    → registrar_pdf()      classifica tipo + modo, registra na tabela `pdfs` (sha256, sem mover o arquivo)
    → [livro, modo=indexado] indice_do_livro()   extrai capítulo→página uma vez, cacheado por hash
    → [pequeno, modo=direto] texto_direto()      cacheia o texto inteiro, sem custo de índice

Nota já concluída, com lacunas (duvidas/avisos_conceitos no manifesto):
    → preencher-lacunas <job_id> [--capitulo N] [--livro NOME] [--sim]
        resolver_capitulos()       manual (sem LLM) OU sugerido (AgenteSeletorCapitulos)
        trechos_dos_capitulos()    extrai só os capítulos resolvidos, cacheado por hash do índice
        consultar()                AgenteBibliotecario responde cada lacuna, com citação obrigatória
        remendo_nota.aplicar()     reescreve só "## Do livro" e "## Pontos sinalizados como difícil"

Nota nova (qualquer job de aula):
    → materiais_da_aula(disciplina, data)   PDFs pequenos com data_aula casando entram direto
      do_livro (do manifesto, se preencher-lacunas já rodou)  sobrevive a reprocessar
```

## Onde os PDFs entram

Duas raízes valem ao mesmo tempo. `estudos/pdfs/<Disciplina>/` é o layout original;
`estudos/inbox/<SIGLA>/pdfs/` é o do registro de disciplinas, criado ao registrar a disciplina. Nos dois casos vale a regra que motivou a separação das fotos:
`inbox/` é uma fila que **drena** (`ingerir_imagem()` move o arquivo e ele vira job de
aula), enquanto **PDF nunca é movido e nunca vira job sozinho** — é material de
referência consultado por várias aulas ao longo do semestre. A varredura de fotos só
olha arquivos de imagem no primeiro nível, então as subpastas de PDF não a atrapalham.

```
estudos/inbox/MAT1/pdfs/
  ementa/                      ementa, plano de ensino
  atuais/{notas,slides,provas,listas}/     material deste semestre
  antigas/{notas,slides,provas,listas}/    material de semestres passados
  livros/{completo,capitulos}/
  qualquer-coisa.pdf           solto: classificado por heurística
```

**Vigência** (`atuais` × `antigas`) não é organização estética: material antigo **nunca**
entra na composição de uma nota nova. Ele só é consultado para preencher lacunas, e com
prioridade maior quando for de autoria de quem ministra a disciplina hoje
(`disciplinas.autoria_de_docente_atual`).

## Classificação (`projetos/estudos/pdf_ingestao.py`)

Determinística, sem LLM. Ordem de resolução do tipo:

1. `--tipo` explícito no CLI.
2. **Nome de gabarito** (`gabarito`, `solutions manual`, `resolução`, `answers`). Vem antes
   da pasta de propósito: um manual de soluções mora junto dos livros e um gabarito de prova
   mora junto das provas — a pasta diz onde o arquivo está, o nome diz o que ele é.
3. Subpasta de tipo: `livros`, `notas`/`aulas`, `slides`, `listas`/`exercicios`, `provas`,
   `ementa`, `gabaritos`.
4. Heurística (`classificar()`):
   - `paginas >= 40` OU (`len(toc) >= 5` E `paginas >= 25`) → **livro**.
   - Paisagem (landscape) E mediana de chars/página < 600 → **slides**.
   - `paginas <= 15` E ≥30% das páginas com linha tipo "1. enunciado..." → **exercicios**.
   - Senão → **aula** (default).

Tipos: `livro`, `aula`, `slides`, `exercicios`, `prova`, `ementa`, `gabarito`.

Modo (`decidir_modo()`): **livro** é sempre `indexado`. Os demais são `direto` se
`chars_total <= 60_000` e `paginas <= 40` (120 para slides — um deck de muitos slides com pouco
texto por página não deve estourar o teto de páginas). Senão, `indexado` também.

### Gabarito: apontar, não copiar

O gabarito é a fonte mais tentadora e a mais nociva: se o texto dele entra na nota, o
exercício vem resolvido e o trabalho de chegar lá — que é o que ensina — desaparece. Por
isso ele **nunca vira `TrechoFonte`**. Em vez disso, `projetos/estudos/gabarito.py` varre o
PDF (sem LLM) por marcações do tipo `Exercise 2.1-1` / `Problem 2-2` e monta
`{referência → página}`; `preencher-lacunas` acrescenta um callout "Onde conferir a solução"
com arquivo, exercício e página, e nada do conteúdo.

Efeito colateral desejado: `livro_da_disciplina` deixa de considerar o manual de soluções
como candidato a livro-texto.

## Texto: nativo por padrão, visão sob pedido

A extração é por **texto nativo** (`pypdf`, licença BSD). `core.pdf.normalizar_texto`
recompõe acentos soltos de PDF gerado por TeX (`"Constru¸ c˜ ao"` → `"Construção"`),
restrito a pares acento+letra que existem na língua para não estragar texto legítimo.

PDF sem camada de texto é **registrado e sinalizado**, nunca cai em visão automaticamente.
Quando vale a pena — notas de aula antigas podem ser manuscrito vetorial exportado de
tablet, sem texto e sem imagem embutida, mas são material do professor — o caminho é
explícito:

```bash
uv run python scripts/estudos.py ocr-pdf MAT1
```

O comando lista os PDFs pendentes, mostra o **custo estimado** e pergunta antes de gastar.
As páginas são rasterizadas com `pypdfium2` (licença permissiva, binário no próprio wheel —
ao contrário de PyMuPDF, que é AGPL, e de pdf2image, que exige poppler no sistema) e lidas
pelo mesmo `AgenteExtrator` que lê foto de lousa. O texto vai para o cache padrão, então o
resto do pipeline consome sem saber a origem. PDF acima de 40 páginas exige `--force`.

## Persistência

- **`core/estado.py`, tabela `pdfs`** (SQLite): registro/consulta (`registrar_pdf_estado`,
  `pdf_por_sha`, `pdfs_por_disciplina`, `pdfs_por_tipo`, `pdfs_por_aula`, `marcar_pdf_indexado`).
  Tabela separada de `arquivos` (fotos) pelo motivo do ciclo de vida já explicado acima — reusar
  `arquivos` faria `fotos_pendentes()` tratar todo PDF como se fosse foto de aula.
- **`cache_dir/pdf/<sha256>/`**: artefatos grandes, chaveados por hash do conteúdo do PDF
  (arquivo mudou → hash novo → cache novo, sem invalidação manual):
  ```
  meta.json (implícito, recalculado on-demand)
  indice.json                              # IndiceLivro materializado (modo=indexado)
  texto.txt                                # texto inteiro cacheado (modo=direto)
  capitulos/<sha_do_indice_12>/<numero:03d>.txt   # texto por capítulo, sob demanda
  paginas/<inicio:04d>-<fim:04d>.txt       # texto_de_paginas() genérico
  ```
  `capitulos/` é chaveado por hash do **índice** (não só do PDF): reindexar com faixas de página
  diferentes gera uma pasta nova em vez de servir texto do capítulo com recorte desatualizado.

## Agentes novos (`core/agents/base.py::Agente`, cache automático por hash de entrada)

| Agente | Tier | Escalada | Papel |
|---|---|---|---|
| `AgenteIndexadorLivro` | Haiku | confiança < 0.7 → Sonnet | TOC nativo (ou texto das ~12 primeiras páginas) → capítulo→página |
| `AgenteSeletorCapitulos` | Haiku | confiança < 0.7 → Sonnet | títulos de capítulo + lacunas → capítulos prováveis (só quando não há `--capitulo`) |
| `AgenteBibliotecario` | Sonnet | — | trechos do livro → seção "Do livro" + resposta de cada lacuna, citação obrigatória |

Validação em código (nunca confia cegamente no modelo):
- **Índice**: páginas fora do range do PDF, ou não estritamente crescentes, ou lista vazia →
  fallback determinístico de janelas fixas de 30 páginas (`fonte_indice="fallback_paginas"`),
  logado como aviso, nunca silencioso.
- **Seleção de capítulo manual (`--capitulo`)**: nunca chama LLM; número inválido → erro claro
  com a lista de capítulos existentes, sem tentar capítulo vizinho.
- **Resposta do bibliotecário**: toda `resolvida=True` sem `citacao` que referencie um dos
  arquivos realmente fornecidos naquela chamada é rebaixada para não-resolvida em código — mesmo
  princípio do filtro anti-alucinação de conexões do `AgenteContexto` (A4).

## Segurança / prompt injection

`core/llm/client.py::envelopar_dados(texto, fonte)` envolve todo conteúdo de PDF em
`<dados fonte="...">...</dados>` antes de entrar em qualquer prompt, neutralizando tentativas de
fechar a tag cedo (`</dados` → `<\/dados`). Usado pelo `AgenteBibliotecario` (por trecho) e por
`materiais_da_aula()` (por PDF pequeno da aula). O guardrail de citação (acima) é a segunda camada:
mesmo que o texto malicioso engane o modelo, uma resposta sem citação válida nunca chega na nota.
Ver `tests/test_injecao_pdf.py` para o teste de ponta a ponta dessa cadeia.

## Comandos CLI (`scripts/estudos.py`)

```bash
# Registro determinístico — sem custo de LLM. Roda dentro de `processar` também.
uv run python scripts/estudos.py pdfs <Disciplina>

# Extrai o índice de capítulos (uma vez por hash). Sem caminho: indexa todos os livros registrados.
uv run python scripts/estudos.py indexar-pdf [caminho] [--tipo] [--disciplina] [--data-aula] [--aula N] [--force]

# Preenche as lacunas de uma nota já concluída, sem reingerir fotos.
uv run python scripts/estudos.py preencher-lacunas <job_id> [--capitulo N ...] [--livro NOME] [--sim]
```

`preencher-lacunas` sem lacunas registradas sai sem custo. Pede confirmação antes de reescrever a
nota, a menos que `--sim`. Revalida a nota (`validar_completo`) depois de aplicar o remendo.

## Materiais da aula no Compositor (`projetos/estudos/biblioteca.py::materiais_da_aula`)

PDFs pequenos (`modo="direto"`) cuja `data_aula` casa com a data do job entram automaticamente na
composição da nota (envelopados, com teto de 40.000 chars e aviso ao truncar) — `data_aula` só é
preenchida se indicada explicitamente (`--data-aula` no registro/indexação), não é inferida.
`do_livro` (seção já resolvida por um `preencher-lacunas` anterior) é lido de volta do manifesto a
cada composição/reprocessamento — não se perde ao rodar `estudos reprocessar`.

## Testes

| Arquivo | Cobre |
|---|---|
| `tests/pdf_fabrica.py` | gera PDFs reais via `reportlab` para teste (texto, TOC/outline, landscape, só-imagem) — nada de binário versionado |
| `tests/test_core_pdf.py` | extração pura: TOC, texto por página, metadados, allowlist, PDF corrompido |
| `tests/test_pdf_ingestao.py` | classificação dos 4 tipos, modo direto/indexado, idempotência, cache de texto |
| `tests/test_biblioteca.py` | índice (TOC/sem TOC/fallback), seleção de capítulo (manual/sugerido), extração por capítulo, `materiais_da_aula` |
| `tests/test_agentes.py` | os 3 agentes novos (mensagem enviada, escalada por confiança) |
| `tests/test_injecao_pdf.py` | cadeia completa de defesa contra prompt injection via PDF |
| `tests/test_remendo_nota.py` | substituição cirúrgica de seção, idempotência, seção ausente |
| `tests/test_estudos_cli.py` | comandos `pdfs`, `indexar-pdf`, `preencher-lacunas` |
| `tests/test_runner.py` | `materiais_da_aula` na composição, `do_livro` sobrevivendo a reprocessar |
| `tests/test_estado.py` | tabela `pdfs`: registro idempotente, consultas por disciplina/tipo/aula |

Rodar só esta fatia: `uv run pytest tests/test_core_pdf.py tests/test_pdf_ingestao.py
tests/test_biblioteca.py tests/test_remendo_nota.py tests/test_injecao_pdf.py -q`

## O que ainda não existe (fora do escopo desta implementação)

- **Slides como deck estruturado**: hoje um deck de slides grande cai em `indexado` com janelas
  fixas de página (sem outline por slide) — não há extração de "capítulo = slide". Funciona, mas
  é menos preciso que um livro com TOC nativo.
- **Metadados de autor/título** de PDFs sem `Info` dict e sem sumário legível: `titulo_livro`/
  `autor` ficam vazios; a citação na nota usa o nome do arquivo.
- **RAG vetorial**: continua fora de escopo
  só voltaria a fazer sentido se o corpus crescesse para múltiplos livros com referência cruzada.
