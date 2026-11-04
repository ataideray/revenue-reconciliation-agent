"""Tipos compartilhados pelos leitores de extrato e pelas conferências."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

Banco = Literal["Cora", "Stone"]
Status = Literal["OK", "ALERTA", "NÃO VERIFICADO"]


class Transacao(TypedDict):
    """Uma linha do extrato, no mesmo formato para todos os bancos."""

    banco: Banco
    data: str             # como impresso no extrato: 'dd/mm/aaaa' (Cora) ou 'dd/mm/aa' (Stone)
    tipo: Literal["Entrada", "Saída"]
    nome: str             # contraparte / histórico, como lido do PDF
    documento: str        # CPF/CNPJ quando o extrato traz (Cora); senão ''
    categoria: str        # 'Transferência Pix', 'Rendimento', 'Pagamento' (Stone); senão ''
    entrada: float
    saida: float
    saldo: float | None   # saldo após a transação, quando o extrato traz (Stone)
    pagina: NotRequired[int | None]   # página do PDF (2026-10-26); não há no .xlsx


class Verificacao(TypedDict):
    """Resultado de uma conferência automática. Nunca bloqueia o pipeline:
    um ALERTA aparece no topo da aba Divergências e no JSON."""

    grupo: Literal["extratos", "planilha"]
    extrato: str          # rótulo curto da origem: 'Cora', 'Stone', 'Resumo', 'Receitas'
    verificacao: str
    status: Status
    esperado: str
    encontrado: str
    detalhe: str          # onde conferir, quando há ALERTA
    rotulos: NotRequired[tuple[str, str]]   # nomes de 'esperado'/'encontrado' na mensagem
