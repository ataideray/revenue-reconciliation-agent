"""Exportar transações para .xlsx (conferência manual) e ler de volta.

O pipeline não precisa desses arquivos: eles existem para quem quer olhar
o extrato lido em planilha (`conselho-fiscal extrato …`) e para o uso
manual com extrato já convertido, que sai como "não verificado".
"""

from __future__ import annotations

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from conselho_fiscal.comum.planilha import (
    BORDA,
    CINZA,
    FONTE,
    MOEDA,
    VERDE,
    VERMELHO,
    cabecalho,
    preencher,
)
from conselho_fiscal.comum.texto import norm_maiusculo
from conselho_fiscal.extratos.modelo import Banco, Transacao

# colunas de cada banco, como na planilha que a tesouraria conhece
COLUNAS = {
    "Cora": [("Data", "data"), ("Tipo", "tipo"), ("Histórico", "nome"),
             ("Documento", "documento"), ("Entrada", "entrada"), ("Saída", "saida")],
    "Stone": [("Data", "data"), ("Tipo", "tipo"), ("Categoria", "categoria"),
              ("Contraparte", "nome"), ("Entrada", "entrada"), ("Saída", "saida")],
}
LARGURAS = {"Cora": [12, 10, 40, 20, 14, 14], "Stone": [11, 10, 18, 42, 14, 14]}


def exportar_xlsx(transacoes: list[Transacao], banco: Banco, caminho: str) -> None:
    colunas = COLUNAS[banco]
    wb = Workbook()
    ws = wb.active
    ws.title = "Extrato"
    cabecalho(ws, [titulo for titulo, _ in colunas])
    for i, t in enumerate(transacoes, start=2):
        for j, (_titulo, campo) in enumerate(colunas, start=1):
            valor = t[campo]
            if campo in ("entrada", "saida") and valor == 0:
                valor = None                       # zero fica vazio, para clareza
            c = ws.cell(row=i, column=j, value=valor)
            c.font = Font(name=FONTE, size=10)
            c.border = BORDA
            if campo in ("entrada", "saida"):
                c.number_format = MOEDA
                c.alignment = Alignment(horizontal="right")
        ws.cell(row=i, column=2).fill = preencher(VERDE if t["tipo"] == "Entrada" else VERMELHO)

    linha_total = len(transacoes) + 2
    ws.cell(row=linha_total, column=4, value="TOTAL").font = Font(name=FONTE, bold=True, size=10)
    ws.cell(row=linha_total, column=4).alignment = Alignment(horizontal="right")
    for letra, coluna in (("E", 5), ("F", 6)):
        c = ws.cell(row=linha_total, column=coluna,
                    value=f"=SUM({letra}2:{letra}{len(transacoes) + 1})")
        c.font = Font(name=FONTE, bold=True, size=10)
        c.fill = preencher(CINZA)
        c.number_format = MOEDA
        c.alignment = Alignment(horizontal="right")
    for j, largura in enumerate(LARGURAS[banco], start=1):
        ws.column_dimensions[get_column_letter(j)].width = largura
    ws.freeze_panes = "A2"
    wb.save(caminho)


def ler_xlsx(caminho: str, banco: Banco) -> list[Transacao]:
    """Lê um extrato já convertido (formato de `exportar_xlsx`)."""
    ws = load_workbook(caminho, data_only=True).active
    titulos = {norm_maiusculo(ws.cell(1, c).value): c for c in range(1, ws.max_column + 1)}

    def celula(linha: int, titulo: str):
        coluna = titulos.get(norm_maiusculo(titulo))
        return ws.cell(linha, coluna).value if coluna else None

    def numero(v) -> float:
        return float(v) if isinstance(v, (int, float)) else 0.0

    campo_nome = "Histórico" if banco == "Cora" else "Contraparte"
    transacoes: list[Transacao] = []
    for r in range(2, ws.max_row + 1):
        nome = celula(r, campo_nome)
        if not nome or str(nome).strip().upper() == "TOTAL":
            continue
        entrada, saida = numero(celula(r, "Entrada")), numero(celula(r, "Saída"))
        transacoes.append({
            "banco": banco, "data": celula(r, "Data"),
            "tipo": celula(r, "Tipo") or ("Entrada" if entrada else "Saída"),
            "nome": str(nome), "documento": celula(r, "Documento") or "",
            "categoria": celula(r, "Categoria") or "",
            "entrada": entrada, "saida": saida, "saldo": None,
        })
    return transacoes
