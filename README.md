# Triagem PLD — Desafio Técnico (Estágio em Engenharia de IA)

Mesa de triagem de Prevenção à Lavagem de Dinheiro (PLD) de um banco fictício. O sistema
combina **regras determinísticas** (pandas) com um **modelo de linguagem** (Gemini) para
apoiar a decisão de quais clientes merecem análise humana.

Dados fictícios gerados exclusivamente para este desafio — não representam clientes,
operações ou políticas reais.

## Mensagem arquitetural

> **Python calcula. O LLM interpreta.**

Toda soma, mediana, contagem e comparação com limite é feita em pandas, testada e
auditável. O LLM nunca recebe a tarefa de calcular ou decidir se um número ultrapassou
um limite — ele recebe os fatos já prontos e produz interpretação, classificação de
risco e redação do parecer.

## Estrutura do repositório

```
dados/              dados_nivel_1.json e dados_nivel_2.json (fornecidos, não alterados)
nivel_1/            nivel_1.ipynb — notebook do Nível 1 (Partes A e B), já executado
nivel_2/            estrutura obrigatória do desafio, sem arquivo auxiliar nenhum:
  tools.py            "Python calcula": config/caminhos, carga+limpeza dos dados,
                       Regra 1 (fracionamento), Regra 2 (valor atípico), top 10
                       clientes, e as 3 ferramentas de consulta do agente
  agente.py            "LLM interpreta": config da LLM, contrato Pydantic (Parecer),
                       cache de respostas, cliente Gemini com tool-calling manual,
                       montagem de contexto, geração do parecer e execução em lote
  confronto.py         baseline determinístico vs parecer do agente -> outputs/confronto.csv
nivel_3/            não implementado (ver docs/DECISOES.md)
outputs/            resultados salvos (CSV, pareceres individuais, cache de LLM)
tests/              testes das regras críticas e do contrato Pydantic (pytest)
docs/               DECISOES.md, USO_DE_IA.md
```

`nivel_2/` tem só os três arquivos que a estrutura do desafio pede. A separação que
importa não é "quantos arquivos" e sim `tools.py` (tudo que é cálculo determinístico,
reaproveitado pelo notebook do Nível 1) vs. `agente.py` (tudo que fala com a LLM) —
ver `docs/DECISOES.md` para o raciocínio da consolidação.

## Instalação

Requer Python 3.11+.

```bash
pip install -r requirements.txt
```

## Configuração

Copie `.env.example` para `.env` e preencha com uma chave gratuita do
[Google AI Studio](https://aistudio.google.com/apikey):

```
LLM_PROVIDER=google-ai-studio
LLM_MODEL=gemini-flash-lite-latest
GEMINI_API_KEY=sua-chave-aqui
```

`gemini-flash-lite-latest` é o modelo usado na execução real do lote (ver seção
"Modelo utilizado" abaixo) — tem quota gratuita separada de `gemini-3.6-flash` e se
mostrou suficiente para os 10 clientes do Nível 2.

Nenhuma chave é lida de outro lugar e nenhuma chave está commitada neste repositório.

## Como executar

**Nível 1** — abra e rode `nivel_1/nivel_1.ipynb` (já vem com as saídas commitadas; as
células de limpeza, regras e agregações são 100% reais). As células que chamam a LLM
(Parte B) precisam de `GEMINI_API_KEY` configurada para produzir uma resposta real — sem
a chave, elas rodam e mostram o tratamento de erro real, sem quebrar.

**Nível 2**:

```bash
python -m nivel_2.tools          # gera outputs/top_10_clientes.csv
python -m nivel_2.agente CLI-014 # debug: roda um unico cliente (--sem-cache p/ ignorar cache)
python -m nivel_2.agente         # sem argumento: roda o lote completo sobre o top 10
                                  # -> outputs/lote.csv e outputs/pareceres/
python -m nivel_2.confronto      # compara baseline determinístico vs LLM -> outputs/confronto.csv
```

Cada uma dessas etapas depende da etapa anterior ter rodado (lote lê o top10; confronto
lê o lote).

**Testes**:

```bash
pytest tests/ -v
```

## Modelo utilizado

Google AI Studio / Gemini (camada gratuita). O lote real do Nível 2 e a execução final
do notebook do Nível 1 rodaram em `gemini-flash-lite-latest`. `gemini-3.6-flash` também
foi testado com sucesso (usado nos 3 primeiros clientes antes de esbarrar na quota
diária gratuita, bem mais apertada nesse modelo — ver `docs/DECISOES.md`). Escolhidos
por terem tool calling e saída estruturada nativos via SDK `google-genai`, e por não
exigirem cartão de crédito.

## Estado real da execução com LLM

Todo o projeto foi executado de ponta a ponta contra a API real do Gemini, incluindo as
partes que dependem de LLM — não é simulação. No processo, três problemas reais
apareceram e foram corrigidos (modelo desativado, quota diária vs. por minuto, e um bug
de validação de acentuação); estão documentados com detalhe em `docs/DECISOES.md` e
`docs/USO_DE_IA.md`.

- `nivel_1/nivel_1.ipynb`: Parte A (pandas) e Parte B (LLM, prompts V1 e V2) executadas
  de verdade, saídas commitadas.
- `outputs/top_10_clientes.csv`: cálculo determinístico, 100% pandas.
- `outputs/lote.csv` e `outputs/pareceres/*.json`: **10/10 clientes com status "ok"**,
  pareceres reais do agente.
- `outputs/confronto.csv`: **10/10 avaliados, taxa de concordância real de 80% (8/10)**.
  As 2 divergências foram analisadas caso a caso em `docs/DECISOES.md#confronto`.

## Principais resultados

- **Nível 1 (dados)**: 1 duplicata exata removida (`OP-0007`), 1 operação sem data
  preservada com flag `data_ausente`, 1 operação em USD convertida corretamente. Regra 1
  captura CLI-A-1 (2026-03-09) e corretamente não captura o caso parecido CLI-A-3
  (2026-03-05, soma abaixo do limite). Regra 2 captura a remessa internacional de
  CLI-A-4 (`OP-0013`).
- **Nível 1 (LLM)**: mesmo cliente e mesmos fatos, prompt V1 (fraco) classificou como
  risco **alto** tratando a flag quase como prova; prompt V2 (estruturado) classificou
  como **médio**, separando explicitamente fato de hipótese na justificativa.
- **Nível 2 (dados)**: 322 operações brutas → 317 após remover 5 duplicatas exatas (10
  linhas envolvidas); 30 clientes. Nenhum cliente disparou as duas regras ao mesmo tempo
  neste dataset.
- **Nível 2 (confronto)**: 80% de concordância entre baseline determinístico e agente.
  Numa divergência (CLI-030) o agente parece mais correto que a regra (outlier isolado,
  sem padrão de estruturação); na outra (CLI-028) o baseline parece mais defensável
  (agente subponderou um padrão de entrada/saída de valores parecidos no mesmo dia).

## Limitações

Ver `docs/DECISOES.md` para a lista completa de trade-offs e limitações, incluindo os
pontos que dependem de execução real da LLM.
