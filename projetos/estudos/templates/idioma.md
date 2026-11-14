# Estrutura padrão das notas de aula de idioma

Perfil `idioma`. Vale para disciplinas de língua (Alemão A1.1). O foco é outro: não há pseudocódigo, complexidade, corretude nem casos de falha — há vocabulário, regra gramatical, exemplo de uso e armadilha de pronúncia.

## 1. Frontmatter YAML

```yaml
---
data: AAAA-MM-DD
disciplina: Nome da Disciplina
aula: número
idioma: de
tags: [tag1, tag2, tag3]
---
```

## 2. Título principal

```markdown
# Aula X — Tema da aula
```

## 3. Resumo da aula

Um a três parágrafos: que situação comunicativa a aula cobriu (apresentar-se, pedir algo num café), que estrutura gramatical apareceu, e o que o professor pediu para praticar.

## 4. Vocabulário

Sempre em tabela, porque a informação é sempre a mesma e a tabela é o que se revisa. Substantivo **sem artigo é vocabulário pela metade** — em alemão o gênero é parte da palavra. Plural na mesma linha, pelo mesmo motivo.

```markdown
## Vocabulário

| Palavra | Gênero / plural | Tradução | Exemplo da aula |
|---|---|---|---|
| Tisch | der / die Tische | mesa | Der Tisch ist groß. |
| lernen | verbo regular | aprender | Ich lerne Deutsch. |
```

Palavra que apareceu só de passagem entra na tabela do mesmo jeito. Se o professor não deu o gênero ou o plural, escreva `(não dado em aula)` — **nunca complete de memória**: gênero errado é pior que gênero ausente, porque é aprendido como se fosse certo.

## 5. Gramática

Uma subseção por ponto gramatical, com a regra em uma frase, os casos que a aula mostrou e as exceções que o professor citou.

```markdown
## Gramática

### Presente dos verbos regulares

Regra: tira-se o `-en` do infinitivo e acrescenta-se a terminação da pessoa.

| Pessoa | Terminação | Exemplo |
|---|---|---|
| ich | -e | ich lerne |
| du | -st | du lernst |

Exceções citadas em aula: verbos com radical terminado em `-t` ganham `-e` antes da
terminação (`du arbeitest`).
```

Ponto gramatical que mereça estudo próprio vira `[[link]]` e entra em `conceitos_novos`.

## 6. Exemplos de uso e diálogos

As frases inteiras como apareceram, com tradução. É o que permite reconhecer a estrutura em uso, e não só em tabela.

```markdown
## Exemplos de uso

- **Wie heißt du?** — Como você se chama?
- **Ich komme aus Brasilien.** — Eu venho do Brasil.

### Diálogo da aula

> — Guten Tag! Wie geht es Ihnen?
> — Danke, gut. Und Ihnen?
```

Trechos ilegíveis permanecem `[ilegível]`.

## 7. Pronúncia e armadilhas

O que se erra e o que confunde: som que não existe em português, palavra parecida com falso amigo, diferença que só aparece na fala.

```markdown
## Pronúncia e armadilhas

- **ü** não é "u": lábios de "u", língua de "i" (`über`).
- `bekommen` **não** é "become" — significa *receber*.
```

Sem nada sinalizado, escreva `- (nada sinalizado nesta aula)`.

## 8. Pontos de atenção do professor

Idêntica ao perfil técnico: **apenas** o que o professor marcou explicitamente como conteúdo de prova ou ponto de atenção. Sem sinalização, a seção fica com `- (nada sinalizado nesta aula)`. Nunca promova a esta seção algo que você apenas considera importante.

## 9. Conceitos novos — precisam de página própria

Pontos de gramática que merecem página própria, com wiki links, nomes idênticos aos usados na seção 5.

## 10. Exercícios relacionados

Exercícios do livro/apostila, com o que cada um treina.

## 11. Ver também

Links para aulas anteriores e pontos de gramática relacionados.

## 12. Estilo

- Escreva em português; o idioma-alvo aparece nas palavras e frases, sempre em **negrito**
  ou em bloco de citação, para não se confundir com o texto explicativo.
- Não invente conjugação, gênero, plural ou tradução que não estejam no material. Ausência
  se escreve `(não coberto na aula)`.
- Não "melhore" a frase do professor: transcreva como está, inclusive erros.
