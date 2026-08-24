"""Testes das regras deterministicas de PLD.

Cobrem os casos descritos no desafio: positivo, negativo por contagem
insuficiente e negativo por operacao isolada >= 20000 (Regra 1); positivo e
negativo por menos de 4 operacoes (Regra 2). Tambem valida contra os dados
reais do nivel 1, onde sabemos exatamente quais casos foram plantados.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nivel_2.tools import (
    aplicar_regra_fracionamento,
    aplicar_regra_valor_atipico,
    carregar_e_limpar,
    limpar_operacoes,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def _op(id_, cliente_id, data, valor, moeda="BRL"):
    return {
        "id": id_,
        "cliente_id": cliente_id,
        "data": data,
        "valor": valor,
        "moeda": moeda,
        "canal": "pix",
        "tipo": "transferencia_enviada",
        "contraparte": "Teste LTDA",
        "observacao": "",
    }


# ---------------------------------------------------------------------------
# Regra 1 - fracionamento
# ---------------------------------------------------------------------------


def test_regra1_positivo_3_ops_soma_maior_50k_nenhuma_isolada_20k():
    ops = [
        _op("OP-1", "CLI-X", "2026-01-10", 18000),
        _op("OP-2", "CLI-X", "2026-01-10", 17000),
        _op("OP-3", "CLI-X", "2026-01-10", 16000),
    ]
    df = limpar_operacoes(ops, taxa_cambio_usd_brl=5.0)
    df = aplicar_regra_fracionamento(df)
    assert df["regra_fracionamento"].all()


def test_regra1_negativo_2_ops_soma_maior_50k():
    ops = [
        _op("OP-1", "CLI-Y", "2026-01-10", 30000),
        _op("OP-2", "CLI-Y", "2026-01-10", 25000),
    ]
    df = limpar_operacoes(ops, taxa_cambio_usd_brl=5.0)
    df = aplicar_regra_fracionamento(df)
    assert not df["regra_fracionamento"].any()


def test_regra1_negativo_3_ops_uma_atinge_20k():
    ops = [
        _op("OP-1", "CLI-Z", "2026-01-10", 20000),
        _op("OP-2", "CLI-Z", "2026-01-10", 16000),
        _op("OP-3", "CLI-Z", "2026-01-10", 15000),
    ]
    df = limpar_operacoes(ops, taxa_cambio_usd_brl=5.0)
    df = aplicar_regra_fracionamento(df)
    assert not df["regra_fracionamento"].any()


def test_regra1_ignora_operacoes_sem_data():
    ops = [
        _op("OP-1", "CLI-W", None, 18000),
        _op("OP-2", "CLI-W", None, 17000),
        _op("OP-3", "CLI-W", None, 16000),
    ]
    df = limpar_operacoes(ops, taxa_cambio_usd_brl=5.0)
    df = aplicar_regra_fracionamento(df)
    assert not df["regra_fracionamento"].any()


# ---------------------------------------------------------------------------
# Regra 2 - valor atipico
# ---------------------------------------------------------------------------


def test_regra2_positivo_valor_maior_5x_mediana_com_4_ops():
    ops = [
        _op("OP-1", "CLI-A", "2026-01-01", 1000),
        _op("OP-2", "CLI-A", "2026-01-02", 1100),
        _op("OP-3", "CLI-A", "2026-01-03", 1200),
        _op("OP-4", "CLI-A", "2026-01-04", 10000),  # mediana=1150, limite=5750
    ]
    df = limpar_operacoes(ops, taxa_cambio_usd_brl=5.0)
    df = aplicar_regra_valor_atipico(df)
    flagradas = df[df["regra_valor_atipico"]]["id"].tolist()
    assert flagradas == ["OP-4"]


def test_regra2_negativo_menos_de_4_operacoes():
    ops = [
        _op("OP-1", "CLI-B", "2026-01-01", 1000),
        _op("OP-2", "CLI-B", "2026-01-02", 1100),
        _op("OP-3", "CLI-B", "2026-01-03", 10000),
    ]
    df = limpar_operacoes(ops, taxa_cambio_usd_brl=5.0)
    df = aplicar_regra_valor_atipico(df)
    assert not df["regra_valor_atipico"].any()


# ---------------------------------------------------------------------------
# Validacao contra os dados reais do nivel 1 (casos plantados conhecidos)
# ---------------------------------------------------------------------------


def test_dados_nivel_1_caso_positivo_regra1_cli_a1():
    df = carregar_e_limpar(ROOT_DIR / "dados" / "dados_nivel_1.json")
    df = aplicar_regra_fracionamento(df)
    flagradas = df[(df["cliente_id"] == "CLI-A-1") & (df["data"] == "2026-03-09")]
    assert flagradas["regra_fracionamento"].all()
    assert len(flagradas) == 3


def test_dados_nivel_1_caso_parecido_nao_dispara_cli_a3():
    df = carregar_e_limpar(ROOT_DIR / "dados" / "dados_nivel_1.json")
    df = aplicar_regra_fracionamento(df)
    grupo = df[(df["cliente_id"] == "CLI-A-3") & (df["data"] == "2026-03-05")]
    assert len(grupo) == 3  # apos remover a duplicata exata do OP-0007
    assert not grupo["regra_fracionamento"].any()
    assert grupo["valor_brl"].sum() == 48500.0


def test_dados_nivel_1_caso_positivo_regra2_cli_a4_usd():
    df = carregar_e_limpar(ROOT_DIR / "dados" / "dados_nivel_1.json")
    df = aplicar_regra_valor_atipico(df)
    op = df[df["id"] == "OP-0013"].iloc[0]
    assert op["valor_brl"] == pytest.approx(64800.0)
    assert bool(op["regra_valor_atipico"]) is True


def test_dados_nivel_1_duplicata_exata_removida():
    df = carregar_e_limpar(ROOT_DIR / "dados" / "dados_nivel_1.json")
    assert (df["id"] == "OP-0007").sum() == 1
    assert len(df) == 19
