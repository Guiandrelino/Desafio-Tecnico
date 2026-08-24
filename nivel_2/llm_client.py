"""Cliente fino sobre o SDK google-genai (Gemini / Google AI Studio).

Isola toda a integracao com o provedor num unico lugar: construcao das
declaracoes de ferramentas, chamada ao modelo, extracao de metricas
(tokens/latencia) e tratamento de erro. nivel_2/agente.py so conhece esta
interface -- nao conhece detalhes do SDK.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from nivel_2.config import LLMConfig
from nivel_2.models import ChamadaLLMMetrica

MAX_TENTATIVAS_RATE_LIMIT = 4
_PADRAO_RETRY_DELAY = re.compile(r"retryDelay['\"]?:\s*['\"](\d+(?:\.\d+)?)s")


def _e_erro_transitorio(exc: Exception) -> bool:
    texto = str(exc)
    return "RESOURCE_EXHAUSTED" in texto or "429" in texto or "UNAVAILABLE" in texto or "503" in texto


def _e_quota_diaria_esgotada(exc: Exception) -> bool:
    """Distingue rate limit por minuto (vale a pena esperar) de quota diaria
    esgotada (retry dentro da sessao nao adianta -- so reseta no dia seguinte).

    Achado na primeira execucao real do lote: o retryDelay sugerido pela API
    (ex: "59s") e generico e aparece mesmo quando o quotaId e
    "...PerDay...", caso em que esperar 59s e inutil. Ver docs/DECISOES.md.
    """
    return "PerDay" in str(exc)


def _delay_sugerido(exc: Exception, tentativa: int) -> float:
    """Usa o retryDelay que a API do Gemini sugere no corpo do erro 429, se houver."""
    match = _PADRAO_RETRY_DELAY.search(str(exc))
    if match:
        return float(match.group(1)) + 1.0
    return min(60.0, 10.0 * (2**tentativa))


def _generate_com_retry(client, **kwargs):
    """Chama generate_content com retry/backoff para erros transitorios (429/503).

    A camada gratuita do Gemini tem limite de requisicoes por minuto E por dia
    -- isso foi observado na primeira execucao real do lote (ver
    docs/DECISOES.md). Quota diaria esgotada falha rapido (retry nao ajuda);
    rate limit por minuto usa backoff com o retryDelay sugerido pela API.
    """
    ultimo_erro: Exception | None = None
    for tentativa in range(MAX_TENTATIVAS_RATE_LIMIT):
        try:
            return client.models.generate_content(**kwargs)
        except Exception as exc:  # noqa: BLE001
            if (
                not _e_erro_transitorio(exc)
                or _e_quota_diaria_esgotada(exc)
                or tentativa == MAX_TENTATIVAS_RATE_LIMIT - 1
            ):
                raise
            ultimo_erro = exc
            time.sleep(_delay_sugerido(exc, tentativa))
    raise ultimo_erro  # pragma: no cover - inatingivel, mas satisfaz o type checker

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "historico_cliente": {
        "description": (
            "Resumo agregado das operacoes de um cliente: quantidade, volume "
            "total/medio/mediano, periodo, canais e tipos usados, e quantas "
            "vezes cada regra deterministica disparou para ele."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cliente_id": {"type": "string", "description": "ID do cliente, ex: CLI-014"},
            },
            "required": ["cliente_id"],
        },
    },
    "operacoes_do_dia": {
        "description": "Lista as operacoes de um cliente numa data especifica.",
        "parameters": {
            "type": "object",
            "properties": {
                "cliente_id": {"type": "string", "description": "ID do cliente, ex: CLI-014"},
                "data": {"type": "string", "description": "Data no formato YYYY-MM-DD"},
            },
            "required": ["cliente_id", "data"],
        },
    },
    "perfil_canal": {
        "description": "Distribuicao de uso de canais (pix, ted, boleto, cartao, especie) de um cliente.",
        "parameters": {
            "type": "object",
            "properties": {
                "cliente_id": {"type": "string", "description": "ID do cliente, ex: CLI-014"},
            },
            "required": ["cliente_id"],
        },
    },
}

MAX_ITERACOES_PADRAO = 5


@dataclass
class ResultadoAgente:
    texto_final: str | None
    ferramentas_chamadas: list[str]
    metrica: ChamadaLLMMetrica
    iteracoes: int


def _build_tools(genai_types):
    declaracoes = [
        genai_types.FunctionDeclaration(
            name=nome, description=schema["description"], parameters=schema["parameters"]
        )
        for nome, schema in TOOL_SCHEMAS.items()
    ]
    return [genai_types.Tool(function_declarations=declaracoes)]


def executar_agente(
    config: LLMConfig,
    system_instruction: str,
    user_prompt: str,
    tool_registry: dict[str, Callable[..., dict]],
    max_iteracoes: int = MAX_ITERACOES_PADRAO,
) -> ResultadoAgente:
    """Executa o loop manual de tool-calling contra o Gemini.

    Fluxo: envia o prompt -> se o modelo pedir uma ferramenta, executa a
    funcao Python correspondente e devolve o resultado -> repete ate o
    modelo parar de pedir ferramentas ou o limite de iteracoes ser atingido.
    """
    if not config.configurado:
        return ResultadoAgente(
            texto_final=None,
            ferramentas_chamadas=[],
            metrica=ChamadaLLMMetrica(
                modelo=config.model,
                provedor=config.provider,
                tempo_resposta_s=0.0,
                status="erro",
                erro="GEMINI_API_KEY nao configurada. Preencha o .env a partir do .env.example.",
            ),
            iteracoes=0,
        )

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.api_key)
    tools = _build_tools(types)

    contents: list[Any] = [types.Content(role="user", parts=[types.Part(text=user_prompt)])]
    ferramentas_chamadas: list[str] = []
    tokens_entrada_total = 0
    tokens_saida_total = 0
    inicio = time.perf_counter()

    try:
        for iteracao in range(1, max_iteracoes + 1):
            resposta = _generate_com_retry(
                client,
                model=config.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=tools,
                    temperature=0.1,
                ),
            )

            uso = getattr(resposta, "usage_metadata", None)
            if uso is not None:
                tokens_entrada_total += getattr(uso, "prompt_token_count", 0) or 0
                tokens_saida_total += getattr(uso, "candidates_token_count", 0) or 0

            candidato = resposta.candidates[0]
            partes = candidato.content.parts or []
            contents.append(candidato.content)

            chamadas_funcao = [p for p in partes if getattr(p, "function_call", None)]
            if not chamadas_funcao:
                texto = "".join(getattr(p, "text", "") or "" for p in partes)
                tempo_total = time.perf_counter() - inicio
                return ResultadoAgente(
                    texto_final=texto,
                    ferramentas_chamadas=ferramentas_chamadas,
                    metrica=ChamadaLLMMetrica(
                        modelo=config.model,
                        provedor=config.provider,
                        tokens_entrada=tokens_entrada_total or None,
                        tokens_saida=tokens_saida_total or None,
                        tokens_totais=(tokens_entrada_total + tokens_saida_total) or None,
                        tempo_resposta_s=round(tempo_total, 3),
                        status="ok",
                    ),
                    iteracoes=iteracao,
                )

            partes_resposta = []
            for parte in chamadas_funcao:
                fc = parte.function_call
                nome_ferramenta = fc.name
                argumentos = dict(fc.args) if fc.args else {}
                ferramentas_chamadas.append(nome_ferramenta)

                funcao = tool_registry.get(nome_ferramenta)
                resultado = (
                    funcao(**argumentos)
                    if funcao is not None
                    else {"erro": f"ferramenta '{nome_ferramenta}' desconhecida"}
                )
                partes_resposta.append(
                    types.Part.from_function_response(
                        name=nome_ferramenta, response={"result": resultado}
                    )
                )
            contents.append(types.Content(role="user", parts=partes_resposta))

        tempo_total = time.perf_counter() - inicio
        return ResultadoAgente(
            texto_final=None,
            ferramentas_chamadas=ferramentas_chamadas,
            metrica=ChamadaLLMMetrica(
                modelo=config.model,
                provedor=config.provider,
                tokens_entrada=tokens_entrada_total or None,
                tokens_saida=tokens_saida_total or None,
                tokens_totais=(tokens_entrada_total + tokens_saida_total) or None,
                tempo_resposta_s=round(tempo_total, 3),
                status="erro",
                erro=f"limite de {max_iteracoes} iteracoes atingido sem resposta final",
            ),
            iteracoes=max_iteracoes,
        )
    except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer falha do SDK/rede
        tempo_total = time.perf_counter() - inicio
        status = "timeout" if "timeout" in str(exc).lower() else "erro"
        return ResultadoAgente(
            texto_final=None,
            ferramentas_chamadas=ferramentas_chamadas,
            metrica=ChamadaLLMMetrica(
                modelo=config.model,
                provedor=config.provider,
                tempo_resposta_s=round(tempo_total, 3),
                status=status,
                erro=str(exc),
            ),
            iteracoes=0,
        )


def extrair_json(texto: str) -> dict[str, Any] | None:
    """Extrai um objeto JSON de um texto que pode vir com cercas de markdown."""
    if texto is None:
        return None
    limpo = texto.strip()
    if limpo.startswith("```"):
        limpo = limpo.strip("`")
        if limpo.lower().startswith("json"):
            limpo = limpo[4:]
    limpo = limpo.strip()
    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        inicio = limpo.find("{")
        fim = limpo.rfind("}")
        if inicio == -1 or fim == -1 or fim <= inicio:
            return None
        try:
            return json.loads(limpo[inicio : fim + 1])
        except json.JSONDecodeError:
            return None
