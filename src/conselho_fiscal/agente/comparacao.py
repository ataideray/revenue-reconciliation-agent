"""Relação entre meses fechados: soma, média, diferença e variação de cada
indicador, e as pessoas com divergência em mais de um mês (2026-10-13).

A IA não faz conta. Quando o CF pergunta sobre mais de um mês ("a soma da
receita de junho e julho", "julho foi melhor que junho?"), os números que
relacionam os meses são calculados aqui e vão prontos nos dados; a IA só
escolhe quais citar.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from conselho_fiscal.agente.consultas import mes_extenso
from conselho_fiscal.comum.texto import norm_maiusculo
from conselho_fiscal.comum.valores import brl, valor_extrato

Mes = tuple[dict[str, Any], list[dict[str, Any]]]    # (estado do mês, conferências do JSON)
MAX_MESES = 12


def _total_receitas(est: dict[str, Any], conferencias: list[dict[str, Any]]) -> float | None:
    for c in conferencias:
        if c["verificacao"].startswith("Total de receitas"):
            try:
                return valor_extrato(c["encontrado"].removeprefix("R$").strip())
            except ValueError:
                return None
    return None


def _soma_itens(chave: str) -> Callable[[dict[str, Any], list], float]:
    return lambda est, _: round(sum(i["valor"] for d in est["divergencias"] for i in d[chave]),
                                2)


Indicador = tuple[str, Callable[[dict[str, Any], list], float | None], bool]
# grupos de (rótulo, valor do mês ou None se o mês não tiver o dado, é dinheiro)
GRUPOS: list[tuple[str, list[Indicador]]] = [
    ("Receitas", [("Total no registro de receitas", _total_receitas, True)]),
    ("Pix recebidos no Cora", [
        ("Valor", lambda est, _: est["resumo"].get("valor_cora"), True),
        ("Quantidade", lambda est, _: est["resumo"]["ent_cora"], False)]),
    ("Pix recebidos na Stone", [
        ("Valor", lambda est, _: est["resumo"].get("valor_stone"), True),
        ("Quantidade", lambda est, _: est["resumo"]["ent_stone"], False)]),
    ("Recibos", [
        ("Emitidos", lambda est, _: est["resumo"]["recibos"], False),
        ("Conformes", lambda est, _: est["resumo"]["conformes"], False),
        ("Divergentes", lambda est, _: est["resumo"]["divergentes"], False)]),
    ("Divergências", [
        ("Quantidade", lambda est, _: len(est["divergencias"]), False),
        ("Recibos sem Pix (soma)", _soma_itens("recibos_sem_pix"), True),
        ("Pix sem recibo (soma)", _soma_itens("pix_sem_recibo"), True)]),
]


def _numero(v: float, dinheiro: bool) -> str:
    if dinheiro:
        return brl(v)
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}".replace(".", ",")


def _variacao(antes: float, depois: float, dinheiro: bool) -> str:
    d = round(depois - antes, 2)
    if abs(d) < 0.005:
        return "igual"
    texto = f"{'aumento' if d > 0 else 'queda'} de {_numero(abs(d), dinheiro)}"
    if antes:
        texto += f" ({d / antes * 100:+.1f}%)".replace(".", ",")
    return texto


def linha(rotulo: str, nomes: list[str], valores: list[float | None], dinheiro: bool) -> str:
    """'• Total na planilha: R$ 1.000,00 (junho/2026) → R$ 1.200,00 (julho/2026):
    aumento de R$ 200,00 (+20,0%) · soma … · média …'."""
    if any(v is None for v in valores):
        sem = [n for n, v in zip(nomes, valores) if v is None]
        return f"• {rotulo}: sem o dado em {', '.join(sem)} (mês conferido antes desse dado)"
    texto = f"• {rotulo}: " + " → ".join(f"{_numero(v, dinheiro)} ({n})"
                                         for n, v in zip(nomes, valores))
    seguidos = list(zip(zip(nomes, valores), zip(nomes[1:], valores[1:])))
    if len(seguidos) == 1:
        texto += f": {_variacao(valores[0], valores[1], dinheiro)}"
    else:
        texto += " · " + "; ".join(f"{n1} → {n2}: {_variacao(v1, v2, dinheiro)}"
                                    for (n1, v1), (n2, v2) in seguidos)
        if max(valores) != min(valores):
            texto += (f" · maior: {nomes[valores.index(max(valores))]}; menor: "
                      f"{nomes[valores.index(min(valores))]}")
    soma = round(sum(valores), 2)
    media = round(soma / len(valores), 2 if dinheiro else 1)
    return texto + f" · soma {_numero(soma, dinheiro)} · média {_numero(media, dinheiro)}"


def recorrentes(meses: list[dict[str, Any]]) -> list[str]:
    """'NOME (junho/2026, julho/2026)' para quem teve divergência em mais de um mês."""
    por_nome: dict[str, tuple[str, list[str]]] = {}
    for est in meses:
        for d in est["divergencias"]:
            nome, lista = por_nome.setdefault(norm_maiusculo(d["pessoa"]), (d["pessoa"], []))
            if mes_extenso(est["mes"]) not in lista:
                lista.append(mes_extenso(est["mes"]))
    return [f"{nome} ({', '.join(lista)})" for nome, lista in por_nome.values() if len(lista) > 1]


def comparar(meses: list[Mes]) -> str:
    """Os indicadores de cada mês, em grupos, com a diferença e a variação
    entre meses seguidos, a soma e a média (e o maior e o menor, a partir de
    3 meses), e quem teve divergência em mais de um mês."""
    meses = sorted(meses, key=lambda m: m[0]["mes"])[-MAX_MESES:]
    nomes = [mes_extenso(est["mes"]) for est, _ in meses]
    linhas = [f"*Comparação: {', '.join(nomes[:-1])} e {nomes[-1]}*",
              "_(meses fechados; diferença, variação, soma e média já calculadas)_"]
    for grupo, indicadores in GRUPOS:
        linhas += ["", f"*{grupo}*"]
        linhas += [linha(rotulo, nomes, [valor(est, conf) for est, conf in meses], dinheiro)
                   for rotulo, valor, dinheiro in indicadores]
    rec = recorrentes([est for est, _ in meses])
    linhas += ["", "*Com divergência em mais de um mês*"]
    linhas += [f"• {r}" for r in rec] or ["• ninguém"]
    return "\n".join(linhas)
