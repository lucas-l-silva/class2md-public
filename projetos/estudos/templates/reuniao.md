# Estrutura padrão da ata de reunião

Perfil `reuniao`. Vale para entradas do registro com `tipo = "reuniao"` (ex.: as reuniões do GRUPO). A entrada é nota manuscrita e/ou transcrição; a saída é uma **ata** — o que foi discutido, o que foi decidido, e o que virou tarefa.

Uma ata não é uma nota de aula: não há conteúdo a ensinar, há compromisso a rastrear. Por isso a seção que mais importa é a de decisões, e o que sai dela vai para o backlog.

## 1. Frontmatter YAML

```yaml
---
data: AAAA-MM-DD
contexto: SIGLA
tipo: ata
participantes: [nome1, nome2]
tags: [tag1, tag2]
---
```

`participantes` só com quem foi nomeado no material. Ninguém é inferido por presença habitual.

## 2. Título principal

```markdown
# Reunião de AAAA-MM-DD — assunto principal
```

## 3. Pauta

O que estava previsto, quando houver pauta explícita. Sem pauta no material, escreva `- (não registrada)` — não reconstrua a pauta a partir do que foi discutido.

## 4. Discussão

Um item por assunto, com o essencial do que foi dito e por quem, quando o material atribui. Discussão sem conclusão continua aqui e **não** vira decisão.

```markdown
## Discussão

### Escolha do dataset
Foi levantado que o dataset atual tem viés de coleta. Não se chegou a uma conclusão.
```

## 5. Decisões

Só o que foi **decidido**, não o que foi cogitado. Cada decisão com a citação literal que a sustenta — é o que permite conferir depois se a ata está certa.

```markdown
## Decisões

- Usar o dataset B a partir da próxima rodada.
  > "então fica combinado, a gente migra pro B"
```

Sem decisão registrada, escreva `- (nenhuma decisão registrada)`.

## 6. Pendências

O que ficou em aberto e depende de alguém ou de algo externo. Diferente de tarefa: aqui não há responsável nem prazo.

## 7. Backlog gerado

Os itens que viraram tarefa, com responsável e prazo quando ditos. Esta seção é um **espelho** do que foi acrescentado em `<SIGLA> - Backlog.md`, com o mesmo identificador de bloco, para você navegar de um para o outro.

```markdown
## Backlog gerado

- [ ] **Rodar o benchmark com o dataset B** · @pessoa · 📅 2026-08-28 ^grupo-20260814-01
- [ ] **Escrever a seção de metodologia** ^grupo-20260814-02
```

Item **com data** vira compromisso proposto na agenda; item sem data fica só no backlog.

## 8. Ver também

Link para a ata anterior e para o backlog.

## 9. Estilo

- Ata é registro, não resumo interpretativo: não conclua o que a reunião não concluiu.
- Nunca invente responsável. Sem nome dito, a tarefa fica sem `@`.
- Nunca invente prazo. "Semana que vem" se resolve contra a data da reunião; "logo" não
  vira data.
- Trechos ilegíveis ou inaudíveis permanecem `[ilegível]` / `[inaudível]`.
