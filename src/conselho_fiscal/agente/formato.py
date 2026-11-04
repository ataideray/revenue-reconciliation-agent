"""Destaques das mensagens do agente, no formato do WhatsApp (*negrito*,
_itálico_), que o simulador também mostra (2026-10-22).

Convenção:
- negrito: o título da mensagem, os nomes de pessoas, os rótulos de seção
  ("Falta:", "Sugestões (a confirmar):", "Entendi:") e a situação que
  importa ("está pronto", "Tudo certo");
- itálico: o que a pessoa faz em seguida ("Confirme pelas opções…") e
  observações;
- sem marca: o que a tesouraria escreveu (as notas) e o que vai para a
  planilha.

No WhatsApp a marca vale dentro de uma linha e não pode ter espaço logo
depois da abertura nem antes do fechamento: as funções marcam linha a
linha, com os espaços do lado de fora.
"""

from __future__ import annotations


def _marcar(texto: str, marca: str) -> str:
    linhas = []
    for linha in str(texto).split("\n"):
        miolo = linha.strip().replace(marca, "")
        if not miolo:
            linhas.append(linha)
            continue
        antes = linha[:len(linha) - len(linha.lstrip())]
        depois = linha[len(linha.rstrip()):]
        linhas.append(f"{antes}{marca}{miolo}{marca}{depois}")
    return "\n".join(linhas)


def negrito(texto: str) -> str:
    return _marcar(texto, "*")


def italico(texto: str) -> str:
    return _marcar(texto, "_")
