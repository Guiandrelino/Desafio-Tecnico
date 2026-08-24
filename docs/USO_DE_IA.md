# Uso de IA neste projeto

## Ferramentas utilizadas

Durante o desenvolvimento, utilizei ferramentas de IA como apoio ao desenvolvimento e à depuração:

* **ChatGPT**: apoio na análise do desafio, discussão de arquitetura, revisão de código, investigação de erros e organização da documentação.
* **Gemini via Google AI Studio**: utilizado como a LLM efetivamente integrada à solução nos Níveis 1 e 2.
*  **Claude Code**: utilizado para revisão, análise e apoio no desenvolvimento do código.

A IA foi utilizada como ferramenta de apoio. As decisões de arquitetura, regras de negócio, implementação final, execução dos testes e validação dos resultados foram realizadas e revisadas por mim.

## Para quê a IA foi utilizada

A IA foi utilizada principalmente para:

* analisar alternativas de implementação e arquitetura;
* auxiliar na criação e revisão de trechos de código;
* investigar erros encontrados durante o desenvolvimento;
* sugerir melhorias na estrutura do agente e no tratamento de respostas da LLM;
* auxiliar na organização e revisão da documentação.

As sugestões foram sempre verificadas através da execução do código e, quando aplicável, comparadas com os resultados esperados.

## Um caso em que a IA levou a uma abordagem incorreta

Um exemplo ocorreu no tratamento do erro **429** da API.

A abordagem inicial sugerida foi utilizar retry automático para tentar novamente a requisição quando esse erro ocorresse. Durante a execução real, porém, percebi que o erro estava relacionado ao **esgotamento de quota diária**, e não apenas a uma falha temporária.

Nesse cenário, repetir imediatamente a mesma requisição não resolveria o problema e apenas consumiria novas tentativas. Após analisar o comportamento real da API, alterei a estratégia para diferenciar limites temporários de esgotamento de quota e, quando necessário, utilizar outro modelo disponível.

Esse caso reforçou que as sugestões da IA precisam ser validadas contra o comportamento real do sistema, especialmente quando envolvem serviços externos e limites de infraestrutura.

## Validação

Além desse caso, durante a integração real foram identificadas outras inconsistências, como a diferença entre `"medio"` e `"médio"` no campo `nivel_risco`. O problema foi reproduzido e corrigido na camada de validação antes da execução final do lote.

Dessa forma, a IA foi utilizada para aumentar a produtividade durante o desenvolvimento, mas as respostas geradas não foram tratadas como fonte definitiva de verdade. As decisões finais foram tomadas a partir dos requisitos do desafio, do comportamento observado na execução e dos testes realizados.
