"""Divergências do mês do ponto de vista da conversa: o que perguntar, que
sugestões oferecer e quando uma divergência fica explicada.

Uma divergência tem itens pendentes: recibos sem Pix e Pix sem recibo. Uma
sugestão confirmada pela tesouraria explica itens:
  - vínculo: o recibo (na divergência de quem tem o recibo) e o Pix (na
    divergência da conta que pagou), ou seja, explica as duas pontas;
  - devolução: o Pix (na divergência da pessoa).
Quando todos os itens estão explicados, a divergência recebe a nota sozinha,
montada com as confirmações. Senão, a tesouraria escreve a explicação.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from conselho_fiscal.comum.valores import brl

Divergencia = dict[str, Any]       # como em resultado["divergencias"]
Confirmacao = dict[str, Any]


def chave_pix(banco: str, data: str | None, valor: float) -> str:
    return f"P:{banco}|{data}|{valor:.2f}"


def pendencias(d: Divergencia) -> Counter[str]:
    return Counter([f"R:{r['numero']}" for r in d["recibos_sem_pix"]]
                   + [chave_pix(p["banco"], p["data"], p["valor"]) for p in d["pix_sem_recibo"]])


def _itens(c: Confirmacao) -> list[tuple[str, str]]:
    """(id da divergência, item) explicados por uma confirmação."""
    if c["tipo"] == "vinculo":
        return [(c["div_recibo"], f"R:{c['recibo']}"), (c["div_pix"], c["pix"])]
    return [(c["div"], c["pix"])]


def chave_sugestao(c: Confirmacao) -> str:
    """A sugestão, igual nas duas pontas (a divergência do recibo e a do Pix),
    para a recusa valer nas duas."""
    if c["tipo"] == "vinculo":
        return f"v|{c['recibo']}|{c['pix']}"
    return f"d|{c['pix']}|{c['saida_nome']}|{c['saida_data']}"


def explicados(d: Divergencia, confirmadas: list[Confirmacao]) -> Counter[str]:
    return Counter(item for c in confirmadas for div, item in _itens(c) if div == d["id"])


def coberta(d: Divergencia, confirmadas: list[Confirmacao]) -> bool:
    """Todos os itens pendentes estão explicados por confirmações."""
    falta = pendencias(d) - explicados(d, confirmadas)
    return bool(pendencias(d)) and not falta


def confirmacoes_de(d: Divergencia, confirmadas: list[Confirmacao]) -> list[Confirmacao]:
    """Confirmações que explicam algum item da divergência."""
    return [c for c in confirmadas if any(div == d["id"] for div, _ in _itens(c))]


def textos_confirmados(d: Divergencia, confirmadas: list[Confirmacao]) -> list[str]:
    return [c["texto"] for c in confirmacoes_de(d, confirmadas)]


CONFIRMADO = "Confirmado pela tesouraria: "


def nota_montada(d: Divergencia, confirmadas: list[Confirmacao], texto: str = "") -> str:
    """A nota padrão: as confirmações que tocam a divergência (em lista,
    quando são mais de uma) e o texto da tesouraria, se houver."""
    textos = textos_confirmados(d, confirmadas)
    if len(textos) > 1:
        partes = [CONFIRMADO.rstrip() + "\n"
                  + "\n".join(f"• {t.removeprefix(CONFIRMADO)}" for t in textos)]
        return "\n".join(partes + [texto] if texto else partes)
    return " ".join(textos + [texto] if texto else textos)


def opcoes(d: Divergencia, confirmadas: list[Confirmacao],
           todas: dict[str, Divergencia]) -> list[Confirmacao]:
    """Sugestões da divergência que ainda podem ser confirmadas: sem as que
    tocam um item já explicado (o mesmo recibo ou Pix não se explica duas
    vezes). `todas`: {id: divergência} do mês, para olhar a outra ponta."""
    usados = Counter(par for c in confirmadas for par in _itens(c))
    candidatas = []
    for i, s in enumerate(d["sugestoes_vinculo"]):
        lado_recibo = s["div_recibo"] == d["id"]
        candidatas.append({
            "tipo": "vinculo", "id": f"v{i}", "div_recibo": s["div_recibo"],
            "div_pix": s["div_pix"], "recibo": s["recibo"],
            "pix": chave_pix(s["pix_banco"], s["pix_data"], s["valor"]),
            "nome_extrato": s["nome_no_extrato"], "pessoa": s["recibo_de"],
            "rotulo": _rotulo_vinculo(s, lado_recibo),
            "botao": (f"Sim: Pix de {_dia(s['pix_data'])}" if lado_recibo
                      else f"Sim: recibo {s['recibo'].split('-')[0]}"),
            "texto": f"{CONFIRMADO}o Pix de {_extrato(s)} "
                     f"({brl(s['valor'])}, "
                     f"{_pag(s['pix_banco'], s['pix_data'], s.get('pix_pagina'))}) "
                     f"pagou o recibo {s['recibo']} de {_de(s)}."})
    for i, dv in enumerate(d["devolucoes_possiveis"]):
        entrada, saida = dv.get("entrada_pagina"), dv.get("saida_pagina")
        candidatas.append({
            "tipo": "devolucao", "id": f"d{i}", "div": dv["div"],
            "pix": chave_pix(dv["entrada_banco"], dv["entrada_data"], dv["valor"]),
            "saida_nome": dv["saida_nome"], "saida_data": dv["saida_data"],
            "rotulo": (f"o Pix de {brl(dv['valor'])} "
                       f"({_quando(dv['entrada_banco'], dv['entrada_data'], entrada)}) foi "
                       f"*devolvido* a \"{dv['saida_nome']}\" em {dv['saida_data']} "
                       f"({dv['saida_banco']}" + (f", pág. {saida}" if saida else "") + ")"),
            "botao": "Sim: devolução",
            "texto": f"{CONFIRMADO}o Pix de {brl(dv['valor'])} "
                     f"({_pag(dv['entrada_banco'], dv['entrada_data'], entrada)}) foi devolvido a "
                     f"{dv['saida_nome']} em {dv['saida_data']}; não é receita."})

    def livre(par: tuple[str, str]) -> bool:
        div, item = par
        return div in todas and usados[par] < pendencias(todas[div])[item]

    return [c for c in candidatas if all(livre(par) for par in _itens(c))]


def nomes(divergencias: list[Divergencia]) -> tuple[tuple[str, bool], ...]:
    """Todos os nomes das divergências, como (nome, é conta do extrato), para
    os apelidos do que vai para a IA. Um nome que é pessoa em algum lugar
    conta como pessoa."""
    conta: dict[str, bool] = {}

    def ver(nome: str, eh_conta: bool) -> None:
        conta[nome] = conta.get(nome, True) and eh_conta

    for d in divergencias:
        ver(d["pessoa"], not d["total_recibos"])
        for p in d["pix_sem_recibo"]:
            ver(p["nome_no_extrato"], True)
        for s in d["sugestoes_vinculo"]:
            ver(s["pix_de"], True)
            ver(s["nome_no_extrato"], True)
            ver(s["recibo_de"], False)
        for x in d["devolucoes_possiveis"]:
            ver(x["pessoa"], True)
            ver(x["saida_nome"], False)
    return tuple(conta.items())


def compativeis(lista: list[Confirmacao]) -> bool:
    """Nenhuma sugestão disputa o mesmo item: dá para confirmar todas juntas."""
    pares = [par for c in lista for par in _itens(c)]
    return len(pares) == len(set(pares))


def assinatura(d: Divergencia) -> str:
    """Identifica o conteúdo da divergência: num reenvio, a nota só é
    reaproveitada se a divergência continuar exatamente igual."""
    base = {k: d[k] for k in ("tipo", "total_recibos", "total_extrato", "recibos_sem_pix")}
    # sem a página do PDF (2026-10-26): as notas de antes dela continuam valendo
    base["pix_sem_recibo"] = [{k: v for k, v in x.items() if k != "pagina"}
                              for x in d["pix_sem_recibo"]]
    return hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False)
                          .encode()).hexdigest()[:16]


# ---------- textos (linguagem do dia a dia; 2026-10-23) ----------

def _dia(data: str | None) -> str:
    """'22/07/2026' -> '22/07' (para caber num botão)."""
    return (data or "?")[:5]


def _pag(banco: str, data: str | None, pagina: int | None = None) -> str:
    """'Stone, 20/07/26, pág. 3' (no texto das confirmações, que vai para a nota)."""
    return f"{banco}, {data}" + (f", pág. {pagina}" if pagina else "")


def _quando(banco: str, data: str | None, pagina: int | None = None) -> str:
    """'20/07/26, Stone, pág. 3': a página do PDF, para achar o lançamento."""
    return f"{data or 'sem data'}, {banco}" + (f", pág. {pagina}" if pagina else "")


def _aviso(s: dict[str, Any]) -> str:
    """O critério só aparece quando a sugestão vem só do valor e há mais de
    um recibo possível (2026-10-23): nos outros casos, os nomes na frase já
    dizem o porquê. A planilha do CF guarda o critério inteiro."""
    m = re.search(r"\((\d+) recibos possíveis\)", s["criterio"])
    return f" _(só pelo valor; {m[1]} recibos possíveis)_" if s["forca"] == 5 and m else ""


def _rotulo_vinculo(s: dict[str, Any], lado_recibo: bool) -> str:
    """A sugestão de vínculo como pergunta, do lado de quem está sendo perguntado."""
    if lado_recibo:
        return (f"o recibo {s['recibo']} ({brl(s['valor'])}) foi pago pelo *Pix de "
                f"{_extrato(s)}* ({_quando(s['pix_banco'], s['pix_data'], s.get('pix_pagina'))})"
                + _aviso(s))
    return (f"o Pix de {brl(s['valor'])} "
            f"({_quando(s['pix_banco'], s['pix_data'], s.get('pix_pagina'))}) pagou o "
            f"*recibo {s['recibo']} de {_de(s)}*" + _aviso(s))


def _nome(d: Divergencia) -> str:
    """O nome da divergência, com "CNPJ" na frente quando é de empresa (2026-10-28)."""
    return ("CNPJ " if d.get("cnpj") else "") + d["pessoa"]


def _extrato(s: dict[str, Any]) -> str:
    """A conta do Pix de uma sugestão, entre aspas (como no extrato): 'CNPJ "ESTUDIO LUMEN…"'."""
    return ("CNPJ " if s.get("pix_cnpj") else "") + f"\"{s['nome_no_extrato']}\""


def _de(s: dict[str, Any]) -> str:
    """A pessoa do recibo de uma sugestão, com "CNPJ" quando é de empresa."""
    return ("CNPJ " if s.get("recibo_cnpj") else "") + s["recibo_de"]


def titulo(d: Divergencia) -> str:
    """O nome da divergência nos textos; com o recibo quando a pessoa tem uma
    divergência por recibo ("LEOPOLDO GIRASSOL LUAR (recibo 0560-2026)")."""
    return _nome(d) + (f" (recibo {d['recibo']})" if d.get("recibo") else "")


def rotulo(d: Divergencia) -> str:
    """O nome num botão (cortado em 20 letras): o recibo vem antes."""
    return (f"Recibo {d['recibo'].split('-')[0]} — " if d.get("recibo") else "") + _nome(d)


def resumo(d: Divergencia) -> str:
    """Uma linha: o que há de errado e quanto ("Pix sem recibo: R$ 150,00")."""
    dif = abs(d["diferenca"])
    if not d["total_recibos"]:
        return f"Pix sem recibo: {brl(dif)}"
    if not d["total_extrato"]:
        return f"recibo sem Pix: {brl(dif)}"
    return f"{brl(dif)} a {'mais' if d['diferenca'] < 0 else 'menos'} no banco que nos recibos"


def agrupar(d: Divergencia, confirmadas: list[Confirmacao],
            ops: list[Confirmacao]) -> list[str] | None:
    """A pergunta com cada item já ligado à sua sugestão (2026-10-28):
    "Pode ser que paguem 2 recibos de HELIO…: 1) Pix de R$ 200,00 (…) →
    recibo 0867-2026". Só quando cada item que falta tem uma sugestão só,
    todas de vínculo e do mesmo lado; senão, None (vale a lista de itens e
    a de sugestões, como antes). A ordem é a das sugestões ("a 1", botões)."""
    recibos, pix = _pendentes(d, list(confirmadas))
    if not ops or any(o["tipo"] != "vinculo" for o in ops):
        return None
    sug = [d["sugestoes_vinculo"][int(o["id"][1:])] for o in ops]
    lado_recibo = {s["div_recibo"] == d["id"] for s in sug}
    if len(lado_recibo) != 1:
        return None
    lado_recibo = lado_recibo.pop()
    if lado_recibo:
        faltam, outro = sorted(r["numero"] for r in recibos), pix
        cobertos = sorted(o["recibo"] for o in ops)
    else:
        faltam, outro = sorted(chave_pix(x["banco"], x["data"], x["valor"]) for x in pix), recibos
        cobertos = sorted(o["pix"] for o in ops)
    if outro or faltam != cobertos:
        return None
    linhas = []
    if d["total_recibos"] and d["total_extrato"] and not explicados(d, list(confirmadas)):
        linhas.append(f"Recibos: {brl(d['total_recibos'])} · Extratos: "
                      f"{brl(d['total_extrato'])}")
    n = len(ops)
    quando = [_quando(s["pix_banco"], s["pix_data"], s.get("pix_pagina")) for s in sug]
    if lado_recibo:
        total = brl(round(sum(r["valor"] for r in recibos), 2))
        linhas.append(f"*{total} em recibo* que não aparece nos extratos." if n == 1 else
                      f"*{total} em {n} recibos* que não aparecem nos extratos.")
        contas = {_extrato(s) for s in sug}
        if len(contas) == 1:
            pago = "tenha sido pago" if n == 1 else "tenham sido pagos"
            linhas.append(f"\n*Pode ser que {pago} por Pix de {contas.pop()}:*")
            itens = [f"recibo {s['recibo']} ({brl(s['valor'])}) → *Pix de {q}*"
                     for s, q in zip(sug, quando)]
        else:
            linhas.append("\n*Pode ser que:*")
            itens = [f"recibo {s['recibo']} ({brl(s['valor'])}) → *Pix de "
                     f"{_extrato(s)}* ({q})" for s, q in zip(sug, quando)]
    else:
        total = brl(round(sum(x["valor"] for x in pix), 2))
        linhas.append(f"Entrou *{total}* no banco *sem recibo*." if n == 1 else
                      f"Entraram *{total}* no banco *sem recibo*, em {n} Pix desta conta.")
        pessoas = {_de(s) for s in sug}
        if len(pessoas) == 1:
            quais = "pague um recibo" if n == 1 else f"paguem {n} recibos"
            linhas.append(f"\n*Pode ser que {quais} de {pessoas.pop()}:*")
            itens = [f"Pix de {brl(s['valor'])} ({q}) → *recibo {s['recibo']}*"
                     for s, q in zip(sug, quando)]
        else:
            linhas.append("\n*Pode ser que paguem:*")
            itens = [f"Pix de {brl(s['valor'])} ({q}) → *recibo {s['recibo']} de "
                     f"{_de(s)}*" for s, q in zip(sug, quando)]
    linhas += [f"{i}) {t}{_aviso(s)}" for i, (t, s) in enumerate(zip(itens, sug), start=1)]
    return linhas


def _pendentes(d: Divergencia, confirmadas: list[Confirmacao]) -> tuple[list, list]:
    """Os recibos sem Pix e os Pix sem recibo que ainda não foram explicados."""
    falta = pendencias(d) - explicados(d, confirmadas)
    recibos, pix = [], []
    for r in d["recibos_sem_pix"]:
        if falta[f"R:{r['numero']}"] > 0:
            falta[f"R:{r['numero']}"] -= 1
            recibos.append(r)
    for x in d["pix_sem_recibo"]:
        chave = chave_pix(x["banco"], x["data"], x["valor"])
        if falta[chave] > 0:
            falta[chave] -= 1
            pix.append(x)
    return recibos, pix


def descrever(d: Divergencia, confirmadas: list[Confirmacao] = ()) -> str:
    """A divergência em linguagem simples, com os itens que ainda faltam
    explicar (sem `confirmadas`, todos)."""
    recibos, pix = _pendentes(d, list(confirmadas))
    linhas = []
    # com parte já confirmada, os totais da pessoa confundem: ficam só os itens que faltam
    if d["total_recibos"] and d["total_extrato"] and not explicados(d, list(confirmadas)):
        # só os totais: a diferença vem detalhada logo abaixo (2026-10-26)
        linhas.append(f"Recibos: {brl(d['total_recibos'])} · Extratos: "
                      f"{brl(d['total_extrato'])}")
    if pix:
        total = brl(round(sum(x["valor"] for x in pix), 2))
        linhas.append(f"Entrou *{total}* no banco *sem recibo*:")
        linhas += [f"• {brl(x['valor'])} em {_quando(x['banco'], x['data'], x.get('pagina'))}"
                   for x in pix]
    if recibos:
        total = brl(round(sum(r["valor"] for r in recibos), 2))
        linhas.append(f"*{total} em recibo* que não aparece nos extratos:")
        linhas += [f"• recibo {r['numero']}: {brl(r['valor'])}" for r in recibos]
    return "\n".join(linhas)
