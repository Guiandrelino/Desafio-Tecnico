"""Execucao em lote do agente sobre os 10 clientes mais sinalizados (Nivel 2, Parte C)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from nivel_2.agente import gerar_parecer
from nivel_2.config import OUTPUTS_DIR, PARECERES_DIR
from nivel_2.top_clientes import top_10_clientes

# A camada gratuita do Gemini limita requisicoes por minuto (observado na pratica
# ao rodar este lote pela primeira vez -- ver docs/DECISOES.md). Cada cliente pode
# custar varias chamadas (loop de tool-calling), entao espacamos entre clientes
# alem do retry/backoff que ja existe dentro de llm_client.py.
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
    df_lote = rodar_lote()
    print(df_lote.to_string(index=False))
    print("\nResumo de custo/latencia:")
    print(df_lote[["status"]].value_counts())
    print("tokens_totais soma:", df_lote["tokens_totais"].sum())
    print("tempo_resposta_s medio:", df_lote["tempo_resposta_s"].mean())
