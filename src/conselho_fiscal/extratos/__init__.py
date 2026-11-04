"""Leitura dos extratos bancários (Cora e Stone) num formato único.

Ponto de entrada: `ler_extrato(caminho, banco)`, que aceita o PDF do banco
(fonte oficial, com a leitura conferida contra o próprio PDF) ou um .xlsx
já convertido (uso manual; sai como "não verificado", menos no modo de
demonstração, `CF_DEMO=1`, em que os extratos fictícios fazem o papel dos PDFs).
"""

from __future__ import annotations

import os

from conselho_fiscal.comum.pdf import texto_pdf
from conselho_fiscal.extratos import cora, stone
from conselho_fiscal.extratos.modelo import Banco, Transacao, Verificacao
from conselho_fiscal.extratos.planilha import exportar_xlsx, ler_xlsx

__all__ = ["Banco", "Transacao", "Verificacao", "exportar_xlsx", "ler_extrato"]

_LEITORES = {"Cora": cora, "Stone": stone}


def ler_extrato(caminho: str, banco: Banco) -> tuple[list[Transacao], list[Verificacao]]:
    """Retorna (transações na ordem do extrato, verificações da leitura)."""
    if caminho.lower().endswith(".pdf"):
        texto = texto_pdf(caminho)
        leitor = _LEITORES[banco]
        transacoes = leitor.ler_transacoes(texto)
        return transacoes, leitor.verificar_leitura(texto, transacoes)
    if os.environ.get("CF_DEMO") == "1":        # demonstração: sem o alerta (2026-10-29)
        return ler_xlsx(caminho, banco), []
    return ler_xlsx(caminho, banco), [{
        "grupo": "extratos", "extrato": banco, "verificacao": "Leitura do PDF",
        "status": "NÃO VERIFICADO", "esperado": "", "encontrado": "",
        "detalhe": "extrato recebido já em .xlsx; não há PDF para conferir a leitura",
    }]
