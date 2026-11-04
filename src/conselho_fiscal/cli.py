"""Linha de comando: `conselho-fiscal …` (ou `python -m conselho_fiscal …`).

    conselho-fiscal receitas ENTRADAS CORA STONE SAIDA [--aba Receitas] [--intermediarios PASTA]
    conselho-fiscal extrato {cora,stone} PDF SAIDA.xlsx
    conselho-fiscal agente [--porta 8000] [--pasta DIR] [--cadastros-reais] [--ia {gemini,nenhuma}]
                           [--host 127.0.0.1] [--sem-simulador] [--demo]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

from conselho_fiscal.comum.valores import brl
from conselho_fiscal.extratos import exportar_xlsx, ler_extrato

LINHA = "=" * 60


def _receitas(args: argparse.Namespace) -> int:
    from conselho_fiscal.receitas import executar

    print(LINHA, "PIPELINE DE CONFERÊNCIA DE RECEITAS", LINHA, sep="\n")
    st = executar(args.entradas, args.cora, args.stone, args.saida, aba=args.aba,
                  pasta_intermediarios=args.intermediarios)
    print(f"[1/2] Lançamentos: {st['pivotados']} recibos")
    print(f"       Colunas de recurso: {', '.join(st['colunas'])}")
    if st["destinos_novos"]:
        print(f"       Destinos NOVOS cadastrados com grafia fixa: "
              f"{', '.join(st['destinos_novos'])} (ver cadastros/destinos.json)")
    if args.intermediarios:
        print(f"       Intermediários salvos em: {args.intermediarios}")
    print("[2/2] Conciliação com os extratos:")
    print(f"       Recibos conciliados: {st['recibos']}")
    print(f"       Entradas Cora/Stone: {st['ent_cora']} / {st['ent_stone']}")
    print(f"       Pessoas: {st['pessoas']} (OK por pessoa: {st['ok']})")
    print(f"       Compatibilidade: {st['conformes']} conformes, {st['divergentes']} divergentes")
    print(f"       Possíveis devoluções (a confirmar com a tesouraria): {st['devolucoes']}")
    print(f"       Sugestões de vínculo (a confirmar com a tesouraria): {st['sugestoes']}")
    limpeza = st["limpeza_cadastros"]
    if limpeza["colunas_apagadas"] or limpeza["vinculos_apagados"]:
        print(f"       Cadastros (guarda de 2 anos): {len(limpeza['colunas_apagadas'])} coluna(s) "
              f"e {limpeza['vinculos_apagados']} vínculo(s) confirmado(s) apagados")
    if st["alertas"]:
        print("-" * 60)
        print(f"ATENÇÃO: {len(st['alertas'])} alerta(s) nas conferências automáticas:")
        for a in st["alertas"]:
            r_esp, r_enc = a.get("rotulos", ("esperado", "encontrado"))
            print(f"  [{a['extrato']}] {a['verificacao']}: {r_esp}: {a['esperado']}; "
                  f"{r_enc}: {a['encontrado']}")
        print("Detalhes no topo da aba 'Divergências'.")
    else:
        print("       Conferências automáticas (extratos e planilha da tesouraria): OK")
    print(LINHA, f"SAÍDA FINAL: {args.saida}",
          f"RESULTADO ESTRUTURADO (agente): {st['saida_json']}", LINHA, sep="\n")
    return 0


def _extrato(args: argparse.Namespace) -> int:
    banco = "Cora" if args.banco == "cora" else "Stone"
    transacoes, verificacoes = ler_extrato(args.pdf, banco)
    exportar_xlsx(transacoes, banco, args.saida)
    print(f"OK: {len(transacoes)} transações -> {args.saida}")
    print(f"Entradas: {brl(sum(t['entrada'] for t in transacoes))} | "
          f"Saídas: {brl(sum(t['saida'] for t in transacoes))}")
    for v in verificacoes:
        detalhe = f" — {v['detalhe']}" if v["detalhe"] else ""
        print(f"  [{v['status']}] {v['verificacao']}{detalhe}")
    return 0


def escolher_ia(escolha: str | None) -> tuple[Any, str | None]:
    """(interpretador, erro) para `--ia`. Sem a opção, o Gemini, se houver
    chave; sem chave, avisa e segue sem IA (sinalizar, não bloquear). Com
    `--ia gemini` e sem chave, é erro; `--ia nenhuma` desliga a IA."""
    if escolha == "nenhuma":
        return None, None
    from conselho_fiscal.agente import gemini
    chave = gemini.chave()
    if chave:
        return gemini.Gemini(chave), None
    falta = f"falta a chave do Gemini (GEMINI_API_KEY ou {gemini.ARQUIVO_CHAVE})"
    if escolha == "gemini":
        return None, f"Não iniciei: {falta}."
    logging.warning("%s; as respostas livres viram a nota como foram escritas.",
                    "F" + falta[1:])
    return None, None


def _agente(args: argparse.Namespace) -> int:
    try:
        from conselho_fiscal.agente import Agente
        from conselho_fiscal.agente.armazenamento import Armazenamento
        from conselho_fiscal.agente.web import LOCAIS, servir
    except ImportError as erro:
        print(f"Faltam as dependências do agente ({erro.name}). "
              "Instale com: pip install -e \".[agente]\"")
        return 1
    if not args.sem_simulador and args.host not in LOCAIS:
        print(f"Não iniciei: o simulador não tem login e não pode escutar em {args.host}. "
              "Use --sem-simulador.")
        return 1
    if args.demo:                       # extratos fictícios em .xlsx (exemplo/)
        os.environ["CF_DEMO"] = "1"
    interpretador, erro = escolher_ia(args.ia)
    if erro:
        print(erro)
        return 1
    from conselho_fiscal.agente import whatsapp as wa
    try:
        cfg, falta = wa.config()
    except ValueError as erro:
        print(f"Não iniciei: {erro}.")
        return 1
    arm = Armazenamento(args.pasta)
    # simulação: cadastros próprios, dentro da pasta do agente
    cadastros = () if args.cadastros_reais else arm.cadastros_proprios()
    agente = Agente(arm, *cadastros, interpretador=interpretador)
    onde = "cadastros REAIS" if args.cadastros_reais else "cadastros da simulação"
    ia = agente.ia.nome
    if getattr(agente.ia, "reserva", None) not in (None, getattr(agente.ia, "modelo", None)):
        ia += f", reserva {agente.ia.reserva}"
    canal = None
    if cfg:
        # números com espaço próprio: dados e conversas em <pasta>/espacos/<nome>;
        # com os cadastros reais, todos usam os mesmos (e a mesma trava)
        por_espaco = {}
        for nome in sorted(set(cfg.espacos.values())):
            arm_e = Armazenamento(arm.base / "espacos" / nome)
            cad_e = () if args.cadastros_reais else arm_e.cadastros_proprios()
            por_espaco[nome] = Agente(arm_e, *cad_e, interpretador=interpretador,
                                      trava=agente._trava if args.cadastros_reais else None)
        canal = wa.WhatsApp(agente, wa.Meta(cfg), cfg.contatos,
                            {num: por_espaco[e] for num, e in cfg.espacos.items()})
    modo = "só /saude, sem o simulador" if args.sem_simulador else "simulador"
    print(f"Agente em http://{args.host}:{args.porta}  ({modo}; dados em {arm.base}; {onde}; "
          f"respostas livres: {ia})")
    print(f"WhatsApp: ligado em /whatsapp ({len(cfg.contatos)} contato(s), "
          f"{len(set(cfg.espacos.values()))} espaço(s) próprio(s))" if cfg
          else f"WhatsApp: desligado (falta {falta})")
    servir(args.porta, agente, args.host, not args.sem_simulador, canal)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="AVISO: %(message)s")
    ap = argparse.ArgumentParser(prog="conselho-fiscal",
                                 description="Conferência mensal dos dados da tesouraria.")
    sub = ap.add_subparsers(dest="comando", required=True)

    r = sub.add_parser("receitas", help="conferência de receitas do mês")
    r.add_argument("entradas", help="planilha de lançamentos da tesouraria (.xlsx)")
    r.add_argument("cora", help="extrato Cora (.pdf; .xlsx já convertido sai 'não verificado')")
    r.add_argument("stone", help="extrato Stone (.pdf; .xlsx já convertido sai 'não verificado')")
    r.add_argument("saida", help="planilha final (.xlsx); o JSON sai com o mesmo nome")
    r.add_argument("--aba", default="Receitas", help="aba de lançamentos (padrão: Receitas)")
    r.add_argument("--intermediarios", metavar="PASTA",
                   help="grava também os extratos lidos e os lançamentos por recibo em .xlsx")
    r.set_defaults(func=_receitas)

    e = sub.add_parser("extrato", help="converte um extrato PDF em planilha, para conferência")
    e.add_argument("banco", choices=["cora", "stone"])
    e.add_argument("pdf")
    e.add_argument("saida")
    e.set_defaults(func=_extrato)

    a = sub.add_parser("agente", help="simulador local do agente (tesouraria e CF)")
    a.add_argument("--porta", type=int, default=8000)
    a.add_argument("--pasta", help="pasta de trabalho do agente (padrão: agente_dados/)")
    a.add_argument("--cadastros-reais", action="store_true",
                   help="grava vínculos e destinos nos cadastros reais (padrão: cópia própria "
                        "dentro da pasta do agente, para simulação)")
    a.add_argument("--ia", choices=["gemini", "nenhuma"],
                   help="IA que lê as respostas livres da tesouraria (padrão: o Gemini, se "
                        "houver chave; senão, sem IA)")
    a.add_argument("--host", default="127.0.0.1",
                   help="endereço em que escuta (padrão: só a própria máquina; outro endereço "
                        "exige --sem-simulador)")
    a.add_argument("--demo", action="store_true",
                   help="aceita os extratos fictícios em .xlsx de exemplo/ no lugar dos PDFs")
    a.add_argument("--sem-simulador", action="store_true",
                   help="servidor sem o simulador (só /saude e o WhatsApp), para a nuvem")
    a.set_defaults(func=_agente)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
