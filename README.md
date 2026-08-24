# Triagem PLD — Desafio Técnico (Estágio em Engenharia de IA)

Mesa de triagem de **Prevenção à Lavagem de Dinheiro (PLD)** de um banco fictício. O sistema combina **regras determinísticas** (`pandas`) com um **modelo de linguagem** (Gemini) para apoiar a decisão de quais clientes merecem análise humana.

Os dados são fictícios e foram gerados exclusivamente para este desafio — não representam clientes, operações ou políticas reais.

## Mensagem arquitetural

> **Python calcula. O LLM interpreta.**

Toda soma, mediana, contagem e comparação com limites é realizada em `pandas`, testada e auditável. O LLM nunca recebe a tarefa de calcular ou decidir se um número ultrapassou um limite. Ele recebe os fatos já preparados e produz a interpretação, a classificação de risco e a redação do parecer.

## Estrutura do repositório

```text
dados/
├── dados_nivel_1.json
└── dados_nivel_2.json
    Dados fornecidos pelo desafio e não alterados.

nivel_1/
└── nivel_1.ipynb
    Notebook do Nível 1 (Partes A e B), já executado.

nivel_2/
├── tools.py
│   "Python calcula": configuração/caminhos, carga e limpeza dos dados,
│   Regra 1 (fracionamento), Regra 2 (valor atípico), geração do top 10
│   de clientes e as 3 ferramentas de consulta do agente.
│
├── agente.py
│   "LLM interpreta": configuração da LLM, contrato Pydantic (Parecer),
│   cache de respostas, cliente Gemini com tool calling manual,
│   montagem de contexto, geração do parecer e execução em lote.
│
└── confronto.py
    Baseline determinístico vs. parecer do agente →
    outputs/confronto.csv.

nivel_3/
    Não implementado (ver docs/DECISOES.md).

outputs/
    Resultados salvos (CSVs, pareceres individuais e cache da LLM).

tests/
    Testes das regras críticas e do contrato Pydantic (pytest).

docs/
    DECISOES.md e USO_DE_IA.md.
```

`nivel_2/` contém apenas os três arquivos definidos pela estrutura obrigatória do desafio. A separação que importa não é a quantidade de arquivos, mas a responsabilidade de cada módulo: `tools.py` concentra os cálculos determinísticos, reaproveitados pelo notebook do Nível 1, enquanto `agente.py` concentra a interação com a LLM.

O raciocínio por trás dessa consolidação está documentado em `docs/DECISOES.md`.

## Instalação

Requer Python 3.11+.

```bash
pip install -r requirements.txt
```

## Configuração

Copie `.env.example` para `.env` e preencha com uma chave do Google AI Studio:

[Google AI Studio](https://aistudio.google.com/apikey)

```env
LLM_PROVIDER=google-ai-studio
LLM_MODEL=gemini-flash-lite-latest
GEMINI_API_KEY=sua-chave-aqui
```

`gemini-flash-lite-latest` é o modelo utilizado na execução real do lote (ver seção **Modelo utilizado** abaixo). Ele se mostrou suficiente para os 10 clientes do Nível 2.

Nenhuma chave é lida de outro local e nenhuma chave está versionada neste repositório.

## Como executar

**Nível 1** — abra e execute `nivel_1/nivel_1.ipynb`. O notebook já contém as saídas da execução registrada; as células de limpeza, regras e agregações são executadas sobre os dados reais fornecidos pelo desafio. As células que utilizam a LLM (Parte B) precisam de `GEMINI_API_KEY` configurada para produzir uma resposta real. Sem a chave, elas executam o tratamento de erro correspondente sem interromper o notebook.

**Nível 2**:

```bash
python -m nivel_2.tools
# Gera outputs/top_10_clientes.csv

python -m nivel_2.agente CLI-014
# Executa o agente para um único cliente.
# Use --sem-cache para ignorar o cache.

python -m nivel_2.agente
# Sem argumento: executa o lote completo sobre o top 10.
# Gera outputs/lote.csv e outputs/pareceres/

python -m nivel_2.confronto
# Compara o baseline determinístico com o agente.
# Gera outputs/confronto.csv
```

Cada etapa depende da anterior:

```text
nivel_2.tools
      ↓
top_10_clientes.csv
      ↓
nivel_2.agente
      ↓
lote.csv + pareceres/
      ↓
nivel_2.confronto
      ↓
confronto.csv
```

**Testes**:

```bash
pytest tests/ -v
```

## Modelo utilizado

Google AI Studio / Gemini.

O lote real do Nível 2 e a execução final do notebook do Nível 1 foram realizados com `gemini-flash-lite-latest`.

`gemini-3.6-flash` também foi testado com sucesso e utilizado nos três primeiros clientes, antes de atingir a quota diária gratuita disponível para esse modelo. Esse histórico está documentado em `docs/DECISOES.md`.

Os modelos foram escolhidos por oferecerem suporte a tool calling e saída estruturada por meio do SDK `google-genai`.

## Estado real da execução com LLM

Todo o projeto foi executado de ponta a ponta utilizando a API real do Gemini, incluindo as partes que dependem de LLM — não se trata de uma simulação.

Durante o desenvolvimento, três problemas reais foram identificados e corrigidos:

* modelo indisponível/desativado;
* diferença entre quota diária e quota por minuto;
* bug de validação relacionado à acentuação.

Esses problemas estão documentados em `docs/DECISOES.md` e `docs/USO_DE_IA.md`.

Resultados registrados:

* `nivel_1/nivel_1.ipynb`: Parte A (pandas) e Parte B (LLM, prompts V1 e V2) executadas de fato, com saídas versionadas.
* `outputs/top_10_clientes.csv`: cálculo determinístico realizado com `pandas`.
* `outputs/lote.csv` e `outputs/pareceres/*.json`: **10/10 clientes com status `ok`**, com pareceres reais do agente.
* `outputs/confronto.csv`: **10/10 clientes avaliados, com taxa de concordância de 80% (8/10)**.

As duas divergências foram analisadas individualmente em `docs/DECISOES.md#confronto`.

## Principais resultados

* **Nível 1 (dados):** 1 duplicata exata removida (`OP-0007`), 1 operação sem data preservada com a flag `data_ausente` e 1 operação em USD convertida corretamente. A Regra 1 captura `CLI-A-1` (2026-03-09) e corretamente não captura o caso semelhante `CLI-A-3` (2026-03-05), cuja soma ficou abaixo do limite. A Regra 2 captura a remessa internacional de `CLI-A-4` (`OP-0013`).

* **Nível 1 (LLM):** utilizando o mesmo cliente e os mesmos fatos, o prompt V1 (mais fraco) classificou o caso como risco **alto**, tratando a flag quase como prova. O prompt V2 (estruturado) classificou o caso como risco **médio**, separando explicitamente fatos de hipóteses na justificativa.

* **Nível 2 (dados):** 322 operações brutas → 317 após a remoção de 5 duplicatas exatas (10 linhas envolvidas); 30 clientes. Nenhum cliente disparou as duas regras simultaneamente neste dataset.

* **Nível 2 (confronto):** 80% de concordância entre o baseline determinístico e o agente. Em uma divergência (`CLI-030`), o agente pareceu mais correto que a regra, considerando um outlier isolado sem padrão de estruturação. Na outra (`CLI-028`), o baseline pareceu mais defensável, pois o agente subponderou um padrão de entrada e saída de valores semelhantes no mesmo dia.

## Nível 3

O Nível 3 não foi implementado. A decisão foi priorizar a solidez e a documentação dos Níveis 1 e 2, conforme a orientação do enunciado do desafio.

A Trilha B — **Servidor MCP** — foi escolhida como a evolução planejada por apresentar maior reaproveitamento da arquitetura existente. O planejamento e a justificativa estão documentados em `docs/DECISOES.md`.

## Limitações

Ver `docs/DECISOES.md` para a lista completa de trade-offs e limitações, incluindo os pontos que dependem da execução real da LLM.
