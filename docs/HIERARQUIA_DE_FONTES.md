# Hierarquia de fontes


Que material o modelo lê primeiro, o que é cortado quando não cabe, e por quê.

## A ordem

| # | Fonte | Por quê está aí |
|---|---|---|
| 1 | **Manuscrito do semestre atual** (fotos da aula) | É onde o professor diz o que é relevante e o que cai na prova. Nenhuma outra fonte tem esse recorte. |
| 2 | **Material atual do docente atual** (site, slides, listas) | Fonte oficial da disciplina neste semestre, escrita por quem a ministra. |
| 3 | **Material atual sem autoria conhecida** | Deste semestre, mas sem saber de quem. |
| 4 | **Livro-texto** (Cormen, Papadimitriou) | Canônico e confiável — mas não é o recorte do professor, e é o que mais facilmente puxa a nota para o genérico. |
| 5 | **Material antigo do docente atual** | Mesmo autor carrega o mesmo recorte e o mesmo estilo de prova. É por isso que material antigo *pode* subir. |
| 6 | **Material antigo de outro autor** | Último recurso. |

Fora da hierarquia, por decisão explícita:

- **Gabarito** nunca é fonte. Se o texto dele entra na nota, o exercício vem resolvido e o
  trabalho de chegar lá — que é o que ensina — desaparece. Ele alimenta um localizador:
  "onde conferir a solução" com arquivo, exercício e página. Ver `docs/INGESTAO_PDF.md`.
- **Material de vigência `antiga`** nunca entra na **composição** de uma nota nova. Só é
  consultado para preencher lacunas de uma nota já escrita.

## Onde isso é aplicado

`projetos/estudos/fontes.py`. A ordenação e o corte acontecem **em Python, antes de
qualquer chamada de modelo**:

```python
mantidas, avisos = truncar(fontes, LIMITE_CHARS)
trechos = [fonte.trecho for fonte in mantidas]
```

A razão de não deixar isso para o prompt é simples: um prompt pode pedir "priorize o
manuscrito" e ser ignorado; uma lista já ordenada e já truncada não pode. O prompt reforça,
o código garante.

Duas regras do truncamento:

- **Corta de baixo para cima.** O que sai é sempre a fonte de menor prioridade.
- **Uma fonte nunca entra pela metade.** Ou cabe inteira, ou fica de fora, com aviso.
  Trecho cortado no meio de um raciocínio é pior que trecho ausente, porque o modelo
  completa a lacuna sozinho.

`preencher-lacunas` imprime a ordem final antes de consultar, para você conferir de onde a
resposta veio.

## Como a autoria é decidida

`disciplinas.autoria_de_docente_atual(disciplina, autor)` casa o campo `autor` do PDF com
os `docentes` registrados. O casamento é por **sobrenome contido na string**, e não por
igualdade, porque a autoria vem de metadado de PDF ou de nome de arquivo — formatos que não
controlamos ("M. S. Lima — notas de aula", "lima_2024_final"). Partículas curtas ("de",
"da") não casam sozinhas.

Docente de disciplina **arquivada** não conta: o objetivo é priorizar quem ministra hoje.

## Como material antigo é ligado a uma aula

Por **assunto**, nunca pelo número no nome do arquivo. `Alg - Aula 5 Mergesort.pdf` é a
aula 5 de *outra oferta* da disciplina — neste semestre a aula 5 é outra coisa. Usar esse
número ligaria conteúdo errado com toda a confiança, e o erro seria invisível para quem lê
a nota depois.

O casamento por assunto (`projetos/estudos/vinculo.py`) exige **dois tokens informativos**
em comum, e trata como ruído as palavras que aparecem em todo lugar — inclusive as do
próprio título da disciplina. Isso saiu de dois falsos positivos reais:

- "Invariantes (busca **linear**)" × "Ordenação em tempo **linear**";
- "PD - Fibonacci: **problema** do corte" × "O **problema** da ordenação".

A etapa determinística é de alta precisão de propósito. O que ela não afirma vai para o
`AgenteVinculadorAula`, que enxerga o conteúdo e tem guardrail de confiança; e o que ele
também não resolve fica **pendente**, listado para você decidir. Deixar pendente é um bom
resultado.
