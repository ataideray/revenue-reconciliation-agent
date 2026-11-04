"""Avaliação do interpretador com respostas escritas para teste
(exemplo/casos_ia_AAAA-MM.json) sobre as divergências de um mês. Usado por
scripts/avaliar_ia.py.

Cada caso é comparado com o que a IA entendeu. O erro mais grave é a IA
confirmar uma sugestão que a tesouraria não confirmou ("CRÍTICO"): mesmo com
o "Entendi" antes de gravar, ele não pode acontecer. Errar para o lado
cauteloso (deixar de confirmar, pedir de novo) é menos grave.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from conselho_fiscal.agente import divergencias as dv
from conselho_fiscal.agente.ia import Contexto, Interpretacao

CRITICO, ERRO, AVISO = "CRÍTICO", "erro", "aviso"
GRAVIDADES = (CRITICO, ERRO, AVISO)


@dataclass(frozen=True)
class Caso:
    pessoa: str
    texto: str
    confirmar_aceitos: tuple[frozenset[int], ...]
    suficiente: bool | None
    adiar: bool
    explicacao_contem: tuple[str, ...]
    explicacao_vazia: bool


def carregar_casos(caminho: str | Path) -> list[Caso]:
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    casos = []
    for c in dados["casos"]:
        aceitos = c["confirmar_aceitos"] if "confirmar_aceitos" in c else [c["confirmar"]]
        casos.append(Caso(c["pessoa"], c["texto"], tuple(frozenset(a) for a in aceitos),
                          c.get("suficiente"), c.get("adiar", False),
                          tuple(c.get("explicacao_contem", ())),
                          c.get("explicacao_vazia", False)))
    return casos


def contexto(caso: Caso, resultado: dict[str, Any]) -> Contexto:
    """O contexto que o agente montaria na primeira pergunta da divergência
    (sem confirmações anteriores)."""
    divs = resultado["divergencias"]
    por_id = {d["id"]: d for d in divs}
    partes = [d for d in divs if d["pessoa"] == caso.pessoa]
    if not partes:
        raise ValueError(f"divergência não encontrada: {caso.pessoa}")
    d = partes[0] if len(partes) == 1 else _juntar(partes)
    return Contexto(d, dv.opcoes(d, [], por_id), [], caso.texto, dv.nomes(divs))


def _juntar(partes: list[dict[str, Any]]) -> dict[str, Any]:
    """As divergências de uma pessoa, uma por recibo (2026-10-26), juntas como
    eram quando os casos foram escritos ("todas menos a 1", "confirmo as
    duas"): avalia a IA com várias sugestões de uma vez."""
    d = dict(partes[0], recibo=None, id=partes[0]["id"].rsplit("-", 2)[0])
    for k in ("total_recibos", "total_extrato", "diferenca"):
        d[k] = round(sum(x[k] for x in partes), 2)
    for k in ("recibos_sem_pix", "pix_sem_recibo", "sugestoes_vinculo", "devolucoes_possiveis"):
        d[k] = [i for x in partes for i in x[k]]
    return d


def comparar(caso: Caso, it: Interpretacao, n_sugestoes: int) -> list[tuple[str, str]]:
    """(gravidade, descrição) de cada diferença entre o esperado e o
    entendido. Lista vazia: acertou."""
    problemas = []
    obtido = frozenset(it.confirmar)
    validos = frozenset(n for n in obtido if 1 <= n <= n_sugestoes)
    permitidos = frozenset().union(*caso.confirmar_aceitos)
    if validos - permitidos:
        problemas.append((CRITICO, f"confirmou {sorted(validos - permitidos)} sem a tesouraria "
                                   "confirmar"))
    elif validos not in caso.confirmar_aceitos:
        esperado = " ou ".join(str(sorted(a)) for a in caso.confirmar_aceitos)
        problemas.append((ERRO, f"confirmou {sorted(validos)}, esperado {esperado}"))
    if obtido - validos:
        problemas.append((AVISO, f"número fora das sugestões: {sorted(obtido - validos)} "
                                 "(o agente pede de novo)"))
    if caso.suficiente is not None and it.suficiente != caso.suficiente:
        problemas.append((ERRO, f"suficiente={it.suficiente}, esperado {caso.suficiente}"))
    if it.adiar != caso.adiar:
        problemas.append((ERRO, f"adiar={it.adiar}, esperado {caso.adiar}"))
    explicacao = it.explicacao.lower()
    faltam = [p for p in caso.explicacao_contem if p.lower() not in explicacao]
    if faltam:
        problemas.append((AVISO, f"explicação sem {faltam}: {it.explicacao!r}"))
    if caso.explicacao_vazia and it.explicacao.strip():
        problemas.append((AVISO, f"explicação deveria ser vazia: {it.explicacao!r}"))
    return problemas


def mais_grave(problemas: list[tuple[str, str]]) -> str:
    """A gravidade do caso: a do problema mais grave, ou "ok"."""
    return min((g for g, _ in problemas), key=GRAVIDADES.index, default="ok")
