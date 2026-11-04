"""Normalização de texto usada em todo o projeto."""

from __future__ import annotations

import math
import unicodedata
from typing import Any


def strip_acentos(s: Any) -> str:
    """Remove acentos: 'Açaí' -> 'Acai'."""
    return "".join(c for c in unicodedata.normalize("NFD", str(s))
                   if unicodedata.category(c) != "Mn")


def norm(s: Any) -> str:
    """Minúsculas, sem acento e com espaços simples: ' Fundo  Lâmpadas' -> 'fundo lampadas'."""
    return " ".join(strip_acentos(s).lower().split())


def norm_maiusculo(s: Any) -> str:
    """Maiúsculas, sem acento e sem espaços nas pontas (cabeçalhos, nomes)."""
    return strip_acentos(s).upper().strip()


def vazio(v: Any) -> bool:
    """None, NaN ou texto em branco."""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return str(v).strip() == ""


def espacos_simples(s: Any) -> str:
    return " ".join(str(s).split())
