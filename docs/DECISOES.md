# Decisões

Este documento explica trade-offs, limitações e o que seria feito com mais tempo. O
código já mostra *o quê* foi feito — aqui está o *porquê*.

## Contexto: desenvolvido sem chave, depois executado de verdade

Decisão consciente, tomada no início do desenvolvimento: construir a solução inteira
(incluindo o código de integração com a LLM) sem ter uma chave de API disponível, e
deixá-la pronta para rodar assim que uma chave gratuita fosse adicionada ao `.env`. A
alternativa — pedir a chave antes de escrever qualquer linha de código — atrasaria todo o
trabalho de regras/dados, que não depende disso. O caminho de erro (sem chave) foi
testado nessa fase e ficou registrado em commits anteriores.

**Depois, com a chave real, três problemas apareceram na primeira execução — nenhum
deles hipotético, todos encontrados rodando de verdade:**

1. **`gemini-2.0-flash` está desativado.** A API respondeu 404 dizendo para usar
   `gemini-3.6-flash`. Ajustado no `.env`.
2. **A camada gratuita tem limite tanto por minuto quanto por dia**, e o limite diário
   (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, 20 requisições/dia) é bem mais
   apertado para `gemini-3.6-flash` do que eu esperava — cada cliente do lote consome de
   2 a 4 chamadas (loop de tool-calling), então 20/dia dá para uns 5-6 clientes no
   máximo. O primeiro retry/backoff que escrevi tratava todo 429 como "esperar e tentar
   de novo", o que é certo para limite por minuto mas inútil para limite diário (o
   `retryDelay` sugerido pela API, ex: "59s", não tem relação com o reset diário — segui
   isso e desperdicei ~160s por cliente batendo na mesma parede). Corrigido em duas
   frentes: `_e_quota_diaria_esgotada` em `nivel_2/llm_client.py` detecta `"PerDay"` na
   mensagem de erro e desiste rápido em vez de tentar de novo; e troquei o modelo para
   `gemini-flash-lite-latest`, que tem um bucket de quota separado (confirmado: os 10
   clientes rodaram com sucesso depois da troca, a maioria em poucos segundos).
3. **A LLM devolveu `"medio"` sem acento**, mas o `Literal` do Pydantic só aceitava
   `"médio"` — um parecer válido em conteúdo saiu classificado como `"malformado"` por
   causa de um detalhe puramente ortográfico que eu mesmo introduzi (o exemplo de JSON
   no system prompt usa `"baixo|medio|alto"` sem acento). Corrigido com um
   `field_validator` em `nivel_2/models.py` que normaliza variações antes de validar
   (`tests/test_models.py` cobre isso). Ver `docs/USO_DE_IA.md` para mais contexto.

Depois desses três ajustes, o notebook do Nível 1 (Parte B) e o lote completo do Nível 2
(10/10 clientes) rodaram com sucesso contra a API real do Gemini — os números abaixo, nas
seções de Prompt e Confronto, vêm dessa execução real, não de simulação.

## Dados

### Problemas encontrados

| Problema | Nível 1 | Nível 2 | Tratamento |
|---|---|---|---|
| Duplicata exata de linha | 1 (`OP-0007`) | 5 IDs / 10 linhas (`OP-00040`, `OP-00160`, `OP-00214`, `OP-00269`, `OP-00272`) | `drop_duplicates()` na linha inteira (todos os campos iguais) |
| Data ausente (`null`) | 1 (`OP-0017`) | 7 | Convertida para `NaT`, flag `data_ausente=True`, mantida na base |
| Moeda estrangeira (USD) | 1 (`OP-0013`) | 7 | `valor_brl = valor * taxa_cambio_usd_brl` |

Todos os números acima vieram de uma checagem programática (`df["id"].value_counts()`,
`df.duplicated(keep=False)`, `df["data"].isna()`), não de inspeção visual — importante
porque o Nível 2 tem 322 linhas, inviável de conferir a olho.

### Por que remover só duplicatas 100% idênticas

Um ID repetido com conteúdo diferente seria ambíguo (qual registro é o correto?) e não
tem uma resposta determinística segura. `nivel_2/data.py` distingue os dois casos:
duplicata exata é removida automaticamente; ID repetido com conteúdo diferente seria
apenas logado como aviso para investigação manual. Neste dataset, todos os IDs
duplicados encontrados eram duplicatas exatas — o caminho de "conteúdo diferente" existe
no código mas não foi exercitado pelos dados fornecidos.

### Por que não remover a operação com data ausente

Removê-la escondería volume real do cliente nas agregações de volume e na Regra 2 (que
não depende de data). A alternativa de "inventar" uma data (ex: usar a data de outra
operação, ou hoje) inseriria um fato falso na base — pior que deixar a ausência
explícita. A Regra 1 exclui essas operações do agrupamento por necessidade lógica (não
dá para agrupar por uma data inexistente), mas isso é uma exclusão *daquela regra*, não
da base.

## Regras (por que em pandas, não na LLM)

Soma, contagem, mediana e comparação com limite são operações determinísticas com uma
única resposta correta. Pedir para uma LLM "calcular" introduz risco de erro aritmético
silencioso e, mais importante, torna o resultado não-reprodutível e não-auditável (dois
runs podem dar respostas diferentes). `nivel_2/rules.py` não importa nada relacionado a
LLM — é pandas puro, testável com `pytest` sem custo e sem rede (ver `tests/test_rules.py`).

Achado ao rodar `resumo_sinalizacoes_por_cliente` sobre o Nível 2: **nenhum dos 30
clientes disparou as duas regras ao mesmo tempo**. O baseline do confronto (ver abaixo)
nunca produz "alto" neste dataset — é uma característica dos dados fornecidos, não um
bug. Isso limita o que dá para observar sobre o caso "baseline=alto" na análise de
divergência.

## LLM (por que só para interpretação)

O contrato de entrada da LLM (`montar_contexto_cliente` em `nivel_2/agente.py`, e a
célula equivalente no notebook) só contém números já calculados: contagens, somas,
mediana, booleanos de regra. O prompt de sistema proíbe explicitamente recalcular,
questionar os números ou inventar operações. Isso é reforçado estruturalmente (o dict
que vai no prompt não contém instrução de cálculo) e textualmente (o system prompt diz
isso de forma explícita) — dupla garantia, porque um prompt sozinho pode ser ignorado
pelo modelo.

## Prompt V1 vs V2 (Nível 1, Parte B)

V1 é deliberadamente mais fraco: não distingue fato de hipótese, não proíbe
recálculo/invenção, não define o contrato JSON com o mesmo rigor. V2 adiciona essas
quatro restrições explicitamente.

**Resultado real** (mesmo cliente, CLI-A-1, mesmos fatos, único cliente que muda é o
prompt de sistema — ver `nivel_1/nivel_1.ipynb`, células 36-37):

| | V1 (fraco) | V2 (estruturado) |
|---|---|---|
| `nivel_risco` | **alto** | **médio** |
| Linguagem da justificativa | "indica**ndo** forte indício de tentativa de burlar os controles" — trata o disparo da regra quase como prova | Separa explicitamente `FATO:` (o que a regra1 mostrou) de `HIPOTESE:` (a inferência), e fecha dizendo "as flags são apenas indícios estatísticos e não provas definitivas de ilicitude" |
| Tokens | 790 | 1016 |

A diferença bateu com a hipótese de desenho: V1, sem a instrução explícita de separar
fato de hipótese, converteu uma flag estatística em quase-certeza e escalou o risco para
"alto"; V2, com a mesma evidência, foi mais comedido e explicitou o raciocínio. Isso não
prova que V2 está "certo" e V1 "errado" em abstrato — mas mostra que o desenho do prompt
muda a conclusão de risco com os mesmos dados, o que é exatamente o ponto de ter as duas
versões.

## Agente (Nível 2)

Três ferramentas, cada uma cobrindo uma dimensão diferente de evidência:
`historico_cliente` (visão agregada), `operacoes_do_dia` (granularidade temporal, útil
quando a Regra 1 disparou), `perfil_canal` (padrão de comportamento, útil para
tipologias como uso concentrado de espécie/pix). O agente decide quais chamar — não há
`for cliente: chama_tudo()` em lugar nenhum do código; `nivel_2/agente.py` só monta o
contexto inicial e delega a decisão ao loop de tool-calling em `nivel_2/llm_client.py`,
que só executa uma ferramenta quando o modelo pede.

**Limite de iterações**: 5 (constante `MAX_ITERACOES_PADRAO`), para evitar loop
infinito caso o modelo fique alternando entre ferramentas sem convergir. Se atingido,
o registro sai com `status="erro"` e mensagem explicando o motivo — não trava o lote.

**Cache**: chave = hash de `(modelo, system_instruction, user_prompt)`. Guardado em
`outputs/cache/`. Escolhido em vez de cache por `cliente_id` puro porque o mesmo cliente
pode gerar prompts diferentes se o contexto mudar (nova execução da base, mudança de
prompt) — cachear pelo conteúdo exato evita servir uma resposta desatualizada.

## Confronto

Critério do baseline: `0 regras -> baixo`, `1 regra -> médio`, `2 regras -> alto`,
contando fracionamento e valor atípico como no máximo 1 ponto cada (não conta quantas
operações/datas cada regra pegou, só se pegou ou não). É deliberadamente simples e
**não é verdade absoluta** — é só um ponto de referência auditável para comparar contra
o agente. A análise de divergências (não só a taxa de concordância) é o que importa: se
o agente discordar do baseline com uma justificativa que aponta uma limitação real da
regra (ex: "o fracionamento aconteceu mas as três operações são para a mesma
contraparte recorrente há meses, típico de um fornecedor fixo, não de estruturação"),
essa divergência é um sinal de que o agente está agregando valor, não errando.

**Resultado real** (10/10 clientes do top10 avaliados com sucesso pelo agente, ver
`outputs/confronto.csv` e `outputs/lote.csv`): taxa de concordância de **80% (8/10)**.
Todos os 10 clientes têm baseline "médio" (nenhum disparou as duas regras ao mesmo
tempo, como já registrado na seção de Regras). As 2 divergências, ambas o agente
puxando o risco para baixo:

- **CLI-030** — baseline "médio" (1 operação de valor atípico: uma TED recebida de
  R$ 77.628,19 contra uma mediana de R$ 4.611,07 do cliente). O agente foi para
  "baixo", justificando que é um evento **isolado**, sem padrão de fracionamento, e
  levantou a hipótese de "venda de ativo ou recebimento extraordinário". **Avaliação:**
  argumento defensável — a Regra 2 é um detector de outlier estatístico puro, sem
  contexto sobre a natureza da contraparte ou do tipo de operação, e é conhecida por
  gerar falso positivo em clientes com poucas operações e um recebimento grande e
  legítimo (13º salário, herança, venda de bem). O agente não inventou nenhum fato para
  chegar lá — usou exatamente a mesma evidência do baseline, só ponderou diferente.
- **CLI-028** — baseline "médio" (2 operações de valor atípico no mesmo dia,
  2026-03-21: uma recebida de R$ 24.875,39 e uma enviada de R$ 27.715,48, ambas via TED).
  O agente também foi para "baixo". **Avaliação: aqui o baseline parece mais defensável
  que o agente.** Um recebimento e um envio de valores parecidos no mesmo dia é um
  padrão clássico de conta de passagem (dinheiro entra e sai rápido, quase sem
  permanência) — um analista humano provavelmente pediria mais evidência antes de
  descartar o caso, não o contrário. O agente descreveu esse padrão corretamente no
  "FATO" da justificativa, mas na "HIPÓTESE" não deu peso ao timing simultâneo
  entrada/saída, tratando as duas operações como eventos comerciais pontuais
  independentes. É o tipo de divergência que uma revisão humana deveria pegar antes de
  um caso ser baixado de risco — evidência de que "o agente discorda com boa
  justificativa" não é sinônimo de "o agente está certo": aqui a boa redação mascarou um
  raciocínio que não considerou o sinal mais forte do próprio fato que ele citou.

Isso ilustra o ponto central do enunciado: a regra determinística gera falsos positivos
(CLI-030 é um caso legítimo de flag simplista demais), mas o agente também erra — e o
jeito de pegar isso é ler a justificativa, não só olhar `nivel_risco`.

## Limitações

- **Duplicata ambígua não resolvida automaticamente por design** — se aparecer um ID
  repetido com conteúdo diferente em dados reais, o pipeline atual loga um aviso mas não
  decide sozinho; um humano precisaria revisar. Isso é intencional (ver seção Dados),
  mas significa que o pipeline não é 100% "hands-off" diante desse tipo de problema.
- **Baseline do confronto é simplista de propósito** — não pondera por severidade
  (quantas operações/datas cada regra pegou), só por presença/ausência. Um cliente com
  1 evento de fracionamento pequeno conta igual a um com 10.
- **Sem validação estatística do modelo de outlier** — a Regra 2 usa um multiplicador
  fixo (5x mediana) e um piso de 4 operações escolhidos pelo enunciado, não calibrados
  contra uma base rotulada. Em produção isso precisaria de validação com casos
  confirmados.
- **Cache não expira** — se a base de dados mudar mas o `cliente_id` e o prompt
  ficarem iguais por coincidência (improvável, mas não impossível), o cache serviria uma
  resposta desatualizada. Não há TTL implementado.
- **Sem paralelismo no lote** — `nivel_2/lote.py` roda os 10 clientes sequencialmente,
  o que é lento e mais sensível a rate limit da camada gratuita, mas mais simples de
  depurar e com progresso mais previsível.
- **Sem retry automático em resposta malformada** — se o JSON vier malformado, o
  registro é marcado `status="malformado"` e segue para o próximo cliente, mas o
  próprio prompt não é reenviado automaticamente pedindo correção. (O normalizador de
  acento em `nivel_2/models.py` cobre o caso mais comum encontrado na prática, mas não
  substitui um retry real para outros tipos de malformação.)
- **Quota diária gratuita é apertada para modelos maiores** — `gemini-3.6-flash` tem
  limite de 20 requisições/dia na camada gratuita, insuficiente para rodar o lote de 10
  clientes inteiro (cada cliente usa 2-4 chamadas). A solução final usa
  `gemini-flash-lite-latest`, que tem quota separada e se mostrou suficiente, mas isso é
  uma característica da conta/modelo no momento do desenvolvimento (2026-08), não uma
  garantia permanente — um projeto real precisaria de um plano pago ou de lógica de
  fallback entre modelos.
- **Um dos 10 clientes do top10 não tem tipologia "conclusiva"** (CLI-030 e CLI-028
  ficaram como "baixo" pelo agente) — ver análise em Confronto acima; não é bug, é uma
  divergência real que vale revisão humana.

## Com mais tempo

1. **Revisar o caso CLI-028 com um analista humano de verdade**: a divergência
   documentada em Confronto (entrada e saída de valores parecidos no mesmo dia, agente
   classificou como "baixo") é exatamente o tipo de caso que deveria ir para revisão
   manual antes de aceitar a conclusão do agente. Validação: comparar o parecer do
   agente com o de um analista PLD real sobre o mesmo caso.
2. **Retry com correção guiada em resposta malformada**: ao detectar JSON inválido,
   reenviar ao modelo o erro específico de validação do Pydantic e pedir só a correção,
   em vez de descartar a tentativa. Validação: injetar uma resposta malformada
   artificial (mock) e confirmar que o segundo round corrige.
3. **Baseline ponderado por severidade** no confronto (nº de operações/datas por regra,
   não só presença/ausência), para diferenciar um fracionamento marginal de um extremo.
   Validação: recalcular `outputs/confronto.csv` e checar se a distribuição de
   `risco_deterministico` fica menos concentrada em "médio".
4. **Nível 3, Trilha B (servidor MCP)**: seria a extensão mais natural do agente atual,
   porque `nivel_2/tools.py` já expõe funções puras e sem estado — expô-las via stdio
   MCP é principalmente um wrapper de protocolo em cima do que já existe, sem reescrever
   a lógica de negócio. Não implementado por priorização de tempo (Níveis 1 e 2 vieram
   primeiro, como pedido no enunciado). Plano: um `nivel_3/mcp_server.py` com um
   `Server` do SDK `mcp`, três `@server.tool()` mapeando 1:1 para as funções de
   `nivel_2/tools.py`, e `nivel_2/agente.py` adaptado para falar com o servidor via
   `stdio_client` em vez de importar `TOOL_REGISTRY` diretamente. Validação: rodar o
   mesmo lote de 10 clientes por MCP e comparar `outputs/lote.csv` contra a versão por
   import direto — devem ser idênticos, já que a lógica de negócio não muda.
