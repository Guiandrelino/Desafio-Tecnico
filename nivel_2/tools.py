"""Ferramentas de consulta que o agente pode chamar.

Cada funcao consulta o DataFrame de operacoes (ja limpo e com as regras
aplicadas) e devolve um dict JSON-serializavel. Nao ha chamada a LLM aqui --
sao apenas consultas/agregacoes deterministicas, iguais em espirito as do
nivel 1, expostas como funcoes que um modelo pode invocar sob demanda.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from nivel_2.config import DADOS_NIVEL_2
from nivel_2.data import carregar_e_limpar
from nivel_2.rules import aplicar_regras


@lru_cache(maxsize=1)
def _base() -> pd.DataFrame:
    df = carregar_e_limpar(DADOS_NIVEL_2)
    return aplicar_regras(df)


def _cliente_existe(cliente_id: str) -> bool:
    return cliente_id in _base()["cliente_id"].values


def historico_cliente(cliente_id: str) -> dict:
    """Resumo agregado de todas as operacoes de um cliente.

    Retorna quantidade, volume total/medio/mediano, periodo coberto, canais e
    tipos utilizados, e quantas vezes cada regra deterministica disparou.
    """
    df = _base()
    if not _cliente_existe(cliente_id):
        return {"erro": f"cliente_id '{cliente_id}' nao encontrado na base"}

    sub = df[df["cliente_id"] == cliente_id]
    com_data = sub[~sub["data_ausente"]]

    return {
        "cliente_id": cliente_id,
        "quantidade_operacoes": int(len(sub)),
        "volume_total_brl": round(float(sub["valor_brl"].sum()), 2),
        "valor_medio_brl": round(float(sub["valor_brl"].mean()), 2),
        "valor_mediano_brl": round(float(sub["valor_brl"].median()), 2),
        "periodo_inicio": com_data["data"].min().date().isoformat() if not com_data.empty else None,
        "periodo_fim": com_data["data"].max().date().isoformat() if not com_data.empty else None,
        "operacoes_sem_data": int(sub["data_ausente"].sum()),
        "canais_utilizados": sorted(sub["canal"].unique().tolist()),
        "tipos_utilizados": sorted(sub["tipo"].unique().tolist()),
        "qtd_moedas_estrangeiras": int((sub["moeda"] != "BRL").sum()),
        "qtd_flags_fracionamento": int(sub["regra_fracionamento"].sum()),
        "qtd_flags_valor_atipico": int(sub["regra_valor_atipico"].sum()),
    }


def operacoes_do_dia(cliente_id: str, data: str) -> dict:
    """Lista as operacoes de um cliente em uma data especifica (YYYY-MM-DD)."""
    df = _base()
    if not _cliente_existe(cliente_id):
        return {"erro": f"cliente_id '{cliente_id}' nao encontrado na base"}

    try:
        data_alvo = pd.Timestamp(data)
    except (ValueError, TypeError):
        return {"erro": f"data '{data}' invalida, use o formato YYYY-MM-DD"}

    sub = df[(df["cliente_id"] == cliente_id) & (df["data"] == data_alvo)]
    operacoes = [
        {
            "id": row["id"],
            "valor": float(row["valor"]),
            "moeda": row["moeda"],
            "valor_brl": round(float(row["valor_brl"]), 2),
            "canal": row["canal"],
            "tipo": row["tipo"],
            "contraparte": row["contraparte"],
        }
        for _, row in sub.iterrows()
    ]
    return {
        "cliente_id": cliente_id,
        "data": data_alvo.date().isoformat(),
        "quantidade_operacoes": len(operacoes),
        "soma_valor_brl": round(float(sub["valor_brl"].sum()), 2),
        "operacoes": operacoes,
    }


def perfil_canal(cliente_id: str) -> dict:
    """Distribuicao de uso de canais por um cliente (contagem, volume e percentual)."""
    df = _base()
    if not _cliente_existe(cliente_id):
        return {"erro": f"cliente_id '{cliente_id}' nao encontrado na base"}

    sub = df[df["cliente_id"] == cliente_id]
    total_ops = len(sub)
    por_canal = sub.groupby("canal").agg(
        quantidade=("id", "count"), volume_brl=("valor_brl", "sum")
    )
    por_canal["percentual_quantidade"] = (por_canal["quantidade"] / total_ops * 100).round(1)

    return {
        "cliente_id": cliente_id,
        "canais": [
            {
                "canal": canal,
                "quantidade": int(row["quantidade"]),
                "volume_brl": round(float(row["volume_brl"]), 2),
                "percentual_quantidade": float(row["percentual_quantidade"]),
            }
            for canal, row in por_canal.sort_values("quantidade", ascending=False).iterrows()
        ],
    }


TOOL_REGISTRY = {
    "historico_cliente": historico_cliente,
    "operacoes_do_dia": operacoes_do_dia,
    "perfil_canal": perfil_canal,
}
