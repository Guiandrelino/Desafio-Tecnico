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
  configurada pelo usuário depois — o código de integração com a LLM foi escrito e
  testado no caminho de erro primeiro, sem chave. O usuário forneceu a chave mais tarde,
  na mesma sessão, e a partir daí notebook e lote foram reexecutados de verdade contra a
  API (ver `docs/DECISOES.md`, que documenta os três problemas reais encontrados nessa
  execução: modelo desativado, quota diária, e um bug de acentuação na validação).
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
  O desenho final (funções `montar_contexto_cliente` + `executar_agente` em
  `nivel_2/agente.py`) deixa a decisão de quais ferramentas chamar inteiramente para o
  modelo, via tool-calling, evitando esse atalho.
- **Retry ingênuo em erro 429**: a primeira versão do retry/backoff em
  `nivel_2/agente.py` (na época, um módulo `llm_client.py` separado) tratava toda
  resposta 429 (RESOURCE_EXHAUSTED) da mesma forma
  — esperar e tentar de novo. Rodando o lote de verdade, isso gastou minutos tentando de
  novo um limite que era **diário**, não por minuto (o corpo do erro dizia
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, mas o código só olhava o código
  HTTP). Corrigido para checar `"PerDay"` na mensagem e desistir rápido nesse caso, e
  para trocar de modelo (`gemini-flash-lite-latest`, quota separada) em vez de insistir
  no mesmo. Sem rodar contra a API real, esse bug nunca teria aparecido.
- **`nivel_risco` malformado por um detalhe que eu mesmo criei**: o `Literal` do
  Pydantic exigia `"médio"` com acento, mas o exemplo de JSON dentro do próprio system
  prompt (escrito por mim) usava `"baixo|medio|alto"` sem acento — a LLM seguiu o
  exemplo do prompt à risca e a validação rejeitou uma resposta perfeitamente boa. Só
  apareceu ao rodar contra a API de verdade (`CLI-029`, primeiro teste do agente).
  Corrigido normalizando a variação no modelo em vez de mudar o prompt (mais robusto:
  não depende da LLM nunca errar o acento de novo).

## Um risco de segurança pego a tempo (não foi a IA que errou)

Ao colar a chave de API para eu rodar o projeto, o usuário editou `.env.example` em vez
de `.env` — ou seja, a chave real ficou por um instante num arquivo que é rastreado pelo
Git e vai para o repositório público. Antes de qualquer commit, a IA conferiu
`git status`/`git log` para confirmar que a mudança ainda não tinha sido commitada, moveu
a chave para `.env` (no `.gitignore`), restaurou `.env.example` ao estado original (sem
valores) e só então seguiu em frente. Fica registrado aqui porque é exatamente o tipo de
deslize que o enunciado trata como eliminatório ("chave commitada é incidente de
segurança") — vale conferir sempre `git diff`/`git status` antes de comitar quando se
mexe em arquivos de configuração.
