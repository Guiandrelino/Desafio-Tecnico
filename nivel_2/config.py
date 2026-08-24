"""Configuracao central via variaveis de ambiente. Nenhuma chave fica hardcoded."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DADOS_NIVEL_1 = ROOT_DIR / "dados" / "dados_nivel_1.json"
DADOS_NIVEL_2 = ROOT_DIR / "dados" / "dados_nivel_2.json"
OUTPUTS_DIR = ROOT_DIR / "outputs"
CACHE_DIR = OUTPUTS_DIR / "cache"
PARECERES_DIR = OUTPUTS_DIR / "pareceres"


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    api_key: str | None

    @property
    def configurado(self) -> bool:
        return bool(self.api_key)


def get_llm_config() -> LLMConfig:
    return LLMConfig(
        provider=os.getenv("LLM_PROVIDER", "google-ai-studio"),
        model=os.getenv("LLM_MODEL", "gemini-2.0-flash"),
        api_key=os.getenv("GEMINI_API_KEY") or None,
    )
