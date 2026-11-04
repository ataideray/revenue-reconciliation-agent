"""Leitura do extrato Cora (PDF -> transações) e conferência da leitura."""

from __future__ import annotations

import re

from conselho_fiscal.comum.valores import brl, mesmo_valor, valor_extrato
from conselho_fiscal.extratos.modelo import Transacao, Verificacao

DATA_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+Saldo do dia")
# linha de transação: <descrição…> <CPF/CNPJ> <sinal> R$ <valor>
DOC_RE = re.compile(r"(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})")
VALOR_RE = re.compile(r"([+-])\s*R\$\s*([\d.]+,\d{2})")

# Cabeçalho/rodapé repetidos em cada página. O teste é "começa com", nunca
# "contém": uma transação para outro núcleo ("Transf Pix enviada ASSOCIACAO
# PARCEIRA B…") não pode ser descartada.
IGNORAR = (
    "ASSOCIACAO VILA DAS FLORES", "CNPJ", "Agência", "Cora SCFI",
    "Ouvidoria", "Extrato gerado", "Extrato do período", "Saldo inicial",
    "Total de entradas", "Total de saídas", "Saldo final", "Transações",
    "pág",
)

RESUMO_RE = {
    "saldo_inicial": re.compile(r"^Saldo inicial dispon[ií]vel\s+R\$\s*([\d.]+,\d{2})"),
    "entradas": re.compile(r"^Total de entradas\s+\+?\s*R\$\s*([\d.]+,\d{2})"),
    "saidas": re.compile(r"^Total de sa[ií]das\s+-?\s*R\$\s*([\d.]+,\d{2})"),
    "saldo_final": re.compile(r"^Saldo final dispon[ií]vel\s+R\$\s*([\d.]+,\d{2})"),
}
SALDO_DIA_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+Saldo do dia\s+(-?)\s*R\$\s*([\d.]+,\d{2})")


def ler_transacoes(texto: str) -> list[Transacao]:
    """Texto do PDF (pdftotext -layout) -> transações, na ordem do extrato."""
    data_atual = None
    transacoes: list[Transacao] = []
    # o pdftotext separa as páginas com \f: a página de cada transação
    linhas = [(pagina, linha) for pagina, parte in enumerate(texto.split("\f"), start=1)
              for linha in parte.splitlines()]
    for pagina, linha in linhas:
        s = linha.strip()
        if not s:
            continue
        m = DATA_RE.match(s)
        if m:
            data_atual = m.group(1)
            continue
        if any(s.startswith(p) for p in IGNORAR):
            continue
        mv = VALOR_RE.search(s)
        if not mv:
            continue
        sinal, valor = mv.group(1), valor_extrato(mv.group(2))
        md = DOC_RE.search(s)
        # descrição = tudo antes do documento (ou do valor), sem o "…" de corte
        desc = s[:md.start() if md else mv.start()]
        desc = re.sub(r"\s+", " ", desc).replace("…", "").strip()
        transacoes.append({
            "banco": "Cora", "data": data_atual,
            "tipo": "Entrada" if sinal == "+" else "Saída",
            "nome": desc, "documento": md.group(1) if md else "", "categoria": "",
            "entrada": valor if sinal == "+" else 0.0,
            "saida": valor if sinal == "-" else 0.0,
            "saldo": None, "pagina": pagina,
        })
    return transacoes


def verificar_leitura(texto: str, transacoes: list[Transacao]) -> list[Verificacao]:
    """Confere a leitura contra os números impressos no próprio PDF.

    1) Totais de entradas e de saídas lidos × totais do cabeçalho.
    2) Saldo de cada dia: saldo anterior + movimento lido = saldo impresso.
       Num ALERTA, aponta EM QUAL DIA conferir.
    """
    resumo: dict[str, float] = {}
    saldos_dia: list[tuple[str, float]] = []
    for linha in texto.splitlines():
        s = linha.strip()
        for chave, rx in RESUMO_RE.items():
            m = rx.match(s)
            if m and chave not in resumo:
                resumo[chave] = valor_extrato(m.group(1))
        m = SALDO_DIA_RE.match(s)
        if m:
            v = valor_extrato(m.group(3))
            saldos_dia.append((m.group(1), -v if m.group(2) else v))

    verif: list[Verificacao] = []

    def item(nome: str, esperado: float | None, encontrado: float, detalhe: str) -> None:
        if esperado is None:
            status, esp = "NÃO VERIFICADO", "(não encontrado no PDF)"
        else:
            status = "OK" if mesmo_valor(esperado, encontrado) else "ALERTA"
            esp = brl(esperado)
        verif.append({"grupo": "extratos", "extrato": "Cora", "verificacao": nome,
                      "status": status, "esperado": esp, "encontrado": brl(encontrado),
                      "detalhe": detalhe if status == "ALERTA" else ""})

    item("Total de entradas (PDF × lido)", resumo.get("entradas"),
         round(sum(t["entrada"] for t in transacoes), 2),
         "Há entradas que não foram lidas ou foram lidas com valor errado.")
    item("Total de saídas (PDF × lido)", resumo.get("saidas"),
         round(sum(t["saida"] for t in transacoes), 2),
         "Há saídas que não foram lidas ou foram lidas com valor errado.")

    if not (saldos_dia and "saldo_inicial" in resumo):
        verif.append({"grupo": "extratos", "extrato": "Cora",
                      "verificacao": "Saldo do dia (dia a dia)", "status": "NÃO VERIFICADO",
                      "esperado": "(saldos não encontrados no PDF)", "encontrado": "",
                      "detalhe": ""})
        return verif

    movimento: dict[str, float] = {}
    for t in transacoes:
        movimento[t["data"]] = movimento.get(t["data"], 0.0) + t["entrada"] - t["saida"]
    anterior = resumo["saldo_inicial"]
    dias_com_erro = []
    for data, saldo in reversed(saldos_dia):     # o PDF lista do dia mais recente ao mais antigo
        calculado = anterior + movimento.get(data, 0.0)
        if not mesmo_valor(calculado, saldo):
            dias_com_erro.append(f"{data} (esperado {brl(saldo)}, calculado {brl(calculado)})")
        anterior = saldo
    verif.append({
        "grupo": "extratos", "extrato": "Cora", "verificacao": "Saldo do dia (dia a dia)",
        "status": "ALERTA" if dias_com_erro else "OK",
        "esperado": f"{len(saldos_dia)} dias conferindo",
        "encontrado": f"{len(saldos_dia) - len(dias_com_erro)} dias conferindo",
        "detalhe": ("Conferir manualmente: " + "; ".join(dias_com_erro)) if dias_com_erro else "",
    })
    return verif
