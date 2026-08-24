# Decisões

Este documento explica trade-offs, limitações e o que seria feito com mais tempo. O
código já mostra *o quê* foi feito — aqui está o *porquê*.

## Contexto importante: execução sem `GEMINI_API_KEY`

Decisão consciente, tomada no início do desenvolvimento: construir a solução inteira
(incluindo o código de integração com a LLM) sem ter uma chave de API disponível na
sessão de desenvolvimento, e deixá-la pronta para rodar assim que uma chave gratuita for
adicionada ao `.env`. A alternativa — pedir a chave antes de escrever qualquer linha de
código — atrasaria todo o trabalho de regras/dados, que não depende disso.

**Consequência honesta:** as células/scripts que chamam a LLM foram testadas no caminho
de erro (sem chave), não no caminho de sucesso. O tratamento de JSON malformado, retry
implícito via cache, extração de tokens/latência etc. seguem a documentação do SDK
`google-genai`, mas não foram validados contra uma resposta real do Gemini. Isso está
refletido com honestidade em `ENTREGA.yaml` — nenhum item que depende de chamada real à
LLM está declarado como `completo`.

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
quatro restrições explicitamente. A comparação de *conteúdo* das duas respostas depende
de execução real (ver seção acima) — o que está validado é que a diferença de *desenho*
existe e é a esperada segundo a literatura de prompt engineering (instruções negativas
explícitas reduzem alucinação e mistura de fato/hipótese).

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

Sem execução real da LLM, este documento não pode apresentar exemplos concretos de
divergência — ver `outputs/confronto.csv` para o estado atual (0 avaliações com
sucesso) e a seção "Com mais tempo" abaixo para o plano.

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
  próprio prompt não é reenviado automaticamente pedindo correção.

## Com mais tempo

1. **Executar de fato com uma `GEMINI_API_KEY` real**: rodar o notebook e os três
   comandos do Nível 2, revisar as respostas reais (tipologia, red flags, justificativa),
   e usar isso para calibrar o prompt V2 (provavelmente precisaria de 1-2 iterações após
   ver respostas reais). Validação: comparar 3-5 pareceres manualmente contra o que um
   analista humano diria, olhando para as mesmas evidências.
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
