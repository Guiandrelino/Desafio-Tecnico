"""Carga e limpeza dos dados de operacoes.

Reaproveitado pelo nivel 2 (regras em escala, ferramentas do agente) a partir
da mesma logica explicada passo a passo no notebook do nivel 1. Ver
docs/DECISOES.md para o trade-off de duplicar a explicacao no notebook em vez
de importar este modulo la dentro.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

COLUNAS_ORIGINAIS = [
    "id",
    "cliente_id",
    "data",
    "valor",
    "moeda",
    "canal",
    "tipo",
    "contraparte",
    "observacao",
]


def carregar_json(caminho: str | Path) -> tuple[list[dict], float]:
    with open(caminho, encoding="utf-8") as f:
        raw = json.load(f)
    return raw["operacoes"], raw["taxa_cambio_usd_brl"]


def _resolver_duplicatas(df: pd.DataFrame) -> pd.DataFrame:
    """Remove apenas duplicatas inequivocas: mesma linha, todos os campos identicos.

    IDs repetidos com conteudo diferente sao mantidos e logados como um
    problema a ser investigado manualmente -- nao ha forma determinística
    segura de decidir qual registro esta correto.
    """
    linhas_100_pct_iguais = df.duplicated(keep="first")
    if linhas_100_pct_iguais.any():
        ids_removidos = df.loc[linhas_100_pct_iguais, "id"].tolist()
        logger.info("Removendo %d duplicata(s) exata(s): %s", len(ids_removidos), ids_removidos)
        df = df.loc[~linhas_100_pct_iguais].copy()

    contagem_por_id = df["id"].value_counts()
    ids_ambiguos = contagem_por_id[contagem_por_id > 1].index.tolist()
    if ids_ambiguos:
        logger.warning(
            "IDs duplicados com conteudo DIFERENTE (nao removidos automaticamente): %s",
            ids_ambiguos,
        )
    return df


def limpar_operacoes(operacoes: list[dict], taxa_cambio_usd_brl: float) -> pd.DataFrame:
    """Aplica a limpeza documentada no notebook do nivel 1 a qualquer base de operacoes.

    Passos (na ordem):
    1. remove duplicatas exatas de linha;
    2. converte 'data' para datetime, preservando nulos como NaT (nunca inventa data);
    3. cria 'data_ausente' para tornar a ausencia auditavel;
    4. cria 'valor_brl' convertendo USD -> BRL pela taxa fixa do arquivo.
    """
    df = pd.DataFrame(operacoes, columns=COLUNAS_ORIGINAIS)
    df = _resolver_duplicatas(df)

    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df["data_ausente"] = df["data"].isna()

    if not df["moeda"].isin(["BRL", "USD"]).all():
        moedas_inesperadas = sorted(set(df["moeda"]) - {"BRL", "USD"})
        raise ValueError(f"Moedas nao suportadas encontradas: {moedas_inesperadas}")

    df["valor_brl"] = df["valor"].where(
        df["moeda"] == "BRL", df["valor"] * taxa_cambio_usd_brl
    )

    return df.reset_index(drop=True)


def carregar_e_limpar(caminho: str | Path) -> pd.DataFrame:
    operacoes, taxa = carregar_json(caminho)
    return limpar_operacoes(operacoes, taxa)
