# Estrutura padrão dos meus Markdowns de aula

Use esta estrutura ao organizar minhas anotações de aula em Markdown, mantendo compatibilidade com Obsidian e wiki links (`[[Nome da Página]]`). Há **dois tipos de arquivo**: nota de **aula** e página de **conceito**.

Esta é a especificação canônica do formato das notas. O pipeline extrai o conteúdo bruto das imagens; a nota final deve seguir esta estrutura à risca.

---

## 1. Frontmatter YAML

**O frontmatter é a PRIMEIRA coisa do arquivo.** A primeira linha é `---`, sem título antes, sem linha em branco antes, e **nunca** dentro de uma cerca de código (```` ```yaml ````). O Obsidian só reconhece frontmatter na primeira linha; fora dali ele vira texto solto, e as consultas do Dataview (de que o calendário depende) param de enxergar a nota.

`aula` é um **número**. Se o número não for conhecido, use o próximo da sequência da disciplina — nunca escreva "desconhecido" ou deixe em branco.

**Arquivo de aula:**

```yaml
---
data: AAAA-MM-DD
disciplina: Nome da Disciplina
aula: número
tags: [tag1, tag2, tag3]
---
```

**Arquivo de conceito:**

```yaml
---
tipo: conceito
disciplina: Nome da Disciplina
tags: [tag1, tag2, tag3]
---
```

## 2. Título principal

Para aula:

```markdown
# Aula X — Nome da Aula
```

Para conceito:

```markdown
# Nome do Conceito
```

## 3. Resumo da aula

Resumo curto, em 1 a 2 parágrafos, explicando:

- Qual foi o tema central da aula.
- Como a aula se conecta com aulas anteriores.
- Quais conceitos, algoritmos ou problemas foram introduzidos.
- Qual é a importância prática ou teórica do conteúdo.

## 4. Conteúdo principal

Organizar o desenvolvimento da aula em seções com `###`. Imagens originais e recortes (equações, grafos, diagramas) são embutidos inline com `![[...]]` onde apoiam o conteúdo.

```markdown
## Conteúdo principal

### Definição do problema
Explicar o problema formalmente, com notação matemática quando necessário.

### Intuição
Explicar o mesmo conceito de forma intuitiva, com analogias simples.

### Derivação / funcionamento / algoritmo
Quando houver equações, recorrências ou algoritmos, mostrar:
- A ideia central.
- O passo a passo.
- A fórmula ou pseudocódigo.
- O motivo pelo qual funciona.

### Exemplo completo
Sempre que possível, incluir um exemplo trabalhado passo a passo, com:
- Dados de entrada.
- Tabelas, matrizes ou grafo.
- Cálculos intermediários.
- Resultado final.
- Conferência do resultado.
```

## 5. Pseudocódigo, fórmulas e tabelas

Usar **blocos de código** para algoritmos:

````text
Entrada: ...
1   passo
2   passo
3   passo
````

Usar **LaTeX** para fórmulas:

```latex
$$
C(1,K) = \min_{i \neq K}\{C(1,i) + w(i,K)\}
$$
```

Usar **tabelas Markdown** quando o conteúdo for tabular.

## 6. Conexão com o livro

Criar uma seção específica:

```markdown
## Do livro — Autor, ano, capítulo/seção
```

Nela, resumir o que o livro confirma ou acrescenta:

- Definições formais.
- Lemas ou teoremas.
- Complexidade de algoritmos.
- Provas importantes.
- Diferenças entre livro, lousa e explicação do professor.
- Possíveis inconsistências encontradas no material.

## 7. Pontos sinalizados como difícil

Criar **sempre** esta seção:

```markdown
## Pontos sinalizados como difícil
```

Listar os pontos que merecem revisão antes da prova, por exemplo:

- Ideias que confundem.
- Hipóteses importantes.
- Provas por contradição ou indução.
- Casos em que o algoritmo falha.
- Diferenças entre conceitos parecidos.
- Interpretações intuitivas úteis.

Cada item deve ter uma **explicação curta**, não apenas o nome do tópico.

## 7.1. Pontos de atenção do professor

Criar **sempre** esta seção, logo depois da anterior:

```markdown
## Pontos de atenção do professor
```

Aqui vão **apenas** os trechos que o professor sinalizou explicitamente como conteúdo de prova ou como ponto de atenção (blocos com a flag `prova` na extração). Cada item cita o que foi dito, sem inflar:

```markdown
## Pontos de atenção do professor

- **A ideia importa mais que o pseudocódigo** — na prova, o esforço deve estar em elaborar a *ideia*
  do algoritmo; a tradução para pseudocódigo deve ser rápida e quase mecânica.
```

Se o professor não sinalizou nada nesta aula, escreva exatamente:

```markdown
## Pontos de atenção do professor

- (nada sinalizado nesta aula)
```

**Nunca** invente um ponto de atenção a partir da sua própria noção do que é importante — sem sinalização do professor, a seção fica vazia.

## 8. Conceitos novos que precisam de página própria

Criar uma seção, listando com wiki links:

```markdown
## Conceitos novos — precisam de página própria

- [[Conceito 1]]
- [[Conceito 2]]
- [[Conceito 3]]
```

Esses conceitos viram arquivos separados quando forem importantes o suficiente para consulta futura.

## 9. Exercícios relacionados

Criar uma seção relacionando listas, questões e temas:

```markdown
## Exercícios relacionados

- [[Lista XX — Disciplina]], Questão Y — explicação do motivo da relação.
- Questões que aplicam diretamente o algoritmo.
- Questões que pedem contraexemplo.
- Questões que conectam com aulas anteriores.
```

## 10. Ver também

Seção final com links internos conectando a aula a outras páginas:

```markdown
## Ver também

- [[Aula anterior]]
- [[Conceito relacionado]]
- [[Algoritmo relacionado]]
- [[Estrutura relacionada]]
```

## 11. Estrutura para páginas de conceito

Quando criar um arquivo de conceito, usar esta estrutura:

```markdown
---
tipo: conceito
disciplina: Nome da Disciplina
tags: [tag1, tag2]
---

# Nome do Conceito

## Definição formal
Definir o conceito com rigor matemático ou técnico.

## Intuição
Explicar o conceito com linguagem simples, analogias e interpretação prática.

## Exemplo
Dar um exemplo pequeno e direto.

## Aparece em
- [[Aula X — Nome da Aula]]

## Relacionado a
- [[Conceito relacionado 1]]
- [[Conceito relacionado 2]]
```

## 12. Estilo geral que o Claude deve seguir

- Escrever de forma didática, clara e completa.
- Manter rigor matemático quando necessário.
- Separar definição formal de intuição.
- Usar exemplos numéricos sempre que possível.
- Usar links internos no formato `[[Nome da Página]]`.
- Não criar explicações genéricas demais.
- Priorizar o que ajuda a revisar para prova.
- Marcar inconsistências do material quando aparecerem.
- Destacar hipóteses importantes dos algoritmos e explicar **por que** cada hipótese importa.

**Em algoritmos, sempre incluir:**

- hipótese de entrada;
- ideia central;
- pseudocódigo;
- exemplo;
- complexidade;
- motivo da corretude;
- casos em que falha.

## 13. Notas que não são de aula

Além de **aula** e **conceito**, o pipeline gera mais três tipos. O que os distingue é o
campo `tipo:` do frontmatter e a subpasta — nunca o nome do arquivo. A regra da casa é
*subpasta própria + `tipo:` próprio*, e não arquivo solto na raiz: `moc.notas_da_disciplina()`
varre só a raiz de `output/<SIGLA>/` e trataria qualquer `.md` de lá como uma aula, poluindo
a tabela de Aulas do MOC.

| tipo | onde | gerado por | o que é |
|---|---|---|---|
| `moc` | raiz, `<SIGLA> - MOC.md` | `estudos moc` | a home da disciplina, determinística |

**Regras comuns a todas.** Valem as mesmas de uma nota de aula, mais duas que nasceram de
defeito real:

- **Zero HTML.** `<details>`/`<summary>` não são renderizados pelo Obsidian: aparecem como
  texto solto no meio da nota, e o bloco de código dentro deles deixa de ser bloco de código.
  Dobrar é com callout nativo (`> [!tip]- Título`; o sufixo `-` é o que dobra).
- **Toda linha de um callout leva `>`, inclusive as vazias.** Uma linha vazia sem o prefixo
  encerra o callout no meio, o texto vaza para fora da caixa e o callout seguinte aparece
  órfão.
