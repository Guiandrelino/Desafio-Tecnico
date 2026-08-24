"""Agente de triagem PLD: LLM + ferramentas, decidindo o que consultar.

O agente NAO calcula nada. Ele recebe do Python os fatos ja apurados
(contagens, somas, medianas, flags das regras) e decide, caso a caso, se
precisa de mais contexto (historico completo, operacoes de um dia, perfil de
canal) antes de emitir o parecer. Clientes diferentes podem levar a
sequencias de ferramentas diferentes -- isso e o que distingue um agente de
um script que sempre chama tudo.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError

from nivel_2 import cache
from nivel_2.config import get_llm_config
from nivel_2.llm_client import executar_agente, extrair_json
from nivel_2.models import ChamadaLLMMetrica, Parecer
from nivel_2.tools import TOOL_REGISTRY, _base, historico_cliente

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

    Tudo aqui vem de rules.py/tools.py (pandas puro) -- a LLM so recebe o
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
        cacheado = cache.obter(chave)
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
        cache.salvar(chave, registro)

    return registro


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Roda o agente de triagem PLD para um cliente.")
    parser.add_argument("cliente_id", help="Ex: CLI-014")
    parser.add_argument("--sem-cache", action="store_true")
    args = parser.parse_args()

    resultado = gerar_parecer(args.cliente_id, usar_cache=not args.sem_cache)
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
