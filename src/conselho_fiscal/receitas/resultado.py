"""Resultado estruturado (JSON) para o agente: tudo o que é preciso para
conversar com a tesouraria sem ler a planilha."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any

FORMATO = "conferencia-receitas/3"
# ent_*: quantos Pix recebidos em cada banco; valor_*: a soma deles
CAMPOS_RESUMO = ("recibos", "conformes", "divergentes", "pessoas", "ok",
                 "ent_cora", "ent_stone", "valor_cora", "valor_stone", "devolucoes",
                 "sugestoes")


def sha256(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 16), b""):
            h.update(bloco)
    return h.hexdigest()


def montar(stats: dict[str, Any], entradas: str, cora: str, stone: str) -> dict[str, Any]:
    return {
        "formato": FORMATO,
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mes_referencia": stats["mes_referencia"],
        "arquivos": {nome: {"arquivo": os.path.basename(c), "sha256": sha256(c)}
                     for nome, c in (("entradas", entradas), ("cora", cora), ("stone", stone))},
        "resumo": {k: stats[k] for k in CAMPOS_RESUMO},
        "conferencias": stats["verificacoes"],
        "alertas": len(stats["alertas"]),
        "destinos_novos": stats["destinos_novos"],
        "limpeza_cadastros": stats["limpeza_cadastros"],
        **stats["detalhes"],
    }


def salvar(resultado: dict[str, Any], caminho: str) -> None:
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
        f.write("\n")
