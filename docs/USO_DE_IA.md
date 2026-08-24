# Uso de IA neste projeto

Este projeto foi desenvolvido com Claude (Anthropic), via Claude Code, como par de
programação durante toda a sessão.

## Para quê foi usado

- **Leitura e verificação dos dados**: em vez de inspecionar os dois JSONs (20 e 322
  operações) manualmente, escrevi e rodei scripts pandas descartáveis para confirmar
  contagens exatas de duplicatas, datas nulas e moedas antes de escrever qualquer regra.
  Isso importava especialmente no Nível 2 (322 linhas) — inviável de conferir a olho com
  confiança.
- **Geração do código de produção**: `nivel_2/*.py`, o notebook do Nível 1 e os testes
  em `tests/test_rules.py` foram escritos pela IA e revisados por mim (usuário) durante a
  sessão, célula a célula no caso do notebook (rodado de verdade via `nbconvert`, não
  só gerado).
- **Redação da documentação**: README, DECISOES.md e este arquivo foram redigidos pela
  IA a partir de decisões tomadas durante a conversa, não geradas de forma genérica.

## Decisões tomadas manualmente (pelo usuário, via perguntas diretas da IA)

- **Provedor de LLM**: Google AI Studio / Gemini, escolhido entre as opções sugeridas no
  enunciado (Gemini, Groq, OpenRouter, Ollama).
- **Momento de configurar a API key**: decidido explicitamente que a chave seria
  configurada pelo usuário depois, fora da sessão de desenvolvimento — isso significa
  que as partes do projeto que chamam a LLM de verdade não foram validadas com uma
  resposta real durante o desenvolvimento (ver `docs/DECISOES.md` para o que isso
  implica em cada entregável).
- **Escopo do Nível 3**: decidido não implementar, para não comprometer a qualidade dos
  Níveis 1 e 2, conforme a própria recomendação do enunciado do desafio.

## Onde a IA errou e foi corrigido

- **Bug de escaping ao gerar o notebook programaticamente**: o script que monta o
  `.ipynb` via `nbformat` usava um wrapper de string raw (`r"""..."""`) para o corpo de
  cada célula; a primeira versão tentou colocar uma docstring Python (`"""..."""`) com
  aspas escapadas (`\"\"\"`) dentro desse wrapper, o que teria produzido código Python
  inválido dentro da célula (barras invertidas literais na fonte). Encontrado ao rodar
  um `compile()` de sanidade em cada célula antes de executar o notebook de verdade, e
  corrigido trocando a docstring interna para aspas triplas simples (`'''...'''`), que
  não colidem com o delimitador externo.
- **Mojibake aparente nos acentos durante a depuração**: ao inspecionar o notebook
  executado via `print()` no terminal, caracteres acentuados apareciam como `�`. A
  primeira hipótese foi corrupção real do arquivo (problema sério, exigiria reexecutar
  tudo). Verificação nos bytes brutos do `.ipynb` mostrou UTF-8 correto (`\xc3\xba` para
  "ú") — o problema era só a *codepage* do console do Windows ao exibir o `print()`, não
  o conteúdo salvo. Evitou um retrabalho desnecessário de reexecução do notebook.
- **Risco identificado a tempo, não um erro já cometido**: a primeira leitura do
  enunciado poderia levar a implementar o agente como um loop "para cada cliente, chama
  as três ferramentas sempre" — o enunciado é explícito que isso não conta como agente.
  O desenho final (`nivel_2/agente.py` + `nivel_2/llm_client.py`) deixa a decisão de
  quais ferramentas chamar inteiramente para o modelo, via tool-calling, evitando esse
  atalho.
