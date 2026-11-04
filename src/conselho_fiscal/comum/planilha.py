"""Estilos comuns das planilhas geradas (openpyxl)."""

from __future__ import annotations

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

FONTE = "Arial"
AZUL = "1F4E78"
VERDE = "E2EFDA"
VERMELHO = "FCE4E4"
AMARELO = "FFF2CC"
CINZA = "D9D9D9"
BRANCO = "FFFFFF"
MOEDA = '"R$" #,##0.00'
BORDA = Border(bottom=Side(style="thin", color="BFBFBF"))


def cabecalho(ws, titulos: list[str], linha: int = 1) -> None:
    """Escreve uma linha de cabeçalho azul com texto branco."""
    for j, titulo in enumerate(titulos, start=1):
        c = ws.cell(row=linha, column=j, value=titulo)
        c.font = Font(name=FONTE, bold=True, color=BRANCO, size=11)
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(horizontal="center", vertical="center")


def preencher(cor: str) -> PatternFill:
    return PatternFill("solid", fgColor=cor)
