# Qualidade da nota: formatação, integração do livro e recortes

> ⚠️ **Documentação de referência — o código descrito aqui não está neste repositório.**
> Ele foi implementado no repositório de origem (privado). Este documento registra a
> arquitetura e as decisões, para quem quiser portar a feature ou implementar algo
> equivalente. Antes de assumir que algo aqui já funciona, confira o código de fato.


Três defeitos apareceram só quando a primeira nota de verdade foi lida com calma. Todos
tinham a mesma forma: o pipeline estava correto passo a passo e errado no resultado.

## Parágrafo é uma linha só

Em testes, o resumo de uma nota veio partido em dezenas de linhas curtas. Não havia
`textwrap` no código — **o modelo estava imitando o template**. `ESTRUTURA_MARKDOWN.md`
foi escrito com quebra manual, e tanto o compositor quanto o bibliotecário copiam a
disciplina de linha do exemplo que recebem.

A correção fica em `projetos/estudos/markdown_fmt.py`, aplicada **depois** da geração:

```python
nota = nota.model_copy(update={"markdown": juntar_paragrafos(nota.markdown)})
```

É a mesma escolha já feita em `fontes.py` para a ordenação das fontes: um prompt pode
pedir "não quebre linhas" e ser ignorado; um passo determinístico não. O prompt também
pede — mas quem garante é o código.

A regra é conservadora, porque o erro inverso é pior: duas linhas só se juntam quando
**ambas** são prosa pura. Interrompem a junção: cerca ```…```, tabela `|`, lista
(`-`/`*`/`+`/`1.`), citação/callout `>`, título `#`, imagem `![[…]]`, LaTeX `$$`,
frontmatter, marcador `<!-- moc:… -->` e **quebra explícita** (dois espaços no fim da
linha, que em markdown é `<br>` intencional).

## O livro vai onde ele responde

Antes, tudo que vinha do livro caía numa seção "Do livro" no fim da nota. Uma seção
monolítica no fim é lida como apêndice, não como matéria.

Agora `RespostaLacuna` carrega `secao_alvo` — o título da seção que aquela resposta
completa — e cada resposta vira um callout dentro dela:

```markdown
### Algoritmo de Inserção (Insertion Sort)

… pseudocódigo da aula …

> [!quote] Do livro — CLRS, cap. 2
>
> `INSERTION-SORT(A,n)` usa `for i = 2 to n`, com `key = A[i]`.
```

"Do livro" encolhe para **procedência**: o que foi consultado, divergências entre livro e
aula, o que os trechos não cobrem, e o callout `[!tip] Onde conferir a solução` — que
aponta o gabarito sem nunca copiar a solução.

Alvo inexistente não derruba nada: se o modelo citar uma seção que não existe, a resposta
é ignorada como destino e o texto continua na nota. Perder conteúdo seria pior que perder
o posicionamento.

### Por que a seção duplicava

`substituir_secao` troca o *corpo* da primeira seção com prefixo "Do livro". Só que o
bibliotecário emitia o próprio cabeçalho `## Do livro — CLRS…` dentro desse corpo. O
cabeçalho novo virava a fronteira da seção, e a execução seguinte inseria **antes** dele:
uma seção a mais por rodada de `preencher-lacunas`. Uma nota chegou a ter quatro.

Três defesas, porque uma só não bastava:

1. o prompt proíbe o cabeçalho próprio;
2. `_sem_cabecalho_proprio` remove se vier mesmo assim;
3. `colapsar_secoes` funde o que já está duplicado no disco.

E `aplicar` remove os callouts `[!quote] Do livro` antes de inserir os novos — é o que
torna rodar três vezes idêntico a rodar uma.

## Recortes órfãos

O extrator recorta todo bloco que vale crop; o compositor decide quais entram. A diferença
fica no disco, e cada job reprocessado deixa os recortes da tentativa anterior. Numa medição
inicial, a maior parte dos recortes estava órfã, herdada de jobs reprocessados.

```bash
uv run python scripts/estudos.py crops              # inventário
uv run python scripts/estudos.py crops --mover      # órfãos → lixeira
```

Duas regras que definem o comando:

- **Move, nunca apaga.** O recorte é a única cópia recortada daquele pedaço de lousa. Vai
  para `estudos/trash/<carimbo>/crops/<SIGLA>/` com um README dizendo o que e por quê —
  sem isso, uma pasta de PNGs com data não significa nada meses depois.
- **`promovidas/` conta como uso.** Promovida é nota que já foi para o vault e continua
  apontando para o recorte. Olhar só `output/` apagaria os recortes justamente das notas
  que você já revisou.

Ordem importa: rode `crops --mover` **depois** de recompor uma nota, nunca antes. Um
recorte órfão hoje pode ser usado pela composição nova.

## Reparar o que já está no disco

```bash
uv run python scripts/estudos.py reparar-notas        # ensaio, não escreve
uv run python scripts/estudos.py reparar-notas --sim  # aplica
```

Determinístico: junta parágrafos e funde seções "Do livro", sem chamar modelo nenhum.
O original inteiro vai para `estudos/trash/<carimbo>/output/` antes de qualquer escrita.
Nota já limpa sai **byte-idêntica** — o reparo não é desculpa para reescrever texto seu.
