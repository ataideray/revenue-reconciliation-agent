"""Gera dois meses fictícios (junho e julho/2026) em exemplo/2026-06/ e
exemplo/2026-07/: a planilha de entradas da tesouraria e os extratos do Cora
e da Stone, já em .xlsx.

Todos os nomes são inventados, de propósito com cara de inventados. Julho
foi montado para mostrar cada situação que o Elo trata:
  - recibos que batem com um Pix (a maioria) ou com dois Pix somados;
  - Pix pago pelo cônjuge (sobrenome em comum: sugestão de vínculo);
  - Pix de uma empresa, com valor único no mês (sugestão sem pista de nome);
  - recibo com o nome escrito errado (nome parecido);
  - dois recibos da mesma pessoa pagos por contas diferentes (uma divergência
    por recibo);
  - Pix devolvido à mesma pessoa (possível devolução).

Junho é menor e vem antes: com os dois meses fechados, o CF pode comparar
("julho foi melhor que junho?"). O Pix do marido para a esposa se repete nos
dois meses: confirmado em junho, volta em julho como "conta já confirmada".

Uso: python3 scripts/gerar_exemplo.py   (depois, veja o README)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from openpyxl import Workbook

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from conselho_fiscal.extratos import exportar_xlsx  # noqa: E402

# recibos que batem com um Pix do mesmo nome e valor: (nome, [(destino, valor)], banco)
EM_DIA = [
    ("AURORA CEU ABERTO", [("Anuidade", 120)], "Cora"),
    ("IARA MARE ALTA", [("Anuidade", 120), ("Cantina", 25)], "Stone"),
    ("OTAVIO PE DE SERRA", [("Anuidade", 120)], "Cora"),
    ("POLIANA FOLHA SECA", [("Bazar", 45)], "Stone"),
    ("RENATO RIO CLARO", [("Anuidade", 120)], "Cora"),
    ("SABRINA LUA CHEIA", [("Açaí", 18), ("Cantina", 12)], "Cora"),
    ("TIAGO VENTO NORTE", [("Anuidade", 120)], "Stone"),
    ("ULISSES PEDRA LISA", [("Fundo reforma", 250)], "Cora"),
    ("VALERIA FLOR DE LIS", [("Anuidade", 120)], "Cora"),
    ("WAGNER SOL POENTE", [("Promoção", 20)], "Stone"),
    ("YARA ARCO IRIS", [("Anuidade", 120)], "Cora"),
    ("ZELIA MATA ATLANTICA", [("Bazar", 60)], "Stone"),
    ("ADRIANO COQUEIRAL", [("Anuidade", 120)], "Cora"),
    ("BEATRIZ BEM TE VI", [("Açaí", 24)], "Cora"),
    ("CAIO JABUTICABA", [("Anuidade", 120)], "Stone"),
    ("DEBORA IPE AMARELO", [("Oferta", 100)], "Cora"),
    ("ENZO BAMBUZAL", [("Anuidade", 120)], "Cora"),
    ("FLAVIA ORQUIDEA", [("Cantina", 35)], "Stone"),
    ("GERSON TROVOADA", [("Anuidade", 120)], "Cora"),
    ("HELENA CAMELIA", [("Promoção", 40)], "Cora"),
    ("IGOR GRANITO", [("Anuidade", 120)], "Stone"),
    ("JULIANA MANGABA", [("Açaí", 30)], "Cora"),
    ("LEANDRO SAMAMBAIA", [("Anuidade", 120)], "Cora"),
    ("MIRIAM PITAYA", [("Bazar", 55)], "Stone"),
    ("NELSON JACARANDA", [("Anuidade", 120)], "Cora"),
    ("OLGA CASCATA", [("Oferta", 80)], "Stone"),
    ("PAMELA ALECRIM", [("Anuidade", 120)], "Cora"),
    ("RAFAEL QUARESMEIRA", [("Cantina", 22)], "Cora"),
    ("SAULO MANDACARU", [("Anuidade", 120)], "Stone"),
    ("TERESA CAJUEIRO", [("Açaí", 15)], "Cora"),
    ("VITOR SERRA AZUL", [("Anuidade", 120)], "Cora"),
    ("WANDA CORREDEIRA", [("Fundo reforma", 150)], "Stone"),
]

# os casos que viram divergência (ou mostram o casamento de dois Pix)
CASOS = [
    # dois Pix somados pagam um recibo
    ("BRENO VAGALUME", [("Anuidade", 120), ("Cantina", 30)],
     [("Stone", "BRENO VAGALUME", 100), ("Stone", "BRENO VAGALUME", 50)]),
    # o marido pagou o recibo da esposa
    ("CARLA JATOBA", [("Anuidade", 120)], [("Cora", "DANILO JATOBA", 120)]),
    # a empresa do associado pagou: valor único no mês
    ("EVANDRO PIRILAMPO", [("Oferta", 275)], [("Cora", "ESTUDIO LUMEN LTDA", 275)]),
    # nome escrito errado no recibo
    ("GISELE MARESIA", [("Bazar", 85)], [("Stone", "GISELLE MARESSIA", 85)]),
    # dois recibos, cada um pago por uma conta diferente
    ("HELIO SABIA", [("Anuidade", 90)], [("Cora", "MARTA SABIA", 90)]),
    ("HELIO SABIA", [("Almoço", 65)], [("Stone", "LOJA BOA VISTA", 65)]),
    # Pix a mais, devolvido depois
    ("KARINA TAMARINDO", [("Anuidade", 120)],
     [("Stone", "KARINA TAMARINDO", 120), ("Stone", "KARINA TAMARINDO", 300)]),
]
DEVOLUCOES = [("Stone", "KARINA TAMARINDO", 300)]       # saída para a mesma pessoa

# junho: menos recibos e valores menores que julho
EM_DIA_JUNHO = [
    ("AURORA CEU ABERTO", [("Anuidade", 120)], "Cora"),
    ("IARA MARE ALTA", [("Anuidade", 120)], "Stone"),
    ("RENATO RIO CLARO", [("Anuidade", 120)], "Cora"),
    ("SABRINA LUA CHEIA", [("Açaí", 12)], "Cora"),
    ("TIAGO VENTO NORTE", [("Anuidade", 120)], "Stone"),
    ("ULISSES PEDRA LISA", [("Fundo reforma", 200)], "Cora"),
    ("VALERIA FLOR DE LIS", [("Anuidade", 120)], "Cora"),
    ("YARA ARCO IRIS", [("Anuidade", 120)], "Cora"),
    ("ZELIA MATA ATLANTICA", [("Bazar", 40)], "Stone"),
    ("BEATRIZ BEM TE VI", [("Açaí", 18)], "Cora"),
    ("CAIO JABUTICABA", [("Anuidade", 120)], "Stone"),
    ("DEBORA IPE AMARELO", [("Oferta", 50)], "Cora"),
    ("FLAVIA ORQUIDEA", [("Cantina", 20)], "Stone"),
    ("GERSON TROVOADA", [("Anuidade", 120)], "Cora"),
    ("JULIANA MANGABA", [("Açaí", 15)], "Cora"),
    ("MIRIAM PITAYA", [("Bazar", 35)], "Stone"),
    ("PAMELA ALECRIM", [("Anuidade", 120)], "Cora"),
    ("WANDA CORREDEIRA", [("Fundo reforma", 100)], "Stone"),
]
CASOS_JUNHO = [
    # o mesmo marido de julho: confirmado aqui, vira "conta já confirmada" em julho
    ("CARLA JATOBA", [("Anuidade", 120)], [("Cora", "DANILO JATOBA", 120)]),
    # nome escrito diferente no recibo
    ("LUANA PITANGA", [("Bazar", 60)], [("Stone", "LUANNA PITTANGA", 60)]),
]

MESES = {"2026-06": (EM_DIA_JUNHO, CASOS_JUNHO, []),
         "2026-07": (EM_DIA, CASOS, DEVOLUCOES)}


def _data(dia: int, banco: str, mes: str) -> str:
    ano, mm = mes.split("-")
    return f"{dia:02d}/{mm}/{ano}" if banco == "Cora" else f"{dia:02d}/{mm}/{ano[2:]}"


def _transacao(banco: str, dia: int, nome: str, mes: str, entrada: float = 0.0,
               saida: float = 0.0) -> dict:
    prefixo = "Transf Pix recebida " if entrada else "Transf Pix enviada "
    return {"banco": banco, "data": _data(dia, banco, mes),
            "tipo": "Entrada" if entrada else "Saída",
            "nome": (prefixo + nome) if banco == "Cora" else nome, "documento": "",
            "categoria": "" if banco == "Cora" else "Transferência | Pix",
            "entrada": float(entrada), "saida": float(saida), "saldo": None}


def gerar(mes: str) -> None:
    em_dia, casos, devolucoes = MESES[mes]
    pasta = RAIZ / "exemplo" / mes
    pasta.mkdir(parents=True, exist_ok=True)
    recibos, extratos = [], {"Cora": [], "Stone": []}
    numero, dia = 1, 1

    def recibo(nome: str, itens: list[tuple[str, float]]) -> None:
        nonlocal numero
        recibos.append((_data(dia, "Cora", mes), f"{numero:04d}-2026", nome.title(), itens))
        numero += 1

    for nome, itens, banco in em_dia:
        recibo(nome, itens)
        extratos[banco].append(_transacao(banco, dia, nome, mes, sum(v for _, v in itens)))
        dia = dia % 28 + 1
    for nome, itens, pix in casos:
        recibo(nome, itens)
        for banco, quem, valor in pix:
            extratos[banco].append(_transacao(banco, dia, quem, mes, valor))
        dia = dia % 28 + 1
    for banco, quem, valor in devolucoes:
        extratos[banco].append(_transacao(banco, 29, quem, mes, saida=valor))

    _planilha(pasta / "entradas.xlsx", recibos)
    for banco, nome in (("Cora", "cora.xlsx"), ("Stone", "stone.xlsx")):
        # os extratos listam do mais recente para o mais antigo
        transacoes = sorted(extratos[banco], key=lambda t: t["data"][:2], reverse=True)
        exportar_xlsx(transacoes, banco, str(pasta / nome))
    print(f"{len(recibos)} recibos, {len(extratos['Cora'])} lançamentos no Cora e "
          f"{len(extratos['Stone'])} na Stone -> {os.path.relpath(pasta, RAIZ)}/")


def _planilha(caminho: Path, recibos: list[tuple]) -> None:
    """A planilha de entradas no formato da tesouraria: uma linha "Total" por
    recibo, uma por item, e a aba Resumo com os totais do mês."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Receitas"
    ws.append(["Data", "Número", "Nome", "Descrição", "Valor"])
    total = 0.0
    for data, numero, nome, itens in recibos:
        soma = sum(v for _, v in itens)
        total += soma
        ws.append([data, numero, nome, "Total", soma])
        for desc, valor in itens:
            ws.append([None, None, None, desc, valor])
        ws.append([None, None, None, None, None])
    wr = wb.create_sheet("Resumo")
    wr.append(["Indicador", "Valor"])
    for k, v in (("Total de Receitas", total), ("Recibos Emitidos", len(recibos)),
                 ("Recibos de Sócios", len(recibos)), ("Recibos de Não Sócios", 0)):
        wr.append([k, v])
    wb.save(caminho)


if __name__ == "__main__":
    for m in MESES:
        gerar(m)
