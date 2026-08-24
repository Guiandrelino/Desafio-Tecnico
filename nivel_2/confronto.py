"""Confronto entre a classificacao deterministica (baseline) e o parecer do agente.

Baseline por definicao simples, NAO e verdade absoluta -- e so um ponto de
referencia auditavel para medir concordancia e, principalmente, para achar
onde o agente discorda da regra e por que (ver docs/DECISOES.md#confronto).

Criterio do baseline:
  0 regras disparadas -> baixo
  1 regra disparada    -> medio
  2 regras disparadas  -> alto
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from nivel_2.tools import (
    DADOS_NIVEL_2,
    OUTPUTS_DIR,
    aplicar_regras,
    carregar_e_limpar,
    resumo_sinalizacoes_por_cliente,
)

MAPA_BASELINE = {0: "baixo", 1: "médio", 2: "alto"}


def classificar_baseline(resumo: pd.DataFrame) -> pd.DataFrame:
    resumo = resumo.copy()
    resumo["qtd_regras_distintas"] = (resumo["qtd_eventos_fracionamento"] > 0).astype(int) + (
        resumo["qtd_operacoes_atipicas"] > 0
    ).astype(int)
    resumo["risco_deterministico"] = resumo["qtd_regras_distintas"].map(MAPA_BASELINE)
    return resumo


def montar_confronto(lote_csv: Path | None = None) -> pd.DataFrame:
    df = carregar_e_limpar(DADOS_NIVEL_2)
    df = aplicar_regras(df)
    resumo = resumo_sinalizacoes_por_cliente(df)
    baseline = classificar_baseline(resumo)[
        ["cliente_id", "qtd_regras_distintas", "risco_deterministico"]
    ]

    lote_csv = lote_csv or (OUTPUTS_DIR / "lote.csv")
    if not lote_csv.exists():
        raise FileNotFoundError(
            f"{lote_csv} nao encontrado. Rode 'python -m nivel_2.agente' primeiro."
        )
    lote = pd.read_csv(lote_csv)

    confronto = baseline.merge(
        lote[["cliente_id", "status", "nivel_risco_llm", "tipologia_suspeita"]],
        on="cliente_id",
        how="left",
    )
    confronto["concorda"] = confronto["risco_deterministico"] == confronto["nivel_risco_llm"]
    return confronto


def relatorio(confronto: pd.DataFrame) -> str:
    avaliados = confronto[confronto["status"] == "ok"]
    linhas = [f"Clientes avaliados pelo agente com sucesso: {len(avaliados)}/{len(confronto)}"]

    if len(avaliados) > 0:
        taxa = avaliados["concorda"].mean() * 100
        linhas.append(f"Taxa de concordancia (baseline == LLM): {taxa:.1f}%")
        linhas.append("\nDistribuicao baseline:")
        linhas.append(avaliados["risco_deterministico"].value_counts().to_string())
        linhas.append("\nDistribuicao LLM:")
        linhas.append(avaliados["nivel_risco_llm"].value_counts().to_string())

        divergentes = avaliados[~avaliados["concorda"]]
        linhas.append(f"\nDivergencias: {len(divergentes)}")
        if len(divergentes) > 0:
            linhas.append(
                divergentes[
                    ["cliente_id", "risco_deterministico", "nivel_risco_llm", "tipologia_suspeita"]
                ].to_string(index=False)
            )
    else:
        linhas.append(
            "Nenhum cliente foi avaliado com sucesso pelo agente ainda "
            "(sem GEMINI_API_KEY configurada -- ver docs/DECISOES.md)."
        )
    return "\n".join(linhas)


if __name__ == "__main__":
    confronto = montar_confronto()
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    confronto.to_csv(OUTPUTS_DIR / "confronto.csv", index=False)
    print(relatorio(confronto))
    print(f"\nSalvo em {OUTPUTS_DIR / 'confronto.csv'}")
