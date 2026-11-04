"""Valores em reais, datas e meses."""

from __future__ import annotations

import math
import re
from typing import Any


def valor_planilha(v: Any) -> float:
    """Converte um valor de planilha em float, detectando o separador decimal.

    Aceita 125, '125.50', '125,50', 'R$ 1.250,00' e '1,250.00'. Vazio -> 0.0.
    """
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return 0.0 if isinstance(v, float) and math.isnan(v) else float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    s = s.replace("R$", "").replace(" ", "").replace("\xa0", "")
    s = re.sub(r"[^\d\.,\-]", "", s)
    if s in ("", "-", ".", ","):
        return 0.0
    tem_ponto, tem_virgula = "." in s, "," in s
    if tem_ponto and tem_virgula:
        if s.rfind(",") > s.rfind("."):        # 1.250,00 -> formato BR
            s = s.replace(".", "").replace(",", ".")
        else:                                   # 1,250.00 -> formato US
            s = s.replace(",", "")
    elif tem_virgula:                           # 12,50: vírgula decimal
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def valor_extrato(s: str) -> float:
    """Valor como impresso nos extratos: '1.234,56' -> 1234.56."""
    return float(s.replace(".", "").replace(",", "."))


def brl(v: float) -> str:
    """1234.5 -> 'R$ 1.234,50'."""
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def mesmo_valor(a: float, b: float) -> bool:
    """Igualdade de valores em reais (tolerância de meio centavo)."""
    return abs(a - b) <= 0.005


def indice_mes(mes: str) -> int:
    """'2026-07' -> número sequencial de meses, para contar meses entre datas."""
    ano, m = (int(x) for x in str(mes).split("-")[:2])
    return ano * 12 + m - 1


def data_ordenavel(s: Any) -> tuple[int, int, int] | None:
    """'dd/mm/aa' (Stone) ou 'dd/mm/aaaa' (Cora) -> (aaaa, mm, dd), para comparar."""
    m = re.match(r"^\s*(\d{2})/(\d{2})/(\d{2,4})", str(s or ""))
    if not m:
        return None
    d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return (a + 2000 if a < 100 else a, mes, d)
