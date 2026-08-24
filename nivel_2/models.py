"""Modelos Pydantic para validar a saida estruturada da LLM."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

_NIVEL_RISCO_CANONICO = {
    "baixo": "baixo",
    "medio": "médio",
    "médio": "médio",
    "alto": "alto",
}


class Parecer(BaseModel):
    nivel_risco: Literal["baixo", "médio", "alto"]
    tipologia_suspeita: str
    red_flags: list[str] = Field(default_factory=list)
    justificativa: str

    @field_validator("nivel_risco", mode="before")
    @classmethod
    def _normalizar_nivel_risco(cls, valor: str) -> str:
        """Aceita 'medio' sem acento -- LLMs frequentemente omitem diacriticos."""
        if isinstance(valor, str):
            chave = valor.strip().lower()
            if chave in _NIVEL_RISCO_CANONICO:
                return _NIVEL_RISCO_CANONICO[chave]
        return valor


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
