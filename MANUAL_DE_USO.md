---
titulo: Manual de uso do class2md
resumo: Como transformar fotos de aula e PDFs em notas Markdown e flashcards, por objetivo. Cada seção traz pré-requisito, comandos, como saber que deu certo e o erro mais comum.
publico: pessoas e agentes de código
prefixo_dos_comandos: uv run python scripts/estudos.py
pasta_de_dados_padrao: ~/agent-data
marcas: "⚠ custa API ou grava arquivo; ✔ como saber que deu certo"
---

# Manual de uso

## Convenções

- Todo comando roda na raiz do repositório.
- `<DADOS>` é a pasta de dados. O padrão é `~/agent-data`. Para mudar, defina `CLASS2MD_HOME` no `.env`.
- `<Disciplina>` é o nome da pasta que você cria. Use letras, números, hífen e sublinhado, sem espaço.
- `<execução>` é o identificador que o comando `status` mostra, com 8 caracteres. Um prefixo basta.
- **Custa API** quer dizer que o comando chama um modelo pago com a sua chave.
- **Pasta de revisão** é `<DADOS>/estudos/output/`. É onde as notas nascem. O class2md nunca escreve no cofre do Obsidian.
- **Resultado guardado** é o que o class2md já calculou para um arquivo. Ele é reconhecido pelo conteúdo do arquivo. Usar de novo não custa.

| Pasta | Conteúdo | Quem escreve |
|---|---|---|
| `<DADOS>/estudos/inbox/<Disciplina>/` | Fotos a processar | você |
| `<DADOS>/estudos/pdfs/<Disciplina>/` | PDFs de livro, lista e slides | você |
| `<DADOS>/estudos/output/<Disciplina>/` | Notas em revisão e páginas de conceito | class2md |
| `<DADOS>/estudos/flashcards/<Disciplina>/` | CSV para o Anki | class2md |
| `<DADOS>/estudos/processed/<Disciplina>/` | Fotos já lidas, sem os metadados da câmera | class2md |
| `<DADOS>/estudos/trash/` | O que os comandos de limpeza retiram. Nada é apagado | class2md |
| `<DADOS>/logs/` e `<DADOS>/estado.db` | Registro de execuções e de gastos | class2md |

## Todos os comandos

Prefixo: `uv run python scripts/estudos.py`.

| Comando | O que faz | Custa API? | Efeito colateral |
|---|---|---|---|
| `status` | Mostra a fila e as últimas execuções | não | nenhum |
| `processar` | Lê as fotos novas e gera nota, flashcards e conceitos | ⚠ sim | move as fotos para `processed/`; grava nota, CSV e recortes |
| `processar --etapas a,b` | Roda só as etapas pedidas | ⚠ sim | os mesmos, limitados às etapas |
| `processar --sem-flashcards` | Conclui as notas sem gerar cartões | ⚠ sim | não grava CSV |
| `custos` | Gasto do mês, projeção e detalhe por passo | não | nenhum |
| `custos --mes AAAA-MM` | O mesmo, para outro mês | não | nenhum |
| `custos --reconciliar` | Completa o registro de gastos com o que o log tem | não | ⚠ acrescenta lançamentos; nunca reduz o total |
| `aprovar <execução>` | Devolve à fila uma execução que parou para perguntar | não | muda o estado; o próximo `processar` pode custar |
| `reprocessar <execução>` | Marca para refazer tudo, sem usar o resultado guardado | não | o próximo `processar` custa a aula inteira |
| `reprocessar <execução> --passo <agente>` | Marca para refazer só um agente | não | o próximo `processar` custa esse agente |
| `reprocessar <execução> --com-cache` | Marca para refazer usando o resultado guardado | não | o próximo `processar` só custa o que mudou |
| `indexar-pdf [caminho]` | Registra PDFs e monta o índice de capítulos dos livros | ⚠ sim, para livro, uma vez | grava o registro e o índice |
| `pdfs <Disciplina>` | Lista os PDFs registrados | não | nenhum |
| `ocr-pdf <Disciplina>` | Lê por imagem os PDFs sem camada de texto | ⚠ sim, por página | grava o texto lido; pede confirmação |
| `preencher-lacunas <execução>` | Responde as dúvidas da nota com trechos do livro | ⚠ sim | ⚠ reescreve duas seções da nota, depois de você confirmar |
| `enriquecer <Disciplina> --aula N` | Acrescenta à nota material que chegou depois | ⚠ sim | ⚠ reescreve seções da nota. Veja a observação abaixo |
| `moc [Disciplina]` ou `moc --todos` | Gera a nota-índice da disciplina | não | grava o índice na pasta de revisão |
| `disciplinas` | Lista o registro de disciplinas | não | nenhum |
| `disciplinas --exemplo` | Cria um registro de exemplo | não | ⚠ grava `disciplinas.toml`, se não existir |
| `programa <Disciplina>` | Mostra o programa de aulas registrado | não | nenhum |
| `inbox` | Mostra o que ainda está na pasta de entrada | não | nenhum |
| `inbox --limpar` | Retira as fotos que já viraram nota | não | ⚠ move para `trash/`; pede confirmação |
| `crops [Disciplina]` | Lista os recortes que nenhuma nota usa | não | nenhum |
| `crops --mover` | Retira esses recortes | não | ⚠ move para `trash/`; pede confirmação |
| `reparar-notas` | Conserta a formatação das notas | não | ⚠ reescreve notas, com cópia de segurança |
| `reparar-notas --renumerar <Disciplina>` | Corrige o número das aulas pela ordem das datas | não | ⚠ renomeia arquivos |
| `promover-finalizar` | Uso interno do promotor | não | não rode à mão |

Outros dois programas:

| Comando | O que faz | Custa API? | Efeito colateral |
|---|---|---|---|
| `uv run python scripts/bootstrap.py` | Cria as pastas e valida a configuração | não | cria `<DADOS>` |
| `uv run python scripts/bootstrap.py --dry-run` | Só lista o que criaria | não | nenhum |
| `uv run python scripts/promover.py` | Mostra o plano de promoção ao Obsidian | não | copia as notas para uma pasta local de conferência |
| `uv run python scripts/promover.py --sem-simular` | Promove, nota a nota, com a sua confirmação | não | ⚠ escreve no cofre do Obsidian |

Opções que pulam a pergunta de confirmação: `--sim` em `ocr-pdf`, `preencher-lacunas`, `enriquecer`, `inbox`, `crops` e `reparar-notas`. Use só em automação.

Observação sobre `enriquecer`: ele só age sobre uma nota já concluída, que você indica pelo número da aula, e só gasta API quando chegou material novo para essa aula. Sem material novo, ele avisa que a nota já está em dia. `--force` reescreve mesmo assim. Para ligar um PDF a uma aula, registre-o com `indexar-pdf <arquivo> --aula N`.

## 1. Quero preparar o computador

**Pré-requisito:** Python 3.12 ou mais novo, `uv` e uma chave da API da Anthropic.

1. Instale as dependências.
   ```bash
   uv sync
   ```
2. Crie o arquivo de configuração.
   ```bash
   cp .env.example .env
   chmod 600 .env
   ```
3. Abra o `.env` e preencha `ANTHROPIC_API_KEY`. Se quiser, ajuste `TETO_MENSAL_USD`.
4. Crie as pastas.
   ```bash
   uv run python scripts/bootstrap.py
   ```

✔ **Deu certo se** a última linha for `Tudo certo: estrutura criada e configuração validada.`

**Erro mais comum:** `ValidationError` citando `anthropic_api_key`. O `.env` está vazio ou fora da raiz do repositório. Confira com `ls -la .env`.

## 2. Quero transformar fotos de uma aula em nota

**Pré-requisito:** seção 1 feita; fotos em JPEG ou PNG.

1. Crie a pasta da disciplina e copie as fotos.
   ```bash
   mkdir -p ~/agent-data/estudos/inbox/Exemplo
   cp /caminho/das/fotos/*.jpg ~/agent-data/estudos/inbox/Exemplo/
   ```
2. ⚠ Processe. Custa API e move as fotos.
   ```bash
   uv run python scripts/estudos.py processar
   ```
3. Veja o resultado.
   ```bash
   uv run python scripts/estudos.py status
   ```

✔ **Deu certo se** `status` mostrar a execução como `concluido` e existir um arquivo `.md` em `~/agent-data/estudos/output/Exemplo/`.

Como as fotos viram aulas:
- Fotos da mesma disciplina e do mesmo dia formam uma aula.
- O dia vem dos metadados da foto. Para informar o dia você mesmo, use uma subpasta com a data: `inbox/Exemplo/2026-03-10/`.
- Foto solta na raiz de `inbox/` não é processada.

**Erro mais comum:** a execução aparece como `aguardando_humano`. O class2md parou para perguntar, por exemplo porque uma foto não parece ser de aula. Leia o motivo em `status`. Para seguir:
```bash
uv run python scripts/estudos.py aprovar <execução>
uv run python scripts/estudos.py processar
```

## 3. Quero rodar só uma parte

**Pré-requisito:** fotos na pasta de entrada, como na seção 2.

| Etapa | O que faz | Precisa de |
|---|---|---|
| `leitura` | Classifica, trata a imagem e transcreve cada foto | nada |
| `nota` | Escreve e confere a nota | `leitura` |
| `flashcards` | Gera os cartões para o Anki | `nota` |
| `conceitos` | Cria as páginas de conceito | `nota` |
| `disciplina` | Atualiza a ementa da disciplina | `leitura` |

⚠ Só ler as fotos, sem escrever a nota:
```bash
uv run python scripts/estudos.py processar --etapas leitura
```
⚠ Ler e escrever a nota, sem cartões nem conceitos:
```bash
uv run python scripts/estudos.py processar --etapas leitura,nota
```

Se você pedir uma etapa sem a anterior, o class2md inclui a anterior e avisa.

✔ **Deu certo se** `status` mostrar a execução como `parcial`, quando você parou antes da nota, ou `concluido`, quando a nota foi escrita.

Para continuar depois, sem pagar de novo pelo que já foi feito:
```bash
uv run python scripts/estudos.py reprocessar <execução> --com-cache
uv run python scripts/estudos.py processar --etapas leitura,nota,flashcards
```

**Erro mais comum:** pedir etapa de PDF em `--etapas`. PDF tem comandos próprios: veja as seções 4 e 5.

## 4. Quero usar um capítulo do livro

**Pré-requisito:** uma nota já concluída e o PDF do livro com camada de texto.

1. Coloque o livro na pasta da disciplina.
   ```bash
   mkdir -p ~/agent-data/estudos/pdfs/Exemplo/livros
   cp /caminho/do/livro.pdf ~/agent-data/estudos/pdfs/Exemplo/livros/
   ```
2. ⚠ Monte o índice de capítulos. Custa uma chamada, uma única vez por livro.
   ```bash
   uv run python scripts/estudos.py indexar-pdf
   ```
3. Confira o registro.
   ```bash
   uv run python scripts/estudos.py pdfs Exemplo
   ```
4. ⚠ Peça ao class2md para responder as dúvidas da nota com o capítulo que você escolher. Ele mostra o que vai mudar e pergunta antes de escrever.
   ```bash
   uv run python scripts/estudos.py preencher-lacunas <execução> --capitulo 3
   ```
   Repita `--capitulo` para mais de um. Sem `--capitulo`, o class2md sugere os capítulos. Com mais de um livro na disciplina, indique qual com `--livro <nome-do-arquivo>`.

✔ **Deu certo se** a nota ganhar a seção `## Do livro`, com a citação do arquivo e das páginas.

O que o class2md não faz: ele não copia a solução de um manual de soluções. Quando existe gabarito, a nota só aponta a página onde conferir.

**Erro mais comum:** o livro aparece em `pdfs` sem texto. É um PDF digitalizado. ⚠ A leitura por imagem custa por página, mostra a estimativa e pede confirmação:
```bash
uv run python scripts/estudos.py ocr-pdf Exemplo
```

## 5. Quero juntar a lista ou os slides à nota da aula

**Pré-requisito:** o PDF da lista ou dos slides e a data da aula.

1. Registre o PDF ligado ao dia da aula. PDF pequeno só é registrado, sem custo.
   ```bash
   uv run python scripts/estudos.py indexar-pdf /caminho/da/lista.pdf --tipo exercicios --data-aula 2026-03-10
   ```
   Valores de `--tipo`: `livro`, `aula`, `slides`, `exercicios`. Sem `--tipo`, o class2md detecta. Use `--disciplina <Disciplina>` se o arquivo estiver fora da pasta da disciplina.
2. ⚠ Processe as fotos daquele dia, como na seção 2. O material entra na composição da nota.

Se a nota daquele dia já existia, refaça só a escrita:
```bash
uv run python scripts/estudos.py reprocessar <execução> --passo compositor
uv run python scripts/estudos.py processar
```

✔ **Deu certo se** a nota citar o material na seção de materiais da aula.

**Erro mais comum:** a data não bate. O PDF só entra quando `--data-aula` é igual ao dia das fotos. Confira o dia em `status` e a data em `pdfs <Disciplina>`.

## 6. Quero ver quanto gastei

**Pré-requisito:** nenhum. O comando só lê.

```bash
uv run python scripts/estudos.py custos
uv run python scripts/estudos.py custos --mes 2026-03
```

✔ **Deu certo se** aparecer o total do mês, a projeção e uma linha por passo e modelo.

Como o limite funciona:
- `TETO_MENSAL_USD` no `.env` é o limite do mês. Sem a variável, vale 25.
- Quando o gasto do mês chega ao limite, o class2md **para de fazer chamadas novas**. O que tem resultado guardado continua funcionando.
- Configure também um limite no console da Anthropic.

**Erro mais comum:** execuções passam a falhar e o log diz `orçamento mensal estourado`. Para liberar só uma rodada, sem mexer no `.env`:
```bash
TETO_MENSAL_USD=40 uv run python scripts/estudos.py processar
```

Se o total parecer menor que o esperado depois de uma interrupção, complete o registro a partir do log. ⚠ Grava no registro de gastos:
```bash
uv run python scripts/estudos.py custos --reconciliar
```

## 7. Quero refazer uma nota sem gastar de novo

**Pré-requisito:** a execução está `concluido`, `falhou` ou `parcial`.

```bash
uv run python scripts/estudos.py reprocessar <execução> --com-cache
uv run python scripts/estudos.py processar
```

✔ **Deu certo se** `custos` mostrar o mesmo total de antes, ou uma diferença de poucos centavos.

Por que pode custar um pouco: o resultado guardado vale para a mesma entrada. Se a disciplina ganhou notas novas ou um PDF da aula desde a última vez, o agente que usa essa informação roda de novo. A leitura das fotos, que é a parte cara, não se repete.

**Erro mais comum:** usar `reprocessar` sem opção. Assim o class2md ignora o resultado guardado e paga a aula inteira outra vez.

## 8. Quero refazer depois de mudar um prompt

**Pré-requisito:** você editou um arquivo em `projetos/estudos/prompts/` e aumentou o número da primeira linha, `PROMPT_VERSION`.

| O que mudou | O que rodar |
|---|---|
| Prompt do compositor | `reprocessar <execução> --passo compositor` |
| Prompt dos flashcards | `reprocessar <execução> --passo flashcards` |
| Prompt do extrator, ou a foto foi mal lida | `reprocessar <execução>` |
| Só a formatação, com conteúdo certo | `reparar-notas`, que não chama modelo |

Depois, ⚠ `uv run python scripts/estudos.py processar`.

✔ **Deu certo se** a nota mudar e `custos` mostrar gasto só no passo refeito.

**Erro mais comum:** esquecer `--passo`. Sem ele, cada foto é lida de novo.

## 9. Quero levar a nota ao Obsidian e os cartões ao Anki

**Pré-requisito:** nota `concluido` na pasta de revisão.

**Obsidian.** Configure uma vez:
```bash
mkdir -p ~/.config/class2md
cp docs/promotor.example.toml ~/.config/class2md/promotor.toml
```
Edite `vault_dir` e `anexos_dir`. Depois:
```bash
uv run python scripts/promover.py
```
Esse comando só mostra o plano. ⚠ Para promover de verdade, com revisão nota a nota:
```bash
uv run python scripts/promover.py --sem-simular
```
O promotor tem um único comando, então não se escreve `promover` depois do nome do script. Para ver as opções: `uv run python scripts/promover.py --help`.

✔ **Deu certo se** a nota aparecer no cofre e `status` mostrar a execução como `promovido`.

**Anki.** Arquivo, Importar, e escolha os CSV de `<DADOS>/estudos/flashcards/<Disciplina>/`. Importe `_basico.csv` e `_cloze.csv` separadamente. Importar de novo não duplica cartões.

**Erro mais comum:** `promover` diz que a configuração não foi encontrada. Falta o `promotor.toml` do primeiro passo.

## 10. Quero arrumar as pastas

**Pré-requisito:** nenhum. Os comandos sem opção só listam.

```bash
uv run python scripts/estudos.py inbox
uv run python scripts/estudos.py crops
```
⚠ Para retirar o que já foi usado. Vai para `trash/`, nada é apagado:
```bash
uv run python scripts/estudos.py inbox --limpar
uv run python scripts/estudos.py crops --mover
```

✔ **Deu certo se** o comando listar o que moveu e `inbox` não mostrar mais fotos processadas.

**Erro mais comum:** esperar que um PDF saia da pasta. PDF nunca é movido: as notas guardam o caminho dele.

## 11. Deu errado

| Sintoma | Causa provável | Correção |
|---|---|---|
| `ConfigInvalido: caminho base não existe` | A pasta de dados não foi criada | `uv run python scripts/bootstrap.py` |
| `ValidationError` com `anthropic_api_key` | `.env` vazio ou fora da raiz | Preencha a chave no `.env` da raiz do repositório |
| `Já existe um processamento em andamento` | Outro `processar` está rodando | Espere terminar |
| `Jobs com falha` ao fim do `processar` | Erro em uma chamada, ou limite do mês atingido | Veja a última linha de `<DADOS>/logs/AAAA-MM-DD.jsonl`; depois `reprocessar <execução> --com-cache` e `processar` |
| `orçamento mensal estourado` no log | O gasto chegou ao limite | Seção 6 |
| Execução em `aguardando_humano` | O class2md fez uma pergunta | Leia o motivo em `status`; `aprovar <execução>` |
| Foto não é processada | Está na raiz de `inbox/`, ou não é JPEG nem PNG | Mova para `inbox/<Disciplina>/`; converta HEIC e WebP para JPEG |
| Aula caiu no dia errado | A data dos metadados da foto não é a da aula | Use a subpasta com a data, `inbox/<Disciplina>/AAAA-MM-DD/` |
| Duas notas para a mesma aula, ou números fora de ordem | Reprocessamentos antigos | `reparar-notas --renumerar <Disciplina>` |
| Nota com parágrafos quebrados | Formatação do modelo | `reparar-notas` |
| `disciplinas`, `programa` ou `moc` saem com erro de registro | Não existe o registro de disciplinas, que é opcional | `disciplinas --exemplo` e edite o arquivo criado |

Se nada resolver, rode os testes. Eles não chamam a API:
```bash
uv run pytest
```

## 12. Quero medir quanto tempo isto me poupa

O class2md não traz número de economia pronto. Você mede.

1. Escolha de 3 a 5 aulas parecidas.
2. Para cada uma, cronometre o jeito manual: transcrever, montar a nota e criar os cartões.
3. Para as mesmas aulas, cronometre só o tempo em que você fica ativo com o class2md: copiar as fotos, rodar, ler a nota, aprovar.
4. Anote em uma planilha com as colunas `material`, `modo`, `unidades`, `atencao_s`, `maquina_s`, `observacao`.
5. Compare as medianas dos dois modos. Informe sempre quantas aulas mediu.

O tempo de espera da máquina fica em coluna separada, porque não exige a sua atenção.

## Referência

| Assunto | Documento |
|---|---|
| Visão geral e início rápido | `README.md` |
| PDFs: tipos, pastas, índice, leitura por imagem | `docs/INGESTAO_PDF.md` |
| Ordem de prioridade das fontes | `docs/HIERARQUIA_DE_FONTES.md` |
| Perfis de nota | `docs/PERFIS_DE_NOTA.md` |
| Qualidade da nota | `docs/QUALIDADE_DA_NOTA.md` |
| Formato da nota | `projetos/estudos/ESTRUTURA_MARKDOWN.md` |
| Promoção ao Obsidian | `docs/promotor.md` |
| Segurança | `SECURITY.md` |
| Regras para agentes de código | `AGENTS.md` |
