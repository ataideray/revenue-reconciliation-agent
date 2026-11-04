"""Configuração por variáveis de ambiente.

CF_CADASTROS_DIR: pasta dos cadastros (destinos.json, vinculos_confirmados.json).
    No servidor, aponta para o armazenamento persistente. Padrão: a pasta
    `cadastros/` do repositório (ou do diretório atual, se o pacote estiver
    instalado fora do repositório).
CF_AGENTE_DIR: pasta de trabalho do agente (arquivos recebidos, versões de
    cada mês, estado e conversas). Padrão: `agente_dados/` do repositório.
"""

from __future__ import annotations

import os
from pathlib import Path

_RAIZ_REPO = Path(__file__).resolve().parents[2]


def diretorio_cadastros() -> Path:
    if os.environ.get("CF_CADASTROS_DIR"):
        return Path(os.environ["CF_CADASTROS_DIR"])
    if (_RAIZ_REPO / "pyproject.toml").exists():
        return _RAIZ_REPO / "cadastros"
    return Path.cwd() / "cadastros"


def caminho_destinos() -> Path:
    return diretorio_cadastros() / "destinos.json"


def caminho_vinculos_confirmados() -> Path:
    return diretorio_cadastros() / "vinculos_confirmados.json"


def diretorio_agente() -> Path:
    if os.environ.get("CF_AGENTE_DIR"):
        return Path(os.environ["CF_AGENTE_DIR"])
    if (_RAIZ_REPO / "pyproject.toml").exists():
        return _RAIZ_REPO / "agente_dados"
    return Path.cwd() / "agente_dados"
