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
nivel_1/             nivel_1.ipynb — notebook do Nível 1 (Partes A e B), já executado
nivel_2/             módulos Python reutilizáveis + regras em escala + agente + confronto
  config.py           configuração via variáveis de ambiente
  models.py           Parecer (Pydantic) e métricas de chamada LLM
  data.py             carga e limpeza dos dados (mesma lógica do notebook, fatorada)
  rules.py            Regra 1 (fracionamento) e Regra 2 (valor atípico) — só pandas
  tools.py            3 ferramentas de consulta que o agente pode chamar
  cache.py            cache em disco das respostas da LLM (por hash do prompt)
  llm_client.py        integração com google-genai: loop de tool-calling, tokens, latência
  agente.py            monta o contexto do cliente e decide quando chamar ferramentas
  top_clientes.py      calcula os 10 clientes mais sinalizados -> outputs/top_10_clientes.csv
  lote.py               roda o agente sobre os 10 clientes -> outputs/lote.csv + pareceres/
  confronto.py          baseline determinístico vs parecer do agente -> outputs/confronto.csv
nivel_3/             não implementado (ver docs/DECISOES.md)
outputs/             resultados salvos (CSV, pareceres individuais, cache de LLM)
tests/               testes das regras críticas (pytest)
docs/                 DECISOES.md, USO_DE_IA.md
```

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
LLM_MODEL=gemini-2.0-flash
GEMINI_API_KEY=sua-chave-aqui
```

Nenhuma chave é lida de outro lugar e nenhuma chave está commitada neste repositório.

## Como executar

**Nível 1** — abra e rode `nivel_1/nivel_1.ipynb` (já vem com as saídas commitadas; as
células de limpeza, regras e agregações são 100% reais). As células que chamam a LLM
(Parte B) precisam de `GEMINI_API_KEY` configurada para produzir uma resposta real — sem
a chave, elas rodam e mostram o tratamento de erro real, sem quebrar.

**Nível 2**:

```bash
python -m nivel_2.top_clientes   # gera outputs/top_10_clientes.csv
python -m nivel_2.lote           # roda o agente sobre o top 10 -> outputs/lote.csv e outputs/pareceres/
python -m nivel_2.confronto      # compara baseline determinístico vs LLM -> outputs/confronto.csv
```

Cada uma dessas etapas depende da etapa anterior ter rodado (lote lê o top10; confronto
lê o lote).

**Testes**:

```bash
pytest tests/ -v
```

## Modelo utilizado

Google AI Studio, `gemini-2.0-flash` (camada gratuita). Escolhido por ter tool calling e
saída estruturada nativos via SDK `google-genai`, e por não exigir cartão de crédito.

## Estado real da execução com LLM

Este projeto foi desenvolvido sem uma `GEMINI_API_KEY` disponível na sessão de
desenvolvimento (decisão consciente registrada em `docs/DECISOES.md`). Isso significa:

- **Tudo que é cálculo em pandas está executado de verdade e commitado**: limpeza de
  dados, conversão de moeda, agregações, Regra 1, Regra 2, validação das regras,
  `outputs/top_10_clientes.csv`.
- **Tudo que depende de chamada real à LLM está com o código completo, testado no
  caminho de erro, mas ainda não executado com uma resposta real do modelo** — as
  células/scripts capturam a ausência de chave e reportam `status: "erro"` de forma
  limpa, sem inventar conteúdo. `outputs/lote.csv`, `outputs/pareceres/*.json` e
  `outputs/confronto.csv` presentes neste repositório refletem exatamente essa
  execução sem chave (10/10 registros com status "erro" e mensagem explicativa).
- Para obter resultados reais, preencha `.env` com uma chave gratuita e rode
  `nivel_1/nivel_1.ipynb` e os três comandos do Nível 2 novamente — nenhuma outra
  mudança de código é necessária.

Isso está declarado com honestidade em `ENTREGA.yaml` (itens de LLM marcados como
`parcial`, nunca `completo`).

## Principais resultados (parte determinística, validada)

- **Nível 1**: 1 duplicata exata removida (`OP-0007`), 1 operação sem data preservada
  com flag `data_ausente`, 1 operação em USD convertida corretamente. Regra 1 captura
  CLI-A-1 (2026-03-09) e corretamente não captura o caso parecido CLI-A-3
  (2026-03-05, soma abaixo do limite). Regra 2 captura a remessa internacional de
  CLI-A-4 (`OP-0013`).
- **Nível 2**: 322 operações brutas → 317 após remover 5 duplicatas exatas (10 linhas
  envolvidas); 30 clientes. Nenhum cliente disparou as duas regras ao mesmo tempo neste
  dataset — ponto discutido em `docs/DECISOES.md`.

## Limitações

Ver `docs/DECISOES.md` para a lista completa de trade-offs e limitações, incluindo os
pontos que dependem de execução real da LLM.
