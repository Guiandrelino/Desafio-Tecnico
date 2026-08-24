"""Dados, regras deterministicas e ferramentas de consulta do agente.

Tudo neste arquivo e puro Python/pandas -- nenhuma chamada a LLM. E a
metade "Python calcula" do projeto: carga/limpeza dos dados (mesma logica
explicada passo a passo em nivel_1/nivel_1.ipynb), as duas regras de PLD, e
as tres funcoes que o agente (nivel_2/agente.py) pode chamar sob demanda.

Consolidado num arquivo so para bater com a estrutura obrigatoria do
desafio (nivel_2/tools.py, agente.py, confronto.py) -- ver docs/DECISOES.md
para o raciocinio da consolidacao.
"""
from __future__ import annotations

import json
import logging
import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Configuracao / caminhos
# --------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DADOS_NIVEL_1 = ROOT_DIR / "dados" / "dados_nivel_1.json"
DADOS_NIVEL_2 = ROOT_DIR / "dados" / "dados_nivel_2.json"
OUTPUTS_DIR = ROOT_DIR / "outputs"

# --------------------------------------------------------------------------
# Carga e limpeza dos dados
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# Regras deterministicas de PLD
# --------------------------------------------------------------------------
#
# Regra 1 (fracionamento): cliente com 3+ operacoes na mesma data, soma > 50000
# e nenhuma operacao isolada >= 20000.
#
# Regra 2 (valor atipico): operacao cujo valor_brl > 5x a mediana do cliente,
# aplicada somente a clientes com 4+ operacoes.

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


def top_10_clientes() -> tuple[pd.DataFrame, Path]:
    """Nivel 2, Parte A: os 10 clientes mais sinalizados -> outputs/top_10_clientes.csv."""
    df = aplicar_regras(carregar_e_limpar(DADOS_NIVEL_2))
    resumo = resumo_sinalizacoes_por_cliente(df)
    top10 = resumo.head(10).reset_index(drop=True)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    caminho = OUTPUTS_DIR / "top_10_clientes.csv"
    top10.to_csv(caminho, index=False)
    return top10, caminho


# --------------------------------------------------------------------------
# Ferramentas de consulta que o agente pode chamar
# --------------------------------------------------------------------------
#
# Cada funcao consulta o DataFrame de operacoes (ja limpo e com as regras
# aplicadas) e devolve um dict JSON-serializavel. Sao apenas consultas/
# agregacoes deterministicas expostas como funcoes que um modelo pode
# invocar sob demanda (ver nivel_2/agente.py).


@lru_cache(maxsize=1)
def _base() -> pd.DataFrame:
    return aplicar_regras(carregar_e_limpar(DADOS_NIVEL_2))


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


if __name__ == "__main__":
    top10, caminho = top_10_clientes()
    print(top10.to_string(index=False))
    print(f"\nSalvo em {caminho}")
