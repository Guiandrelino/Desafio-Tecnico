"""Calcula os 10 clientes mais sinalizados pelas regras deterministicas (Nivel 2, Parte A)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nivel_2.config import DADOS_NIVEL_2, OUTPUTS_DIR
from nivel_2.data import carregar_e_limpar
from nivel_2.rules import aplicar_regras, resumo_sinalizacoes_por_cliente


def top_10_clientes():
    df = carregar_e_limpar(DADOS_NIVEL_2)
    df = aplicar_regras(df)
    resumo = resumo_sinalizacoes_por_cliente(df)
    top10 = resumo.head(10).reset_index(drop=True)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    caminho = OUTPUTS_DIR / "top_10_clientes.csv"
    top10.to_csv(caminho, index=False)
    return top10, caminho


if __name__ == "__main__":
    top10, caminho = top_10_clientes()
    print(top10.to_string(index=False))
    print(f"\nSalvo em {caminho}")
