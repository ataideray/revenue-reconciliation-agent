"""Avalia o Gemini com as respostas de teste sobre as divergências do mês de
exemplo (exemplo/) e mostra os erros. Roda à mão, quando mudam o modelo ou as
instruções (custa chamadas e depende de rede).

    python3 scripts/avaliar_ia.py                         # exemplo de julho/2026
    python3 scripts/avaliar_ia.py --mes 2026-06           # exemplo de junho/2026
    python3 scripts/avaliar_ia.py --modelo gemini-3.8-flash --pausa 6

O que vai para o Gemini é o mesmo do agente (apelidos, sem CPF); antes de
enviar, o script confere que nenhuma palavra dos nomes do mês está na
pergunta. Sai com código 1 se houver erro CRÍTICO (confirmação que a
tesouraria não fez).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from conselho_fiscal.agente import avaliacao, gemini  # noqa: E402
from conselho_fiscal.agente import divergencias as dv  # noqa: E402
from conselho_fiscal.agente.ia import para_ia  # noqa: E402


def palavras_dos_nomes(nomes: tuple[tuple[str, bool], ...]) -> set[str]:
    from conselho_fiscal.comum.texto import norm_maiusculo
    return {p for n, _ in nomes for p in re.findall(r"\w+", norm_maiusculo(n))
            if len(p) >= 3 and p not in ("DAS", "DOS")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mes", default="2026-07")
    ap.add_argument("--modelo", help="padrão: o do agente (CF_IA_MODELO ou gemini.MODELO_PADRAO)")
    ap.add_argument("--pausa", type=float, default=4.5,
                    help="segundos entre chamadas (limite por minuto do plano gratuito)")
    ap.add_argument("--so", help="só os casos cujo texto contém este trecho")
    args = ap.parse_args()

    chave = gemini.chave()
    if not chave:
        print(f"Falta a chave do Gemini (GEMINI_API_KEY ou {gemini.ARQUIVO_CHAVE}).")
        return 2
    resultado = json.loads((RAIZ / "exemplo" / "resultado" / f"receitas_{args.mes}.json")
                           .read_text(encoding="utf-8"))
    casos = avaliacao.carregar_casos(RAIZ / "exemplo" / f"casos_ia_{args.mes}.json")
    if args.so:
        casos = [c for c in casos if args.so.lower() in c.texto.lower()]
    proibidas = palavras_dos_nomes(dv.nomes(resultado["divergencias"]))
    ia = gemini.Gemini(chave, args.modelo, reserva="")      # um modelo só, sem o reserva
    print(f"{ia.nome}: {len(casos)} casos de {args.mes}\n")

    contagem, falhas_rede, criticos = Counter(), 0, 0
    for i, caso in enumerate(casos, start=1):
        ctx = avaliacao.contexto(caso, resultado)
        pergunta, _ = para_ia(ctx)
        vazou = [p for p in proibidas if re.search(rf"\b{p}\b", pergunta.upper())]
        if vazou:                                 # trava: não envia nome nenhum
            print(f"[{i}] NÃO ENVIADO: nomes na pergunta {vazou}")
            return 3
        if i > 1:
            time.sleep(args.pausa)
        inicio = time.monotonic()
        try:
            it = ia.interpretar(ctx)
        except Exception as erro:
            falhas_rede += 1
            print(f"[{i}] {caso.pessoa[:20]} | {caso.texto!r}\n     FALHOU: {erro}")
            continue
        problemas = avaliacao.comparar(caso, it, len(ctx.sugestoes))
        gravidade = avaliacao.mais_grave(problemas)
        criticos += gravidade == avaliacao.CRITICO
        contagem[gravidade] += 1
        if problemas:
            print(f"[{i}] {caso.pessoa[:20]} | {caso.texto!r} ({time.monotonic() - inicio:.1f}s)")
            print(f"     entendeu: confirmar={list(it.confirmar)} suficiente={it.suficiente} "
                  f"adiar={it.adiar} explicacao={it.explicacao!r}")
            for g, texto in problemas:
                print(f"     {g}: {texto}")

    avaliados = len(casos) - falhas_rede
    print(f"\nResumo ({ia.nome}): {contagem['ok']}/{avaliados} sem problema; "
          f"CRÍTICO: {contagem[avaliacao.CRITICO]}; erro: {contagem[avaliacao.ERRO]}; "
          f"só aviso: {contagem[avaliacao.AVISO]}; falhas de rede: {falhas_rede}")
    return 1 if criticos else 0


if __name__ == "__main__":
    sys.exit(main())
