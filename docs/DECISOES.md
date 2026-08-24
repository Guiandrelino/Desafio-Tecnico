# Decisões

Este documento apresenta as principais decisões técnicas, trade-offs, limitações e possíveis evoluções do projeto. O objetivo é explicar **por que determinadas abordagens foram escolhidas**, complementando o código, que demonstra **o que foi implementado**.

## Contexto: desenvolvimento e execução com a API

Durante o desenvolvimento, optei por construir inicialmente a solução sem uma chave de API disponível. A integração com a LLM foi preparada e o fluxo de erro, quando não havia chave configurada, foi validado nessa etapa.

Essa decisão permitiu desenvolver e testar as partes determinísticas do projeto — tratamento dos dados, regras, modelos e estrutura do agente — sem depender da disponibilidade da API.

Posteriormente, com uma chave válida configurada no `.env`, a integração foi executada contra a API real. Durante essa execução foram identificados alguns problemas que não poderiam ser observados apenas em testes locais:

1. **Modelo inicialmente configurado indisponível**: a API retornou erro informando que o modelo configurado não estava disponível. O modelo foi atualizado conforme os modelos disponíveis.

2. **Limite de requisições da camada gratuita**: a execução do lote mostrou que o limite da API gratuita poderia ser atingido rapidamente, principalmente porque cada cliente pode exigir múltiplas chamadas durante o processo de tool-calling. A estratégia inicial de retry foi revisada para diferenciar limites temporários de limites diários. Também foi utilizado um modelo com quota adequada para concluir a execução.

3. **Diferença de acentuação no campo `nivel_risco`**: a LLM retornou `"medio"` enquanto o modelo Pydantic esperava `"médio"`. O problema foi tratado com normalização antes da validação, tornando o processamento mais tolerante a pequenas variações de formatação.

Após esses ajustes, o notebook do Nível 1 e o lote do Nível 2 foram executados contra a API real. Portanto, os resultados apresentados neste documento são baseados em execuções reais e não em simulações.

## Estrutura do Nível 2

O desafio estabelece três arquivos principais: `tools.py`, `agente.py` e `confronto.py`.

Durante o desenvolvimento, foram considerados arquivos auxiliares para separar responsabilidades, porém, após revisão, optei por consolidar a implementação nos três arquivos definidos pelo desafio.

A divisão final ficou:

* `tools.py`: tratamento dos dados, regras determinísticas, cálculo do top 10 e ferramentas de consulta.
* `agente.py`: integração com a LLM, modelos Pydantic, cache, montagem de contexto, execução do agente e processamento em lote.
* `confronto.py`: comparação entre o resultado determinístico e o resultado produzido pelo agente.

Essa estrutura mantém uma separação clara entre duas responsabilidades:

> **Python calcula, LLM interpreta.**

Dessa forma, cálculos determinísticos não dependem da LLM, enquanto a LLM é utilizada principalmente para interpretação e elaboração do parecer.

## Dados

### Problemas encontrados

Durante a análise dos dados foram identificados:

| Problema                 | Nível 1 |           Nível 2 | Tratamento                                                 |
| ------------------------ | ------: | ----------------: | ---------------------------------------------------------- |
| Duplicata exata de linha |       1 | 5 IDs / 10 linhas | Remoção utilizando `drop_duplicates()`                     |
| Data ausente (`null`)    |       1 |                 7 | Conversão para `NaT` e criação da flag `data_ausente=True` |
| Moeda estrangeira (USD)  |       1 |                 7 | Conversão para BRL utilizando a taxa de câmbio             |

Essas informações foram verificadas de forma programática, utilizando pandas, em vez de depender de inspeção visual dos arquivos. Isso foi especialmente importante no Nível 2, que possui 322 registros.

### Por que remover somente duplicatas idênticas

Apenas registros completamente idênticos são removidos automaticamente.

Caso o mesmo ID apareça com informações diferentes, não existe uma forma segura de determinar automaticamente qual registro é correto. Por isso, esse cenário é tratado como alerta para investigação.

No conjunto de dados fornecido, os IDs duplicados encontrados correspondiam a registros totalmente idênticos.

### Por que manter operações sem data

As operações sem data não são removidas da base.

Excluir esses registros poderia alterar o volume real de operações de um cliente. Além disso, não seria correto atribuir uma data artificial.

A ausência de data é tratada explicitamente. Na Regra 1, essas operações não participam do agrupamento temporal porque não existe uma data válida para realizar essa análise. Isso representa uma limitação daquela regra, e não uma exclusão do registro da base.

## Regras: por que utilizar Python e não a LLM

As regras de negócio envolvem operações determinísticas, como soma, contagem, mediana e comparação com limites.

Essas operações possuem uma resposta calculável e reproduzível. Delegá-las para uma LLM adicionaria risco de erro, dificultaria a auditoria e poderia produzir resultados diferentes entre execuções.

Por isso, as regras foram implementadas utilizando pandas e podem ser executadas e testadas sem acesso à internet ou à API da LLM.

Durante a análise do Nível 2, foi observado que nenhum dos 30 clientes disparou as duas regras simultaneamente. Consequentemente, o baseline determinístico não classificou nenhum cliente como `"alto"` nesse conjunto de dados.

Esse comportamento foi interpretado como uma característica dos dados fornecidos, e não como um problema da implementação.

## LLM: utilização para interpretação

A LLM recebe informações previamente calculadas pelo código, como:

* quantidade de operações;
* valores agregados;
* mediana;
* indicadores das regras;
* informações obtidas pelas ferramentas.

O modelo não recebe a responsabilidade de realizar os cálculos principais.

Essa decisão reduz a possibilidade de a LLM alterar os dados ou realizar cálculos incorretos. O papel do modelo é interpretar as evidências disponíveis e produzir um parecer estruturado.

## Prompt V1 vs V2 — Nível 1

Foram utilizadas duas versões de prompt para avaliar o impacto das instruções fornecidas à LLM.

A V1 possui menos restrições e permite maior liberdade de interpretação.

A V2 possui instruções mais estruturadas, principalmente para:

* diferenciar fatos de hipóteses;
* evitar a invenção de informações;
* impedir que a LLM refaça os cálculos;
* exigir um formato de resposta mais consistente.

### Resultado observado

Com os mesmos dados, a diferença entre os prompts produziu resultados diferentes:

|                            | V1                           | V2                              |
| -------------------------- | ---------------------------- | ------------------------------- |
| `nivel_risco`              | Alto                         | Médio                           |
| Abordagem                  | Interpretação mais agressiva | Interpretação mais conservadora |
| Estrutura da justificativa | Mistura fato e hipótese      | Separa fato e hipótese          |

Esse resultado demonstra que a estrutura do prompt influencia diretamente a interpretação da evidência apresentada à LLM.

Isso não significa que uma versão seja necessariamente correta em todos os cenários, mas evidencia a importância da engenharia de prompt em aplicações de análise de risco.

## Agente — Nível 2

O agente possui três ferramentas principais:

* `historico_cliente`: fornece uma visão agregada do comportamento do cliente;
* `operacoes_do_dia`: permite analisar as operações de uma determinada data;
* `perfil_canal`: apresenta informações relacionadas aos canais utilizados.

O agente decide quais ferramentas utilizar de acordo com as informações disponíveis.

Não existe uma lógica fixa que execute todas as ferramentas para todos os clientes. O fluxo utiliza tool-calling para que a própria LLM solicite informações adicionais quando necessário.

### Limite de iterações

Foi definido um limite de 5 iterações para evitar que o agente fique preso em um ciclo de chamadas.

Caso esse limite seja atingido, o processamento é encerrado para aquele cliente e o registro recebe um status de erro, sem interromper o processamento dos demais.

### Cache

O cache utiliza como chave um hash baseado no modelo, instrução de sistema e prompt enviado.

Essa abordagem foi escolhida em vez de utilizar apenas o `cliente_id`, pois o mesmo cliente pode gerar resultados diferentes caso os dados ou o prompt sejam alterados.

Dessa forma, o cache está relacionado ao conteúdo efetivamente processado.

## Confronto

O baseline utilizado como referência é simples:

* 0 regras acionadas → `baixo`;
* 1 regra acionada → `médio`;
* 2 regras acionadas → `alto`.

O objetivo do baseline não é representar uma classificação definitiva de risco, mas fornecer uma referência determinística para comparar o comportamento do agente.

A análise considera não apenas a taxa de concordância, mas principalmente os casos em que o agente diverge do baseline.

### Resultado observado

Na execução realizada com os 10 clientes do top 10:

**Taxa de concordância: 80% (8/10).**

As duas divergências ocorreram nos clientes `CLI-030` e `CLI-028`.

### CLI-030

O baseline classificou o cliente como `médio` devido a uma operação de valor atípico.

O agente classificou como `baixo`, considerando que o evento era isolado e poderia possuir uma explicação legítima, como um recebimento extraordinário.

Essa divergência é relevante porque demonstra uma limitação da regra estatística: um único valor elevado pode gerar um alerta sem necessariamente representar comportamento suspeito.

### CLI-028

Nesse caso, o baseline também classificou como `médio`, enquanto o agente classificou como `baixo`.

Entretanto, essa divergência parece menos defensável. O cliente apresentou uma entrada e uma saída de valores semelhantes no mesmo dia.

Esse comportamento poderia justificar uma investigação adicional, pois pode representar um padrão de passagem de recursos.

O agente identificou corretamente os eventos, mas não atribuiu peso suficiente ao fato de ocorrerem próximos temporalmente.

Esse caso demonstra uma limitação importante: **uma justificativa bem escrita pela LLM não significa necessariamente que a conclusão esteja correta**.

Por isso, decisões de risco deveriam continuar sujeitas a validação humana.

## Limitações

O projeto possui algumas limitações conhecidas:

* **Duplicatas ambíguas**: registros com o mesmo ID, mas informações diferentes, não são resolvidos automaticamente.
* **Baseline simplificado**: considera apenas a presença das regras, sem ponderar sua intensidade ou quantidade de ocorrências.
* **Regra de outlier não calibrada**: o limite utilizado foi definido pelo próprio desafio e não foi validado contra uma base histórica rotulada.
* **Cache sem TTL**: atualmente não existe expiração automática do cache.
* **Processamento sequencial**: os clientes são processados um por vez, tornando o lote mais simples de acompanhar, porém menos eficiente.
* **Sem retry para qualquer JSON malformado**: algumas inconsistências são normalizadas, mas respostas estruturalmente inválidas não são automaticamente reenviadas.
* **Dependência da quota da API**: a execução utilizando modelos gratuitos está sujeita aos limites estabelecidos pelo provedor.
* **Necessidade de revisão humana**: divergências do agente, especialmente em casos de maior risco, não devem ser aceitas automaticamente.

## O que seria feito com mais tempo

### 1. Validar os casos divergentes com um analista de PLD

O primeiro passo seria validar principalmente o caso `CLI-028` com um especialista humano, comparando a conclusão do agente com uma análise profissional.

### 2. Implementar retry para respostas inválidas

Quando a LLM retornar um JSON inválido, o sistema poderia enviar novamente a resposta juntamente com o erro específico retornado pelo Pydantic, solicitando apenas a correção da estrutura.

### 3. Melhorar o baseline

O baseline poderia considerar a intensidade dos eventos, e não apenas se uma regra foi acionada.

Por exemplo, diferenciar:

* uma única operação marginalmente acima do limite;
* várias operações atípicas;
* várias operações atípicas concentradas no mesmo período.

Isso permitiria uma comparação mais representativa com o agente.

### 4. Implementar o Nível 3

Com mais tempo, a evolução mais natural seria implementar o servidor MCP.

Como as ferramentas do Nível 2 já estão separadas e possuem funções bem definidas, seria possível disponibilizá-las através do protocolo MCP sem alterar significativamente a lógica de negócio.

A validação seria executar o mesmo conjunto de clientes através do MCP e comparar os resultados com a implementação atual.

Plano detalhado (por que a Trilha B e não A/C, arquitetura com diagrama, passos e critério de validação): `nivel_3/README.md`.

## Conclusão

As principais decisões do projeto buscaram manter uma separação clara entre **processamento determinístico e interpretação por IA**.

O Python é responsável pelos dados, cálculos e regras, garantindo reprodutibilidade e auditabilidade. A LLM é utilizada para interpretar os resultados, consultar ferramentas quando necessário e produzir um parecer estruturado.

Os testes realizados também mostraram que tanto as regras determinísticas quanto a LLM possuem limitações. Por isso, o projeto não trata a classificação gerada pelo agente como uma decisão definitiva, mas como **apoio à análise**, mantendo a possibilidade de revisão humana nos casos relevantes.
