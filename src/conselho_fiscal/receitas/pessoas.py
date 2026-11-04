"""Nomes de pessoas: quando dois nomes são da MESMA pessoa, e o agrupamento
de recibos e Pix por pessoa.

Só variações do nome da mesma pessoa são juntadas automaticamente (corte do
nome pelo banco, acentos, ordem dos nomes). Nomes diferentes nunca são
ligados aqui: isso é sugestão, confirmada com a tesouraria (conciliacao.py).
"""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, TypedDict

from conselho_fiscal.comum.texto import strip_acentos

PREPOSICOES = {"DE", "DA", "DO", "DAS", "DOS", "E"}
SUFIXOS = {"JR", "JUNIOR", "FILHO", "NETO", "LTDA"}
# termos de razão social e rótulos que não servem como pista de nome
GENERICOS = {
    "LTDA", "ME", "EIRELI", "COMERCIO", "SERVICOS", "SERVICO", "REALIZACOES",
    "REALIZACAO", "EMPREENDIMENTOS", "SOLUCOES", "SOLUCAO", "CIA", "GRUPO",
    "CONSULTORIA", "ASSESSORIA", "COMERCIAL", "INDUSTRIA", "REPRESENTACOES",
    "PARTICIPACOES", "HOLDING", "NEGOCIOS", "TESOURARIA", "GERAL", "ASSOCIACAO",
    "INSTITUTO", "SEDE",
    # rótulo usado para rendimento com valor suspeito (ver conciliacao.py)
    "RENDIMENTO", "RENDIMENTOS", "SUSPEITO", "REVISAR", "VALOR",
}
# prefixos que os extratos põem antes do nome da contraparte
PREFIXO_EXTRATO_RE = re.compile(
    r"^\s*(Transf(er[êe]ncia)?\s+Pix\s+(recebida|enviada)|Pix\s+(recebid[ao]|enviad[ao])|"
    r"Transfer[êe]ncia\s*\|\s*Pix|Pgto\s+QR\s+Code\s+Pix|Boleto\s+pago)\s*",
    re.IGNORECASE,
)


class Pessoa(TypedDict):
    chave: str
    nome: str                   # o nome mais completo encontrado, para exibição
    nomes: set[str]             # todas as grafias (recibos e extratos)
    recibos: list[Any]
    entradas: list[dict[str, Any]]
    tot_recibo: float
    tot_cora: float
    tot_stone: float
    primeira_ordem: int | None  # posição do 1º Pix no extrato (Cora, depois Stone)


def limpar_nome_extrato(nome: str) -> str:
    """'Transf Pix recebida FULANO' -> 'FULANO'."""
    return PREFIXO_EXTRATO_RE.sub("", str(nome)).strip()


def palavras(nome: str) -> list[str]:
    """Palavras do nome em maiúsculas, sem acento, preposições e sufixos."""
    s = re.sub(r"[^A-Z ]", " ", strip_acentos(nome).upper())
    return [p for p in s.split() if p not in PREPOSICOES and p not in SUFIXOS]


def nome_compacto(nome: str) -> str:
    """Nome em maiúsculas, sem acento, com a ordem das letras mantida."""
    s = re.sub(r"[^A-Z ]", " ", strip_acentos(nome).upper())
    return re.sub(r"\s+", " ", s).strip()


def tokens_relevantes(nome: str) -> set[str]:
    """Palavras úteis como pista de nome (4+ letras, sem termos genéricos)."""
    return {p for p in palavras(nome) if p not in GENERICOS and len(p) >= 4}


def mesmo_nome(a: str, b: str) -> bool:
    """Se dois nomes provavelmente são da mesma pessoa. Dois sinais seguros:

    1) um é PREFIXO exato do outro (mín. 5 letras): o Cora corta o nome num
       tamanho fixo ('NAYLA ESTER DA VER' -> 'NAYLA ESTER DA VERDE ORVALHO');
    2) DUAS ou mais palavras em comum, quando ambos têm 2+ palavras
       ('NAIRA MANJERICAO' × 'NAIRA CAPIVARA MANJERICAO'); só o primeiro nome
       em comum não basta ('NOELI VERDE' × 'NOELI LARANJAL').
    Nomes de uma palavra só casam se forem idênticos.
    """
    na, nb = nome_compacto(a), nome_compacto(b)
    if not na or not nb:
        return False
    if (na.startswith(nb) or nb.startswith(na)) and min(len(na), len(nb)) >= 5:
        return True
    ta, tb = set(palavras(a)), set(palavras(b))
    if not ta or not tb:
        return False
    if len(ta) >= 2 and len(tb) >= 2:
        return len(ta & tb) >= 2
    return ta == tb


def nomes_parecidos(a: str, b_nomes: set[str]) -> list[str]:
    """Pares de palavras com grafia parecida (5+ letras, similaridade >= 0,85),
    ex.: 'Girasol ≈ Girassol'. Usado só como critério de SUGESTÃO."""
    da_pessoa = set().union(*(tokens_relevantes(n) for n in b_nomes))
    return sorted(f"{x.title()} ≈ {y.title()}"
                  for x in tokens_relevantes(a) for y in da_pessoa
                  if x != y and min(len(x), len(y)) >= 5
                  and SequenceMatcher(None, x, y).ratio() >= 0.85)


class _UnionFind:
    def __init__(self) -> None:
        self.pai: dict[str, str] = {}

    def raiz(self, x: str) -> str:
        self.pai.setdefault(x, x)
        r = x
        while self.pai[r] != r:
            r = self.pai[r]
        while self.pai[x] != r:
            self.pai[x], x = r, self.pai[x]
        return r

    def unir(self, a: str, b: str) -> None:
        ra, rb = self.raiz(a), self.raiz(b)
        if ra != rb:
            self.pai[ra] = rb


def agrupar(recibos: list[Any], entradas: list[dict[str, Any]]) -> dict[str, Pessoa]:
    """Agrupa recibos e Pix por pessoa, usando mesmo_nome().

    Só compara nomes com a mesma 1ª palavra (mesmo_nome já exige que o
    início bata). `entradas` vem na ordem do extrato (Cora, depois Stone).
    """
    distintos = sorted({r["origem"] for r in recibos} | {e["nome"] for e in entradas})
    grupos = defaultdict(list)
    for nome in distintos:
        ps = palavras(nome)
        grupos[ps[0] if ps else nome].append(nome)
    uf = _UnionFind()
    for nome in distintos:
        uf.raiz(nome)
    for lista in grupos.values():
        for i in range(len(lista)):
            for j in range(i + 1, len(lista)):
                if mesmo_nome(lista[i], lista[j]):
                    uf.unir(lista[i], lista[j])

    pessoas: dict[str, Pessoa] = {}

    def pessoa_de(nome: str) -> Pessoa:
        raiz = uf.raiz(nome)
        if raiz not in pessoas:
            pessoas[raiz] = {"chave": raiz, "nome": nome, "nomes": set(), "recibos": [],
                             "entradas": [], "tot_recibo": 0.0, "tot_cora": 0.0,
                             "tot_stone": 0.0, "primeira_ordem": None}
        p = pessoas[raiz]
        p["nomes"].add(nome)
        if len(nome) > len(p["nome"]):
            p["nome"] = nome
        return p

    for rec in recibos:
        p = pessoa_de(rec["origem"])
        p["recibos"].append(rec)
        p["tot_recibo"] += rec["valor"]
    for ordem, ent in enumerate(entradas):
        p = pessoa_de(ent["nome"])
        p["tot_cora" if ent["banco"] == "Cora" else "tot_stone"] += ent["valor"]
        p["entradas"].append({"ordem": ordem, "valor": ent["valor"], "banco": ent["banco"],
                              "data": ent.get("data"), "nome": ent["nome"],
                              "pagina": ent.get("pagina"), "cnpj": ent.get("cnpj", False)})
        if p["primeira_ordem"] is None:
            p["primeira_ordem"] = ordem
    return pessoas
