"""Testes do contrato Pydantic do parecer.

Achado ao rodar o agente pela primeira vez contra a API real do Gemini:
o modelo devolveu "medio" sem acento (o system prompt pede "medio|alto|baixo"
sem diacritico no proprio JSON de exemplo, mas o enum de negocio usa
"médio"). Sem normalizacao, isso virava falso "malformado". Ver
docs/USO_DE_IA.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from pydantic import ValidationError

from nivel_2.models import Parecer


@pytest.mark.parametrize("valor_entrada", ["medio", "médio", "MEDIO", " medio "])
def test_nivel_risco_aceita_variacoes_de_medio(valor_entrada):
    parecer = Parecer(
        nivel_risco=valor_entrada,
        tipologia_suspeita="x",
        red_flags=[],
        justificativa="y",
    )
    assert parecer.nivel_risco == "médio"


def test_nivel_risco_invalido_ainda_rejeitado():
    with pytest.raises(ValidationError):
        Parecer(
            nivel_risco="critico",
            tipologia_suspeita="x",
            red_flags=[],
            justificativa="y",
        )
