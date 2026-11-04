"""Agente da conferência mensal: conversa com a tesouraria e com o
Conselho Fiscal, sem depender do canal (simulador web local ou WhatsApp).

    tesouraria ── arquivos ──► agente ── pipeline de receitas ──► divergências
         ▲                       │
         └── lista e perguntas ──┘     (uma nota por divergência)
    CF ── "envie julho" ──► agente ── pacote do mês ──► fim do papel do agente

O agente não faz conta: os números vêm de `conselho_fiscal.receitas`.
As respostas da tesouraria são botões de confirmação das sugestões ou
texto livre, lido por um interpretador (agente/ia.py): sem IA, o texto vira
a nota; com IA, o agente confere o que ela entendeu antes de gravar.
"""

from conselho_fiscal.agente.agente import Agente

__all__ = ["Agente"]
