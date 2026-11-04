"""Planilha final para o Conselho Fiscal (3 abas).

1. Receitas (reordenada): os recibos na ordem real dos extratos, com a
   compatibilidade e a sugestão de vínculo de cada recibo (ou a nota da
   tesouraria, quando houver).
2. Conferência por Pessoa: totais por pessoa.
3. Divergências: conferências automáticas no topo e uma linha por pessoa
   que não fecha, com sugestões (vínculo ou devolução) e nota da tesouraria.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from conselho_fiscal.comum.planilha import (
    AMARELO,
    BORDA,
    CINZA,
    FONTE,
    MOEDA,
    VERDE,
    VERMELHO,
    cabecalho,
    preencher,
)
from conselho_fiscal.comum.valores import brl
from conselho_fiscal.extratos.modelo import Verificacao
from conselho_fiscal.receitas.conciliacao import (
    detalhar_divergencias,
    div_do_recibo,
    nota_da_pessoa,
    onde,
    status_pessoa,
    texto_devolucao,
    texto_sugestao,
)
from conselho_fiscal.receitas.lancamentos import COLUNAS_FIXAS, Recibo
from conselho_fiscal.receitas.pessoas import Pessoa

GRUPOS_CONFERENCIA = (
    # grupo, título, aviso quando há alerta, descrição quando tudo OK
    ("extratos", "LEITURA DOS EXTRATOS",
     "parte das divergências abaixo pode ser erro de leitura, não de lançamento",
     "totais e saldos do Cora e da Stone"),
    ("planilha", "PLANILHA DA TESOURARIA",
     "a aba Resumo, os totais dos recibos ou os rendimentos não batem",
     "aba Resumo, total de cada recibo e rendimentos × extratos"),
)
COLUNAS_CONFERENCIA = ["compatibilidade_extrato", "Sugestão de vínculo"]
COM_NOTA = " - nota da tesouraria na aba Divergências"


def cor_status(status: str) -> str:
    if status == "OK":
        return VERDE
    if status.startswith("Sem extrato"):
        return VERMELHO
    return AMARELO


def gerar(caminho: str, colunas_recurso: list[str], recibos_ordenados: list[tuple[Pessoa, Recibo]],
          pessoas_ordenadas: list[Pessoa], sugestoes: list[dict[str, Any]],
          verificacoes: list[Verificacao], devolucoes: list[dict[str, Any]],
          notas: dict[str, str] | None = None) -> None:
    wb = Workbook()
    _aba_receitas(wb.active, COLUNAS_FIXAS + colunas_recurso, recibos_ordenados, sugestoes,
                  notas or {})
    _aba_pessoas(wb.create_sheet("Conferência por Pessoa"), pessoas_ordenadas, notas or {})
    _aba_divergencias(wb.create_sheet("Divergências"), pessoas_ordenadas, sugestoes,
                      verificacoes, notas, devolucoes)
    wb.save(caminho)


def _aba_receitas(ws, titulos: list[str], recibos_ordenados, sugestoes,
                  notas: dict[str, str]) -> None:
    ws.title = "Receitas (reordenada)"
    n_orig = len(titulos)
    cabecalho(ws, titulos + COLUNAS_CONFERENCIA)
    por_recibo = defaultdict(list)
    for s in sugestoes:
        por_recibo[s["_rec"]].append(s)

    r = 2
    for p, rec in recibos_ordenados:
        for j, val in enumerate(rec["celulas"], start=1):
            v = None if (j >= 3 and isinstance(val, (int, float)) and val == 0) else val
            c = ws.cell(row=r, column=j, value=v)
            c.font = Font(name=FONTE, size=10)
            c.border = BORDA
            if j >= 3:
                c.number_format = MOEDA
                c.alignment = Alignment(horizontal="right")
        compat = rec.get("compat", "Divergente")
        sugestao = "; ".join(f"Pix de \"{s['nome_no_extrato']}\" ({s['pix_banco']}, "
                             f"{s['pix_data']}) — {s['criterio']}" for s in por_recibo[id(rec)])
        # recibo sem Pix já explicado pela tesouraria: a nota substitui a sugestão
        nota = notas.get(div_do_recibo(p, rec)) if compat == "Divergente" else None
        sugestao = nota or sugestao
        for k, val in enumerate([compat, sugestao]):
            c = ws.cell(row=r, column=n_orig + 1 + k, value=val)
            c.font = Font(name=FONTE, size=10)
            c.border = BORDA
        ws.cell(row=r, column=n_orig + 1).fill = preencher(
            VERDE if compat.startswith("Conforme") else AMARELO)
        if sugestao:
            ws.cell(row=r, column=n_orig + 2).fill = preencher(AMARELO)
        r += 1

    ws.cell(row=r, column=1, value="TOTAL").font = Font(name=FONTE, bold=True, size=10)
    for j in range(3, n_orig + 1):
        letra = get_column_letter(j)
        c = ws.cell(row=r, column=j, value=f"=SUM({letra}2:{letra}{r - 1})")
        c.font = Font(name=FONTE, bold=True, size=10)
        c.number_format = MOEDA
        c.alignment = Alignment(horizontal="right")
        c.fill = preencher(CINZA)

    ws.column_dimensions["A"].width = 11
    ws.column_dimensions["B"].width = 36
    for j in range(3, n_orig + 1):
        ws.column_dimensions[get_column_letter(j)].width = max(13, len(str(titulos[j - 1])) + 2)
    for k, largura in enumerate([22, 60]):
        ws.column_dimensions[get_column_letter(n_orig + 1 + k)].width = largura
    ws.freeze_panes = "C2"


def _aba_pessoas(ws, pessoas_ordenadas: list[Pessoa], notas: dict[str, str]) -> None:
    cabecalho(ws, ["Ordem", "Pessoa", "Total Recibos", "Recebido Cora",
                   "Recebido Stone", "Total Extrato", "Diferença", "Status"])
    for r, p in enumerate(pessoas_ordenadas, start=2):
        st, dif = status_pessoa(p)
        # divergência comentada pela tesouraria: o status aponta para a nota
        texto_st = st + COM_NOTA if st != "OK" and nota_da_pessoa(p, notas) else st
        valores = [r - 1, p["nome"], round(p["tot_recibo"], 2), round(p["tot_cora"], 2),
                   round(p["tot_stone"], 2), round(p["tot_cora"] + p["tot_stone"], 2), dif,
                   texto_st]
        for j, v in enumerate(valores, start=1):
            c = ws.cell(row=r, column=j, value=v)
            c.font = Font(name=FONTE, size=10)
            c.border = BORDA
            if 3 <= j <= 7:
                c.number_format = MOEDA
                c.alignment = Alignment(horizontal="right")
        ws.cell(row=r, column=8).fill = preencher(cor_status(st))
    larguras = [7, 36, 14, 14, 14, 14, 12, 64 if notas else 22]
    for j, largura in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(j)].width = largura
    ws.freeze_panes = "A2"


def escrever_conferencias(ws, verificacoes: list[Verificacao]) -> int:
    """Topo da aba Divergências: uma linha por grupo de conferência (verde se
    OK; vermelha com uma linha por alerta, dizendo onde conferir; amarela se
    não verificada). Nunca bloqueia. Retorna a próxima linha livre."""
    r = 1
    for grupo, nome, aviso, descricao in GRUPOS_CONFERENCIA:
        vs = [v for v in verificacoes if v.get("grupo", "extratos") == grupo]
        alertas = [v for v in vs if v["status"] == "ALERTA"]
        nao_verif = [v for v in vs if v["status"] == "NÃO VERIFICADO"]
        n_ok = len(vs) - len(alertas) - len(nao_verif)
        if not vs:
            titulo, cor, cor_texto = f"{nome}: não verificada", AMARELO, "7F6000"
        elif alertas:
            titulo = f"{nome}: {len(alertas)} ALERTA(S) — {aviso}"
            cor, cor_texto = VERMELHO, "9C0006"
        elif nao_verif:
            titulo = f"{nome}: {n_ok} verificação(ões) OK, {len(nao_verif)} não verificada(s)"
            cor, cor_texto = AMARELO, "7F6000"
        else:
            titulo = f"{nome}: OK — {n_ok} verificações conferidas ({descricao})"
            cor, cor_texto = VERDE, "375623"
        ws.cell(row=r, column=1, value=titulo).font = Font(
            name=FONTE, bold=True, size=10, color=cor_texto)
        for j in range(1, 6):
            ws.cell(row=r, column=j).fill = preencher(cor)
        r += 1
        for v in alertas + nao_verif:
            texto = f"[{v['extrato']}] {v['verificacao']}"
            if v["status"] == "ALERTA":
                r_esp, r_enc = v.get("rotulos", ("esperado", "encontrado"))
                texto += f" — {r_esp}: {v['esperado']}; {r_enc}: {v['encontrado']}"
            if v["detalhe"]:
                texto += f". {v['detalhe']}"
            ws.cell(row=r, column=1, value=texto).font = Font(name=FONTE, size=10, color=cor_texto)
            r += 1
    return r + 1


def _aba_divergencias(ws, pessoas_ordenadas, sugestoes, verificacoes, notas, devolucoes) -> None:
    r = escrever_conferencias(ws, verificacoes) + 1
    ws.cell(row=r, column=1, value="DIVERGÊNCIAS QUE PRECISAM DE REVISÃO").font = Font(
        name=FONTE, bold=True, size=12, color="9C0006")
    r += 1
    ws.cell(row=r, column=1,
            value="Nenhum vínculo entre nomes diferentes nem devolução é feito "
                  "automaticamente: as sugestões abaixo são confirmadas com a tesouraria, e a "
                  "resposta fica em 'Nota da tesouraria'.").font = Font(
        name=FONTE, italic=True, size=9, color="808080")
    r += 1
    # "Pix sem recibo": onde achar cada um no PDF do banco (2026-10-26)
    cabecalho(ws, ["Pessoa", "Total Recibos", "Total Extrato", "Diferença", "Status",
                   "Pix sem recibo (no extrato)", "Sugestão (a confirmar)",
                   "Nota da tesouraria"], linha=r)
    r += 1
    for d in detalhar_divergencias(pessoas_ordenadas, sugestoes, notas, devolucoes):
        textos = [texto_sugestao(s, "recibo" if s["div_recibo"] == d["id"] else "pix")
                  for s in d["sugestoes_vinculo"]]
        textos += [texto_devolucao(dv) for dv in d["devolucoes_possiveis"]]
        pix = [f"{brl(x['valor'])} — {onde(x['banco'], x['data'], x.get('pagina'))}"
               for x in d["pix_sem_recibo"]]
        pessoa = d["pessoa"] + (f" (recibo {d['recibo']})" if d.get("recibo") else "")
        valores = [pessoa, d["total_recibos"], d["total_extrato"], d["diferenca"], d["tipo"],
                   "\n".join(pix), "\n".join(textos), d["nota_tesouraria"]]
        for j, v in enumerate(valores, start=1):
            c = ws.cell(row=r, column=j, value=v)
            c.font = Font(name=FONTE, size=10)
            c.alignment = Alignment(vertical="top", wrap_text=j >= 6)
            if j in (2, 3, 4):
                c.number_format = MOEDA
        ws.cell(row=r, column=5).fill = preencher(cor_status(d["tipo"]))
        if textos:
            ws.cell(row=r, column=7).fill = preencher(AMARELO)
        r += 1
    for j, largura in enumerate([36, 14, 14, 12, 22, 34, 70, 50], start=1):
        ws.column_dimensions[get_column_letter(j)].width = largura
