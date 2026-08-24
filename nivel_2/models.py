"""Modelos Pydantic para validar a saida estruturada da LLM."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Parecer(BaseModel):
    nivel_risco: Literal["baixo", "médio", "alto"]
    tipologia_suspeita: str
    red_flags: list[str] = Field(default_factory=list)
    justificativa: str


class ChamadaLLMMetrica(BaseModel):
    """Metricas de observabilidade de uma chamada ao modelo."""

    modelo: str
    provedor: str
    tokens_entrada: int | None = None
    tokens_saida: int | None = None
    tokens_totais: int | None = None
    tempo_resposta_s: float
    status: Literal["ok", "erro", "malformado", "timeout", "cache_hit"]
    erro: str | None = None
