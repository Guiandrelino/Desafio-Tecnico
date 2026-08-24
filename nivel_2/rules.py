"""Regras deterministicas de PLD. Somente pandas -- nenhuma chamada a LLM aqui.

Regra 1 (fracionamento): cliente com 3+ operacoes na mesma data, soma > 50000
e nenhuma operacao isolada >= 20000.

Regra 2 (valor atipico): operacao cujo valor_brl > 5x a mediana do cliente,
aplicada somente a clientes com 4+ operacoes.
"""
from __future__ import annotations

import pandas as pd

LIMITE_FRACIONAMENTO_SOMA = 50_000.0
LIMITE_FRACIONAMENTO_OP_ISOLADA = 20_000.0
MIN_OPERACOES_FRACIONAMENTO = 3
MULTIPLICADOR_VALOR_ATIPICO = 5
MIN_OPERACOES_VALOR_ATIPICO = 4


def aplicar_regra_fracionamento(df: pd.DataFrame) -> pd.DataFrame:
    """Retorna o df original com a coluna booleana 'regra_fracionamento'.

    Operacoes sem data (data_ausente=True) sao excluidas do agrupamento por
    definicao (a regra depende de "mesma data"), mas nao sao removidas do
    DataFrame retornado.
    """
    df = df.copy()
    df["regra_fracionamento"] = False

    elegiveis = df[~df["data_ausente"]]
    agregado = elegiveis.groupby(["cliente_id", "data"])["valor_brl"].agg(
        qtd="count", soma="sum", maximo="max"
    )
    grupos_flagrados = agregado[
        (agregado["qtd"] >= MIN_OPERACOES_FRACIONAMENTO)
        & (agregado["soma"] > LIMITE_FRACIONAMENTO_SOMA)
        & (agregado["maximo"] < LIMITE_FRACIONAMENTO_OP_ISOLADA)
    ].index

    if len(grupos_flagrados) > 0:
        chave_flagrada = elegiveis.set_index(["cliente_id", "data"]).index.isin(grupos_flagrados)
        idx_flagrado = elegiveis.index[chave_flagrada]
        df.loc[idx_flagrado, "regra_fracionamento"] = True

    return df


def aplicar_regra_valor_atipico(df: pd.DataFrame) -> pd.DataFrame:
    """Retorna o df original com 'mediana_cliente_brl' e 'regra_valor_atipico'."""
    df = df.copy()
    mediana_por_cliente = df.groupby("cliente_id")["valor_brl"].transform("median")
    qtd_por_cliente = df.groupby("cliente_id")["valor_brl"].transform("count")

    df["mediana_cliente_brl"] = mediana_por_cliente
    df["regra_valor_atipico"] = (qtd_por_cliente >= MIN_OPERACOES_VALOR_ATIPICO) & (
        df["valor_brl"] > MULTIPLICADOR_VALOR_ATIPICO * mediana_por_cliente
    )
    return df


def aplicar_regras(df: pd.DataFrame) -> pd.DataFrame:
    df = aplicar_regra_fracionamento(df)
    df = aplicar_regra_valor_atipico(df)
    return df


def resumo_sinalizacoes_por_cliente(df: pd.DataFrame) -> pd.DataFrame:
    """Conta quantas regras cada cliente disparou (operacao ou grupo) e o volume total.

    'qtd_sinalizacoes' soma: (1 se o cliente tem ao menos uma operacao com
    regra_fracionamento) + (numero de operacoes com regra_valor_atipico).
    Cada dimensao de risco conta separadamente; um cliente flagrado pelas
    duas regras conta 2, mesmo que a Regra 1 tenha marcado varias linhas do
    mesmo grupo (fracionamento e um fenomeno por data, nao por operacao).
    """
    por_cliente = df.groupby("cliente_id").agg(
        volume_total_brl=("valor_brl", "sum"),
        qtd_operacoes=("id", "count"),
    )

    frac_por_cliente = (
        df[df["regra_fracionamento"]]
        .groupby("cliente_id")["data"]
        .nunique()
        .rename("qtd_eventos_fracionamento")
    )
    atipico_por_cliente = (
        df[df["regra_valor_atipico"]]
        .groupby("cliente_id")["id"]
        .count()
        .rename("qtd_operacoes_atipicas")
    )

    resumo = por_cliente.join(frac_por_cliente).join(atipico_por_cliente).fillna(0)
    resumo["qtd_eventos_fracionamento"] = resumo["qtd_eventos_fracionamento"].astype(int)
    resumo["qtd_operacoes_atipicas"] = resumo["qtd_operacoes_atipicas"].astype(int)
    resumo["qtd_sinalizacoes"] = (
        (resumo["qtd_eventos_fracionamento"] > 0).astype(int)
        + (resumo["qtd_operacoes_atipicas"] > 0).astype(int)
    )
    resumo = resumo.sort_values(
        by=["qtd_sinalizacoes", "volume_total_brl"], ascending=[False, False]
    )
    return resumo.reset_index()
