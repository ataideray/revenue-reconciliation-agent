"""Quanto entrou por destino (açaí, bazar, anuidade…) nos meses
fechados, para as perguntas do CF (2026-10-22).

Os valores vêm dos recibos da planilha de entradas da tesouraria, com a
mesma leitura do pipeline (`lancamentos.pivotar`): cada item do recibo vai
para a coluna do seu destino. São os valores lançados nos recibos, não os
do extrato. As contas (soma, variação, média) são feitas aqui; a IA só
escreve a resposta com elas.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from conselho_fiscal.agente.comparacao import linha
from conselho_fiscal.agente.consultas import mes_extenso
from conselho_fiscal.cadastros import destinos
from conselho_fiscal.comum.valores import brl
from conselho_fiscal.receitas import lancamentos

Totais = dict[str, tuple[float, int]]       # destino -> (valor, recibos com ele)
# vai para o CF (a IA costuma repetir); que as contas já vêm feitas, a IA sabe pelas instruções
ORIGEM = "_Valores lançados nos recibos do registro de receitas da tesouraria._"


def totais(entradas: str | Path, cadastro: destinos.Cadastro) -> Totais:
    """Valor e número de recibos de cada destino do mês, na ordem da planilha."""
    # cópia: a consulta não pode mexer no cadastro (destino novo, último uso)
    p = lancamentos.pivotar(lancamentos.carregar(str(entradas)), copy.deepcopy(cadastro))
    resultado: Totais = {}
    for c in p["colunas"]:
        valores = [r[c] for r in p["linhas"] if r[c]]
        resultado[c] = (round(sum(valores), 2), len(valores))
    return resultado


def _palavras(texto: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", destinos.chave(texto)))


def achar(nome: str, nomes: list[str]) -> list[str]:
    """Os destinos que têm todas as palavras do que o CF escreveu, sem
    acento e no singular ("açaís" acha "Açaí"; "fundo" acha "Fundo reforma",
    "Fundo reforma - Venda das Camisetas" e "Fundo - Lâmpadas"; a resposta
    mostra cada um e a soma)."""
    alvo = _palavras(nome)
    return [n for n in nomes if alvo <= _palavras(n)] if alvo else []


def citado(texto: str, nomes: list[str]) -> str | None:
    """Sem IA: o destino com todas as palavras no texto ("quanto deu o açaí
    em julho?" -> "Açaí"); havendo vários, o de mais palavras."""
    palavras = _palavras(texto)
    achados = [n for n in nomes if _palavras(n) and _palavras(n) <= palavras]
    return max(achados, key=lambda n: len(_palavras(n))) if achados else None


def _recibos(n: int) -> str:
    return f"{n} recibo" + ("s" if n != 1 else "")


def _todos(mes: str, t: Totais) -> list[str]:
    linhas = [f"*Receitas por destino — {mes_extenso(mes)}*"]
    linhas += [f"• {d}: {brl(v)} ({_recibos(n)})"
               for d, (v, n) in sorted(t.items(), key=lambda x: -x[1][0])]
    linhas.append(f"• Total: {brl(round(sum(v for v, _ in t.values()), 2))}")
    return linhas


def texto(nome: str, meses: list[tuple[str, Totais]]) -> str:
    """Os dados da resposta. Sem `nome`: todos os destinos de cada mês. Com
    ele: o destino em cada mês e, com mais de um mês, a variação, a soma e a
    média; achando mais de um destino, também a soma deles."""
    meses = sorted(meses)
    nomes_meses = [mes_extenso(m) for m, _ in meses]
    if not nome:
        partes = ["\n".join(_todos(m, t)) for m, t in meses]
        return "\n\n".join(partes + [ORIGEM])
    achados = list(dict.fromkeys(d for _, t in meses for d in achar(nome, list(t))))
    if not achados:
        linhas = [f"*Nenhum recibo com o destino \"{nome}\"* em {', '.join(nomes_meses)}."]
        linhas += [f"*Destinos de {mes_extenso(m)}:* {', '.join(t) or 'nenhum'}." for m, t in meses]
        return "\n".join(linhas + [ORIGEM])

    def valor(t: Totais, ds: list[str]) -> tuple[float, int]:
        return (round(sum(t.get(d, (0.0, 0))[0] for d in ds), 2),
                sum(t.get(d, (0.0, 0))[1] for d in ds))

    grupos = [(d, [d]) for d in achados]
    if len(achados) > 1:
        grupos.append((" + ".join(achados), achados))
    linhas = [f"*{nome.strip().capitalize()} — {', '.join(nomes_meses)}*"]
    for rotulo, ds in grupos:
        por_mes = [valor(t, ds) for _, t in meses]
        if len(meses) == 1:
            v, n = por_mes[0]
            linhas.append(f"• {rotulo}: {brl(v)} ({_recibos(n)})")
        else:
            linhas.append(linha(rotulo, nomes_meses, [v for v, _ in por_mes], True)
                          + " · recibos: " + " → ".join(str(n) for _, n in por_mes))
    return "\n".join(linhas + [ORIGEM])
