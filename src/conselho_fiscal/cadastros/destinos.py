"""Cadastro de destinos (destinos.json): em que coluna cai cada descrição.

Formato, editável sem mexer no código:
  "colunas":  chave -> {"nome": nome fixo da coluna, "ultimo_uso": "AAAA-MM"}
  "apelidos": descrição EXATA (chave) -> coluna  (ex.: "sopa" -> "oficina")
  "prefixos": descrição que COMEÇA com -> coluna (ex.: "anuidade" pega
              "Anuidade — Conselheira Flora")

Apelidos e prefixos valem para a descrição inteira e para a parte antes do
traço ("Retiro - Arrecadação…" -> "retiro"). Descrição nova vira coluna
nova, cadastrada com a grafia mais usada no mês. Coluna sem uso há 24 meses
é apagada; apelidos e prefixos são regras e não expiram.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypedDict

from conselho_fiscal import config
from conselho_fiscal.cadastros import MESES_GUARDA
from conselho_fiscal.comum.texto import espacos_simples, norm
from conselho_fiscal.comum.valores import indice_mes

# colunas conhecidas, na ordem em que aparecem na planilha; as demais vêm depois
ORDEM_PREFERIDA = [
    "Anuidade", "Cantina", "Açaí", "Espetinho", "Retiro", "Oficina Horta",
    "Feira dos Pais", "Cafés", "Oficina", "Ofertas", "Bazar", "Brechó", "Lojinha",
    "Promoções", "Rendimentos",
]


class Coluna(TypedDict):
    nome: str
    ultimo_uso: str | None


class Cadastro(TypedDict):
    colunas: dict[str, Coluna]
    apelidos: dict[str, str]
    prefixos: dict[str, str]


def chave(descricao: str) -> str:
    """Chave que junta grafias do MESMO destino: ignora maiúsculas, acentos,
    espaços, traços e singular/plural. 'Fundo - Lampadas' -> 'fundo lampada'."""
    s = re.sub(r"[—–-]", " ", norm(descricao))
    return " ".join(_singular(p) for p in s.split())


def _singular(palavra: str) -> str:
    """Singular aproximado (texto já sem acento): licoes -> licao, lampadas -> lampada."""
    if len(palavra) > 4 and palavra.endswith(("oes", "aes")):
        return palavra[:-3] + "ao"
    if len(palavra) > 3 and palavra.endswith("s"):
        return palavra[:-1]
    return palavra


def vazio() -> Cadastro:
    return {"colunas": {}, "apelidos": {}, "prefixos": {}}


def carregar(caminho: str | Path | None = None) -> Cadastro:
    caminho = caminho or config.caminho_destinos()
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
    except FileNotFoundError:
        dados = {}
    if dados and "colunas" not in dados:          # formato antigo: chave -> nome
        dados = {"colunas": {k: {"nome": v, "ultimo_uso": None} for k, v in dados.items()}}
    cadastro = vazio()
    for parte in cadastro:
        cadastro[parte] = dados.get(parte, {})
    return cadastro


def salvar(cadastro: Cadastro, caminho: str | Path | None = None) -> None:
    caminho = caminho or config.caminho_destinos()
    saida = {
        "_leia_me": ("colunas: nome fixo de cada coluna (edite só o 'nome'). "
                     "apelidos: descrição exata -> coluna. prefixos: descrição que começa "
                     "com -> coluna. Use as chaves sem acento, minúsculas e no singular."),
        **{parte: dict(sorted(cadastro[parte].items()))
           for parte in ("colunas", "apelidos", "prefixos")},
    }
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
        f.write("\n")


def resolver(descricao: str, cadastro: Cadastro) -> tuple[str, str | None] | None:
    """Descrição do lançamento -> (chave da coluna, grafia para cadastrar se
    for nova), ou None para linhas que não são destino ('Total', vazio)."""
    n = chave(descricao)
    if n in ("", "total"):
        return None
    raiz = chave(re.split(r"\s*[—–-]\s*", espacos_simples(descricao), maxsplit=1)[0])
    for base in (n, raiz):
        for prefixo, coluna in cadastro["prefixos"].items():
            if base.startswith(prefixo):
                return coluna, None
    for base in (n, raiz):
        if base in cadastro["apelidos"]:
            return cadastro["apelidos"][base], None
    # destino não previsto: coluna própria, com a parte antes de "—"/"–"
    limpo = re.split(r"\s*[—–]\s*", espacos_simples(descricao), maxsplit=1)[0].strip()
    limpo = limpo or espacos_simples(descricao)
    return chave(limpo), limpo


def limpar(cadastro: Cadastro, mes: str | None, meses: int = MESES_GUARDA) -> list[str]:
    """Apaga colunas sem uso há `meses` meses ou mais, contados a partir do mês
    da conferência (não da data do computador). Retorna os nomes apagados."""
    if not mes:
        return []
    limite = indice_mes(mes) - meses
    velhas = [k for k, c in cadastro["colunas"].items()
              if c.get("ultimo_uso") and indice_mes(c["ultimo_uso"]) <= limite]
    return [cadastro["colunas"].pop(k)["nome"] for k in velhas]
