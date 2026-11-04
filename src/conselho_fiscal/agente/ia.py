"""Interpretação das respostas livres da tesouraria.

O agente pergunta uma divergência por vez. Quando a tesouraria responde com
texto (e não pelos botões), um `Interpretador` lê a resposta e devolve uma
`Interpretacao`: que sugestões ela confirmou, que trecho explica a
divergência, se a resposta explica o que falta e se ela quer responder
depois. O interpretador só lê: quem confere a interpretação (número de
sugestão existente, item ainda livre) e grava é o agente.

O interpretador também redige a nota para o CF (`redigir`): a partir dos
fatos da divergência, do que foi confirmado e do que a tesouraria escreveu,
um texto claro, que a tesouraria aprova antes de valer (decisão de
2026-10-09). A redação não pode trazer número que não esteja nos fatos nem
na resposta (`de_redacao`): a IA não faz conta.

Quando a regra fixa do agente não reconhece um pedido simples (menu, ajuda,
trocar de papel), a IA diz qual é (`comando` na interpretação e na consulta
do CF; `comando` sozinho para a tesouraria sem pergunta aberta;
2026-10-26). Vai só o texto, com os nomes trocados pelos apelidos.

E atende as perguntas do CF: `entender` diz qual consulta ele quer, de que
meses e de que pessoa; `agente.consultas` busca os dados; `responder`
escreve a resposta à pergunta só com esses dados. Como na nota, a resposta
não pode trazer número que não esteja nos dados (decisão de 2026-10-13).

  - `SemIA`: o comportamento sem IA (o texto vira a nota). É o padrão e a
    reserva quando a IA falha.
  - `agente.gemini.Gemini`: o adaptador do Gemini. Ele envia só o que
    `para_ia` monta (veja abaixo) e devolve `de_ia(...)`.
  - nos testes, um interpretador falso devolve respostas prontas.

O que sai da máquina (decisão de 2026-10-09: o mínimo possível):
  - da divergência e das sugestões: valores, datas, banco e número do
    recibo. Nomes de pessoas e de contas viram apelidos (PESSOA_A, …), e
    o critério das sugestões não vai (ele cita pedaços de nomes);
  - do extrato, nada além disso: nem a descrição, nem CPF;
  - o texto da tesouraria, com os nomes conhecidos trocados pelos apelidos
    (os da divergência e os das outras divergências do mês) e números com
    cara de CPF mascarados. Um nome que não aparece em nenhuma divergência
    (ex.: "a mãe dela, Noeli") vai como foi escrito;
  - da pergunta do CF: o texto, com os nomes das divergências de todos os
    meses trocados pelos apelidos, a data de hoje e os meses com dados;
  - para a resposta ao CF: a pergunta e os dados que o agente achou
    (resumo do mês, divergências com os itens e as notas da tesouraria),
    com os mesmos apelidos e CPFs mascarados.
Na volta, os apelidos são trocados de novo pelos nomes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from conselho_fiscal.comum.texto import norm_maiusculo
from conselho_fiscal.comum.valores import brl


@dataclass(frozen=True)
class Contexto:
    divergencia: dict[str, Any]     # como em resultado["divergencias"]
    sugestoes: list[dict[str, Any]]  # dv.opcoes, na ordem da pergunta (1, 2, …)
    ja_confirmado: list[dict[str, Any]]   # confirmações que já tocam a divergência
    texto: str                      # a resposta da tesouraria
    # nomes das divergências do mês, (nome, é conta do extrato), só para os apelidos
    outros_nomes: tuple[tuple[str, bool], ...] = ()


@dataclass(frozen=True)
class Interpretacao:
    confirmar: tuple[int, ...] = ()     # números das sugestões confirmadas (a partir de 1)
    explicacao: str = ""                # trecho da resposta que explica (sem reescrever)
    suficiente: bool = True             # a resposta explica o que falta na divergência?
    adiar: bool = False                 # "vou ver", "depois respondo"
    pergunta: str = ""                  # o que pedir de volta, quando insuficiente
    nome_errado: bool = False           # o recibo saiu com o nome errado: é a mesma pessoa
    comando: str = "nenhum"             # um pedido ao agente, não uma resposta (COMANDOS)


@dataclass(frozen=True)
class ContextoNota:
    divergencia: dict[str, Any]
    confirmadas: list[dict[str, Any]]    # confirmações que tocam a divergência
    respostas: list[str]                 # o que a tesouraria escreveu (pode ser nada)
    outros_nomes: tuple[tuple[str, bool], ...] = ()


# pedidos simples ao agente, quando a regra fixa não reconhece ("me mostra as
# opções", "me explica como você funciona", "quero falar como conselho")
COMANDOS = ("nenhum", "menu", "ajuda", "trocar_cf", "trocar_tesouraria", "trocar")
CONSULTAS = ("pacote", "resumo", "divergencias", "pessoa", "comparar", "destino", "situacao",
             "outra") + COMANDOS[1:]


@dataclass(frozen=True)
class ContextoPergunta:
    texto: str                      # a mensagem do CF
    hoje: str                       # AAAA-MM-DD, para "o mês passado"
    meses: tuple[str, ...]          # meses com dados (AAAA-MM)
    nomes: tuple[tuple[str, bool], ...] = ()    # das divergências, só para os apelidos


@dataclass(frozen=True)
class Pergunta:
    consulta: str                   # uma das CONSULTAS
    meses: tuple[str, ...] = ()     # AAAA-MM
    pessoa: str = ""                # o nome (de volta do apelido) ou como o CF escreveu
    destino: str = ""               # na consulta "destino": "açaí", como o CF escreveu


@dataclass(frozen=True)
class ContextoComando:
    texto: str                      # a mensagem
    papel: str                      # "tesouraria" ou "cf"
    nomes: tuple[tuple[str, bool], ...] = ()    # das divergências, só para os apelidos


@dataclass(frozen=True)
class ContextoResposta:
    pergunta: str                   # a mensagem do CF
    dados: str                      # o que o agente achou (`agente.consultas`)
    nomes: tuple[tuple[str, bool], ...] = ()    # das divergências, só para os apelidos


class Interpretador(Protocol):
    nome: str       # vai para a nota, para auditoria (ex.: provedor e modelo)

    def interpretar(self, contexto: Contexto) -> Interpretacao: ...

    def redigir(self, contexto: ContextoNota) -> str:
        """A nota para o CF; "" quando não redige (fica a nota montada)."""
        ...

    def entender(self, contexto: ContextoPergunta) -> Pergunta | None:
        """O que o CF pergunta; None quando não entende (sem IA)."""
        ...

    def responder(self, contexto: ContextoResposta) -> str:
        """A resposta ao CF; "" quando não responde (vão os dados como estão)."""
        ...

    def comando(self, contexto: ContextoComando) -> str:
        """O pedido simples da mensagem (um dos COMANDOS); "nenhum" sem IA."""
        ...


class SemIA:
    """Sem IA: a resposta inteira vira a nota, sem redação."""
    nome = "sem IA"

    def interpretar(self, contexto: Contexto) -> Interpretacao:
        return Interpretacao(explicacao=contexto.texto)

    def redigir(self, contexto: ContextoNota) -> str:
        return ""

    def entender(self, contexto: ContextoPergunta) -> Pergunta | None:
        return None

    def responder(self, contexto: ContextoResposta) -> str:
        return ""

    def comando(self, contexto: ContextoComando) -> str:
        return "nenhum"


# ---------- o que vai para a IA ----------

PALAVRAS_COMUNS = {"DE", "DA", "DO", "DAS", "DOS", "E", "DI", "DU"}
CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
APELIDO = re.compile(r"\bPESSOA_\w+\b")


class Apelidos:
    """Troca nomes por PESSOA_A, PESSOA_B… e desfaz a troca.

    No texto livre, cada palavra de um nome vira o apelido desse nome. Se a
    palavra estiver em dois nomes, vale o primeiro, mas o nome de uma pessoa
    passa na frente do nome de uma conta do extrato: "Odir", com a conta
    "ODIR P J …" e a pessoa "ODIR VALERIO …", é a pessoa."""

    def __init__(self) -> None:
        self.nomes: dict[str, str] = {}          # apelido -> nome
        self._por_nome: dict[str, str] = {}      # NOME NORMALIZADO -> apelido
        self._por_palavra: dict[str, tuple[str, bool]] = {}   # palavra -> (apelido, é conta)

    def __call__(self, nome: str, conta: bool = False) -> str:
        chave = norm_maiusculo(nome)
        if chave not in self._por_nome:
            n = len(self.nomes)
            apelido = "PESSOA_" + (chr(ord("A") + n) if n < 26 else str(n + 1))
            self._por_nome[chave] = apelido
            self.nomes[apelido] = nome
        apelido = self._por_nome[chave]
        for palavra in re.findall(r"\w+", chave):
            if len(palavra) < 3 or palavra in PALAVRAS_COMUNS:
                continue
            atual = self._por_palavra.get(palavra)
            if atual is None or (atual[1] and not conta):
                self._por_palavra[palavra] = (apelido, conta)
        return apelido

    def trocar(self, texto: str) -> str:
        """Texto livre: palavras dos nomes conhecidos viram o apelido (um
        nome inteiro vira um apelido só) e CPFs viram [CPF]."""
        texto = CPF.sub("[CPF]", texto)
        texto = re.sub(r"\w+", lambda m: self._por_palavra.get(
            norm_maiusculo(m.group()), (m.group(),))[0], texto)
        return re.sub(r"\b(PESSOA_\w+)(?:\s+\1\b)+", r"\1", texto)

    def desfazer(self, texto: str) -> str:
        return APELIDO.sub(lambda m: self.nomes.get(m.group(), m.group()), texto)


def _pix(chave: str) -> str:
    """'P:Cora|05/07/2026|150.00' -> 'R$ 150,00 (Cora, 05/07/2026)'."""
    banco, data, valor = chave[2:].split("|")
    return f"{brl(float(valor))} ({banco}, {data})"


def _sugestao(c: dict[str, Any], ap: Apelidos) -> str:
    if c["tipo"] == "vinculo":
        return (f"vínculo: o Pix {_pix(c['pix'])} da conta {ap(c['nome_extrato'], True)} pagou o "
                f"recibo {c['recibo']} de {ap(c['pessoa'])}")
    return (f"devolução: o Pix {_pix(c['pix'])} foi devolvido a {ap(c['saida_nome'])} em "
            f"{c['saida_data']}; não é receita")


def _fatos(d: dict[str, Any], ap: Apelidos) -> list[str]:
    """Os números da divergência, com apelidos."""
    # sem recibo, a "pessoa" da divergência é a conta do extrato
    linhas = [f"Divergência de {ap(d['pessoa'], not d['total_recibos'])} — {d['tipo']}",
              f"Total dos recibos: {brl(d['total_recibos'])} · Total no extrato: "
              f"{brl(d['total_extrato'])} · Diferença: {brl(d['diferenca'])}"]
    if d["recibos_sem_pix"]:
        linhas.append("Recibos sem Pix: " + ", ".join(
            f"{r['numero']} ({brl(r['valor'])})" for r in d["recibos_sem_pix"]))
    if d["pix_sem_recibo"]:
        linhas.append("Pix sem recibo: " + ", ".join(
            f"{brl(p['valor'])} ({p['banco']}, {p['data']}) da conta "
            f"{ap(p['nome_no_extrato'], True)}"
            for p in d["pix_sem_recibo"]))
    return linhas


def para_ia(contexto: Contexto) -> tuple[str, Apelidos]:
    """A pergunta para a IA, só com o necessário (veja o início do módulo)."""
    ap = Apelidos()
    linhas = _fatos(contexto.divergencia, ap)
    if contexto.ja_confirmado:
        linhas.append("Já confirmado pela tesouraria:")
        linhas += [f"- {_sugestao(c, ap)}" for c in contexto.ja_confirmado]
    if contexto.sugestoes:
        linhas.append("Sugestões do sistema (a tesouraria pode confirmar pelo número):")
        linhas += [f"{i}) {_sugestao(c, ap)}" for i, c in enumerate(contexto.sugestoes, 1)]
    else:
        linhas.append("Sem sugestões do sistema.")
    for nome, conta in contexto.outros_nomes:   # se a tesouraria citar outra divergência
        ap(nome, conta)
    linhas.append(f"Resposta da tesouraria: \"{ap.trocar(contexto.texto)}\"")
    return "\n".join(linhas), ap


INSTRUCOES = """Você ajuda o Conselho Fiscal de uma associação a registrar as explicações \
da tesouraria para divergências entre os recibos emitidos e os Pix recebidos no extrato do \
banco. Você recebe UMA divergência, as sugestões do sistema numeradas e a resposta da \
tesouraria. Nomes de pessoas e de contas foram trocados por apelidos (PESSOA_A, PESSOA_B…).

Sua tarefa é só interpretar a resposta. Não faça contas e não invente fatos.
- confirmar: números das sugestões que a tesouraria afirmou estarem corretas ("a 1", \
"a primeira", "as duas", "a1 e a2"). Afirmações gerais ("tudo certo", "td certo", "conf", \
"pode confirmar", "isso mesmo", "exato") confirmam todas as sugestões. Dizer que o Pix ou \
o recibo é da pessoa ou conta que aparece numa sugestão ("é PESSOA_B", "o nome do recibo \
saiu errado, é PESSOA_B", "quem pagou foi PESSOA_B") confirma essa sugestão. Começar a \
resposta com "sim", "isso", "certo" ou "confirmo", quando há uma sugestão só, confirma \
essa sugestão. Explicar o parentesco ou a relação entre as pessoas da sugestão ("sim, é a \
esposa dele", "é o filho dela", "é a mãe que paga") confirma a sugestão: "dele"/"dela" \
é a pessoa do recibo. Na dúvida, ou se ela negou a sugestão, não inclua o número.
- explicacao: o trecho da resposta que explica a divergência, copiado da resposta, sem \
reescrever e sem a parte que só confirma ("a 1 tá certa"). Vazio se não houver.
- suficiente: true se a resposta, com as confirmações, explica TODOS os recibos sem Pix e \
TODOS os Pix sem recibo da divergência. Explica: confirmar a sugestão do item, dizer de quem \
é o Pix ("é a empresa do PESSOA_A", "é a esposa dele", "é ele mesmo"), por que o recibo não \
tem pagamento no extrato (dinheiro, outra forma), que o valor foi devolvido ou que houve \
erro de lançamento. Uma explicação geral cobre todos os itens a que se refere: "ele pagou \
tudo em dinheiro" explica todos os recibos; "esses Pix são do bazar" explica todos os Pix. \
false se sobrar item sem explicação (ex.: confirmou só parte das sugestões e não explicou o \
resto), para respostas vagas ("ok", "não sei", "vou ver", "?", só cumprimentos) e para uma \
sugestão negada sem outra explicação.
- adiar: true se a tesouraria disse que vai verificar ou responder depois.
- nome_errado: true se a tesouraria disse que o recibo saiu com o nome errado (erro de \
digitação ou de grafia) e que o recibo é da própria pessoa ou conta que fez o Pix, ou que \
não deve haver vínculo entre as duas ("o nome do recibo está errado, é ela mesma", "erro \
de digitação no recibo", "não vincular"). false se ela disse que uma pessoa pagou por \
outra ("é a mãe dela", "a empresa é do PESSOA_A") ou não falou disso. nome_errado não \
muda "confirmar": um nome errado no recibo ou no extrato que aponta para a sugestão \
("o nome do recibo saiu errado, é PESSOA_B", "nome do extrato errado, é o PESSOA_C") \
continua confirmando essa sugestão.
- pergunta: se suficiente for false e adiar for false, uma pergunta curta e educada, em \
português, dirigida à tesouraria, pedindo o que falta (ex.: de quem é o Pix, por que o \
recibo não tem pagamento). Use os apelidos só para citar as pessoas; fale com a \
tesouraria diretamente, sem nome nem apelido. Vazio nos outros casos.
- comando: "nenhum" quando a mensagem responde à divergência (mesmo em parte). Só quando a \
mensagem inteira é um pedido ao agente, sem explicar nada: "menu" (cumprimentos, "me \
mostra as opções", "o que dá pra fazer?"), "ajuda" ("como você funciona?", "não sei usar"), \
"trocar_cf" (falar como Conselho Fiscal), "trocar_tesouraria" (falar como tesouraria), \
"trocar" (trocar de papel sem dizer qual). Com comando, confirmar fica vazio."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "confirmar": {"type": "array", "items": {"type": "integer"}},
        "explicacao": {"type": "string"},
        "suficiente": {"type": "boolean"},
        "adiar": {"type": "boolean"},
        "pergunta": {"type": "string"},
        "nome_errado": {"type": "boolean"},
        "comando": {"type": "string", "enum": list(COMANDOS)},
    },
    "required": ["confirmar", "explicacao", "suficiente", "adiar", "pergunta", "nome_errado",
                 "comando"],
}


def de_ia(resposta: str, ap: Apelidos) -> Interpretacao:
    """A resposta da IA (JSON no ESQUEMA) -> Interpretacao, com os nomes de
    volta. Resposta fora do formato levanta ValueError (o agente avisa e o
    texto vira a nota)."""
    try:
        r = json.loads(resposta)
        if not isinstance(r, dict) or not isinstance(r.get("suficiente"), bool):
            raise ValueError("faltam campos")
        confirmar = tuple(int(n) for n in r.get("confirmar") or ())
    except (TypeError, ValueError) as erro:
        raise ValueError(f"resposta da IA fora do formato ({erro})") from None
    pergunta = ap.desfazer(str(r.get("pergunta") or ""))
    if APELIDO.search(pergunta):    # apelido inventado ("PESSOA_TESOURARIA"): a pergunta padrão
        pergunta = ""
    return Interpretacao(confirmar=confirmar,
                         explicacao=ap.desfazer(str(r.get("explicacao") or "")),
                         suficiente=r["suficiente"], adiar=bool(r.get("adiar")),
                         pergunta=pergunta, nome_errado=r.get("nome_errado") is True,
                         comando=_comando(r.get("comando")))


def _comando(valor: Any) -> str:
    return valor if valor in COMANDOS else "nenhum"


# ---------- a nota para o CF ----------

def para_redacao(contexto: ContextoNota) -> tuple[str, Apelidos]:
    """O pedido de redação: os mesmos fatos (com apelidos), o que foi
    confirmado e o que a tesouraria escreveu."""
    ap = Apelidos()
    linhas = _fatos(contexto.divergencia, ap)
    if contexto.confirmadas:
        linhas.append("Confirmado pela tesouraria:")
        linhas += [f"- {_sugestao(c, ap)}" for c in contexto.confirmadas]
    for nome, conta in contexto.outros_nomes:
        ap(nome, conta)
    if contexto.respostas:
        linhas += [f"A tesouraria escreveu: \"{ap.trocar(t)}\"" for t in contexto.respostas]
    else:
        linhas.append("A tesouraria não escreveu nada além das confirmações.")
    return "\n".join(linhas), ap


INSTRUCOES_NOTA = """Você escreve a nota que acompanha UMA divergência na planilha que o \
Conselho Fiscal de uma associação vai ler. A divergência é entre os recibos emitidos pela \
tesouraria e os Pix recebidos no extrato do banco. Você recebe os números da divergência, o \
que a tesouraria confirmou e o que ela escreveu. Nomes de pessoas e de contas foram trocados \
por apelidos (PESSOA_A, PESSOA_B…): use os apelidos.

O que escrever: o que explica cada recibo sem Pix e cada Pix sem recibo, em poucas palavras.
- Comece direto pelos itens. Não repita os totais nem a diferença; não diga quem encontrou a \
divergência ("o Conselho Fiscal constatou", "foi verificada").
- Use só o que recebeu. Não invente, não deduza (ex.: de quem é "dele") e não julgue.
- Não faça contas: não some nem subtraia; use os valores como aparecem, sempre sem sinal \
de menos.
- O que a tesouraria escreveu entra reescrito, em terceira pessoa e sem abreviações ("pq" \
vira "porque"), atribuído a ela ("segundo a tesouraria"); nunca entre aspas.
- Mantenha dúvidas e ressalvas ("acho que", "não sei", "vai verificar") como dúvidas. Se um \
item ficou sem explicação, diga isso.
- Uma devolução confirmada não é receita: diga que o valor foi devolvido.
- Um item só: uma ou duas frases. Vários itens: uma linha por item, cada uma começando com \
"• ", separadas por quebra de linha.
- Valores como R$ 1.234,56; datas e números de recibo como aparecem.

Exemplos (só o formato; os fatos de cada pedido são outros):
- "Pix de R$ 60,00 (Cora, 21/07/2026) sem recibo: segundo a tesouraria, PESSOA_A é esposa \
de um associado."
- "Recibos de PESSOA_A pagos por outras contas, segundo a tesouraria:\n• 0814-2026 (R$ \
130,00): Pix da conta PESSOA_B (Cora, 22/07/2026)\n• 0864-2026 (R$ 150,00): pago em \
dinheiro"
- "O Pix de R$ 300,00 (Stone, 20/07/26) foi devolvido a PESSOA_A em 24/07/26 e não é \
receita; segundo a tesouraria, ela tinha pagado em duplicidade."
"""

ESQUEMA_NOTA = {"type": "object", "properties": {"nota": {"type": "string"}},
                "required": ["nota"]}
NUMERO = re.compile(r"\d+(?:[.,]\d+)*")


def _valores(texto: str) -> set[float]:
    """Os números do texto, como valores ('1.234,56', '60' e '0864' viram float)."""
    valores = set()
    for n in NUMERO.findall(texto):
        bruto = n.replace(".", "").replace(",", ".") if "," in n else n.replace(".", "")
        try:
            valores.add(float(bruto))
        except ValueError:
            pass
    return valores


def de_redacao(resposta: str, ap: Apelidos, pedido: str) -> str:
    """A nota redigida, com os nomes de volta. ValueError se vier fora do
    formato, com apelido inventado ou com número que não está no pedido
    (conta feita pela IA, valor ou recibo inventado). Números pequenos
    (até 12: "os 2 Pix") podem aparecer."""
    try:
        r = json.loads(resposta)
        nota = r["nota"].strip() if isinstance(r, dict) else None
    except (TypeError, ValueError, KeyError, AttributeError) as erro:
        raise ValueError(f"redação fora do formato ({erro})") from None
    if not nota:
        raise ValueError("redação vazia")
    if nota.startswith("• ") and "\n" not in nota:      # um item só: sem marcador
        nota = nota[2:]
    return _conferir(nota, ap, pedido, "redação")


def _conferir(texto: str, ap: Apelidos, pedido: str, o_que: str) -> str:
    """O texto da IA com os nomes de volta. ValueError com número que não
    está no pedido (até 12 pode: "os 2 Pix") ou com apelido inventado."""
    novos = {v for v in _valores(texto) - _valores(pedido) if not (v.is_integer() and v <= 12)}
    if novos:
        raise ValueError(f"{o_que} com número que não está nos fatos: {sorted(novos)}")
    texto = ap.desfazer(texto)
    if APELIDO.search(texto):
        raise ValueError(f"{o_que} com apelido desconhecido")
    return texto


# ---------- as perguntas do CF ----------

def para_pergunta(contexto: ContextoPergunta) -> tuple[str, Apelidos]:
    ap = Apelidos()
    for nome, conta in contexto.nomes:
        ap(nome, conta)
    linhas = [f"Hoje: {contexto.hoje}",
              "Meses com dados: " + (", ".join(contexto.meses) or "nenhum"),
              f"Mensagem do Conselho Fiscal: \"{ap.trocar(contexto.texto)}\""]
    return "\n".join(linhas), ap


INSTRUCOES_CF = """Você ajuda um agente que atende o Conselho Fiscal de uma associação. Para \
cada mês, o agente guarda a conferência das receitas: os recibos emitidos pela tesouraria \
comparados com os Pix do extrato do banco, e as divergências encontradas, cada uma com a nota \
da tesouraria. Você recebe a mensagem do Conselho Fiscal e diz só o que ele quer; quem \
responde é o agente. Nomes de pessoas e de contas foram trocados por apelidos (PESSOA_A, \
PESSOA_B…).

- consulta, uma destas:
  - "pacote": quer receber o mês (a planilha da conferência e os arquivos): "manda julho", \
"quero a conferência de junho e julho".
  - "resumo": números gerais do mês: total de receitas, entradas no extrato, quantos recibos, \
quantas divergências, valor total das divergências, "resuma julho", "como foi julho?".
  - "divergencias": quais são as divergências do mês ou quem teve divergência ("quem teve \
divergência de valor em julho?", "quais Pix ficaram sem recibo?").
  - "pessoa": a divergência ou a nota de uma pessoa ou conta ("o que houve com PESSOA_A?", \
"PESSOA_B já apareceu em junho?", "por que PESSOA_C pagou a mais?").
  - "comparar": relação entre meses: soma de meses, diferença, aumento ou queda, média, \
qual foi maior, evolução ("qual a soma da receita de junho e julho?", "julho foi melhor que \
junho?", "como evoluíram as divergências nos últimos 3 meses?", "compare com o mês \
anterior", "qual a média mensal de Pix na Stone?"). Em "comparar", liste todos os meses \
envolvidos; "o mês anterior" a um mês citado também entra. Média, soma ou evolução sem mês \
citado também é "comparar", com meses vazio (o agente usa todos os meses fechados).
  - "destino": quanto entrou de um destino de receita, ou de cada destino, no mês: açaí, \
bazar, brechó, anuidade, café, lojinha, oferta, rifa, almoço… ("quanto arrecadamos com \
açaí em julho?", "quantas anuidades entraram em junho?", "quanto deu o bazar em junho e \
julho?", "quanto entrou por destino em julho?"). Também quando compara meses: um destino \
citado é sempre "destino", com todos os meses envolvidos.
  - "situacao": que meses existem ou em que pé estão ("o que já está pronto?", "julho já \
fechou?").
  - "menu": cumprimentos sem pedido ("oi", "bom dia") e pedidos das opções ("o que você \
faz?", "me mostra o menu").
  - "ajuda": como o agente funciona ("como te uso?", "me explica como funciona").
  - "trocar_tesouraria" / "trocar_cf" / "trocar": quer falar como tesouraria, como Conselho \
Fiscal ou trocar de papel sem dizer qual ("quero entrar como tesouraria").
  - "outra": qualquer outra coisa: pedidos que o agente não faz (alterar dados, comparar \
com o orçamento), opiniões, assuntos fora da conferência.
- meses: os meses citados, no formato AAAA-MM. "Mês passado" é o mês anterior ao de hoje. \
Um mês sem ano é o mais recente entre os meses com dados; se não houver, o mais recente que \
já começou. Vazio se a mensagem não citar mês.
- pessoa: na consulta "pessoa", o apelido (PESSOA_A) ou, se a pessoa não tiver apelido, o \
nome como foi escrito. Vazio nas outras consultas.
- destino: na consulta "destino", o destino como foi escrito, sem o mês ("açaí", \
"anuidade"); vazio se a pergunta for sobre todos os destinos. Vazio nas outras consultas."""

ESQUEMA_CF = {
    "type": "object",
    "properties": {
        "consulta": {"type": "string", "enum": list(CONSULTAS)},
        "meses": {"type": "array", "items": {"type": "string"}},
        "pessoa": {"type": "string"},
        "destino": {"type": "string"},
    },
    "required": ["consulta", "meses", "pessoa", "destino"],
}
MES = re.compile(r"20\d{2}-(0[1-9]|1[0-2])")


def de_pergunta(resposta: str, ap: Apelidos) -> Pergunta:
    """A resposta da IA (JSON no ESQUEMA_CF) -> Pergunta, com o nome de
    volta. Meses fora do formato são descartados; um apelido inventado deixa
    a pessoa vazia (o agente pergunta de quem)."""
    try:
        r = json.loads(resposta)
        consulta = r["consulta"]
        meses = [str(m) for m in r.get("meses") or ()]
    except (TypeError, ValueError, KeyError) as erro:
        raise ValueError(f"resposta da IA fora do formato ({erro})") from None
    if consulta not in CONSULTAS:
        raise ValueError(f"consulta desconhecida: {consulta}")
    pessoa = ap.desfazer(str(r.get("pessoa") or "").strip())
    if APELIDO.search(pessoa):
        pessoa = ""
    return Pergunta(consulta, tuple(dict.fromkeys(m for m in meses if MES.fullmatch(m))),
                    pessoa, str(r.get("destino") or "").strip())


# ---------- pedidos simples ----------

def para_comando(contexto: ContextoComando) -> tuple[str, Apelidos]:
    ap = Apelidos()
    for nome, conta in contexto.nomes:
        ap(nome, conta)
    quem = "da tesouraria" if contexto.papel == "tesouraria" else "do Conselho Fiscal"
    return f"Mensagem {quem}: \"{ap.trocar(contexto.texto)}\"", ap


INSTRUCOES_COMANDO = """Você ajuda um agente de WhatsApp que confere as receitas de uma \
associação: a tesouraria envia o registro de receitas e os extratos bancários e explica as \
divergências; o Conselho Fiscal recebe o resultado e faz perguntas. A regra fixa do agente \
não reconheceu a mensagem. Diga se ela é um destes pedidos simples:
- "menu": cumprimento ou pedido das opções ("oi gente", "o que dá pra fazer?", "e agora?");
- "ajuda": como o agente funciona ("como te uso?", "não entendi como funciona");
- "trocar_cf": falar como Conselho Fiscal; "trocar_tesouraria": falar como tesouraria; \
"trocar": trocar de papel sem dizer qual;
- "nenhum": qualquer outra coisa (explicações, perguntas sobre os dados, assuntos fora).
Na dúvida, "nenhum"."""

ESQUEMA_COMANDO = {
    "type": "object",
    "properties": {"comando": {"type": "string", "enum": list(COMANDOS)}},
    "required": ["comando"],
}


def de_comando(resposta: str) -> str:
    try:
        r = json.loads(resposta)
        return _comando(r.get("comando"))
    except (TypeError, ValueError, AttributeError) as erro:
        raise ValueError(f"resposta da IA fora do formato ({erro})") from None


def para_resposta(contexto: ContextoResposta) -> tuple[str, Apelidos]:
    ap = Apelidos()
    for nome, conta in contexto.nomes:
        ap(nome, conta)
    linhas = [f"Pergunta do Conselho Fiscal: \"{ap.trocar(contexto.pergunta)}\"",
              "Dados:", ap.trocar(contexto.dados)]
    return "\n".join(linhas), ap


INSTRUCOES_RESPOSTA = """Você responde, pelo WhatsApp, a uma pergunta do Conselho Fiscal de \
uma associação sobre a conferência das receitas de um mês: os recibos emitidos pela \
tesouraria comparados com os Pix do extrato do banco, e as divergências, cada uma com a nota \
da tesouraria. Você recebe a pergunta e os dados. Nomes de pessoas e de contas foram trocados \
por apelidos (PESSOA_A, PESSOA_B…): use os apelidos.

- Responda só o que foi perguntado, em português.
- Use só os dados recebidos. Não invente e não deduza o que não está neles.
- Não faça contas: não some, não subtraia, não conte além de poucos itens. Use os valores \
como aparecem. Se a resposta precisar de uma conta que não está nos dados, diga que essa \
informação não está no que você tem e diga o que está.
- Valores como R$ 1.234,56; datas e números de recibo como aparecem.
- "Segundo a tesouraria" só para o que vem de uma nota da tesouraria; os números da \
conferência são fatos.
- Somas, médias, diferenças e variações entre meses já vêm calculadas nos dados: use-as \
como estão.
- O valor das divergências não é um total único: informe os recibos sem Pix e os Pix sem \
recibo separados, como estão nos dados.
- Formato (WhatsApp):
  - pergunta específica ("qual a soma da receita de junho e julho?", "quanto entrou na \
Stone?"): uma ou duas linhas, direto ao ponto;
  - pergunta ampla ("compare julho com junho", "como foi o mês?", "resuma"): uma frase \
curta de conclusão; depois, um grupo por assunto, com o título em negrito numa linha \
própria (*Receitas*) e os itens embaixo, um por linha, começando com "• " e curtos (ex.: \
"• Total: R$ 18.388,87 → R$ 17.864,11 (queda de 2,9%)"). Uma linha em branco entre os \
grupos. Deixe de fora soma e média quando não foram pedidas;
  - várias pessoas ou itens: um por linha, começando com "• ".
- Destaques, como no WhatsApp: negrito com um asterisco de cada lado (*assim*) nos títulos \
dos grupos, no número ou na conclusão principal da resposta (ex.: "Em julho, o açaí rendeu \
*R$ 65,00*, em 3 recibos.") e nos apelidos das pessoas; itálico com um sublinhado de cada \
lado (_assim_) só para observações, como de onde vêm os valores. Destaque pouco: só o que \
ajuda a achar a resposta. Nada de #, tabelas ou outros símbolos de formatação.
- Fale como quem conhece o mês, sem citar "os dados".
- Se o que você tem não responde à pergunta, diga isso em uma frase e resuma o que tem."""

ESQUEMA_RESPOSTA = {"type": "object", "properties": {"resposta": {"type": "string"}},
                    "required": ["resposta"]}


def de_resposta(resposta: str, ap: Apelidos, pedido: str) -> str:
    """A resposta da IA ao CF, conferida como a nota (`_conferir`)."""
    try:
        r = json.loads(resposta)
        texto = r["resposta"].strip() if isinstance(r, dict) else None
    except (TypeError, ValueError, KeyError, AttributeError) as erro:
        raise ValueError(f"resposta fora do formato ({erro})") from None
    if not texto:
        raise ValueError("resposta vazia")
    texto = re.sub(r"[ \t]*\n?[ \t]*• ", "\n• ", texto)       # um item por linha
    # título de grupo (*Receitas*) numa linha própria, com uma linha em branco antes; valor
    # (*R$ 65,00*) ou pessoa (*PESSOA_A*) em negrito no fim de um item não é título
    texto = re.sub(r"[ \t]*\n*[ \t]*(\*(?![^*\n]*(?:\d|PESSOA_|CONTA_))[^*\n]+\*)[ \t]*\n?(?=• )",
                   r"\n\n\1\n", texto)
    texto = texto.lstrip("\n")
    return _conferir(texto, ap, pedido, "resposta")
