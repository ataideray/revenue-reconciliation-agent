"""Identificação dos arquivos que a tesouraria envia.

Regra (decisão de 2026-10-05): os extratos só valem em PDF do banco. Um
extrato em .xlsx não é aceito: o agente pede o PDF. No modo de demonstração
(`CF_DEMO=1`, ou `conselho-fiscal agente --demo`), os extratos fictícios de
exemplo/ (.xlsx com "cora" ou "stone" no nome) fazem o papel dos PDFs.

O mês da planilha de entradas vem das datas dos recibos; o dos extratos, do
período impresso no PDF (2026-10-23).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal

from conselho_fiscal.comum.pdf import texto_pdf
from conselho_fiscal.comum.texto import norm_maiusculo
from conselho_fiscal.receitas import lancamentos

Tipo = Literal["entradas", "Cora", "Stone", "extrato_xlsx", "desconhecido"]

# trechos que só aparecem no PDF de cada banco (rodapé/cabeçalho)
MARCAS_PDF = {"Cora": "CORA SCFI", "Stone": "STONE INSTITUICAO DE PAGAMENTO"}
# "Extrato do período 01/09/2026 a 30/09/2026" (Cora) e
# "Período: de 01/09/2026 a 30/09/2026" (Stone), já em maiúsculas e sem acento
PERIODO = re.compile(r"PERIODO:?\s+(?:DE\s+)?\d{2}/(\d{2})/(\d{4})\s+A\s+\d{2}/(\d{2})/(\d{4})")


@dataclass
class Identificacao:
    tipo: Tipo
    mes: str | None = None        # AAAA-MM; None se não deu para saber
    motivo: str = ""              # por que não foi aceito


def mes_do_periodo(texto: str) -> str | None:
    """O mês do período do extrato (AAAA-MM); None se não achar o período ou
    se ele pegar mais de um mês."""
    m = PERIODO.search(texto)
    if not m or (m[1], m[2]) != (m[3], m[4]):
        return None
    return f"{m[2]}-{m[1]}"


def identificar(caminho: str, nome: str) -> Identificacao:
    ext = os.path.splitext(nome)[1].lower()
    if ext == ".pdf":
        try:
            texto = norm_maiusculo(texto_pdf(caminho))
        except Exception:   # PDF corrompido ou protegido: não interrompe a conversa
            return Identificacao("desconhecido", motivo="não consegui ler este PDF")
        for banco, marca in MARCAS_PDF.items():
            if marca in texto:
                return Identificacao(banco, mes=mes_do_periodo(texto))
        return Identificacao("desconhecido",
                             motivo="este PDF não parece um extrato bancário que eu saiba ler")
    if ext in (".xlsx", ".xls"):
        banco = next((b for b in MARCAS_PDF if b.lower() in nome.lower()), None)
        try:
            mes = lancamentos.mes_referencia(lancamentos.carregar(caminho))
        except Exception:   # sem aba "Receitas" ou planilha ilegível
            mes = None
        if mes and not banco:
            return Identificacao("entradas", mes=mes)
        if banco and os.environ.get("CF_DEMO") == "1":
            return Identificacao(banco)
        if banco:
            return Identificacao("extrato_xlsx",
                                 motivo="o extrato bancário precisa vir no PDF do banco")
        return Identificacao("desconhecido",
                             motivo="o registro de receitas da tesouraria precisa ter a aba "
                                    "\"Receitas\" com as datas dos recibos")
    return Identificacao("desconhecido",
                         motivo="envie o registro de receitas da tesouraria (.xlsx) ou os "
                                "extratos bancários em PDF")

