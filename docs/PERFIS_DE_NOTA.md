# Perfis de nota


Nem toda nota é técnica. O template com pseudocódigo, complexidade e corretude é lei
para uma disciplina de algoritmos, e é ruído para um curso de idioma, que precisa de vocabulário com
gênero e plural, regra gramatical e diálogo. Uma reunião de grupo de pesquisa não é nem uma coisa nem
outra: precisa de pauta, decisões e backlog.

O **perfil** é o campo do registro que escolhe o template, as seções obrigatórias e o
comportamento dos agentes de flashcard e de conceito.

```toml
[[disciplinas]]
nome = "ALEMAO-A1.1"
perfil = "idioma"        # tecnica | idioma | reuniao
```

Omitido, o perfil deriva do `tipo`: `reuniao` → `reuniao`, qualquer outro → `tecnica`.
Disciplina fora do registro também cai em `tecnica`, para o pipeline continuar utilizável
antes de qualquer configuração.

## Os três perfis

| Perfil | Template | Seções que definem | Flashcards | "Conceito novo" |
|---|---|---|---|---|
| `tecnica` | `templates/tecnica.md` | Conteúdo principal, Do livro, Pontos difíceis, Pontos de atenção | definição, complexidade, contraexemplo | conceito com página própria |
| `idioma` | `templates/idioma.md` | Vocabulário, Gramática, Exemplos de uso, Pronúncia e armadilhas | palavra→tradução com artigo e plural, cloze de frase real | ponto de gramática |
| `reuniao` | `templates/reuniao.md` | Pauta, Discussão, Decisões, Pendências, Backlog gerado | — | — |

Comum aos três: **Pontos de atenção do professor** só recebe o que foi explicitamente
sinalizado; sem sinalização, fica `- (nada sinalizado nesta aula)`.

## Decisões do perfil `idioma`

- **Substantivo sem artigo é vocabulário pela metade.** Em alemão o gênero é parte da
  palavra, e plural também — por isso a tabela de vocabulário tem colunas para os dois.
- **Gênero ausente se escreve `(não dado em aula)`.** Gênero errado é pior que gênero
  ausente, porque é aprendido como se fosse certo.
- **Sem pseudocódigo, complexidade, corretude ou "casos em que falha".** Não é economia
  de espaço: exigir essas seções obriga o modelo a preenchê-las com algo, e o algo é
  invenção.

## Decisões do perfil `reuniao`

- **Ata é registro, não resumo interpretativo.** Discussão sem conclusão fica em
  "Discussão" e **não** vira decisão.
- **Toda decisão carrega a citação literal** que a sustenta, para você conferir depois.
- **Nada de responsável ou prazo inventado.** Sem nome dito, a tarefa fica sem `@`;
  "semana que vem" resolve contra a data da reunião, "logo" não vira data.

## Como está ligado

- `agentes._template(perfil)` escolhe o arquivo; perfil desconhecido cai no técnico —
  é melhor compor com o template errado e o validador reprovar do que quebrar o job por
  causa de um campo de configuração.
- `EntradaCompositor.perfil` entra na chave de cache, e `AgenteCompositor.hash_adicional`
  hasheia o template **daquele perfil**: sem isso, trocar o perfil da disciplina deixaria
  a nota sendo composta pelo template anterior, vinda do cache.
- `validador.SECOES_POR_PERFIL` decide as seções obrigatórias; o runner lê o perfil do
  registro (`disciplinas.perfil_de`) e o passa para o compositor e para a validação.

- **Flashcards** e **páginas de conceito** recebem o perfil na entrada. No `idioma`, o card
  de vocabulário leva o artigo e o plural na resposta (substantivo sem artigo é vocabulário
  pela metade), a gramática vira cloze sobre a frase real da aula, e gênero registrado como
  "(não dado em aula)" não vira card. "Conceito novo" passa a ser ponto de gramática:
  regra, exceções e frases de exemplo.
