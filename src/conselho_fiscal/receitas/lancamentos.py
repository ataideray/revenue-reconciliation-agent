"""Planilha de lançamentos da tesouraria (aba 'Receitas' + aba 'Resumo').

Regras da planilha:
- cada recibo começa numa linha com 'Data' preenchida (a linha 'Total');
- as linhas seguintes, sem 'Data', são os itens do recibo (Descrição/Valor);
- 'Origem' = nome do titular, em maiúsculas; nome terminado em '*' = não sócio;
- os itens são somados por coluna de recurso (ver cadastros.destinos).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, TypedDict

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from conselho_fiscal.cadastros import destinos
from conselho_fiscal.comum.planilha import BORDA, CINZA, FONTE, MOEDA, cabecalho, preencher
from conselho_fiscal.comum.texto import espacos_simples, norm, vazio
from conselho_fiscal.comum.valores import brl, mesmo_valor, valor_planilha
from conselho_fiscal.extratos.modelo import Verificacao

COLUNAS_FIXAS = ["Número", "Origem"]
# recibos que não vêm de Pix de pessoas e ficam fora da conciliação
ORIGENS_FORA_DA_CONCILIACAO = {"TOTAL", "RENDIMENTOS", "RENDIMENTO"}


class Pivotado(TypedDict):
    """Uma linha por recibo, uma coluna por destino (recurso)."""

    colunas: list[str]                 # colunas de recurso, na ordem da planilha
    linhas: list[dict[str, Any]]       # {"Número", "Origem", <coluna>: valor}
    destinos_novos: list[str]          # destinos cadastrados nesta execução


class Recibo(TypedDict, total=False):
    celulas: list[Any]     # Número, Origem e os valores por coluna, na ordem da planilha
    origem: str
    valor: float           # total do recibo
    compat: str            # preenchido na conciliação: Conforme / Conforme (2 Pix) / Divergente


def carregar(caminho: str, aba: str = "Receitas") -> pd.DataFrame:
    if caminho.lower().endswith((".csv", ".tsv")):
        sep = "\t" if caminho.lower().endswith(".tsv") else None
        df = pd.read_csv(caminho, sep=sep, engine="python", dtype=str, header=0)
    else:
        df = pd.read_excel(caminho, sheet_name=aba or "Receitas", dtype=str, header=0)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _coluna(df: pd.DataFrame, nome: str) -> str | None:
    return next((c for c in df.columns if norm(c) == nome), None)


def mes_referencia(df: pd.DataFrame) -> str | None:
    """Mês mais frequente nas datas dos recibos (ex.: '2026-07')."""
    meses: Counter[str] = Counter()
    coluna = _coluna(df, "data")
    for d in (df[coluna] if coluna else []):
        m = re.match(r"^\s*\d{1,2}/(\d{1,2})/(\d{4})", str(d))
        if m:
            meses[f"{m.group(2)}-{int(m.group(1)):02d}"] += 1
        elif hasattr(d, "year"):
            meses[f"{d.year}-{d.month:02d}"] += 1
    return meses.most_common(1)[0][0] if meses else None


def pivotar(df: pd.DataFrame, cadastro: destinos.Cadastro | None = None,
            mes: str | None = None) -> Pivotado:
    """Uma linha por recibo, uma coluna por destino.

    Destinos novos são incluídos no `cadastro` (quem chama salva) e o
    'ultimo_uso' das colunas usadas passa a ser `mes` (AAAA-MM).
    """
    usar_cadastro = cadastro is not None
    cadastro = cadastro if cadastro is not None else destinos.vazio()
    col_data, col_num = _coluna(df, "data"), _coluna(df, "numero")
    col_nome, col_desc = _coluna(df, "nome"), _coluna(df, "descricao")
    col_valor = _coluna(df, "valor")
    faltando = [n for n, c in [("Data", col_data), ("Nome", col_nome),
                               ("Descrição", col_desc), ("Valor", col_valor)] if c is None]
    if faltando:
        raise ValueError(f"Colunas não encontradas: {faltando}. Disponíveis: {list(df.columns)}")

    recibos: list[dict[str, Any]] = []
    grafias_por_destino: dict[str, Counter] = {}
    atual = None
    for _, row in df.iterrows():
        data, nome, desc, valor = row[col_data], row[col_nome], row[col_desc], row[col_valor]
        if not vazio(data):                     # início de um novo recibo
            atual = None
            if not vazio(nome):
                numero = row[col_num] if col_num else None
                atual = {"Número": "" if vazio(numero) else espacos_simples(numero),
                         "Origem": espacos_simples(nome).rstrip("*").strip().upper(),
                         "destinos": defaultdict(float)}
                recibos.append(atual)
            continue
        if atual is None or vazio(desc) or vazio(valor):
            continue
        resolvido = destinos.resolver(desc, cadastro)
        if resolvido is None:
            continue
        chave, grafia = resolvido
        grafias_por_destino.setdefault(chave, Counter())[grafia] += 1
        atual["destinos"][chave] += valor_planilha(valor)

    # nome de cada coluna: o fixo do cadastro; senão o canônico; senão a
    # grafia mais usada no mês, que passa a ser o nome fixo daqui em diante
    canonicos = {destinos.chave(c): c for c in destinos.ORDEM_PREFERIDA}
    colunas_cadastro = cadastro["colunas"]
    novos, nome_coluna = [], {}
    for k, grafias in grafias_por_destino.items():
        if k not in colunas_cadastro:
            sugeridas = [g for g, _ in grafias.most_common() if g]
            colunas_cadastro[k] = {"nome": canonicos.get(k) or (sugeridas[0] if sugeridas else k),
                                   "ultimo_uso": None}
            novos.append(colunas_cadastro[k]["nome"])
        if mes and (not colunas_cadastro[k].get("ultimo_uso")
                    or colunas_cadastro[k]["ultimo_uso"] < mes):
            colunas_cadastro[k]["ultimo_uso"] = mes
        nome_coluna[k] = colunas_cadastro[k]["nome"]

    # ordem pela chave: "Oferta" no cadastro ocupa o lugar de "Ofertas" da lista
    ordem = [destinos.chave(c) for c in destinos.ORDEM_PREFERIDA]
    colunas = [nome_coluna[k] for k in ordem if k in nome_coluna]
    colunas += [c for k, c in nome_coluna.items() if k not in ordem]
    linhas = []
    for r in recibos:
        por_nome = {nome_coluna[k]: v for k, v in r["destinos"].items()}
        linha = {"Número": r["Número"], "Origem": r["Origem"]}
        for c in colunas:
            v = por_nome.get(c, 0.0)
            linha[c] = int(v) if float(v).is_integer() else round(v, 2)
        linhas.append(linha)
    return {"colunas": colunas, "linhas": linhas,
            "destinos_novos": novos if usar_cadastro else []}


def recibos_para_conciliacao(pivotado: Pivotado) -> list[Recibo]:
    """Recibos que entram na conciliação com os extratos (sem 'Rendimentos')."""
    ordem = COLUNAS_FIXAS + pivotado["colunas"]
    recibos: list[Recibo] = []
    for linha in pivotado["linhas"]:
        origem = linha["Origem"]
        if not origem or origem.upper() in ORIGENS_FORA_DA_CONCILIACAO:
            continue
        valores = [linha[c] for c in pivotado["colunas"]]
        recibos.append({"celulas": [linha[c] for c in ordem], "origem": origem,
                        "valor": round(sum(v for v in valores if isinstance(v, (int, float))), 2)})
    return recibos


def exportar_xlsx(pivotado: Pivotado, caminho: str) -> None:
    """Planilha intermediária (uma linha por recibo), para conferência manual."""
    titulos = COLUNAS_FIXAS + pivotado["colunas"]
    n = len(pivotado["linhas"])
    wb = Workbook()
    ws = wb.active
    ws.title = "Receitas"
    cabecalho(ws, titulos)
    for i, linha in enumerate(pivotado["linhas"], start=2):
        for j, t in enumerate(titulos, start=1):
            c = ws.cell(row=i, column=j, value=linha[t])
            c.font = Font(name=FONTE, size=10)
            c.border = BORDA
            if t not in COLUNAS_FIXAS:
                c.number_format = MOEDA
                c.alignment = Alignment(horizontal="right")
    total = n + 2
    ws.cell(row=total, column=1, value="TOTAL").font = Font(name=FONTE, bold=True, size=10)
    ws.cell(row=total, column=1).fill = preencher(CINZA)
    ws.merge_cells(start_row=total, start_column=1, end_row=total, end_column=2)
    for j, t in enumerate(titulos, start=1):
        if t in COLUNAS_FIXAS:
            continue
        letra = get_column_letter(j)
        c = ws.cell(row=total, column=j, value=f"=SUM({letra}2:{letra}{n + 1})")
        c.font = Font(name=FONTE, bold=True, size=10)
        c.fill = preencher(CINZA)
        c.number_format = MOEDA
        c.alignment = Alignment(horizontal="right")
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 38
    for j in range(3, len(titulos) + 1):
        ws.column_dimensions[get_column_letter(j)].width = max(12, len(titulos[j - 1]) + 2)
    ws.freeze_panes = "C2"
    wb.save(caminho)


def conferir_planilha(caminho: str, df: pd.DataFrame) -> list[Verificacao]:
    """Confere a planilha da tesouraria contra ela mesma (N1). Não bloqueia.

    - Aba 'Resumo' × aba 'Receitas': total de receitas, recibos emitidos,
      recibos de sócios e de não sócios (não sócio = nome terminado em '*',
      convenção confirmada pela tesouraria).
    - Total de cada recibo (linha 'Total') = soma dos itens dele.
    """
    def contagem(v: float) -> str:
        return str(int(v)) if float(v).is_integer() else str(v)

    def item(nome: str, esperado: float | None, encontrado: float, detalhe: str,
             moeda: bool = False) -> Verificacao:
        fmt = brl if moeda else contagem
        if esperado is None:
            status, esp = "NÃO VERIFICADO", "(indicador não encontrado na aba Resumo)"
        else:
            ok = mesmo_valor(esperado, encontrado) if moeda else esperado == encontrado
            status, esp = ("OK" if ok else "ALERTA"), fmt(esperado)
        return {"grupo": "planilha", "extrato": "Resumo", "verificacao": nome,
                "status": status, "esperado": esp, "encontrado": fmt(encontrado),
                "rotulos": ("Resumo", "Receitas"),
                "detalhe": detalhe if status == "ALERTA" else ""}

    c_data, c_nome, c_num = _coluna(df, "data"), _coluna(df, "nome"), _coluna(df, "numero")
    c_desc, c_valor = _coluna(df, "descricao"), _coluna(df, "valor")

    recibos, atual = [], None
    for _, row in df.iterrows():
        if not vazio(row[c_data]):
            atual = {"numero": "" if not c_num or vazio(row[c_num]) else str(row[c_num]).strip(),
                     "nome": "" if vazio(row[c_nome]) else str(row[c_nome]).strip(),
                     "total": None, "itens": 0.0}
            recibos.append(atual)
            if norm(row[c_desc]) == "total":
                atual["total"] = valor_planilha(row[c_valor])
        elif atual is not None and not vazio(row[c_desc]) and not vazio(row[c_valor]):
            atual["itens"] += valor_planilha(row[c_valor])

    total = round(sum(r["total"] or 0.0 for r in recibos), 2)
    nao_socios = [r for r in recibos if r["nome"].endswith("*")]
    errados = [r for r in recibos
               if r["total"] is None or not mesmo_valor(r["total"], r["itens"])]

    resumo = None
    if not caminho.lower().endswith((".csv", ".tsv")):
        try:
            aba = pd.read_excel(caminho, sheet_name="Resumo", header=None, dtype=object)
            resumo = {norm(r[0]): r[1] for r in aba.itertuples(index=False)
                      if len(r) > 1 and not vazio(r[0])}
        except ValueError:
            resumo = None

    verif: list[Verificacao] = []
    if resumo is None:
        verif.append({"grupo": "planilha", "extrato": "Resumo", "verificacao": "Aba Resumo",
                      "status": "NÃO VERIFICADO", "esperado": "", "encontrado": "",
                      "detalhe": "o registro de receitas não tem aba 'Resumo'"})
    else:
        def indicador(chave: str) -> float | None:
            v = resumo.get(chave)
            return None if vazio(v) else valor_planilha(v)

        verif += [
            item("Total de receitas (Resumo × Receitas)", indicador("total de receitas"), total,
                 "O total do Resumo não bate com a soma dos recibos.", moeda=True),
            item("Recibos emitidos (Resumo × Receitas)", indicador("recibos emitidos"),
                 len(recibos), "Nº de recibos do Resumo difere dos lançados."),
            item("Recibos de sócios (Resumo × Receitas)", indicador("recibos de socios"),
                 len(recibos) - len(nao_socios), "Sócios = recibos cujo nome não termina em '*'."),
            item("Recibos de não sócios (Resumo × Receitas)", indicador("recibos de nao socios"),
                 len(nao_socios), "Não sócios = recibos cujo nome termina em '*': "
                 + ", ".join(r["nome"] for r in nao_socios[:10])),
        ]
    verif.append({
        "grupo": "planilha", "extrato": "Receitas",
        "verificacao": "Total de cada recibo = soma dos itens",
        "status": "ALERTA" if errados else "OK",
        "esperado": f"{len(recibos)} recibos conferindo",
        "encontrado": f"{len(recibos) - len(errados)} recibos conferindo",
        "detalhe": ("Conferir: " + "; ".join(
            f"{r['numero']} {r['nome']} (Total "
            f"{brl(r['total']) if r['total'] is not None else 'ausente'}, itens {brl(r['itens'])})"
            for r in errados[:10])) if errados else "",
    })
    return verif
