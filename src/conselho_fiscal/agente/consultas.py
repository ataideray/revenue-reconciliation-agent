"""O lado do Conselho Fiscal: reconhecer o mês pedido e responder às
perguntas sobre um mês fechado (item 5 da IA, 2026-10-13).

A IA só diz o que o CF quer (`ia.Pergunta`: qual consulta, que meses, que
pessoa). As respostas são montadas aqui, com os números do mês, e não
passam pela IA (decisão do usuário: nenhum dado do mês vai para a IA).

Só meses fechados (pronto ou entregue) são consultados: de um mês que
ainda está com a tesouraria, o CF recebe só a situação, porque as notas
ainda podem mudar. Uma pergunta não envia o pacote. Ele vai só num pedido
(o mês sozinho, "manda julho" ou o botão), e só o envio conta como entrega.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from conselho_fiscal.agente import divergencias as dv
from conselho_fiscal.agente.formato import italico, negrito
from conselho_fiscal.comum.texto import norm_maiusculo
from conselho_fiscal.comum.valores import brl

MESES_PT = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
            "agosto", "setembro", "outubro", "novembro", "dezembro")
FECHADO = ("pronto", "entregue")
# o que cabe num pedido do pacote, além do mês: "pode me enviar julho?",
# "manda o pacote de julho/2026, por favor"
PALAVRAS_PEDIDO = {
    "PODE", "PODERIA", "ME", "NOS", "MANDA", "MANDE", "MANDAR", "ENVIA", "ENVIE", "ENVIAR",
    "RECEBER", "QUERO", "QUERIA", "GOSTARIA", "PRECISO", "DE", "DO", "DA", "O", "A", "OS",
    "AS", "AO", "PARA", "PRA", "MES", "PACOTE", "PLANILHA", "ARQUIVOS", "CONFERENCIA",
    "RECEITAS", "REFERENTE", "POR", "FAVOR", "PF", "PFV", "OI", "OLA", "BOM", "BOA", "DIA",
    "TARDE", "NOITE", "OBRIGADO", "OBRIGADA", "VOCE", "VC"}
MAX_DETALHES = 5    # divergências de uma pessoa numa resposta
AJUDA = ("Não sei responder isso. " + negrito("Sobre os meses prontos, posso:") + " enviar o "
         "pacote, resumir, listar as divergências, mostrar a nota de uma pessoa, dizer quanto "
         "entrou por destino e comparar meses.\n"
         + negrito("Exemplos:") + " \"manda julho\", \"quem teve divergência em julho?\", "
         "\"o que houve com a Eva?\", \"quanto entrou de açaí em julho?\".")
SO_DIVERGENCIAS = italico("Só guardo as divergências: quem pagou sem divergência não aparece "
                           "nas minhas consultas.")


def mes_extenso(mes: str) -> str:
    ano, m = mes.split("-")
    return f"{MESES_PT[int(m) - 1]}/{ano}"


def reconhecer_mes(texto: str, disponiveis: list[str],
                   hoje: date | None = None) -> str | None:
    """'2026-07', '07/2026', 'julho', 'julho de 2026' -> '2026-07'. Sem ano,
    usa o mês mais recente disponível; se o mês não estiver disponível, o
    último que já começou (julho, pedido em março de 2027, é julho de 2026)."""
    t = norm_maiusculo(texto)
    if m := re.search(r"(\d{4})-(\d{1,2})", t):
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    if m := re.search(r"\b(\d{1,2})/(\d{4})\b", t):
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    for i, nome in enumerate(MESES_PT, start=1):
        if norm_maiusculo(nome) in t:
            ano = re.search(r"\b(20\d{2})\b", t)
            if ano:
                return f"{ano.group(1)}-{i:02d}"
            candidatos = [d for d in disponiveis if d.endswith(f"-{i:02d}")]
            if candidatos:
                return candidatos[-1]
            hoje = hoje or date.today()
            return f"{hoje.year if i <= hoje.month else hoje.year - 1}-{i:02d}"
    return None


# "desse mês", "neste mês", "mês atual": não diz qual mês; o agente pergunta
MES_CORRENTE = re.compile(r"\b(?:(d|n)?(?:este|esse))\s+m[eê]s\b"
                          r"|\bm[eê]s\s+(?:atual|corrente|vigente)\b", re.IGNORECASE)


def cita_mes_corrente(texto: str) -> bool:
    """O texto fala "deste mês" (ou "esse mês", "mês atual"...) sem dizer qual."""
    return bool(MES_CORRENTE.search(texto or ""))


def com_mes(texto: str, mes: str) -> str:
    """Troca "deste mês" pelo mês escolhido: "quanto deu o açaí desse mês?" ->
    "quanto deu o açaí de julho de 2026?"."""
    nome, ano = mes_extenso(mes).split("/")

    def trocar(m: re.Match) -> str:
        prep = {"d": "de ", "n": "em "}.get((m.group(1) or "").lower(), "")
        return f"{prep}{nome} de {ano}"
    return MES_CORRENTE.sub(trocar, texto)


def so_pedido(texto: str) -> bool:
    """O texto só pede o mês, sem pergunta: "julho", "pode me enviar julho?".
    Dois meses ("junho e julho") ou qualquer outra palavra deixam de ser só
    um pedido e passam pela IA."""
    t = re.sub(r"\d{4}-\d{1,2}|\b\d{1,2}/\d{4}\b|\b20\d{2}\b", " ", norm_maiusculo(texto))
    palavras = re.findall(r"[A-Z]+", t)
    meses = [p for p in palavras if p in {norm_maiusculo(m) for m in MESES_PT}]
    return len(meses) <= 1 and all(p in PALAVRAS_PEDIDO or p in meses for p in palavras)


def fechado(est: dict[str, Any] | None) -> bool:
    return bool(est) and est["situacao"] in FECHADO


def situacao(est: dict[str, Any]) -> str:
    """De um mês fechado: 'pronto, ainda não enviado ao Conselho Fiscal', …"""
    if est["situacao"] == "entregue":
        return f"enviado ao Conselho Fiscal em {est['entregas'][-1]['em'][:10]}"
    if est["entregas"]:
        return ("pronto; o Conselho Fiscal recebeu uma versão anterior em "
                f"{est['entregas'][-1]['em'][:10]}")
    return "pronto, ainda não enviado ao Conselho Fiscal"


def _soma(valores: list[float]) -> str:
    return brl(round(sum(valores), 2))


def totais(est: dict[str, Any]) -> str:
    ds = est["divergencias"]
    if not ds:
        return "• Nenhuma divergência"
    recibos = [r["valor"] for d in ds for r in d["recibos_sem_pix"]]
    pix = [p["valor"] for d in ds for p in d["pix_sem_recibo"]]
    return (f"• {len(ds)} divergência(s), todas com nota da tesouraria\n"
            f"• Recibos sem Pix: {len(recibos)}, somando {_soma(recibos)}\n"
            f"• Pix sem recibo: {len(pix)}, somando {_soma(pix)}")


def resumo(est: dict[str, Any], conferencias: list[dict[str, Any]]) -> str:
    """Os números gerais do mês. `conferencias`: as do JSON da conferência
    (pode ser vazio, se o arquivo não estiver lá)."""
    r = est["resumo"]
    linhas = [negrito(f"Receitas de {mes_extenso(est['mes'])} — versão {est['versao']}")
              + f" ({situacao(est)})"]
    for c in conferencias:
        if c["verificacao"].startswith("Total de receitas"):
            linhas.append(f"• Total no registro de receitas: {c['encontrado']}")
    for banco, no in (("cora", "no Cora"), ("stone", "na Stone")):
        n, valor = r[f"ent_{banco}"], r.get(f"valor_{banco}")
        # meses conferidos antes de 2026-10-13 não têm a soma
        linhas.append(f"• Pix recebidos {no}: {n}"
                      + (f", somando {brl(valor)}" if valor is not None else ""))
    linhas += [f"• {r['recibos']} recibos: {r['conformes']} conformes, "
               f"{r['divergentes']} divergentes",
               totais(est)]
    linhas += [f"⚠️ [{a['extrato']}] {a['verificacao']}: {a['status']}" for a in est["alertas"]]
    return "\n".join(linhas)


def lista(est: dict[str, Any], opcoes: bool = True) -> str:
    ds = est["divergencias"]
    if not ds:
        return f"Nenhuma divergência em {mes_extenso(est['mes'])}: tudo confere."
    linhas = [negrito(f"Divergências de {mes_extenso(est['mes'])} ({len(ds)})")
              + ", todas com nota da tesouraria:"]
    linhas += [f"{i}. {negrito(dv.titulo(d))} — {dv.resumo(d)}"
               for i, d in enumerate(ds, start=1)]
    if opcoes:
        linhas.append(italico("Para ver os itens e a nota de uma, escolha nas opções ou "
                              "pergunte pelo nome."))
    return "\n".join(linhas)


def detalhe(est: dict[str, Any], d: dv.Divergencia) -> str:
    nota = est["notas"].get(d["id"], {}).get("texto", "")
    return (f"{negrito(mes_extenso(est['mes']).capitalize())}\n{dv.descrever(d)}\n"
            f"{negrito('Nota da tesouraria:')} {nota or '(sem nota)'}")


def _palavras(nome: str) -> set[str]:
    return {p for p in re.findall(r"\w+", norm_maiusculo(nome))
            if len(p) >= 3 and p not in {"DAS", "DOS"}}


def achar(nome: str, meses: list[dict[str, Any]]) -> list[tuple[dict[str, Any],
                                                               dv.Divergencia]]:
    """As divergências de `nome` nos meses dados: o nome inteiro ou todas as
    palavras dele ("Eva Olmo" acha EVA OLMO GIRASOL)."""
    alvo, palavras = norm_maiusculo(nome), _palavras(nome)
    achadas = []
    for est in meses:
        for d in est["divergencias"]:
            if norm_maiusculo(d["pessoa"]) == alvo or (
                    palavras and palavras <= _palavras(d["pessoa"])):
                achadas.append((est, d))
    return achadas


def da_pessoa(nome: str, meses: list[dict[str, Any]]) -> str:
    """A divergência e a nota de `nome` em cada mês fechado dado."""
    achadas = achar(nome, meses)
    if not achadas:
        onde = ", ".join(mes_extenso(e["mes"]) for e in meses) or "nenhum mês fechado"
        return f"Não encontrei divergência de {nome} ({onde}). {SO_DIVERGENCIAS}"
    partes = [detalhe(est, d) for est, d in achadas[:MAX_DETALHES]]
    if len(achadas) > MAX_DETALHES:
        partes.append(f"… e mais {len(achadas) - MAX_DETALHES}. "
                      + italico("Pergunte por um mês só."))
    return "\n\n".join(partes)
