"""Agente de triagem PLD: LLM + ferramentas, decidindo o que consultar.

O agente NAO calcula nada. Ele recebe do Python (nivel_2/tools.py) os fatos
ja apurados -- contagens, somas, medianas, flags das regras -- e decide,
caso a caso, se precisa de mais contexto (historico completo, operacoes de
um dia, perfil de canal) antes de emitir o parecer. Clientes diferentes
podem levar a sequencias de ferramentas diferentes: isso e o que distingue
um agente de um script que sempre chama tudo.

Este arquivo tambem concentra tudo que e especifico da integracao com a
LLM -- configuracao, contrato de saida (Pydantic), cache de respostas,
cliente Gemini com tool-calling manual, e a execucao em lote sobre os 10
clientes do Nivel 2 Parte C. Consolidado num arquivo so para bater com a
estrutura obrigatoria do desafio (nivel_2/tools.py, agente.py,
confronto.py) -- ver docs/DECISOES.md para o raciocinio da consolidacao:
a divisao logica que importa e "tools.py calcula, agente.py fala com a
LLM", nao o numero de arquivos.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

import pandas as pd
from pydantic import BaseModel, Field, ValidationError, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nivel_2.tools import OUTPUTS_DIR, TOOL_REGISTRY, _base, historico_cliente, top_10_clientes

CACHE_DIR = OUTPUTS_DIR / "cache"
PARECERES_DIR = OUTPUTS_DIR / "pareceres"

# --------------------------------------------------------------------------
# Configuracao via variaveis de ambiente. Nenhuma chave fica hardcoded.
# ROOT_DIR/.env ja foi carregado como efeito colateral de importar nivel_2.tools.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    api_key: str | None

    @property
    def configurado(self) -> bool:
        return bool(self.api_key)


def get_llm_config() -> LLMConfig:
    return LLMConfig(
        provider=os.getenv("LLM_PROVIDER", "google-ai-studio"),
        model=os.getenv("LLM_MODEL", "gemini-flash-lite-latest"),
        api_key=os.getenv("GEMINI_API_KEY") or None,
    )


# --------------------------------------------------------------------------
# Contrato de saida estruturada (validado com Pydantic)
# --------------------------------------------------------------------------

_NIVEL_RISCO_CANONICO = {
    "baixo": "baixo",
    "medio": "médio",
    "médio": "médio",
    "alto": "alto",
}


class Parecer(BaseModel):
    nivel_risco: Literal["baixo", "médio", "alto"]
    tipologia_suspeita: str
    red_flags: list[str] = Field(default_factory=list)
    justificativa: str

    @field_validator("nivel_risco", mode="before")
    @classmethod
    def _normalizar_nivel_risco(cls, valor: str) -> str:
        """Aceita 'medio' sem acento -- LLMs frequentemente omitem diacriticos."""
        if isinstance(valor, str):
            chave = valor.strip().lower()
            if chave in _NIVEL_RISCO_CANONICO:
                return _NIVEL_RISCO_CANONICO[chave]
        return valor


class ChamadaLLMMetrica(BaseModel):
    """Metricas de observabilidade de uma chamada ao modelo."""

    modelo: str
    provedor: str
    tokens_entrada: int | None = None
    tokens_saida: int | None = None
    tokens_totais: int | None = None
    tempo_resposta_s: float
    status: Literal["ok", "erro", "malformado", "timeout", "cache_hit"]
    erro: str | None = None


# --------------------------------------------------------------------------
# Cache em disco das respostas da LLM
#
# Motivacao: a camada gratuita do provedor tem limite de requisicoes por
# minuto e por dia. Cachear por hash do (modelo + prompt) evita chamadas
# repetidas ao reexecutar o notebook/scripts, reduz consumo de cota e torna
# os testes reproduziveis. Nenhuma chave de API e armazenada aqui -- so o
# prompt/contexto (dado publico e ficticio do proprio desafio) e a resposta.
# --------------------------------------------------------------------------


def _cache_chave_hash(chave: str) -> str:
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()[:24]


def _cache_caminho(chave: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{_cache_chave_hash(chave)}.json"


def _cache_obter(chave: str) -> dict[str, Any] | None:
    caminho = _cache_caminho(chave)
    if not caminho.exists():
        return None
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def _cache_salvar(chave: str, valor: dict[str, Any]) -> None:
    caminho = _cache_caminho(chave)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(valor, f, ensure_ascii=False, indent=2, default=str)


# --------------------------------------------------------------------------
# Cliente Gemini: declaracao das ferramentas, loop manual de tool-calling,
# retry/backoff e extracao de tokens/latencia
# --------------------------------------------------------------------------

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
MAX_TENTATIVAS_RATE_LIMIT = 4
_PADRAO_RETRY_DELAY = re.compile(r"retryDelay['\"]?:\s*['\"](\d+(?:\.\d+)?)s")


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


# --------------------------------------------------------------------------
# Montagem do contexto do cliente e geracao do parecer
# --------------------------------------------------------------------------

SYSTEM_INSTRUCTION = """Voce e um analista de Prevencao a Lavagem de Dinheiro (PLD) \
em um banco fazendo a triagem de clientes sinalizados por regras automaticas.

Voce recebe fatos JA CALCULADOS por um sistema deterministico em Python/pandas \
sobre um cliente: contagens, somas, medianas e se as regras de fracionamento e \
de valor atipico dispararam para ele.

REGRAS IMPORTANTES:
- Voce NUNCA calcula, soma, conta ou verifica limites. Os numeros fornecidos ja \
sao definitivos e corretos -- nao os recalcule nem os questione.
- Voce NAO inventa operacoes, valores, datas ou contrapartes que nao estejam nos \
fatos fornecidos ou no retorno das ferramentas.
- Uma flag de regra (fracionamento ou valor atipico) e um indicio estatistico, \
nao uma prova de ilicitude. Avalie o conjunto de evidencias antes de concluir.
- Se precisar de mais contexto para avaliar o caso (historico completo, operacoes \
de um dia especifico, perfil de uso de canais), use as ferramentas disponiveis. \
Nao chame uma ferramenta que nao vai mudar sua conclusao.
- Diferencie fatos (o que os dados mostram) de hipoteses (o que voce esta \
inferindo) -- deixe isso explicito na justificativa.
- Ao concluir, responda EXCLUSIVAMENTE com um JSON valido (sem markdown, sem \
texto antes ou depois), exatamente neste formato:
{"nivel_risco": "baixo|medio|alto", "tipologia_suspeita": "...", "red_flags": \
["..."], "justificativa": "..."}
"""


def montar_contexto_cliente(cliente_id: str) -> dict[str, Any]:
    """Monta o pacote de fatos pre-calculados que vai no prompt do usuario.

    Tudo aqui vem de nivel_2/tools.py (pandas puro) -- a LLM so recebe o
    resultado ja pronto.
    """
    df = _base()
    sub = df[df["cliente_id"] == cliente_id]
    if sub.empty:
        raise ValueError(f"cliente_id '{cliente_id}' nao encontrado")

    resumo = historico_cliente(cliente_id)
    return {
        "cliente_id": cliente_id,
        "quantidade_operacoes": resumo["quantidade_operacoes"],
        "volume_total_brl": resumo["volume_total_brl"],
        "valor_mediano_brl": resumo["valor_mediano_brl"],
        "regra_fracionamento_disparada": bool(sub["regra_fracionamento"].any()),
        "qtd_datas_com_fracionamento": int(
            sub.loc[sub["regra_fracionamento"], "data"].nunique()
        ),
        "regra_valor_atipico_disparada": bool(sub["regra_valor_atipico"].any()),
        "qtd_operacoes_atipicas": int(sub["regra_valor_atipico"].sum()),
        "operacoes_com_flag": [
            {
                "id": row["id"],
                "data": row["data"].date().isoformat() if not row["data_ausente"] else None,
                "valor_brl": round(float(row["valor_brl"]), 2),
                "canal": row["canal"],
                "tipo": row["tipo"],
                "regra_fracionamento": bool(row["regra_fracionamento"]),
                "regra_valor_atipico": bool(row["regra_valor_atipico"]),
            }
            for _, row in sub[sub["regra_fracionamento"] | sub["regra_valor_atipico"]].iterrows()
        ],
    }


def _chave_cache(model: str, user_prompt: str) -> str:
    return f"{model}::{SYSTEM_INSTRUCTION}::{user_prompt}"


def gerar_parecer(cliente_id: str, usar_cache: bool = True) -> dict[str, Any]:
    """Executa o agente para um cliente e devolve um registro pronto para outputs/lote.csv."""
    config = get_llm_config()
    contexto = montar_contexto_cliente(cliente_id)
    user_prompt = (
        "Fatos calculados pelo sistema (nao recalcule nada abaixo, apenas interprete):\n"
        + json.dumps(contexto, ensure_ascii=False, indent=2)
        + "\n\nVoce pode chamar historico_cliente, operacoes_do_dia ou perfil_canal "
        "se precisar de mais evidencia antes de decidir. Ao concluir, responda so com o JSON do parecer."
    )

    chave = _chave_cache(config.model, user_prompt)
    inicio = time.perf_counter()

    if usar_cache:
        cacheado = _cache_obter(chave)
        if cacheado is not None:
            registro = dict(cacheado)
            registro["metrica"]["status"] = "cache_hit"
            registro["metrica"]["tempo_resposta_s"] = round(time.perf_counter() - inicio, 4)
            return registro

    resultado = executar_agente(
        config=config,
        system_instruction=SYSTEM_INSTRUCTION,
        user_prompt=user_prompt,
        tool_registry=TOOL_REGISTRY,
    )

    parecer_dict: dict[str, Any] | None = None
    status_final = resultado.metrica.status
    erro_validacao = None

    if status_final == "ok":
        bruto = extrair_json(resultado.texto_final)
        if bruto is None:
            status_final = "malformado"
            erro_validacao = "resposta nao continha JSON valido"
        else:
            try:
                parecer_dict = Parecer(**bruto).model_dump()
            except ValidationError as exc:
                status_final = "malformado"
                erro_validacao = str(exc)

    registro = {
        "cliente_id": cliente_id,
        "parecer": parecer_dict,
        "nivel_risco_llm": parecer_dict["nivel_risco"] if parecer_dict else None,
        "ferramentas_utilizadas": resultado.ferramentas_chamadas,
        "qtd_chamadas_llm": resultado.iteracoes,
        "resposta_bruta": resultado.texto_final,
        "erro_validacao": erro_validacao,
        "metrica": resultado.metrica.model_dump(),
        "status": status_final,
    }
    registro["metrica"]["status"] = status_final

    if usar_cache and status_final == "ok":
        _cache_salvar(chave, registro)

    return registro


# --------------------------------------------------------------------------
# Execucao em lote sobre os 10 clientes mais sinalizados (Nivel 2, Parte C)
# --------------------------------------------------------------------------

# A camada gratuita do Gemini limita requisicoes por minuto (observado na pratica
# ao rodar este lote pela primeira vez -- ver docs/DECISOES.md). Cada cliente pode
# custar varias chamadas (loop de tool-calling), entao espacamos entre clientes
# alem do retry/backoff acima.
PAUSA_ENTRE_CLIENTES_S = 20


def rodar_lote(usar_cache: bool = True) -> pd.DataFrame:
    top10, _ = top_10_clientes()
    PARECERES_DIR.mkdir(parents=True, exist_ok=True)

    linhas = []
    for i, cliente_id in enumerate(top10["cliente_id"]):
        if i > 0:
            time.sleep(PAUSA_ENTRE_CLIENTES_S)
        registro = gerar_parecer(cliente_id, usar_cache=usar_cache)

        with open(PARECERES_DIR / f"{cliente_id}.json", "w", encoding="utf-8") as f:
            json.dump(registro, f, ensure_ascii=False, indent=2, default=str)

        parecer = registro["parecer"] or {}
        linhas.append(
            {
                "cliente_id": cliente_id,
                "status": registro["status"],
                "nivel_risco_llm": registro["nivel_risco_llm"],
                "tipologia_suspeita": parecer.get("tipologia_suspeita"),
                "qtd_red_flags": len(parecer.get("red_flags", [])) if parecer else None,
                "ferramentas_utilizadas": ";".join(registro["ferramentas_utilizadas"]),
                "qtd_chamadas_llm": registro["qtd_chamadas_llm"],
                "modelo": registro["metrica"]["modelo"],
                "tokens_totais": registro["metrica"]["tokens_totais"],
                "tempo_resposta_s": registro["metrica"]["tempo_resposta_s"],
                "erro": registro["metrica"]["erro"],
            }
        )

    df_lote = pd.DataFrame(linhas)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    df_lote.to_csv(OUTPUTS_DIR / "lote.csv", index=False)
    return df_lote


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Agente de triagem PLD: um cliente (debug) ou o lote completo do top 10."
    )
    parser.add_argument(
        "cliente_id", nargs="?", default=None, help="Ex: CLI-014. Se omitido, roda o lote completo."
    )
    parser.add_argument("--sem-cache", action="store_true")
    args = parser.parse_args()

    if args.cliente_id:
        resultado = gerar_parecer(args.cliente_id, usar_cache=not args.sem_cache)
        print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
    else:
        df_lote = rodar_lote(usar_cache=not args.sem_cache)
        print(df_lote.to_string(index=False))
        print("\nResumo de custo/latencia:")
        print(df_lote[["status"]].value_counts())
        print("tokens_totais soma:", df_lote["tokens_totais"].sum())
        print("tempo_resposta_s medio:", df_lote["tempo_resposta_s"].mean())
