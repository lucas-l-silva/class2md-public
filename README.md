# class2md

Conjunto de ferramentas que reduz o atrito entre a aula e a revisão.

Você fotografa a lousa e o caderno, ou indica o PDF do livro. O class2md devolve uma nota em Markdown para o Obsidian e flashcards em CSV para o Anki. As chamadas vão para a API da Anthropic, com a sua chave, no seu computador.

<img src="docs/img/fluxo-class2md.svg" width="340" alt="Fluxo em seis etapas: fotos ou PDF, leitura pela IA, nota e flashcards, pasta de revisão, revisão feita por você, Obsidian e Anki.">

1. **Fotos ou PDF.** Lousa, caderno ou livro.
2. **Leitura.** A IA transcreve cada foto.
3. **Nota e flashcards.** Agentes escrevem e conferem.
4. **Pasta de revisão.** Nada vai direto ao Obsidian.
5. **Você revisa.** Só entra o que você aprova.
6. **Obsidian e Anki.** Nota em Markdown e cartões.

Cada etapa pode ser usada sozinha.

## Começar em 5 minutos

Você precisa de Python 3.12 ou mais novo, do [`uv`](https://docs.astral.sh/uv/), de macOS ou Linux e de uma chave da API da Anthropic.

```bash
git clone https://github.com/lucas-l-silva/class2md-public class2md
cd class2md
uv sync
cp .env.example .env
```

Abra o `.env` e preencha `ANTHROPIC_API_KEY`. Depois:

```bash
uv run python scripts/bootstrap.py
```

Deu certo se a última linha for `Tudo certo: estrutura criada e configuração validada.`

## Primeira nota

⚠ Os comandos abaixo chamam uma API paga.

```bash
mkdir -p ~/agent-data/estudos/inbox/Exemplo
cp /caminho/das/suas/fotos/*.jpg ~/agent-data/estudos/inbox/Exemplo/
uv run python scripts/estudos.py processar
uv run python scripts/estudos.py status
```

Deu certo se `status` mostrar a execução como `concluido`. A nota está em `~/agent-data/estudos/output/Exemplo/`.

A pasta dentro de `inbox/` define a disciplina. Fotos em JPEG ou PNG.

## O que ele processa

| Material | Comando | Resultado |
|---|---|---|
| Foto de quadro ou de caderno | `processar` | Nota, flashcards e páginas de conceito |
| PDF de livro inteiro | `indexar-pdf` | Índice de capítulos, feito uma vez |
| PDF por capítulos | `preencher-lacunas <execução> --capitulo N` | Dúvidas da nota respondidas com citação do livro |
| Lista de exercícios ou slides em PDF | `indexar-pdf <arquivo> --data-aula AAAA-MM-DD` | O material entra na nota da aula daquele dia |
| PDF sem camada de texto | `ocr-pdf` | Leitura por imagem, com confirmação de custo |

O class2md não resolve listas de exercícios.

## Rodar só uma parte

```bash
uv run python scripts/estudos.py processar --etapas leitura
uv run python scripts/estudos.py processar --etapas leitura,nota
```

Etapas de foto: `leitura`, `nota`, `flashcards`, `conceitos`, `disciplina`. Uma etapa que depende de outra inclui a anterior e avisa. O que já foi feito para o mesmo arquivo vem do resultado guardado e não é cobrado de novo.

## Custo e proteção

- Cada tarefa usa o modelo mais barato que a resolve: Haiku para classificar, Sonnet para ler e escrever.
- **Limite do mês.** `TETO_MENSAL_USD` no `.env`. Quando o gasto do mês chega ao limite, o class2md para de fazer chamadas novas. Sem a variável, o limite é 25 dólares.
- **Resultado guardado.** O class2md guarda cada resultado pelo identificador do conteúdo do arquivo. Repetir o mesmo material não chama a API.
- **Imagem menor.** Cada foto é tratada e reduzida antes do envio, o que diminui o custo de leitura.
- Configure também um limite de gasto no console da Anthropic.

Veja o gasto real:

```bash
uv run python scripts/estudos.py custos
```

Refaça uma nota aproveitando tudo o que está guardado:

```bash
uv run python scripts/estudos.py reprocessar <execução> --com-cache
uv run python scripts/estudos.py processar
```

## Segurança

- **Sua chave fica no seu computador.** Ela vive no `.env`, que o git ignora, e nunca é escrita em log, nota ou resultado guardado.
- **O class2md não escreve no seu cofre do Obsidian.** As notas saem em uma pasta de revisão. Você decide o que promover.
- **Foto e PDF são dado.** Texto que parece uma ordem para a IA é transcrito como texto comum e a nota recebe um aviso.
- **Acesso restrito a pastas.** O programa só lê e escreve na pasta de dados do class2md.

Suas fotos e PDFs são enviados à API da Anthropic para leitura. Não processe material que você não pode enviar a um serviço externo. Detalhes e como reportar uma falha: [SECURITY.md](SECURITY.md).

## Interface local (em desenvolvimento)

Uma página que roda só no seu computador, em `127.0.0.1`. Ela pergunta o que você quer fazer, mostra o custo antes de rodar e deixa a nota na pasta de revisão.

Estado: em desenvolvimento. Ainda não faz parte desta versão. Use a linha de comando.

<!-- INTERFACE: quando a interface for entregue, apague as duas linhas de "Estado" acima e descomente o bloco abaixo.

```bash
uv run python scripts/estudos.py ui
```

Abra `http://127.0.0.1:8765` no navegador.

| Passo | O que acontece |
|---|---|
| 1. O que você quer fazer? | Você escolhe o material e as etapas. Nada vem marcado |
| 2. Arquivos | Você envia as fotos |
| 3. Custo e tempo | A página mostra a estimativa e pede confirmação |
| 4. Acompanhar | Uma linha por etapa, com o custo parcial |
| 5. Revisar | A nota aparece ao lado das fotos. Ela fica na pasta de revisão |

Ainda em desenvolvimento dentro da interface: tirar dúvidas antes de gravar e o painel de economia de tempo.
-->

## Como funciona

Cada aula passa por uma sequência de agentes de IA. Cada agente tem um prompt versionado, um formato de saída validado e um resultado guardado.

| Agente | Faz | Modelo |
|---|---|---|
| Triagem | Classifica cada foto e escolhe o tratamento da imagem | Haiku |
| Extrator | Transcreve a lousa ou o manuscrito | Sonnet |
| Contexto | Propõe título, tópicos e ligações com notas anteriores | Haiku |
| Compositor | Escreve a nota no modelo da disciplina | Sonnet |
| Validador | Confere a nota e devolve os problemas para uma correção | Haiku |
| Flashcards | Gera os cartões para o Anki | Sonnet |
| Conceito | Cria uma página para cada termo novo | Sonnet |

Triagem e Contexto repetem a tarefa no Sonnet quando a confiança da primeira resposta é baixa. Para livros em PDF há mais três agentes: um monta o índice, outro escolhe os capítulos e outro responde as dúvidas com citação obrigatória.

## Onde ficam as coisas

| O quê | Onde |
|---|---|
| Fotos a processar | `~/agent-data/estudos/inbox/<Disciplina>/` |
| Notas em revisão | `~/agent-data/estudos/output/<Disciplina>/` |
| Flashcards | `~/agent-data/estudos/flashcards/<Disciplina>/` |
| PDFs | `~/agent-data/estudos/pdfs/<Disciplina>/` |
| Registro de gastos e execuções | `~/agent-data/estado.db` e `~/agent-data/logs/` |

Para usar outra pasta de dados, defina `CLASS2MD_HOME` no `.env`.

## Documentação

| Para | Leia |
|---|---|
| Usar no dia a dia, por objetivo | [MANUAL_DE_USO.md](MANUAL_DE_USO.md) |
| Agentes de código que abrem o repositório | [AGENTS.md](AGENTS.md) |
| PDFs: tipos, índice, leitura por imagem | [docs/INGESTAO_PDF.md](docs/INGESTAO_PDF.md) |
| Levar a nota ao Obsidian | [docs/promotor.md](docs/promotor.md) |
| Formato da nota | [projetos/estudos/ESTRUTURA_MARKDOWN.md](projetos/estudos/ESTRUTURA_MARKDOWN.md) |
| Qualidade e perfis de nota | [docs/QUALIDADE_DA_NOTA.md](docs/QUALIDADE_DA_NOTA.md), [docs/PERFIS_DE_NOTA.md](docs/PERFIS_DE_NOTA.md) |

## Desenvolvimento

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Os testes não chamam a API. A lógica compartilhada fica em `core/`.

## Limitações

- Fotos em HEIC e WebP não são aceitas. Exporte como JPEG.
- Não há banco vetorial. O índice de capítulos resolve o volume de uma disciplina.
- A promoção ao Obsidian é feita por `scripts/promover.py`, com simulação por padrão.

## Licença

MIT. Veja [LICENSE](LICENSE).
