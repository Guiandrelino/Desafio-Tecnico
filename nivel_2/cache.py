"""Cache em disco para respostas da LLM.

Motivacao: a camada gratuita do provedor tem limite de requisicoes por
minuto. Cachear por hash do (modelo + prompt + contexto) evita chamadas
repetidas ao reexecutar o notebook/scripts, reduz consumo de cota e torna os
testes reproduziveis. Nenhuma chave de API e armazenada aqui -- so o
prompt/contexto (dado publico e fictício do proprio desafio) e a resposta.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from nivel_2.config import CACHE_DIR


def _chave_hash(chave: str) -> str:
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()[:24]


def _caminho(chave: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{_chave_hash(chave)}.json"


def obter(chave: str) -> dict[str, Any] | None:
    caminho = _caminho(chave)
    if not caminho.exists():
        return None
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def salvar(chave: str, valor: dict[str, Any]) -> None:
    caminho = _caminho(chave)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(valor, f, ensure_ascii=False, indent=2, default=str)
