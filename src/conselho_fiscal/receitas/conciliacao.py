"""Conciliação dos recibos com os Pix dos extratos.

Automático (só dentro da MESMA pessoa):
  - 1 recibo : 1 Pix de mesmo valor;
  - 1 recibo : 2 Pix da mesma pessoa que somam o valor (B7).
Nunca automático, vira SUGESTÃO confirmada com a tesouraria:
  - ligar Pix de uma conta com outro nome ao recibo de alguém (decisão de
    2026-10-06);
  - devolução: Pix sem recibo devolvido à mesma pessoa (B4; decisão de
    2026-10-08).
"""

from __future__ import annotations

import logging
import re
from itertools import combinations
from typing import Any

from conselho_fiscal.cadastros.destinos import chave as chave_destino
from conselho_fiscal.cadastros.vinculos import VinculoConfirmado
from conselho_fiscal.comum.texto import norm_maiusculo, strip_acentos
from conselho_fiscal.comum.valores import brl, data_ordenavel, mesmo_valor
from conselho_fiscal.extratos.modelo import Transacao, Verificacao
from conselho_fiscal.receitas.lancamentos import Recibo
from conselho_fiscal.receitas.pessoas import (
    Pessoa,
    limpar_nome_extrato,
    mesmo_nome,
    nomes_parecidos,
    tokens_relevantes,
)

log = logging.getLogger(__name__)

MAX_PIX_POR_RECIBO = 2          # decisão de 2026-10-06
LIMIAR_RENDIMENTO = 2.00        # rendimento bancário genuíno é sempre centavos
NOME_RENDIMENTO_SUSPEITO = "Rendimento (valor suspeito — revisar)"


# ---------- Pix recebidos e enviados ----------

CNPJ_RE = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
# nome de empresa: sufixo societário, ou a razão social do MEI, que leva o CPF
# no fim ("NOELI P J 12345678901") ou a raiz do CNPJ no começo ("12.345.678 NOELI")
EMPRESA_RE = re.compile(r"\b(LTDA|EIRELI|S/A)\b|\b(EPP|MEI|CNPJ|S\.A)\.?$"
                        r"|\S+\s+\S+\s+ME\.?$|\s\d{11}$|^\d{2}\.\d{3}\.\d{3}\s")
# a Stone às vezes cola a instituição de quem pagou ("FULANO Banco Bradesco S.A.",
# "FULANO NU PAGAMENTOS S.A. - <CPF> …"): o nome vale só até ela
INSTITUICAO_RE = re.compile(r"\s*\b(BANCO|ITAU|UNIBANCO|INSTITUICAO|MERCADO PAGO|PAGSEGURO|"
                            r"99PAY|RECARGAPAY|NU PAGAMENTOS|PICPAY|SOCIEDADE DE CREDITO)\b.*$")


def eh_cnpj(documento: str = "", nome: str = "") -> bool:
    """A conta (ou o recibo) é de um CNPJ: pelo documento do extrato (o
    Cora traz CPF ou CNPJ) ou, sem ele, pelo nome. Só a marca vai para o
    JSON, nunca o número (2026-10-28)."""
    if documento:
        return bool(CNPJ_RE.fullmatch(documento.strip()))
    nome = INSTITUICAO_RE.sub("", norm_maiusculo(nome or "").strip())
    return bool(EMPRESA_RE.search(nome))


def _nome_de_rendimento(nome: str) -> bool:
    nh = norm_maiusculo(nome)
    return "RENDIMENTO" in nh or "AUTOMATICO" in nh


def rendimentos(transacoes: list[Transacao]) -> list[float]:
    """Os 'Rendimento automático' genuínos do extrato (até R$ 2,00), os
    mesmos que `entradas` deixa de fora."""
    return [round(t["entrada"], 2) for t in transacoes
            if t["entrada"] and abs(t["entrada"]) <= LIMIAR_RENDIMENTO
            and _nome_de_rendimento(limpar_nome_extrato(t["nome"] or ""))]


def conferir_rendimentos(pivotado: dict[str, Any], transacoes_cora: list[Transacao],
                         transacoes_stone: list[Transacao]) -> Verificacao:
    """Soma da coluna Rendimentos da planilha (todos os recibos: a tesouraria
    lança um por rendimento ou um pelo mês) = soma dos rendimentos dos
    extratos. Os dois lados ficam fora da conciliação recibo × Pix."""
    coluna = next((c for c in pivotado["colunas"] if chave_destino(c) == "rendimento"), None)
    recibos = [lin[coluna] for lin in pivotado["linhas"] if coluna and lin.get(coluna)]
    planilha = round(sum(recibos), 2)
    por_banco = {"Stone": rendimentos(transacoes_stone), "Cora": rendimentos(transacoes_cora)}
    extratos = round(sum(sum(v) for v in por_banco.values()), 2)
    status = "OK" if mesmo_valor(extratos, planilha) else "ALERTA"
    lados = "; ".join(f"{banco}: {len(v)} lançamento(s), {brl(round(sum(v), 2))}"
                      if v else f"{banco}: nenhum" for banco, v in por_banco.items())
    return {"grupo": "planilha", "extrato": "Rendimentos",
            "verificacao": "Rendimentos (extratos × planilha)", "status": status,
            "esperado": brl(extratos), "encontrado": brl(planilha),
            "rotulos": ("Extratos", "Planilha"),
            "detalhe": (f"Extratos: {lados}. Planilha: {len(recibos)} recibo(s) na coluna "
                        "Rendimentos." if status == "ALERTA" else "")}


def entradas(transacoes: list[Transacao]) -> list[dict[str, Any]]:
    """Pix recebidos, na ordem do extrato.

    'Rendimento automático' de centavos é ignorado. Acima de R$ 2,00 não é
    rendimento genuíno: é quase certamente um Pix com o nome perdido na
    leitura, e entra como entrada sem dono, para a tesouraria explicar.
    """
    lista, suspeitas = [], 0
    for t in transacoes:
        v = t["entrada"]
        if not v:
            continue
        nome = t["nome"]
        if not nome or str(nome).strip().upper() == "TOTAL":
            continue
        nome = limpar_nome_extrato(nome)
        if not nome:
            continue
        if _nome_de_rendimento(nome):
            if abs(v) <= LIMIAR_RENDIMENTO:
                continue
            nome = NOME_RENDIMENTO_SUSPEITO
            suspeitas += 1
        lista.append({"nome": nome, "valor": round(v, 2), "banco": t["banco"], "data": t["data"],
                      "pagina": t.get("pagina"),
                      "cnpj": eh_cnpj(str(t.get("documento") or ""), nome)})
    if suspeitas:
        log.warning("%s lançamento(s) 'Rendimento automático' acima de R$ %.2f: tratados como "
                    "possível Pix com nome perdido na leitura", suspeitas, LIMIAR_RENDIMENTO)
    return lista


def saidas(transacoes: list[Transacao]) -> list[dict[str, Any]]:
    """Pix enviados (usados só para achar devoluções)."""
    lista = []
    for t in transacoes:
        if not t["saida"]:
            continue
        nome = limpar_nome_extrato(t["nome"] or "")
        if not nome or norm_maiusculo(nome) == "TOTAL":
            continue
        lista.append({"nome": nome, "valor": round(abs(t["saida"]), 2),
                      "banco": t["banco"], "data": t["data"], "pagina": t.get("pagina")})
    return lista


# ---------- casamento recibo × Pix (mesma pessoa) ----------

def casar(p: Pessoa) -> dict[int, list[dict[str, Any]]]:
    """id(recibo) -> Pix casados ([] = nenhum), sempre dentro da pessoa.

    1) 1 recibo : 1 Pix de mesmo valor (prioridade);
    2) recibos que sobraram: até MAX_PIX_POR_RECIBO Pix que também sobraram
       e somam o valor. Se houver mais de uma combinação com valores
       diferentes, não combina (fica Divergente).
    """
    ents = sorted(p["entradas"], key=lambda e: e["ordem"])
    usados = [False] * len(ents)
    casamento: dict[int, list] = {}
    recibos = sorted(p["recibos"], key=lambda x: -x["valor"])
    for rec in recibos:
        casamento[id(rec)] = []
        for i, e in enumerate(ents):
            if not usados[i] and mesmo_valor(e["valor"], rec["valor"]):
                usados[i] = True
                casamento[id(rec)] = [e]
                break
    for rec in recibos:
        if casamento[id(rec)]:
            continue
        livres = [i for i in range(len(ents)) if not usados[i]]
        achadas: dict[tuple, tuple] = {}
        for n in range(2, MAX_PIX_POR_RECIBO + 1):
            for combo in combinations(livres, n):
                if mesmo_valor(sum(ents[i]["valor"] for i in combo), rec["valor"]):
                    valores = tuple(sorted(round(ents[i]["valor"], 2) for i in combo))
                    achadas.setdefault(valores, combo)   # 1ª = Pix mais antigos
        if len(achadas) == 1:
            combo = next(iter(achadas.values()))
            for i in combo:
                usados[i] = True
            casamento[id(rec)] = [ents[i] for i in combo]
    return casamento


def _pix_usados(casamento: dict[int, list]) -> set[int]:
    return {id(e) for es in casamento.values() for e in es}


# ---------- devoluções ----------

def sugerir_devolucoes(pessoas: dict[str, Pessoa], saidas_: list[dict[str, Any]]
                       ) -> list[dict[str, Any]]:
    """Sugere (NUNCA aplica) que um Pix SEM recibo foi devolvido à mesma
    pessoa (ex.: um Pix pago a mais e devolvido dias depois). O Pix continua
    nos totais da pessoa, que fica em Divergências até a tesouraria confirmar.

    Critério: o nome da saída casa com UMA única pessoa; só Pix que sobraram
    (um recibo 'Conforme' nunca é afetado); mesmo valor; saída na mesma data
    ou depois (com várias opções, a mais próxima antes da saída). Cada Pix é
    sugerido para no máximo uma saída. Roda antes das sugestões de vínculo,
    que ignoram esses Pix.
    """
    devolucoes, sugeridos = [], set()
    for sai in saidas_:
        candidatas = [p for p in pessoas.values()
                      if any(mesmo_nome(sai["nome"], n) for n in p["nomes"])]
        if len(candidatas) != 1:
            continue
        p = candidatas[0]
        usados = _pix_usados(casar(p)) | sugeridos
        d_sai = data_ordenavel(sai["data"])
        possiveis = [e for e in p["entradas"]
                     if id(e) not in usados and mesmo_valor(e["valor"], sai["valor"])
                     and (d_sai is None or data_ordenavel(e.get("data")) is None
                          or data_ordenavel(e.get("data")) <= d_sai)]
        if not possiveis:
            continue
        ent = max(possiveis, key=lambda e: (data_ordenavel(e.get("data")) or (0, 0, 0), e["ordem"]))
        sugeridos.add(id(ent))
        devolucoes.append({
            "pessoa": p["nome"], "valor": ent["valor"],
            "entrada_banco": ent["banco"], "entrada_data": ent.get("data"),
            "entrada_pagina": ent.get("pagina"),
            "saida_nome": sai["nome"], "saida_banco": sai["banco"], "saida_data": sai["data"],
            "saida_pagina": sai.get("pagina"),
            "div": id_divergencia(p["nome"]),
            "_pix": id(ent),      # uso interno: o Pix não recebe sugestão de vínculo
        })
    return devolucoes


def onde(banco: str, data: str | None, pagina: int | None = None) -> str:
    """'Stone, 20/07/26, pág. 3' (a página do PDF, quando se sabe)."""
    return f"{banco}, {data}" + (f", pág. {pagina}" if pagina else "")


def texto_devolucao(d: dict[str, Any]) -> str:
    """Texto curto de uma possível devolução."""
    return (f"Possível devolução: Pix {brl(d['valor'])} "
            f"({onde(d['entrada_banco'], d['entrada_data'], d.get('entrada_pagina'))}) ↔ saída "
            f"para \"{d['saida_nome']}\" "
            f"({onde(d['saida_banco'], d['saida_data'], d.get('saida_pagina'))}) — mesma pessoa, "
            "mesmo valor")


# ---------- sugestões de vínculo (nunca aplicadas) ----------

def id_divergencia(nome: str, recibo: str | None = None) -> str:
    """Id estável ('DIV-<NOME>', ou 'DIV-<NOME>-<RECIBO>' na divergência de um
    recibo só): num reenvio, a mesma divergência mantém o id."""
    texto = strip_acentos(nome + (f" {recibo}" if recibo else "")).upper()
    return "DIV-" + re.sub(r"[^A-Z0-9]+", "-", texto).strip("-")


def por_recibo(p: Pessoa, casamento: dict[int, list] | None = None) -> bool:
    """A pessoa só tem recibos sem Pix, mais de um, e nenhum Pix sobrando: uma
    divergência por recibo (2026-10-26), porque cada um pode ter sido pago por
    uma conta diferente (ex.: um pela esposa, outro pela empresa). Com Pix
    sobrando, fica uma só: o Pix pode explicar mais de um."""
    casamento = casar(p) if casamento is None else casamento
    sem_pix = [r for r in p["recibos"] if not casamento[id(r)]]
    return len(sem_pix) > 1 and not set(id(e) for e in p["entradas"]) - _pix_usados(casamento)


def div_do_recibo(p: Pessoa, r: Recibo, casamento: dict[int, list] | None = None) -> str:
    """O id da divergência em que o recibo (sem Pix) aparece."""
    return id_divergencia(p["nome"], r["celulas"][0] if por_recibo(p, casamento) else None)


def ids_da_pessoa(p: Pessoa) -> list[str]:
    """Os ids das divergências da pessoa (um, ou um por recibo sem Pix)."""
    casamento = casar(p)
    if not por_recibo(p, casamento):
        return [id_divergencia(p["nome"])]
    return [id_divergencia(p["nome"], r["celulas"][0]) for r in p["recibos"]
            if not casamento[id(r)]]


def nota_da_pessoa(p: Pessoa, notas: dict[str, str]) -> str:
    """As notas das divergências da pessoa, juntas (para as abas por pessoa)."""
    return "\n".join(n for i in ids_da_pessoa(p) if (n := notas.get(i)))


def sugerir_vinculos(pessoas: dict[str, Pessoa],
                     confirmados: list[VinculoConfirmado] = (),
                     devolucoes: list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """Sugere (NUNCA aplica) que um Pix sem recibo de uma conta pagou um
    recibo sem Pix de OUTRA pessoa, de mesmo valor. Pix com sugestão de
    devolução ficam de fora. Critérios, do mais forte (1) para o mais fraco
    (5):
      1) conta já confirmada pela tesouraria antes (cadastro de vínculos);
      2) nome em comum (inclusive sobrenomes comuns) ou nome parecido;
      3) outro Pix da mesma conta tem pista de nome com a pessoa;
      4) valor único no mês;
      5) mesmo valor, com vários recibos possíveis.
    """
    pix_pendentes, recibos_pendentes = [], []
    devolvidos = {d["_pix"] for d in devolucoes}
    for p in pessoas.values():
        casamento = casar(p)
        usados = _pix_usados(casamento) | devolvidos
        pix_pendentes += [(p, e) for e in sorted(p["entradas"], key=lambda e: e["ordem"])
                          if id(e) not in usados]
        recibos_pendentes += [(p, r) for r in p["recibos"] if not casamento[id(r)]]

    def confirmacao(nome_extrato: str, pessoa: Pessoa):
        return next((c for c in confirmados
                     if mesmo_nome(c["nome_extrato"], nome_extrato)
                     and any(mesmo_nome(c["pessoa"], n) for n in pessoa["nomes"])), None)

    def em_comum(nome_extrato: str, pessoa: Pessoa) -> list[str]:
        da_pessoa = set().union(*(tokens_relevantes(n) for n in pessoa["nomes"]))
        return sorted(tokens_relevantes(nome_extrato) & da_pessoa)

    candidatos = [(a, e, [(b, r) for b, r in recibos_pendentes
                          if b is not a and mesmo_valor(r["valor"], e["valor"])])
                  for a, e in pix_pendentes]
    contas_com_evidencia = {(id(a), id(b)) for a, e, cands in candidatos for b, _ in cands
                            if confirmacao(e["nome"], b) or em_comum(e["nome"], b)
                            or nomes_parecidos(e["nome"], b["nomes"])}

    sugestoes = []
    for a, e, cands in candidatos:
        for b, r in cands:
            c = confirmacao(e["nome"], b)
            comuns = em_comum(e["nome"], b)
            parecidos = [] if comuns else nomes_parecidos(e["nome"], b["nomes"])
            if c:
                criterio, forca = f"conta já confirmada pela tesouraria ({c['confirmado_em']})", 1
            elif comuns:
                criterio, forca = f"nome em comum ({', '.join(comuns).title()})", 2
            elif parecidos:
                criterio, forca = f"nome parecido ({', '.join(parecidos)})", 2
            elif (id(a), id(b)) in contas_com_evidencia:
                criterio, forca = "outro Pix da mesma conta tem pista de nome com esta pessoa", 3
            elif len(cands) == 1:
                criterio, forca = "valor único no mês (sem pista de nome)", 4
            else:
                criterio, forca = f"mesmo valor ({len(cands)} recibos possíveis)", 5
            sugestoes.append({
                "pix_de": a["nome"], "nome_no_extrato": e["nome"], "valor": e["valor"],
                "pix_banco": e["banco"], "pix_data": e.get("data"), "pix_pagina": e.get("pagina"),
                "recibo": r["celulas"][0], "recibo_de": b["nome"],
                "pix_cnpj": e.get("cnpj", False), "recibo_cnpj": eh_cnpj(nome=b["nome"]),
                "criterio": criterio, "forca": forca,
                "div_pix": id_divergencia(a["nome"]), "div_recibo": div_do_recibo(b, r),
                "_rec": id(r),        # uso interno: localizar o recibo na planilha
            })
    sugestoes.sort(key=lambda x: (x["forca"], x["recibo"]))
    return sugestoes


def publicas(sugestoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sugestões (de vínculo ou de devolução) sem os campos internos (para o JSON)."""
    return [{k: v for k, v in s.items() if not k.startswith("_")} for s in sugestoes]


def texto_sugestao(s: dict[str, Any], lado: str) -> str:
    """Texto curto de uma sugestão, do ponto de vista do recibo ou do Pix."""
    if lado == "recibo":
        return (f"Recibo {s['recibo']} ({brl(s['valor'])}) ↔ Pix de \"{s['nome_no_extrato']}\" "
                f"({onde(s['pix_banco'], s['pix_data'], s.get('pix_pagina'))}) — {s['criterio']}")
    return (f"Pix {brl(s['valor'])} ({onde(s['pix_banco'], s['pix_data'], s.get('pix_pagina'))}) "
            f"↔ recibo {s['recibo']} de {s['recibo_de']} — {s['criterio']}")


# ---------- situação por pessoa e divergências ----------

def status_pessoa(p: Pessoa) -> tuple[str, float]:
    total_recibos = round(p["tot_recibo"], 2)
    total_extrato = round(p["tot_cora"] + p["tot_stone"], 2)
    dif = round(total_recibos - total_extrato, 2)
    if total_recibos == 0 and total_extrato > 0:
        return "Sem recibo (só extrato)", dif
    if total_extrato == 0 and total_recibos > 0:
        return "Sem extrato (só recibo)", dif
    if abs(dif) <= 0.005:
        return "OK", dif
    return "Divergência de valor", dif


def ordenar_pessoas(pessoas: dict[str, Pessoa]) -> list[Pessoa]:
    """Na ordem do 1º Pix no extrato; quem não tem Pix vai para o fim."""
    return sorted(pessoas.values(),
                  key=lambda p: (p["primeira_ordem"] is None, p["primeira_ordem"] or 0))


def _cnpj(p: Pessoa) -> bool:
    """A pessoa da divergência é um CNPJ: um Pix dela veio de CNPJ, ou o nome
    é de empresa."""
    return any(e.get("cnpj") for e in p["entradas"]) or eh_cnpj(nome=p["nome"])


def detalhar_divergencias(ordenadas: list[Pessoa], sugestoes: list[dict[str, Any]] = (),
                          notas: dict[str, str] | None = None,
                          devolucoes: list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """Uma entrada por pessoa que não está OK (ou uma por recibo, veja
    `por_recibo`): recibos sem Pix, Pix sem recibo, sugestões de vínculo e
    possíveis devoluções que a envolvem e a nota da tesouraria (preenchida
    pelo agente: notas = {id: texto})."""
    notas = notas or {}
    divergencias = []

    def sugestoes_de(did: str) -> list[dict[str, Any]]:
        return publicas([s for s in sugestoes if did in (s["div_pix"], s["div_recibo"])])

    for p in ordenadas:
        st, dif = status_pessoa(p)
        if st == "OK":
            continue
        casamento = casar(p)
        usados = _pix_usados(casamento)
        if por_recibo(p, casamento):
            for r in p["recibos"]:
                if casamento[id(r)]:
                    continue
                did = id_divergencia(p["nome"], r["celulas"][0])
                divergencias.append({
                    "id": did, "pessoa": p["nome"], "cnpj": _cnpj(p), "recibo": r["celulas"][0],
                    "tipo": "Sem extrato (só recibo)",
                    "total_recibos": round(r["valor"], 2), "total_extrato": 0.0,
                    "diferenca": round(r["valor"], 2),
                    "recibos_sem_pix": [{"numero": r["celulas"][0], "valor": r["valor"]}],
                    "pix_sem_recibo": [], "sugestoes_vinculo": sugestoes_de(did),
                    "devolucoes_possiveis": [], "nota_tesouraria": notas.get(did, ""),
                })
            continue
        did = id_divergencia(p["nome"])
        divergencias.append({
            "id": did, "pessoa": p["nome"], "cnpj": _cnpj(p), "tipo": st,
            "total_recibos": round(p["tot_recibo"], 2),
            "total_extrato": round(p["tot_cora"] + p["tot_stone"], 2),
            "diferenca": dif,
            "recibos_sem_pix": [{"numero": r["celulas"][0], "valor": r["valor"]}
                                for r in p["recibos"] if not casamento[id(r)]],
            "pix_sem_recibo": [{"valor": e["valor"], "banco": e["banco"], "data": e.get("data"),
                                "nome_no_extrato": e.get("nome"), "pagina": e.get("pagina"),
                                "cnpj": e.get("cnpj", False)}
                               for e in sorted(p["entradas"], key=lambda e: e["ordem"])
                               if id(e) not in usados],
            "sugestoes_vinculo": sugestoes_de(did),
            "devolucoes_possiveis": publicas([d for d in devolucoes if d["div"] == did]),
            "nota_tesouraria": notas.get(did, ""),
        })
    return divergencias


def ordenar_recibos(pessoas: dict[str, Pessoa]) -> list[tuple[Pessoa, Recibo]]:
    """Recibos na ordem FIEL aos extratos: cada recibo na posição do Pix com
    que casou (Cora primeiro, Stone depois). Sem Pix, usa o próximo Pix livre
    da pessoa; sem Pix algum, vai para o fim. Preenche rec['compat']."""
    fim = 10 ** 9
    itens = []
    for p in pessoas.values():
        casamento = casar(p)
        usados = _pix_usados(casamento)
        livres = [e for e in sorted(p["entradas"], key=lambda e: e["ordem"]) if id(e) not in usados]
        proximo_livre = 0
        for rec in sorted(p["recibos"], key=lambda x: -x["valor"]):
            pix = casamento[id(rec)]
            if len(pix) == 1:
                pos, compat = pix[0]["ordem"], "Conforme"
            elif pix:
                pos, compat = min(e["ordem"] for e in pix), f"Conforme ({len(pix)} Pix)"
            else:
                compat = "Divergente"
                if proximo_livre < len(livres):
                    pos = livres[proximo_livre]["ordem"]
                    proximo_livre += 1
                else:
                    pos = p["primeira_ordem"] if p["primeira_ordem"] is not None else fim
            rec["compat"] = compat
            itens.append((pos, str(rec["celulas"][0]), p, rec))
    itens.sort(key=lambda t: (t[0], t[1]))
    return [(p, rec) for _, _, p, rec in itens]
