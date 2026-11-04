"""O agente: recebe mensagens (texto, botão ou arquivo) de um papel
(tesouraria ou CF) e devolve as mensagens de resposta.

Tesouraria:
  1. envia a planilha de entradas e os extratos do Cora e da Stone em PDF
     (o agente pede o que faltar; extrato em .xlsx não vale);
  2. com os três, o agente roda a conferência e manda o resumo e quantas
     divergências há; depois pergunta uma a uma;
  3. cada resposta vira a nota da divergência. Sugestão confirmada por botão
     também vira nota e, se for vínculo, vai para o cadastro de vínculos.
     Texto livre passa pelo interpretador (agente/ia.py): uma confirmação
     tirada do texto só vale depois do clique em "Está certo" (ou de um
     "sim" escrito); "sim" sozinho nunca vira a nota; uma resposta
     que não explica a divergência é pedida de novo (ou registrada assim
     mesmo, se a tesouraria quiser). Com IA, cada nota com texto da
     tesouraria é reescrita para o CF e só vale depois que ela aprova
     ("Está certo"), mantém a original ou escreve a dela; a nota só de
     confirmações fica no texto padrão; sem IA, a nota fica como está;
  4. com todas as notas, o agente gera a planilha final e avisa que está ok.
     Reenviar os arquivos abre uma nova versão do mês (notas de divergências
     que não mudaram são mantidas). Para corrigir um arquivo só, o agente
     oferece usar os outros da versão atual.
  5. "corrigir" (ou "corrigir <nome>") reabre uma divergência com nota, mesmo
     depois da entrega ao CF: as confirmações dela são desfeitas (inclusive
     no cadastro de vínculos), a outra ponta de cada vínculo também volta
     para a fila, e a pergunta é feita de novo.
Os dois papéis (2026-10-23): "oi" ou "menu", em qualquer ponto, mostram o
menu (a situação e as opções do momento) e nunca viram nota; "ajuda" ou
"como funciona" explicam o fluxo. Quem escreveu (`autor`, o nome que o
canal guarda) fica no histórico da conversa e nos registros do mês (notas,
confirmações, versões e entregas), não na planilha.
CF:
  pede um mês; se estiver pronto, recebe o pacote e o papel do agente
  termina. Se não estiver, o agente diz que o mês ainda não foi fechado e
  por quê (sem arquivos, arquivos incompletos ou divergências sem nota). Se
  o CF não aprovar, a tesouraria reenvia e tudo recomeça.
  Também pode perguntar sobre um mês fechado (resumo, divergências, a de
  uma pessoa): o interpretador diz o que ele quer e `agente.consultas`
  responde com os números do mês, sem anexos. Uma pergunta não envia o
  pacote; o mês sozinho ("julho", "manda julho") ou o botão, sim.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import unicodedata
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from conselho_fiscal.agente import arrecadacao as arr
from conselho_fiscal.agente import comparacao as cmp
from conselho_fiscal.agente import consultas as cs
from conselho_fiscal.agente import divergencias as dv
from conselho_fiscal.agente.armazenamento import Armazenamento, agora
from conselho_fiscal.agente.arquivos import identificar
from conselho_fiscal.agente.consultas import MESES_PT, mes_extenso, reconhecer_mes
from conselho_fiscal.agente.formato import italico, negrito
from conselho_fiscal.agente.ia import (
    COMANDOS,
    Contexto,
    ContextoComando,
    ContextoNota,
    ContextoPergunta,
    ContextoResposta,
    Interpretador,
    Pergunta,
    SemIA,
)
from conselho_fiscal.cadastros import destinos, vinculos
from conselho_fiscal.comum.texto import norm_maiusculo
from conselho_fiscal.comum.valores import brl
from conselho_fiscal.receitas import executar
from conselho_fiscal.receitas.resultado import sha256

PAPEIS = ("tesouraria", "cf")
TIPOS_ENVIO = ("entradas", "Cora", "Stone")
NOME_ARQUIVO = {"entradas": "entradas", "Cora": "cora", "Stone": "stone"}   # + extensão
CONFIRMACOES_CURTAS = {"SIM", "CONFIRMO", "OK", "ISSO", "CORRETO", "CERTO", "ISSO MESMO",
                       "ESTA CERTO", "EXATO"}
NEGACOES_CURTAS = {"NAO", "NAO FOI ISSO", "ERRADO", "ESTA ERRADO"}
# começo de resposta que confirma ("sim, é a esposa dele", "a 1, …"): a IA às
# vezes deixa passar (2026-10-23); com negação em qualquer ponto, não vale
AFIRMACOES = {"SIM", "ISSO", "CERTO", "CORRETO", "CONFIRMO", "EXATO", "EXATAMENTE"}
NEGACOES = {"NAO", "NEM", "ERRADO", "ERRADA", "NUNCA"}
# resposta que só confirma, sem explicar nada ("exatamente", "as duas estão
# certas"): vale o mesmo que o botão "Sim", sem nota escrita (2026-10-29)
SO_CONFIRMA = AFIRMACOES | {"A", "AS", "O", "OS", "E", "DUAS", "DOIS", "TODAS", "TODOS",
                            "AMBAS", "AMBOS", "ESSA", "ESSE", "ESSAS", "ESSES", "ESTA",
                            "ESTAO", "SAO", "CERTA", "CERTOS", "CERTAS", "CORRETA",
                            "CORRETOS", "CORRETAS", "MESMO", "OK", "PODE", "CONFIRMAR"}
OBSERVACAO_VINCULO = "confirmado pela tesouraria (agente)"
BOTAO_CORRIGIR = {"id": "corrigir:", "rotulo": "Corrigir uma nota"}
BOTOES_PENDENTE = {"confirmar": ("ia_ok", "ia_sem", "ia_com", "ia_nao"), "insuficiente": ("assim",),
                   "falha_ia": ("tentar", "assim")}
REDACAO = {"redacao_ok": "aprovada", "redacao_orig": "original"}   # botão -> como ficou
REDACAO_FALHA = ("redacao_tentar", "redacao_orig")                 # depois de a IA falhar
NOME_AGENTE = "Elo"      # como o agente se apresenta (decisão do usuário, 2026-10-26)
BOTAO_AJUDA = {"id": "ajuda:", "rotulo": "Como funciona"}
# os arquivos nas mensagens, sem o nome do banco (2026-10-29)
REGISTRO = "registro de receitas da tesouraria"
EXTRATOS = [t for t in TIPOS_ENVIO if t != "entradas"]
ENVIAR_ARQUIVOS = f"o {REGISTRO} (.xlsx) e os {len(EXTRATOS)} extratos bancários em PDF"
NOME_PAPEL = {"tesouraria": "Tesouraria", "cf": "Conselho Fiscal"}
# "oi", "menu", "bom dia": o menu; "ajuda", "como funciona": a explicação
PALAVRAS_MENU = {"OI", "OIE", "OLA", "MENU", "INICIO", "OPCOES", "COMECAR", "VOLTAR", "BOM",
                 "BOA", "DIA", "TARDE", "NOITE", "TUDO", "BEM", "E", "AI", "EAI"}
CHAVES_MENU = {"OI", "OIE", "OLA", "MENU", "INICIO", "OPCOES", "COMECAR", "VOLTAR", "BOM",
               "BOA", "EAI"}
PALAVRAS_AJUDA = {"AJUDA", "COMO", "FUNCIONA", "ISSO", "O", "QUE", "VOCE", "VC", "FAZ",
                  "SOCORRO", "PRECISO", "DE", "UMA", "ME", "AJUDE", "AJUDAR", "POR", "FAVOR",
                  "PODE", "PODERIA"}
CHAVES_AJUDA = {"AJUDA", "FUNCIONA", "FAZ", "SOCORRO", "AJUDE", "AJUDAR"}
COMO_FUNCIONA = {
    "tesouraria": "\n".join([
        negrito(f"Como o {NOME_AGENTE} funciona"),
        f"1. Você envia os 3 arquivos do mês, em qualquer ordem: {ENVIAR_ARQUIVOS}.",
        "2. Eu confiro os recibos com os extratos e pergunto, uma por vez, as diferenças.",
        "3. Sua resposta vira a nota que o Conselho Fiscal lê.",
        "4. Com todas as notas, o mês fica pronto e o Conselho recebe quando pedir.",
        "",
        italico("A qualquer momento: \"menu\" mostra as opções; \"corrigir\" reabre uma "
                "nota.")]),
    "cf": "\n".join([
        negrito(f"Como o {NOME_AGENTE} funciona"),
        "A tesouraria envia os arquivos do mês e explica cada diferença entre os recibos e "
        "os extratos. Quando o mês fica pronto, você pede o pacote: a planilha da "
        "conferência e os arquivos originais.",
        negrito("Sobre os meses prontos, também respondo:") + " resumo, divergências, a nota "
        "de uma pessoa, quanto entrou por destino e comparação entre meses.",
        negrito("Exemplos:") + " \"manda julho\", \"quanto entrou de açaí em julho?\", "
        "\"o que houve com a Eva?\", \"julho foi maior que junho?\"",
        "",
        italico("A qualquer momento: \"menu\" mostra as opções.")]),
}

Mensagem = dict[str, Any]
log = logging.getLogger(__name__)


def _linhas_entendi(numeros: list[int], escolhidas: list[dv.Confirmacao], nota: str,
                    redigida: bool) -> list[str]:
    """O "Entendi". Com a nota reescrita, ela já conta o que foi confirmado
    (é o que o CF lê). Sem ela, cada confirmação por extenso (2026-10-23).
    O vínculo no cadastro não aparece: é decidido sem perguntar (2026-10-27)."""
    linhas = [negrito("Entendi:")]
    if redigida:
        linhas.append(f"• {negrito('Nota para o Conselho Fiscal:')} {nota}")
    else:
        linhas += [f"• confirma a {n}: {o['rotulo']}" for n, o in zip(numeros, escolhidas)]
        if nota:
            linhas.append(f"• {negrito('nota:')} {nota}")
    return linhas


def _botoes_entendi(prefixo: str, did: str) -> list[dict[str, str]]:
    return [{"id": f"{prefixo}_ok:{did}", "rotulo": "Está certo"},
            {"id": f"{prefixo}_nao:{did}", "rotulo": "Não foi isso"}]


INICIO_CONFIRMACAO = re.compile(
    r"\s*(?:(?:sim|isso|certo|correto|confirmo|exato|exatamente)\b[\s,.!:;-]*)?"
    r"(?:(?:a|é a)\s*(\d)\b[\s,.!:;-]*)?", re.I)


def sem_confirmacao(texto: str) -> str:
    """A explicação sem o "sim", "isso", "a 1" do começo, que só respondem à
    pergunta ("sim, é a esposa dele" -> "é a esposa dele"); se não sobrar
    nada, o texto como veio. O texto original fica no histórico."""
    return texto[INICIO_CONFIRMACAO.match(texto).end():].strip() or texto


def so_confirma(texto: str) -> bool:
    """A resposta só confirma ("exatamente", "as duas estão certas", "a 1 e
    a 2"): não sobra explicação para a nota."""
    palavras = re.findall(r"[^\W\d]+", norm_maiusculo(texto))
    return bool(palavras) and set(palavras) <= SO_CONFIRMA


def confirmacao_explicita(texto: str, n_opcoes: int) -> tuple[tuple[int, ...], str]:
    """O que o começo da resposta confirma, sem depender da IA: "sim, …"
    com uma sugestão só confirma ela; "a 2, …" confirma a 2. Devolve os
    números e o resto do texto (a explicação). Nada, se houver negação."""
    palavras = re.findall(r"\w+", norm_maiusculo(texto))
    if not palavras or NEGACOES & set(palavras):
        return (), texto
    m = INICIO_CONFIRMACAO.match(texto)
    if m.group(1) and 1 <= int(m.group(1)) <= n_opcoes:
        return (int(m.group(1)),), texto[m.end():].strip()
    if palavras[0] in AFIRMACOES and n_opcoes == 1:
        return (1,), texto[m.end():].strip()
    return (), texto


# "sim, a Carla é esposa do Danilo", "sim, é a empresa dele": confirma sem a IA
RELACOES = {"ESPOSA": "a esposa", "MARIDO": "o marido", "FILHO": "o filho", "FILHA": "a filha",
            "EMPRESA": "a empresa", "MAE": "a mãe", "PAI": "o pai", "IRMA": "a irmã",
            "IRMAO": "o irmão"}
RELACAO_RE = re.compile(
    r"(?:SIM|ISSO|CERTO|CORRETO|CONFIRMO|EXATO|EXATAMENTE)\b[\s,.!:;-]*"
    r"(?:(?P<x>[A-Z0-9][A-Z0-9 ]*?)\s+)?E\s+(?:A\s+|O\s+)?(?P<rel>" + "|".join(RELACOES) + r")\b"
    r"\s*(?:(?:DE|DO|DA)\s+(?P<y>[A-Z0-9][A-Z0-9 ]*?)|DELE|DELA)?[\s.!]*")
ARTIGOS = {"A", "O", "AS", "OS", "DE", "DA", "DO"}


def relacao_simples(texto: str, ops: list[dv.Confirmacao]) -> str | None:
    """ "Sim, x é esposa/marido/filho/filha/empresa de y" com sugestões que
    ligam todas a mesma conta à mesma pessoa: a explicação pronta para a nota,
    sem passar pela IA (2026-10-28). Nomes citados têm de ser da conta ou da
    pessoa; senão (ou com negação), None e a IA interpreta."""
    t = " ".join(re.findall(r"[A-Z0-9]+", norm_maiusculo(texto)))
    m = RELACAO_RE.fullmatch(t)
    if not m or NEGACOES & set(t.split()) or not ops or not dv.compativeis(ops):
        return None
    if any(o["tipo"] != "vinculo" for o in ops):
        return None
    pares = {(o["nome_extrato"], o["pessoa"]) for o in ops}
    if len(pares) != 1:
        return None
    conta, pessoa = pares.pop()

    def de(citado: str | None, nome: str) -> bool:
        palavras = set(citado.split()) - ARTIGOS if citado else set()
        return bool(palavras) and palavras <= set(re.findall(r"[A-Z0-9]+", norm_maiusculo(nome)))
    x, y = m["x"], m["y"]
    if x in ("ELE", "ELA", "A CONTA", "ESSA CONTA", "ESTA CONTA"):   # a conta que pagou
        x = None
    if (x and not (de(x, conta) or de(x, pessoa))) or (y and not (de(y, conta) or de(y, pessoa))):
        return None
    if (x and de(x, pessoa) and not de(x, conta)) or (y and de(y, conta) and not de(y, pessoa)):
        conta, pessoa = pessoa, conta           # "Danilo é marido da Carla"
    return f"Segundo a tesouraria, {conta} é {RELACOES[m['rel']]} de {pessoa}."


def _msg_anotado(escolhidas: list[dv.Confirmacao]) -> Mensagem:
    textos = [c["texto"].removeprefix(dv.CONFIRMADO) for c in escolhidas]
    if len(textos) == 1:
        return mensagem(f"✅ {negrito('Anotado:')} {textos[0]}")
    return mensagem(f"✅ {negrito('Anotado:')}\n" + "\n".join(f"• {t}" for t in textos))


def _botao_pacote(mes: str) -> dict[str, str]:
    return {"id": f"enviar:{mes}", "rotulo": f"Pacote {mes_extenso(mes)}"}


# limites do WhatsApp (Cloud API): até 3 botões de resposta com até 20
# caracteres; acima disso, uma lista com até 10 opções de até 24 caracteres
# (e descrição de até 72), aberta por um botão de até 20
MAX_BOTOES, MAX_ROTULO_BOTAO = 3, 20
MAX_LISTA, MAX_ROTULO_LISTA, MAX_DESCRICAO = 10, 24, 72
ABRIR_LISTA = "Ver opções"


def _pendencias(est: dict[str, Any]) -> str:
    """'faltam 3 explicações' e/ou '1 nota a aprovar'."""
    partes = []
    if n := len(est["fila"]):
        partes.append(f"faltam {n} explicações" if n > 1 else "falta 1 explicação")
    if n := len(est.get("revisar", [])):
        partes.append(f"{n} notas a aprovar" if n > 1 else "1 nota a aprovar")
    return " e ".join(partes)


def _palavras(texto: str | None) -> set[str]:
    return set(re.findall(r"[A-Z]+", norm_maiusculo(texto or "")))


# saudações (2026-10-26): letras repetidas valem ("oii", "bom diaa"); a primeira
# palavra é um cumprimento, depois podem vir outros, "tudo bem", o nome do agente…
_PRIMEIRA = (r"OI+E*|OL+A+|OPA+|SALVE|EAE+|HELLO+|HI+|ELO|"
             r"BO[MA]+\s+(?:DIA+|TARDE+|NOITE+)S?")
_SEGUINTE = (_PRIMEIRA + r"|E\s+AI+|TUDO\s+BEM|TD\s+BEM|BLZ|BELEZA|COMO\s+VAI(?:\s+VOCE)?"
             r"|PESSOAL|GENTE")
SAUDACAO = re.compile(rf"[\W_]*(?:{_PRIMEIRA})\b(?:[\W_]*(?:{_SEGUINTE})\b)*[\W_]*")
# só sozinhas: no começo de uma frase podem ser outra coisa ("fala com ela")
SO_SAUDACAO = re.compile(r"[\W_]*(?:E\s*A[IE]+|FALA+|EAI+)(?:[\W_]+(?:TUDO\s+BEM|BLZ))?[\W_]*")


def _base(texto: str) -> str:
    """Maiúsculas sem acento, com o mesmo tamanho do texto (para cortar o original)."""
    def letra(c: str) -> str:
        b = unicodedata.normalize("NFKD", c)[0].upper()
        return b if len(b) == 1 else c
    return "".join(letra(c) for c in texto)


def sem_saudacao(texto: str) -> str:
    """O pedido que vem depois da saudação ("oi, preciso de ajuda" -> "preciso
    de ajuda"); só a saudação, ou sem saudação, fica como está."""
    m = SAUDACAO.match(_base(texto))
    resto = texto[m.end():].strip() if m else ""
    return resto or texto


def pede_menu(texto: str | None) -> bool:
    """Saudação ou "menu": mostra as opções (nunca vira nota)."""
    base = _base(texto or "")
    if SAUDACAO.fullmatch(base) or SO_SAUDACAO.fullmatch(base):
        return True
    p = _palavras(texto)
    return bool(p & CHAVES_MENU) and p <= PALAVRAS_MENU


def pede_ajuda(texto: str | None) -> bool:
    p = _palavras(texto)
    return bool(p & CHAVES_AJUDA) and p <= PALAVRAS_AJUDA


def data_br(iso: str) -> str:
    """'2026-10-23T10:00:00-03:00' -> '23/10/2026'."""
    return "/".join(reversed(iso[:10].split("-")))


def _cortar(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + "…"


def _msg_tambem(outras: list[dv.Divergencia]) -> str:
    """As outras divergências que a confirmação resolveu, cada uma com o que
    era ("recibo sem Pix: R$ 130,00"), para a tesouraria saber o que saiu da fila."""
    itens = [f"{negrito(dv.titulo(d))} ({dv.resumo(d)})" for d in outras]
    if len(itens) == 1:
        return f"Isso também resolve a divergência de {itens[0]}."
    return ("Isso também resolve as divergências de "
            + ", ".join(itens[:-1]) + f" e {itens[-1]}.")


def _separar_dicas(texto: str) -> str:
    """As linhas em itálico no fim da mensagem (dicas: "_Toque em "Sim"…_")
    ficam separadas do conteúdo por uma linha em branco (2026-10-27)."""
    linhas = texto.split("\n")
    i = len(linhas)
    while i > 0 and re.fullmatch(r"_[^_].*_", linhas[i - 1].strip()):
        i -= 1
    if 0 < i < len(linhas) and linhas[i - 1].strip():
        linhas.insert(i, "")
    return "\n".join(linhas)


def mensagem(texto: str, anexos: list[dict[str, str]] = (),
             botoes: list[dict[str, str]] = ()) -> Mensagem:
    """Mensagem do agente. As opções saem no formato do WhatsApp: até 3
    viram botões; mais que isso, uma lista (`lista`) de até 10 opções.
    Rótulos longos são cortados; na lista, o rótulo inteiro vai na
    descrição."""
    m = {"de": "agente", "texto": _separar_dicas(texto), "anexos": list(anexos), "botoes": [],
         "em": agora()}
    if len(botoes) <= MAX_BOTOES:
        m["botoes"] = [dict(b, rotulo=_cortar(b["rotulo"], MAX_ROTULO_BOTAO)) for b in botoes]
        return m
    if len(botoes) > MAX_LISTA:
        log.warning("lista com %d opções; o WhatsApp mostra só %d", len(botoes), MAX_LISTA)
    itens = []
    for b in botoes[:MAX_LISTA]:
        item = {"id": b["id"], "rotulo": _cortar(b["rotulo"], MAX_ROTULO_LISTA)}
        if item["rotulo"] != b["rotulo"]:
            item["descricao"] = _cortar(b["rotulo"], MAX_DESCRICAO)
        itens.append(item)
    m["lista"] = {"abrir": ABRIR_LISTA, "itens": itens}
    return m


# "corrigir" no meio da mensagem: o verbo no infinitivo ou como pedido
PEDE_CORRIGIR = re.compile(r"\b(?:corrigir|corrija|corrige|corrijam)\b", re.IGNORECASE)


def _achar_divergencias(est: dict[str, Any], busca: str) -> list[str]:
    """As divergências cujo nome tem todas as palavras de `busca` ("corrigir
    karina" -> a da KARINA; "corrigir helio" -> uma por recibo dele)."""
    palavras = [p for p in re.findall(r"\w+", norm_maiusculo(busca))
                if len(p) >= 3 and p not in ("NOTA", "DAS", "DOS")]
    return [d["id"] for d in est["divergencias"] if palavras and all(
        p in norm_maiusculo(d["pessoa"]) for p in palavras)]


class Agente:
    def __init__(self, armazenamento: Armazenamento | None = None,
                 cadastro_destinos: str | Path | None = None,
                 vinculos_confirmados: str | Path | None = None,
                 interpretador: Interpretador | None = None,
                 trava: threading.Lock | None = None):
        self.arm = armazenamento or Armazenamento()
        self.cadastro_destinos = cadastro_destinos
        self.vinculos_confirmados = vinculos_confirmados
        self.ia = interpretador or SemIA()
        # uma mensagem por vez; agentes com os mesmos cadastros dividem a trava
        self._trava = trava or threading.Lock()
        self._autor: str | None = None          # quem escreveu a mensagem em curso
        self._extras: list[dict[str, str]] = []  # opções do canal para o menu

    # ---------- entrada única ----------

    def receber(self, papel: str, texto: str | None = None, botao: str | None = None,
                rotulo: str | None = None, anexo: tuple[str, bytes] | None = None,
                autor: str | None = None,
                extras: list[dict[str, str]] = ()) -> list[Mensagem]:
        """Uma mensagem do `papel`: texto livre, clique num botão (id e rótulo)
        ou um arquivo (nome, conteúdo). `autor`: o nome de quem escreveu (vai
        para o histórico); `extras`: opções do canal que entram no menu (ex.:
        trocar de papel). Retorna as respostas do agente."""
        if papel not in PAPEIS:
            raise ValueError(f"papel desconhecido: {papel}")
        with self._trava:
            self._autor, self._extras = autor, list(extras)
            self.arm.registrar_mensagem(papel, {
                "de": papel, **({"autor": autor} if autor else {}),
                "texto": rotulo if botao else (texto or ""),
                "anexos": [{"nome": anexo[0]}] if anexo else [], "botoes": [], "em": agora()})
            if texto and not botao:
                texto = sem_saudacao(texto)
            if papel == "cf":
                respostas = self._cf(texto, botao)
            elif anexo:
                caminho = self.arm.guardar_recebido(*anexo)
                respostas = self._arquivo(caminho, anexo[0])
            else:
                respostas = self._tesouraria(texto, botao)
            for r in respostas:
                self.arm.registrar_mensagem(papel, r)
            return respostas

    def receber_arquivos(self, anexos: list[tuple[str, bytes]], autor: str | None = None,
                         extras: list[dict[str, str]] = ()) -> list[Mensagem]:
        """Vários arquivos da tesouraria mandados juntos (o canal espera uns
        segundos por eles): uma resposta só, com uma linha por arquivo e, no
        fim, o que falta ou o resultado da conferência (2026-10-23)."""
        with self._trava:
            self._autor, self._extras = autor, list(extras)
            self.arm.registrar_mensagem("tesouraria", {
                "de": "tesouraria", **({"autor": autor} if autor else {}), "texto": "",
                "anexos": [{"nome": nome} for nome, _ in anexos], "botoes": [], "em": agora()})
            respostas: list[Mensagem] = []
            recebidos: list[str] = []          # as linhas dos arquivos do meio do lote
            for i, (nome, conteudo) in enumerate(anexos):
                ultimo = i == len(anexos) - 1
                r = self._arquivo(self.arm.guardar_recebido(nome, conteudo), nome, ultimo)
                if not ultimo and len(r) == 1 and not r[0]["botoes"] and not r[0].get("lista"):
                    recebidos.append(r[0]["texto"])
                    continue
                if recebidos:
                    r = [dict(r[0], texto="\n".join(recebidos + [r[0]["texto"]]))] + r[1:]
                    recebidos = []
                respostas += r
            for r in respostas:
                self.arm.registrar_mensagem("tesouraria", r)
            return respostas

    def menu(self, papel: str, autor: str | None = None,
             extras: list[dict[str, str]] = ()) -> list[Mensagem]:
        """O menu do papel, sem mensagem de quem escreve (o canal mostra depois
        do nome ou da troca de papel)."""
        if papel not in PAPEIS:
            raise ValueError(f"papel desconhecido: {papel}")
        with self._trava:
            self._autor, self._extras = autor, list(extras)
            m = self._menu_tesouraria() if papel == "tesouraria" else self._menu_cf(saudar=True)
            self.arm.registrar_mensagem(papel, m)
            return [m]

    def conversa(self, papel: str) -> list[Mensagem]:
        return self.arm.conversa(papel)

    def _por(self) -> dict[str, str]:
        """Quem fez, para os registros do mês (só com o nome vindo do canal)."""
        return {"por": self._autor} if self._autor else {}

    def _saudacao(self, papel: str) -> str:
        nome = f"Oi, {negrito(self._autor)}! " if self._autor else ""
        return f"{nome}Você está como {negrito(NOME_PAPEL[papel])}."

    def _pedido(self, texto: str, papel: str,
                nomes: tuple[tuple[str, bool], ...] = ()) -> str:
        """O pedido simples que a IA vê no texto (um dos COMANDOS)."""
        try:
            return self.ia.comando(ContextoComando(texto, papel, nomes))
        except Exception as erro:       # sinaliza e segue sem a IA
            log.warning("a IA não classificou o pedido: %s", erro)
            return "nenhum"

    def _comando(self, papel: str, comando: str) -> list[Mensagem] | None:
        """A resposta a um pedido simples entendido pela IA; None se não é um.
        A troca de papel vai marcada para o canal (`trocar_papel`), que sabe
        os papéis do número; o texto é para quem não faz a troca (a web)."""
        if comando == "menu":
            return [self._menu_tesouraria() if papel == "tesouraria"
                    else self._menu_cf(saudar=True)]
        if comando == "ajuda":
            return [self._como_funciona(papel)]
        if comando.startswith("trocar"):
            m = mensagem(f"Você está como {negrito(NOME_PAPEL[papel])}. " + italico(
                "Para trocar de papel, use o botão \"Trocar de papel\" do menu."))
            m["trocar_papel"] = {"trocar_cf": "cf",
                                 "trocar_tesouraria": "tesouraria"}.get(comando, "trocar")
            return [m]
        return None

    def _como_funciona(self, papel: str) -> Mensagem:
        return mensagem(COMO_FUNCIONA[papel], botoes=[{"id": "menu:", "rotulo": "Menu"}])

    def entrega_falhou(self, entrega: dict[str, Any]) -> None:
        """O canal não conseguiu mandar os arquivos de uma entrega ao CF:
        desfaz o registro, para o mês não constar como enviado."""
        with self._trava:
            est = self.arm.estado_mes(entrega["mes"])
            if not est or len(est["entregas"]) != entrega["n"]:
                return              # outra entrega veio depois: não mexe
            desfeita = est["entregas"].pop()
            shutil.rmtree(self.arm.caminho(desfeita["planilha"]).parent, ignore_errors=True)
            if est["situacao"] == "entregue" and not est["entregas"]:
                est["situacao"] = "pronto"
            self.arm.salvar_estado_mes(est)
            log.warning("entrega %d de %s desfeita: os arquivos não chegaram ao CF",
                        entrega["n"], entrega["mes"])

    # ---------- tesouraria: arquivos ----------

    def _falta(self, envio: dict[str, Any]) -> list[str]:
        falta = [f"o {REGISTRO} (.xlsx)"] if "entradas" not in envio else []
        if n := sum(t not in envio for t in EXTRATOS):
            falta.append(f"{n} extrato bancário (PDF)" if n == 1
                         else f"{n} extratos bancários (PDF)")
        return falta

    @staticmethod
    def _recebidos(envio: dict[str, Any]) -> list[str]:
        """O que já chegou, sem o nome do banco: 'o registro…', '1 extrato bancário'."""
        recebidos = [f"o {REGISTRO}"] if "entradas" in envio else []
        if n := sum(t in envio for t in EXTRATOS):
            recebidos.append(f"{n} extrato bancário" if n == 1 else f"{n} extratos bancários")
        return recebidos

    def _arquivo(self, caminho: Path, nome: str, ultimo: bool = True) -> list[Mensagem]:
        """Um arquivo da tesouraria. Sem `ultimo` (há outros no mesmo lote),
        só a linha do recebido: o que falta vem com o último."""
        geral = self.arm.estado_geral()
        envio = geral.setdefault("envio", {})
        ident = identificar(str(caminho), nome)
        if ident.tipo not in TIPOS_ENVIO:
            os.remove(caminho)
            falta = self._falta(envio) if ultimo else []
            return [mensagem(f"Não usei \"{nome}\": {ident.motivo}."
                             + (f"\n{negrito('Falta:')} {', '.join(falta)}." if falta else ""))]

        anterior = envio.get(ident.tipo)
        if anterior:
            self.arm.caminho(anterior["caminho"]).unlink(missing_ok=True)
        # arquivo de outro mês: começou um envio novo; os que esperavam saem
        descartados = []
        for t, a in list(envio.items()):
            if t != ident.tipo and ident.mes and a.get("mes") and a["mes"] != ident.mes:
                self.arm.caminho(envio.pop(t)["caminho"]).unlink(missing_ok=True)
                descartados.append(f"\"{a['nome']}\" ({mes_extenso(a['mes'])})")
        envio[ident.tipo] = {"nome": nome, "caminho": self.arm.relativo(caminho),
                             "mes": ident.mes, **self._por()}
        self.arm.salvar_estado_geral(geral)
        recebido = (REGISTRO.capitalize() if ident.tipo == "entradas" else
                     f"Extrato bancário ({sum(t in envio for t in EXTRATOS)} de {len(EXTRATOS)})")
        recebido += f" — {mes_extenso(ident.mes)}" if ident.mes else ""
        texto = f"✅ {negrito(recebido)}" + (" " + italico("(substituí o anterior)")
                                            if anterior else "")
        if descartados:
            texto += (f"\n{negrito('Descartei')} o que esperava de outro mês: "
                      f"{', '.join(descartados)}.")
        falta = self._falta(envio)
        if falta and not ultimo:
            return [mensagem(texto)]
        if falta:
            texto += f"\n{negrito('Falta:')} {', '.join(falta)}."
            mes = self._mes_do_envio(envio, geral)
            est = self.arm.estado_mes(mes) if mes else None
            if est and est["versoes"]:          # correção de um mês em andamento
                texto += "\n" + italico(f"Se só esse mudou, posso usar os outros da versão "
                                        f"{est['versao']} de {mes_extenso(mes)}.")
                return [mensagem(texto, botoes=[{"id": f"completar:{mes}",
                                                 "rotulo": f"Usar os da versão {est['versao']}"}])]
            return [mensagem(texto)]
        respostas = self._processar_envio()       # o recebido vai junto do resultado
        return [dict(respostas[0], texto=texto + "\n\n" + respostas[0]["texto"])] + respostas[1:]

    def _mes_do_envio(self, envio: dict[str, Any], geral: dict[str, Any]) -> str | None:
        """O mês do envio: o da planilha de entradas, se ela veio; senão, o do
        período de um extrato; senão, o mês em conversa."""
        meses = (envio.get(t, {}).get("mes") for t in TIPOS_ENVIO)
        return next((m for m in meses if m), None) or geral.get("mes_atual")

    def _completar(self, mes: str) -> list[Mensagem]:
        """Completa o envio com os arquivos que faltam, copiados da última
        versão do mês, e roda a conferência (decisão de 2026-10-13)."""
        geral = self.arm.estado_geral()
        envio = geral.get("envio", {})
        falta = [t for t in TIPOS_ENVIO if t not in envio]
        est = self.arm.estado_mes(mes)
        if not envio or not falta or self._mes_do_envio(envio, geral) != mes or not est:
            return [mensagem("Esse botão é de uma pergunta anterior.")]
        versao = est["versoes"][-1]
        for t in falta:
            antigo = versao["arquivos"][t]
            copia = self.arm.guardar_recebido(antigo["nome"],
                                              self.arm.caminho(antigo["caminho"]).read_bytes())
            envio[t] = {"nome": antigo["nome"], "caminho": self.arm.relativo(copia),
                        "mes": mes}
        self.arm.salvar_estado_geral(geral)
        usados = ", ".join(f"\"{versao['arquivos'][t]['nome']}\"" for t in falta)
        return ([mensagem(f"Usei da versão {est['versao']}: {usados}.")]
                + self._processar_envio())

    def _processar_envio(self) -> list[Mensagem]:
        geral = self.arm.estado_geral()
        envio = geral["envio"]
        mes = envio["entradas"]["mes"]
        est = self.arm.estado_mes(mes) or {
            "mes": mes, "situacao": None, "versao": 0, "versoes": [], "divergencias": [],
            "notas": {}, "confirmadas": [], "fila": [], "entregas": []}
        hashes = {t: sha256(str(self.arm.caminho(envio[t]["caminho"]))) for t in TIPOS_ENVIO}
        if est["versoes"] and est["versoes"][-1]["sha256"] == hashes:
            for t in TIPOS_ENVIO:
                self.arm.caminho(envio[t]["caminho"]).unlink(missing_ok=True)
            geral.update(envio={}, mes_atual=mes)
            self.arm.salvar_estado_geral(geral)
            return [mensagem(f"Esses arquivos são iguais aos da versão {est['versao']} de "
                             f"{mes_extenso(mes)}; {negrito('nada mudou')}.")] + self._situacao(est)

        versao = est["versao"] + 1
        pasta = self.arm.pasta_versao(mes, versao)
        arquivos = {}
        for t in TIPOS_ENVIO:
            nome = NOME_ARQUIVO[t] + os.path.splitext(envio[t]["nome"])[1].lower()
            destino = self.arm.mover(self.arm.caminho(envio[t]["caminho"]), pasta / nome)
            arquivos[t] = {"nome": envio[t]["nome"], "caminho": self.arm.relativo(destino)}
        geral.update(envio={}, mes_atual=mes)
        self.arm.salvar_estado_geral(geral)

        reaberto = est["situacao"] in ("pronto", "entregue")
        planilha = pasta / f"receitas_{mes}.xlsx"
        try:
            stats = self._rodar(arquivos, planilha, {})
        except Exception as erro:   # o agente avisa e segue; os arquivos ficam na versão
            return [mensagem(f"⚠️ {negrito('Não consegui processar')} os arquivos de "
                             f"{mes_extenso(mes)}: {str(erro).rstrip('.')}. "
                             + italico("Confira os arquivos e envie de novo."))]
        resultado = stats["resultado"]
        divs = resultado["divergencias"]
        mantidas = {d["id"]: est["notas"][d["id"]] for d in divs
                    if d["id"] in est["notas"]
                    and est["notas"][d["id"]]["assinatura"] == dv.assinatura(d)}
        est.pop("pendente", None)
        est["revisar"] = [i for i in est.get("revisar", []) if i in mantidas]
        est.update(versao=versao, situacao="aguardando_respostas", divergencias=divs,
                   notas=mantidas, confirmadas=[], resumo=resultado["resumo"],
                   fila=[d["id"] for d in divs if d["id"] not in mantidas],
                   alertas=[c for c in resultado["conferencias"] if c["status"] != "OK"],
                   destinos_novos=resultado["destinos_novos"])
        est["versoes"].append({"n": versao, "recebido_em": agora(), "arquivos": arquivos,
                               "sha256": hashes, "planilha": self.arm.relativo(planilha),
                               **self._por()})

        respostas = [self._msg_conferencia(est, reaberto, len(mantidas))] + self._proxima(est)
        self.arm.salvar_estado_mes(est)
        return respostas

    def _rodar(self, arquivos: dict[str, Any], planilha: Path,
               notas: dict[str, str]) -> dict[str, Any]:
        c = {t: str(self.arm.caminho(arquivos[t]["caminho"])) for t in TIPOS_ENVIO}
        return executar(c["entradas"], c["Cora"], c["Stone"], str(planilha), notas=notas,
                        cadastro_destinos=self.cadastro_destinos,
                        vinculos_confirmados=self.vinculos_confirmados)

    # ---------- tesouraria: mensagens ----------

    def _msg_conferencia(self, est: dict[str, Any], reaberto: bool, mantidas: int) -> Mensagem:
        """O resultado da conferência e quantas divergências faltam explicar,
        numa mensagem só."""
        r = est["resumo"]
        versao = f"versão {est['versao']}" + (", mês reaberto" if reaberto else "")
        linhas = [f"📊 {negrito(mes_extenso(est['mes']).capitalize() + ' conferido')} "
                  + italico(f"({versao})"),
                  f"{r['recibos']} recibos: {negrito(str(r['conformes']) + ' batem')} com os "
                  "extratos."]
        for a in est["alertas"]:
            linhas.append(f"⚠️ [{a['extrato']}] {a['verificacao']}: {a['status']}"
                          + (f" — {a['detalhe']}" if a["detalhe"] else ""))
        if est["alertas"]:
            linhas.append(italico("Os alertas acima vão para o Conselho Fiscal; parte das "
                                  "divergências pode ser erro de leitura."))
        if est.get("destinos_novos"):
            linhas.append(f"🆕 {negrito('Destinos novos')} (viraram colunas na planilha): "
                          + ", ".join(est["destinos_novos"])
                          + f". Se algum for erro de digitação, corrija o {REGISTRO} e envie "
                            "de novo.")
        if mantidas:
            linhas.append(italico(f"{mantidas} divergência(s) não mudaram desde a versão "
                                  "anterior: mantive as notas."))
        if est["fila"]:
            # só a contagem: as divergências vêm uma por vez, nas perguntas
            n = len(est["fila"])
            linhas.append("\n" + negrito(f"{n} divergência{'s' if n > 1 else ''} para explicar.")
                          + " " + italico("Vou perguntar uma por vez; sua resposta vai como nota "
                                          "para o Conselho Fiscal."))
        return mensagem("\n".join(linhas))

    @staticmethod
    def _opcoes(est: dict[str, Any], d: dv.Divergencia,
                por_id: dict[str, dv.Divergencia]) -> list[dv.Confirmacao]:
        """As sugestões que ainda valem: sem as que a tesouraria recusou."""
        recusadas = {r["chave"] for r in est.get("recusadas", [])}
        return [o for o in dv.opcoes(d, est["confirmadas"], por_id)
                if dv.chave_sugestao(o) not in recusadas]

    def _pergunta(self, est: dict[str, Any]) -> Mensagem:
        por_id = {d["id"]: d for d in est["divergencias"]}
        d = por_id[est["fila"][0]]
        n_total = len(est["divergencias"])
        linhas = [negrito(f"Divergência {n_total - len(est['fila']) + 1} de {n_total} — "
                          f"{dv.titulo(d)}")]
        if ja := dv.textos_confirmados(d, est["confirmadas"]):
            linhas.append(italico(f"Já confirmado: {len(ja)} parte(s). Falta:"))
        ops = self._opcoes(est, d, por_id)
        # cada item ligado à sua sugestão, quando dá; senão, os itens e depois as sugestões
        if agrupada := dv.agrupar(d, est["confirmadas"], ops):
            linhas += agrupada
        else:
            linhas.append(dv.descrever(d, est["confirmadas"]))
            if ops:
                linhas.append("\n" + negrito("Pode ser que:"))
                linhas += [f"{i}) {o['rotulo']}" for i, o in enumerate(ops, start=1)]
        confirmar, extras = [], []
        if ops:
            rotulos = [o["botao"] for o in ops]
            for i, o in enumerate(ops, start=1):
                rotulo = o["botao"] if rotulos.count(o["botao"]) == 1 else f"Sim: a {i}"
                confirmar.append({"id": f"conf:{d['id']}:{o['id']}", "rotulo": rotulo})
            if len(ops) > 1 and dv.compativeis(ops):
                extras.append({"id": f"todas:{d['id']}", "rotulo": "Sim: todas"})
            extras.append({"id": f"nao:{d['id']}",
                           "rotulo": "Não" if len(ops) == 1 else "Não é nenhuma"})
            linhas.append(italico("Toque em \"Sim\" se for isso, ou escreva a explicação."))
        else:
            linhas.append(italico("Escreva a explicação: ela vai como nota para o Conselho "
                                  "Fiscal."))
        if len(est["fila"]) > 1:
            extras.append({"id": f"depois:{d['id']}", "rotulo": "Responder depois"})
        # muitas sugestões: as que não cabem na lista são confirmadas por escrito ("a 9")
        return mensagem("\n".join(linhas), botoes=confirmar[:MAX_LISTA - len(extras)] + extras)

    def _situacao(self, est: dict[str, Any]) -> list[Mensagem]:
        if est["situacao"] == "aguardando_respostas" and (est["fila"] or est.get("revisar")):
            return self._proxima(est)
        if est["situacao"] == "pronto":
            return [mensagem(negrito(f"{mes_extenso(est['mes']).capitalize()} está pronto")
                             + ": todas as divergências têm nota. "
                             + italico("O Conselho Fiscal recebe quando pedir."),
                             botoes=[BOTAO_CORRIGIR])]
        if est["situacao"] == "entregue":
            return [mensagem(negrito(f"{mes_extenso(est['mes']).capitalize()} já foi enviado "
                                     "ao Conselho Fiscal") + ". " + italico(
                                 "Para corrigir uma nota, use o botão ou escreva \"corrigir\"; "
                                 "para corrigir os dados, envie os arquivos de novo."),
                             botoes=[BOTAO_CORRIGIR])]
        return []

    # ---------- tesouraria: respostas ----------

    def _tesouraria(self, texto: str | None, botao: str | None) -> list[Mensagem]:
        if (botao or "").startswith("completar:"):
            return self._completar(botao.split(":", 1)[1])
        if (botao or "").startswith("ajuda:") or (not botao and pede_ajuda(texto)):
            return [self._como_funciona("tesouraria")]
        if (botao or "").startswith("menu:") or (not botao and (not texto or pede_menu(texto))):
            return [self._menu_tesouraria()]
        geral = self.arm.estado_geral()
        est = self.arm.estado_mes(geral["mes_atual"]) if geral.get("mes_atual") else None
        if (botao or "").startswith("continuar:"):
            return self._situacao(est) if est else [self._menu_tesouraria()]
        if est and (botao or "").startswith("corrigir:"):
            respostas = self._corrigir(est, did=botao.split(":", 1)[1] or None)
            self.arm.salvar_estado_mes(est)
            return respostas
        if est and texto and re.match(r"CORRIG|CORRIJ", norm_maiusculo(texto)):
            respostas = self._corrigir(est, busca=texto.split(maxsplit=1)[1:])
            self.arm.salvar_estado_mes(est)
            return respostas
        # no meio do texto ("me confundi, quero corrigir ESTUDIO LUMEN"): só com um nome
        # de divergência depois do verbo; senão é explicação ("corrigir o recibo")
        if est and texto and (m := PEDE_CORRIGIR.search(texto)) and _achar_divergencias(
                est, texto[m.end():]):
            respostas = self._corrigir(est, busca=[texto[m.end():]])
            self.arm.salvar_estado_mes(est)
            return respostas
        if est and est["situacao"] == "aguardando_respostas" and est.get("revisar"):
            respostas = self._resposta_revisao(est, texto, botao)
            self.arm.salvar_estado_mes(est)
            return respostas
        if est and est["situacao"] == "aguardando_respostas" and est["fila"]:
            if botao:
                respostas = self._botao(est, botao)
            elif texto and texto.strip():
                respostas = self._resposta_texto(est, texto.strip())
            else:
                respostas = [self._pergunta(est)]
            self.arm.salvar_estado_mes(est)
            return respostas
        if texto and (r := self._comando("tesouraria", self._pedido(
                texto, "tesouraria", dv.nomes(est["divergencias"]) if est else ()))):
            return r
        return [self._menu_tesouraria(entendi=False)]

    def _menu_tesouraria(self, entendi: bool = True) -> Mensagem:
        """A situação do momento e as opções da tesouraria."""
        geral = self.arm.estado_geral()
        est = self.arm.estado_mes(geral["mes_atual"]) if geral.get("mes_atual") else None
        envio = geral.get("envio", {})
        linhas = [self._saudacao("tesouraria") if entendi else
                  "Não entendi. " + self._saudacao("tesouraria")]
        botoes = []
        if est:
            nome = negrito(mes_extenso(est["mes"]).capitalize() + ":")
            if est["situacao"] == "aguardando_respostas" and (est["fila"] or est.get("revisar")):
                linhas.append(f"{nome} {_pendencias(est)}.")
                botoes.append({"id": "continuar:",
                               "rotulo": f"Continuar {MESES_PT[int(est['mes'][5:]) - 1]}"})
            elif est["situacao"] == "entregue":
                linhas.append(f"{nome} enviado ao Conselho Fiscal em "
                              f"{data_br(est['entregas'][-1]['em'])}.")
                botoes.append(BOTAO_CORRIGIR)
            elif est["situacao"] == "pronto":
                linhas.append(f"{nome} pronto; o Conselho Fiscal recebe quando pedir.")
                botoes.append(BOTAO_CORRIGIR)
        if envio:
            mes = self._mes_do_envio(envio, {})
            recebidos = " e ".join(self._recebidos(envio))
            linhas.append(negrito("Envio" + (f" de {mes_extenso(mes)}" if mes else "") + ":")
                          + f" recebi {recebidos}; falta {', '.join(self._falta(envio))}.")
        elif not est:
            linhas.append("Nenhum mês conferido ainda.")
        linhas.append(italico(f"Para conferir um mês, {negrito('envie')} {ENVIAR_ARQUIVOS} "
                              "(📎 → Documento)."))
        return mensagem("\n".join(linhas), botoes=botoes + [BOTAO_AJUDA] + self._extras)

    def _botao(self, est: dict[str, Any], botao: str) -> list[Mensagem]:
        acao, did, *resto = botao.split(":") + [""]
        if did != est["fila"][0]:
            return [mensagem("Esse botão é de uma pergunta anterior."), self._pergunta(est)]
        pendente = est.pop("pendente", None)       # qualquer clique encerra o "Entendi"
        if acao in ("ia_ok", "ia_sem", "ia_com", "ia_nao", "assim", "tentar"):
            if not pendente or pendente["div"] != did or acao not in BOTOES_PENDENTE[
                    pendente["tipo"]]:
                return [mensagem("Esse botão é de uma pergunta anterior."), self._pergunta(est)]
            return self._resolver_pendente(est, acao, pendente)
        if acao == "depois":
            est["fila"].append(est["fila"].pop(0))
            return [self._pergunta(est)]
        if acao == "nao":
            return self._recusar(est)
        por_id = {d["id"]: d for d in est["divergencias"]}
        ops = self._opcoes(est, por_id[did], por_id)
        escolhidas = ops if acao == "todas" else [o for o in ops if o["id"] == resto[0]]
        if not escolhidas:
            return [mensagem("Essa sugestão não está mais disponível."), self._pergunta(est)]
        return self._confirmar(est, escolhidas)

    def _recusar(self, est: dict[str, Any]) -> list[Mensagem]:
        """"Não" às sugestões da divergência atual: nada é confirmado, elas
        saem da pergunta (das duas pontas) e a explicação vem por escrito."""
        por_id = {d["id"]: d for d in est["divergencias"]}
        d = por_id[est["fila"][0]]
        recusadas = est.setdefault("recusadas", [])
        for o in self._opcoes(est, d, por_id):
            recusadas.append({"chave": dv.chave_sugestao(o),
                              "divs": list(dict.fromkeys(div for div, _ in dv._itens(o))),
                              "texto": o["rotulo"], **self._por()})
        botoes = ([{"id": f"depois:{d['id']}", "rotulo": "Responder depois"}]
                  if len(est["fila"]) > 1 else [])
        return [mensagem("Certo, não é isso. " + italico(
            "Escreva a explicação: ela vai como nota para o Conselho Fiscal."), botoes=botoes)]

    def _confirmar(self, est: dict[str, Any], escolhidas: list[dv.Confirmacao],
                   explicacao: str = "", origem: dict[str, str] | None = None,
                   redigida: dict[str, str] | None = None,
                   cadastro: bool = True) -> list[Mensagem]:
        """Registra as confirmações. Com `explicacao` (tirada de texto livre),
        a nota da divergência atual leva as confirmações e a explicação; com
        `redigida` (a nota reescrita, aprovada junto no "Entendi"), vale ela.
        Sem `cadastro`, os vínculos não vão para o cadastro de vínculos."""
        atual = est["fila"][0]
        respostas = [_msg_anotado(escolhidas)]
        resolvidas = self._registrar_confirmacoes(est, escolhidas, cadastro)
        por_id = {d["id"]: d for d in est["divergencias"]}
        if explicacao:
            d = por_id[atual]
            self._anotar(est, d, dv.nota_montada(d, est["confirmadas"], explicacao), origem)
            if redigida:                    # já aprovada: não volta para a revisão
                nota = est["notas"][atual]
                nota.update(nota_montada=nota["texto"], texto=redigida["texto"],
                            redigida_por=redigida["por"], redacao="aprovada")
                est["revisar"].remove(atual)
        outras = [por_id[i] for i in resolvidas if i != atual]
        if outras:
            respostas.append(mensagem(_msg_tambem(outras)))
        return respostas + self._proxima(est)

    def _registrar_confirmacoes(self, est: dict[str, Any], escolhidas: list[dv.Confirmacao],
                                cadastro: bool = True) -> list[str]:
        """Grava as confirmações (o vínculo também no cadastro, salvo quando a
        tesouraria diz que foi só o nome errado no recibo) e devolve as
        divergências da fila que elas explicaram."""
        for c in escolhidas:
            sem = {"cadastro": False} if c["tipo"] == "vinculo" and not cadastro else {}
            est["confirmadas"].append({k: v for k, v in c.items()
                                       if k not in ("id", "rotulo", "botao")}
                                      | self._por() | sem)
            if c["tipo"] == "vinculo" and cadastro:
                vinculos.registrar(c["nome_extrato"], c["pessoa"], est["mes"],
                                   observacao=OBSERVACAO_VINCULO,
                                   caminho=self.vinculos_confirmados)
        return self._resolver_cobertas(est)

    def _resolver_cobertas(self, est: dict[str, Any]) -> list[str]:
        """Divergências da fila totalmente explicadas por confirmações recebem
        a nota montada com elas e saem da fila."""
        resolvidas = []
        for d in est["divergencias"]:
            if d["id"] in est["fila"] and dv.coberta(d, est["confirmadas"]):
                self._anotar(est, d, dv.nota_montada(d, est["confirmadas"]))
                resolvidas.append(d["id"])
        return resolvidas

    def _resposta_texto(self, est: dict[str, Any], texto: str) -> list[Mensagem]:
        """Texto livre: "sim" com uma única sugestão confirma direto; o resto
        passa pelo interpretador, e o agente confere o que ele entendeu."""
        curto = " ".join(re.findall(r"\w+", norm_maiusculo(texto)))
        pendente = est.pop("pendente", None)        # um texto novo substitui o "Entendi"…
        if pendente and pendente["tipo"] == "confirmar":
            if curto in CONFIRMACOES_CURTAS:        # …menos "isso", "sim": é o "Está certo"
                return self._resolver_pendente(est, "ia_ok", pendente)
            if curto in NEGACOES_CURTAS:            # e "não" é o "Não foi isso"
                return self._resolver_pendente(est, "ia_nao", pendente)
        por_id = {d["id"]: d for d in est["divergencias"]}
        d = por_id[est["fila"][0]]
        ops = self._opcoes(est, d, por_id)
        if len(ops) == 1 and curto in CONFIRMACOES_CURTAS:
            return self._confirmar(est, ops)
        if ops and curto in NEGACOES_CURTAS:     # "não": o mesmo que o botão
            return self._recusar(est)
        if explicacao := relacao_simples(texto, ops):   # "sim, é a esposa dele": direto
            return self._confirmar(est, ops, explicacao,
                                   {"resposta": texto, "interpretado_por": "regra"})
        origem = {"texto_original": texto, "interpretado_por": self.ia.nome}
        try:
            it = self.ia.interpretar(Contexto(d, ops, dv.confirmacoes_de(
                d, est["confirmadas"]), texto, dv.nomes(est["divergencias"])))
        except Exception as erro:
            # não grava pela metade (ex.: "é a Marinilda" sem confirmar o vínculo):
            # a tesouraria escolhe entre tentar de novo e registrar o texto como está
            origem.update(interpretado_por="sem IA", erro_ia=str(erro))
            est["pendente"] = {"tipo": "falha_ia", "div": d["id"], **origem}
            botoes = [{"id": f"tentar:{d['id']}", "rotulo": "Tentar de novo"},
                      {"id": f"assim:{d['id']}", "rotulo": "Registrar assim"}]
            if len(est["fila"]) > 1:
                botoes.append({"id": f"depois:{d['id']}", "rotulo": "Responder depois"})
            return [mensagem(f"⚠️ {negrito('Não consegui interpretar sua resposta agora')} "
                             "(a IA não respondeu). "
                             + italico("Quer tentar de novo ou registrar o texto como está?"),
                             botoes=botoes)]
        origem["interpretado_por"] = getattr(self.ia, "ultimo", self.ia.nome)  # ou o reserva
        numeros, resto = confirmacao_explicita(texto, len(ops))
        if numeros and not it.confirmar and not it.adiar:   # a IA deixou passar o "sim"
            explicacao = it.explicacao.strip()
            if norm_maiusculo(explicacao) == norm_maiusculo(texto):
                explicacao = resto
            it = replace(it, confirmar=numeros, explicacao=explicacao)

        # um pedido ao agente, não uma resposta; o que explica algo nunca é engolido
        if it.comando != "nenhum" and not it.confirmar and not it.suficiente and (
                r := self._comando("tesouraria", it.comando)):
            return r
        if it.adiar and len(est["fila"]) > 1:
            est["fila"].append(est["fila"].pop(0))
            return [mensagem("Combinado, volto nela no fim."), self._pergunta(est)]
        if it.confirmar:
            numeros = sorted(set(it.confirmar))
            escolhidas = [ops[n - 1] for n in numeros if 1 <= n <= len(ops)]
            if len(escolhidas) != len(numeros) or not dv.compativeis(escolhidas):
                return [mensagem("Não entendi qual sugestão você confirmou. " + italico(
                    "Use as opções ou escreva de novo, citando o número.")), self._pergunta(est)]
            # a explicação só fecha a divergência se a resposta toda explica o que falta;
            # senão, depois das confirmações a pergunta volta, com o que já foi confirmado
            explicacao = (sem_confirmacao(it.explicacao.strip())
                          if it.suficiente and not so_confirma(texto) else "")
            cadastro = not it.nome_errado
            est["pendente"] = {"tipo": "confirmar", "div": d["id"],
                               "confirmar": [o["id"] for o in escolhidas],
                               "explicacao": explicacao, "cadastro": cadastro, **origem}
            # a nota reescrita vai no mesmo "Entendi": um clique aprova as duas
            # (sem redação, a nota volta à revisão depois)
            redigida = (self._redigir_junto(est, d, escolhidas, sem_confirmacao(texto))
                        if explicacao else None)
            if redigida:
                est["pendente"]["redigida"] = redigida
            linhas = _linhas_entendi(numeros, escolhidas,
                                     redigida["texto"] if redigida else explicacao,
                                     bool(redigida))
            return [mensagem("\n".join(linhas), botoes=_botoes_entendi("ia", d["id"]))]
        if curto in CONFIRMACOES_CURTAS:            # "sim" sem dizer o quê nunca vira a nota
            return [mensagem("Não entendi o que está certo. " + italico(
                "Use as opções ou escreva de novo, citando o número.")), self._pergunta(est)]
        if not it.suficiente or it.adiar:
            est["pendente"] = {"tipo": "insuficiente", "div": d["id"], **origem}
            botoes = [{"id": f"assim:{d['id']}", "rotulo": "Registrar assim"}]
            if len(est["fila"]) > 1:
                botoes.append({"id": f"depois:{d['id']}", "rotulo": "Responder depois"})
            if it.adiar:                            # e é a última da fila
                resposta = ("Combinado. É a última divergência: "
                            + italico("quando tiver a resposta, é só escrever aqui."))
            else:
                resposta = it.pergunta.strip() or (
                    f"Isso ainda não explica a divergência de {negrito(dv.titulo(d))} "
                    f"({brl(d['diferenca'])}). {negrito('Pode detalhar?')}")
            return [mensagem(resposta, botoes=botoes)]
        return self._nota(est, d, texto, origem)

    def _resolver_pendente(self, est: dict[str, Any], acao: str,
                           pendente: dict[str, Any]) -> list[Mensagem]:
        """Clique em "Está certo", "Certo, sem vínculo", "Não foi isso",
        "Registrar assim" ou "Tentar de novo"."""
        por_id = {d["id"]: d for d in est["divergencias"]}
        d = por_id[pendente["div"]]
        origem = {k: pendente[k] for k in ("texto_original", "interpretado_por", "erro_ia")
                  if k in pendente}
        if acao == "tentar":
            return self._resposta_texto(est, pendente["texto_original"])
        if acao == "assim":
            return self._nota(est, d, pendente["texto_original"], origem)
        if acao == "ia_nao":
            return [mensagem("Desconsiderei. "
                             + italico("Confirme pelas opções ou escreva de novo.")),
                    self._pergunta(est)]
        ops = {o["id"]: o for o in self._opcoes(est, d, por_id)}
        if not all(i in ops for i in pendente["confirmar"]):
            return [mensagem("Essa sugestão não está mais disponível."), self._pergunta(est)]
        return self._confirmar(est, [ops[i] for i in pendente["confirmar"]],
                               pendente["explicacao"], origem, pendente.get("redigida"),
                               cadastro={"ia_sem": False, "ia_com": True}.get(
                                   acao, pendente.get("cadastro", True)))

    def _redigir_junto(self, est: dict[str, Any], d: dv.Divergencia,
                       escolhidas: list[dv.Confirmacao], texto: str) -> dict[str, str] | None:
        """A nota reescrita da divergência como ficará com as confirmações
        `escolhidas`, para o "Entendi". None sem redação (sem IA ou falha:
        a nota passa pela revisão de sempre depois)."""
        novas = [{k: v for k, v in c.items() if k not in ("id", "rotulo", "botao")}
                 for c in escolhidas]
        try:
            nota = self.ia.redigir(ContextoNota(
                d, dv.confirmacoes_de(d, est["confirmadas"] + novas), [texto],
                dv.nomes(est["divergencias"])))
        except Exception:
            return None
        if not nota.strip():
            return None
        return {"texto": nota, "por": getattr(self.ia, "ultimo", self.ia.nome)}

    def _nota(self, est: dict[str, Any], d: dv.Divergencia, texto: str,
              origem: dict[str, str] | None = None) -> list[Mensagem]:
        """O texto da tesouraria vira a nota (depois das confirmações que já
        tocam a divergência)."""
        texto = sem_confirmacao(texto)
        self._anotar(est, d, dv.nota_montada(d, est["confirmadas"], texto), origem)
        return [mensagem(f"✅ {negrito('Anotado para ' + dv.titulo(d) + ':')} {texto}")] \
            + self._proxima(est)

    def _anotar(self, est: dict[str, Any], d: dv.Divergencia, nota: str,
                origem: dict[str, str] | None = None) -> None:
        """Grava a nota (com a origem, se veio de texto livre) e tira a
        divergência da fila."""
        est["notas"][d["id"]] = {"texto": nota, "assinatura": dv.assinatura(d), "em": agora(),
                                 **self._por(), **(origem or {})}
        if d["id"] in est["fila"]:
            est["fila"].remove(d["id"])
        revisar = est.setdefault("revisar", [])
        if (origem or {}).get("texto_original") and d["id"] not in revisar:
            revisar.append(d["id"])         # só confirmações: o texto padrão já vale

    # ---------- tesouraria: correção de nota ----------

    def _corrigir(self, est: dict[str, Any], did: str | None = None,
                  busca: list[str] = ()) -> list[Mensagem]:
        """Reabre uma divergência com nota. Sem `did`, procura pelo nome
        escrito depois de "corrigir"; sem achar uma só, mostra a lista (só as
        achadas, se o nome apontar mais de uma)."""
        por_id = {d["id"]: d for d in est["divergencias"]}
        achadas = _achar_divergencias(est, busca[0]) if did is None and busca else []
        if len(achadas) == 1:
            did = achadas[0]
        if did is None or did not in por_id:
            # o nome aponta várias (uma por recibo): a lista só com elas
            com_nota = [d for d in est["divergencias"] if d["id"] in est["notas"]
                        and (not achadas or d["id"] in achadas)]
            if not com_nota:
                return [mensagem(f"Nenhuma divergência de {mes_extenso(est['mes'])} tem nota "
                                 "para corrigir.")] + self._situacao(est)
            linhas = [negrito(f"Qual nota de {mes_extenso(est['mes'])} você quer corrigir?")]
            linhas += [f"{i}. {negrito(dv.titulo(d))}" for i, d in enumerate(com_nota, start=1)]
            if len(com_nota) > MAX_LISTA:
                linhas.append(italico(f"As opções mostram as {MAX_LISTA} primeiras; para outra, "
                                      "escreva \"corrigir\" e o nome."))
            return [mensagem("\n".join(linhas), botoes=[
                {"id": f"corrigir:{d['id']}", "rotulo": dv.rotulo(d)}
                for d in com_nota[:MAX_LISTA]])]
        d = por_id[did]
        if did not in est["notas"]:
            est["fila"].remove(did)
            est["fila"].insert(0, did)
            return [mensagem(f"{negrito(dv.titulo(d))} ainda está sem nota."), self._pergunta(est)]
        return self._reabrir(est, d)

    def _reabrir(self, est: dict[str, Any], d: dv.Divergencia) -> list[Mensagem]:
        """Desfaz as confirmações da divergência (e o registro do vínculo no
        cadastro), tira as notas que dependiam delas e pergunta de novo."""
        desfeitas = dv.confirmacoes_de(d, est["confirmadas"])
        est["confirmadas"] = [c for c in est["confirmadas"] if c not in desfeitas]
        # quem corrige pode querer a sugestão recusada de volta
        est["recusadas"] = [r for r in est.get("recusadas", []) if d["id"] not in r["divs"]]
        for c in desfeitas:
            ainda = any(o["tipo"] == "vinculo" and o.get("cadastro", True)
                        and (o["nome_extrato"], o["pessoa"]) == (c["nome_extrato"], c["pessoa"])
                        for o in est["confirmadas"])
            if c["tipo"] == "vinculo" and c.get("cadastro", True) and not ainda:
                vinculos.remover(c["nome_extrato"], c["pessoa"], est["mes"],
                                 observacao=OBSERVACAO_VINCULO,
                                 caminho=self.vinculos_confirmados)
        reabertas = [d["id"]] + [div for c in desfeitas for div, _ in dv._itens(c)
                                 if div != d["id"]]
        reabertas = [i for i in dict.fromkeys(reabertas) if i in est["notas"]]
        for i in reabertas:
            del est["notas"][i]
        est["revisar"] = [i for i in est.get("revisar", []) if i not in reabertas]
        est["fila"] = reabertas + [i for i in est["fila"] if i not in reabertas]
        est.pop("pendente", None)
        entregue = est["situacao"] == "entregue"
        est["situacao"] = "aguardando_respostas"

        por_id = {x["id"]: x for x in est["divergencias"]}
        linhas = [f"Reabri {negrito(dv.titulo(d))}."]
        if desfeitas:
            linhas.append(negrito("Desfiz:") + "\n"
                          + "\n".join(f"• {c['texto']}" for c in desfeitas))
        if len(reabertas) > 1:
            linhas.append("Isso também reabre: "
                          + ", ".join(negrito(dv.titulo(por_id[i])) for i in reabertas[1:])
                          + ".")
        if entregue:
            linhas.append(f"⚠️ {negrito('O Conselho Fiscal já recebeu este mês')}; "
                          + italico("quando as notas estiverem completas, ele precisa pedir de "
                                    "novo."))
        return [mensagem("\n".join(linhas)), self._pergunta(est)]

    # ---------- tesouraria: nota reescrita para o CF ----------

    def _proxima(self, est: dict[str, Any]) -> list[Mensagem]:
        """Primeiro as notas a aprovar, depois a próxima pergunta; sem nada,
        o fechamento."""
        while est.get("revisar"):
            m = self._revisao(est)
            if m:
                return [m]
        return [self._pergunta(est)] if est["fila"] else self._finalizar(est)

    def _revisao(self, est: dict[str, Any]) -> Mensagem | None:
        """A nota reescrita da primeira divergência da revisão, para a
        tesouraria aprovar. Só a nota com texto da tesouraria é reescrita; a
        de confirmações já sai no texto padrão (decisão de 2026-10-13). Sem
        IA, não há redação. Se a IA falhar, a tesouraria escolhe entre
        tentar de novo e manter a original."""
        did = est["revisar"][0]
        nota = est["notas"].get(did)
        pessoa = next(dv.titulo(x) for x in est["divergencias"] if x["id"] == did)
        if nota and "reinterpretacao" in nota:          # "Entendi" ainda sem resposta
            return nota["reinterpretacao"]["mensagem"]
        if nota and nota.get("erro_ia") and not nota.get("reinterpretado"):
            m = self._reinterpretar(est, did, nota)
            if m:
                return m
        if nota and nota.get("texto_original") and "proposta" not in nota \
                and not nota.get("falha_redacao"):
            d = next(x for x in est["divergencias"] if x["id"] == did)
            try:
                nota["proposta"] = self.ia.redigir(ContextoNota(
                    d, dv.confirmacoes_de(d, est["confirmadas"]),
                    [sem_confirmacao(nota["texto_original"])],
                    dv.nomes(est["divergencias"])))
                nota["redigida_por"] = getattr(self.ia, "ultimo", self.ia.nome)
                nota.pop("erro_redacao", None)
            except Exception as erro:
                nota.update(erro_redacao=str(erro), falha_redacao=True)
        if nota and nota.get("falha_redacao"):
            return mensagem(f"⚠️ Não consegui reescrever a nota de {negrito(pessoa)} para o "
                            "Conselho Fiscal agora (a IA não respondeu). "
                            f"{negrito('A nota original é:')}\n{nota['texto']}", botoes=[
                                {"id": f"redacao_tentar:{did}", "rotulo": "Tentar de novo"},
                                {"id": f"redacao_orig:{did}", "rotulo": "Manter a original"}])
        if not nota or not nota.get("texto_original") or not nota.get("proposta", "").strip() \
                or nota["proposta"] == nota["texto"]:
            if nota:
                nota.pop("proposta", None)
                nota.pop("redigida_por", None)
            est["revisar"].pop(0)
            return None
        return mensagem(negrito(f"Nota para o Conselho Fiscal — {pessoa}:")
                        + f"\n{nota['proposta']}\n\n"
                        + italico("Se preferir, escreva a nota do seu jeito."), botoes=[
                            {"id": f"redacao_ok:{did}", "rotulo": "Está certo"},
                            {"id": f"redacao_orig:{did}", "rotulo": "Manter a original"}])

    def _reinterpretar(self, est: dict[str, Any], did: str,
                       nota: dict[str, Any]) -> Mensagem | None:
        """A nota foi registrada porque a IA não respondeu. Se agora ela
        responde e acha uma confirmação no texto, mostra o "Entendi" (com a
        nota reescrita); senão, segue a revisão de sempre. Tenta uma vez só."""
        nota["reinterpretado"] = True
        por_id = {d["id"]: d for d in est["divergencias"]}
        d, texto = por_id[did], nota["texto_original"]
        ops = self._opcoes(est, d, por_id)
        if not ops:
            return None
        try:
            it = self.ia.interpretar(Contexto(d, ops, dv.confirmacoes_de(d, est["confirmadas"]),
                                              texto, dv.nomes(est["divergencias"])))
        except Exception:
            return None
        numeros = sorted(set(it.confirmar))
        escolhidas = [ops[n - 1] for n in numeros if 1 <= n <= len(ops)]
        if not numeros or len(escolhidas) != len(numeros) or not dv.compativeis(escolhidas):
            return None
        redigida = self._redigir_junto(est, d, escolhidas, sem_confirmacao(texto))
        nota["reinterpretacao"] = {"confirmar": [o["id"] for o in escolhidas],
                                   "redigida": redigida, "cadastro": not it.nome_errado,
                                   "por": getattr(self.ia, "ultimo", self.ia.nome)}
        linhas = [f"Agora consegui interpretar sua resposta para {negrito(dv.titulo(d))}."]
        linhas += _linhas_entendi(numeros, escolhidas,
                                  redigida["texto"] if redigida else texto, bool(redigida))
        m = mensagem("\n".join(linhas), botoes=_botoes_entendi("reint", did))
        nota["reinterpretacao"]["mensagem"] = m
        return m

    def _aplicar_reinterpretacao(self, est: dict[str, Any], did: str, nota: dict[str, Any],
                                 cadastro: bool = True) -> list[Mensagem]:
        """"Está certo" (ou "Certo, sem vínculo") no "Entendi" da
        reinterpretação: grava as confirmações e refaz a nota com elas (e a
        nota reescrita, se veio)."""
        r = nota.pop("reinterpretacao")
        por_id = {d["id"]: d for d in est["divergencias"]}
        d = por_id[did]
        ops = {o["id"]: o for o in self._opcoes(est, d, por_id)}
        if not all(i in ops for i in r["confirmar"]):
            return [mensagem("Essa sugestão não está mais disponível.")] + self._proxima(est)
        escolhidas = [ops[i] for i in r["confirmar"]]
        resolvidas = self._registrar_confirmacoes(est, escolhidas, cadastro)
        origem = {"texto_original": nota["texto_original"], "interpretado_por": r["por"],
                  "erro_ia_antes": nota.get("erro_ia", ""), "reinterpretado": True}
        self._anotar(est, d, dv.nota_montada(d, est["confirmadas"],
                                             sem_confirmacao(nota["texto_original"])),
                     origem)
        respostas = [_msg_anotado(escolhidas)]
        if r["redigida"]:                   # aprovada junto: sai da revisão
            nova = est["notas"][did]
            nova.update(nota_montada=nova["texto"], texto=r["redigida"]["texto"],
                        redigida_por=r["redigida"]["por"], redacao="aprovada")
            est["revisar"].remove(did)
        outras = [por_id[i] for i in resolvidas if i != did]
        if outras:
            respostas.append(mensagem(_msg_tambem(outras)))
        return respostas + self._proxima(est)

    def _resposta_revisao(self, est: dict[str, Any], texto: str | None,
                          botao: str | None) -> list[Mensagem]:
        """"Está certo" (ou "sim"), "Manter a original" (ou "não") ou a nota
        escrita pela tesouraria, que vale como foi escrita. Depois de uma
        falha da IA, "Tentar de novo" (ou "sim") pede a redação outra vez."""
        did = est["revisar"][0]
        nota = est["notas"].get(did, {})
        falhou = nota.get("falha_redacao", False)
        texto = (texto or "").strip()
        curto = " ".join(re.findall(r"\w+", norm_maiusculo(texto)))
        if "reinterpretacao" in nota:
            acao = (botao or "").split(":")[0] if botao else (
                "reint_ok" if curto in CONFIRMACOES_CURTAS else
                "reint_nao" if curto in NEGACOES_CURTAS else "")
            if botao and (botao.split(":") + [""])[1] != did:
                acao = ""
            if acao in ("reint_ok", "reint_sem", "reint_com"):
                cadastro = {"reint_sem": False, "reint_com": True}.get(
                    acao, nota["reinterpretacao"].get("cadastro", True))
                return self._aplicar_reinterpretacao(est, did, nota, cadastro)
            if acao == "reint_nao":             # fica a nota registrada; segue a revisão
                nota.pop("reinterpretacao")
                return [mensagem("Desconsiderei; fica a nota que você registrou.")] \
                    + self._proxima(est)
            return [mensagem(f"Use {negrito('Está certo')} ou {negrito('Não foi isso')}.")] \
                + self._proxima(est)
        if botao:
            acao, alvo = (botao.split(":") + [""])[:2]
            valido = REDACAO_FALHA if falhou else REDACAO
            if acao not in valido or alvo != did:
                return [mensagem("Esse botão é de uma pergunta anterior.")] + self._proxima(est)
        elif curto in CONFIRMACOES_CURTAS:
            acao = "redacao_tentar" if falhou else "redacao_ok"
        elif curto in NEGACOES_CURTAS:
            acao = "redacao_orig"
        elif texto:
            acao = "escrita"
        else:
            return self._proxima(est)
        if acao == "redacao_tentar":
            nota.pop("falha_redacao", None)
            return self._proxima(est)
        if "proposta" not in nota and not falhou:   # não chegou a ser mostrada: mostra
            return self._proxima(est)
        proposta = nota.pop("proposta", None)
        nota.pop("falha_redacao", None)
        if acao == "redacao_ok":
            nota.update(nota_montada=nota["texto"], texto=proposta)
        else:
            nota.pop("redigida_por", None)
        if acao == "escrita":
            nota.update(nota_montada=nota["texto"], texto=texto)
        nota["redacao"] = REDACAO.get(acao, "escrita pela tesouraria")
        if self._autor:
            nota["revisada_por"] = self._autor
        est["revisar"].pop(0)
        pessoa = next(dv.titulo(x) for x in est["divergencias"] if x["id"] == did)
        return [mensagem(f"Nota de {negrito(pessoa)} registrada.")] + self._proxima(est)

    def _finalizar(self, est: dict[str, Any]) -> list[Mensagem]:
        """Todas as divergências com nota: gera a planilha final (com as notas)."""
        versao = est["versoes"][-1]
        planilha = self.arm.caminho(versao["planilha"])
        try:
            self._rodar(versao["arquivos"], planilha,
                        {i: n["texto"] for i, n in est["notas"].items()})
        except Exception as erro:
            return [mensagem(f"⚠️ {negrito('Não consegui gerar a planilha final')}: "
                             f"{str(erro).rstrip('.')}. " + italico(
                                 "Envie os arquivos de novo; as notas das divergências que não "
                                 "mudarem serão mantidas."))]
        est["situacao"] = "pronto"
        n = len(est["divergencias"])
        texto = f"✅ {negrito('Tudo certo: ' + mes_extenso(est['mes']) + ' está pronto')}"
        texto += (f". As {n} divergência(s) têm nota." if n else ", sem divergências.")
        texto += "\n" + italico("O Conselho Fiscal recebe o pacote quando pedir.")
        if est["entregas"]:
            texto += (f"\n⚠️ {negrito('Atenção:')} ele já recebeu uma versão anterior em "
                      f"{est['entregas'][-1]['em'][:10]} e precisa pedir de novo.")
        return [mensagem(texto, anexos=[{"nome": planilha.name, "caminho": versao["planilha"]}],
                         botoes=[BOTAO_CORRIGIR] if n else [])]

    # ---------- Conselho Fiscal ----------

    def _cf(self, texto: str | None, botao: str | None) -> list[Mensagem]:
        pendente = self._pergunta_pendente()
        if botao:
            tipo, _, resto = botao.partition(":")
            if tipo == "qual_mes":                  # resposta a "qual mês?"
                return self._cf(cs.com_mes(pendente, resto), None) if pendente else [
                    self._menu_cf()]
            if tipo == "enviar":
                return self._enviar(resto)
            if tipo == "div":
                return self._divergencia_cf(*resto.split(":", 1))
            if tipo == "ajuda":
                return [self._como_funciona("cf")]
            return [self._menu_cf(saudar=True)]
        if pede_ajuda(texto):
            return [self._como_funciona("cf")]
        if not texto or pede_menu(texto):
            return [self._menu_cf(saudar=True)]
        meses = self.arm.meses()
        mes = reconhecer_mes(texto, meses)
        if pendente and mes and cs.so_pedido(texto):    # respondeu "qual mês?" por escrito
            return self._cf(cs.com_mes(pendente, mes), None)
        if not mes and meses and cs.cita_mes_corrente(texto):
            return [self._perguntar_mes(texto, meses)]
        if mes and cs.so_pedido(texto):     # "julho", "manda julho": nem passa pela IA
            return self._enviar(mes)
        nomes = self._nomes(meses)
        ctx = ContextoPergunta(texto, date.today().isoformat(), tuple(meses), nomes)
        aviso = ""
        try:
            pergunta = self.ia.entender(ctx)
        except Exception as erro:       # sinaliza e segue sem a IA
            log.warning("a IA não entendeu a pergunta do CF: %s", erro)
            aviso = italico("Não consegui ler a pergunta agora (falha na IA).") + "\n"
            pergunta = None
        if pergunta is None:
            pergunta = self._sem_ia(texto, mes)
        elif not pergunta.meses and mes:
            pergunta = replace(pergunta, meses=(mes,))
        if pergunta.consulta in COMANDOS and (r := self._comando("cf", pergunta.consulta)):
            return r
        respostas = self._consultar(pergunta, texto, nomes)
        if aviso:
            respostas[0]["texto"] = aviso + respostas[0]["texto"]
        return respostas

    def _pergunta_pendente(self) -> str | None:
        """A pergunta do CF que esperava "qual mês?". Vale só para a mensagem
        seguinte: qualquer outra coisa a descarta."""
        geral = self.arm.estado_geral()
        pendente = geral.pop("pergunta_cf", None)
        if pendente is not None:
            self.arm.salvar_estado_geral(geral)
        return pendente

    def _perguntar_mes(self, texto: str, meses: list[str]) -> Mensagem:
        """ "Deste mês" não diz qual: pergunta se é o mês atual ou um dos meses
        com dados, e guarda a pergunta para responder depois da escolha."""
        geral = self.arm.estado_geral()
        geral["pergunta_cf"] = texto
        self.arm.salvar_estado_geral(geral)
        atual = date.today().strftime("%Y-%m")
        opcoes = [atual] + [m for m in reversed(meses) if m != atual]
        com_dados = ", ".join(mes_extenso(m) for m in meses)
        return mensagem(f"Você está falando de {negrito(mes_extenso(atual))} (o mês atual) ou de "
                        f"outro mês? Meses com dados: {com_dados}.",
                        botoes=[{"id": f"qual_mes:{m}", "rotulo": mes_extenso(m).capitalize()}
                                for m in opcoes[:MAX_LISTA]])

    def _sem_ia(self, texto: str, mes: str | None) -> Pergunta:
        """Sem a IA: uma pergunta que cita um mês e um destino dele ("quanto
        deu o açaí em julho?") recebe o destino; que cita só o mês, o resumo."""
        if not mes:
            return Pergunta("situacao")
        est = self.arm.estado_mes(mes)
        totais = self._totais_destino(est) if cs.fechado(est) else None
        destino = arr.citado(texto, list(totais or {}))
        return Pergunta("destino", (mes,), destino=destino) if destino else Pergunta("resumo",
                                                                                     (mes,))

    def _nomes(self, meses: list[str]) -> tuple[tuple[str, bool], ...]:
        """Os nomes das divergências de todos os meses, para os apelidos."""
        nomes: dict[str, bool] = {}
        for mes in meses:
            for nome, conta in dv.nomes(self.arm.estado_mes(mes)["divergencias"]):
                nomes.setdefault(nome, conta)
        return tuple(nomes.items())

    def _consultar(self, p: Pergunta, texto: str = "",
                   nomes: tuple[tuple[str, bool], ...] = ()) -> list[Mensagem]:
        """A resposta à pergunta `p`. Resumo, lista e pessoa: os dados vêm de
        `consultas`, e a IA escreve a resposta ao `texto` com eles (sem IA, ou
        se ela falhar, vão os dados como estão)."""
        if p.consulta == "pacote":
            if not p.meses:
                return [self._menu_cf()]
            return [m for mes in p.meses for m in self._enviar(mes)]
        if p.consulta == "situacao":
            if not p.meses:
                return [self._menu_cf()]
            return [m for mes in p.meses for m in self._situacao_cf(mes)]
        if p.consulta == "outra":
            return [mensagem(cs.AJUDA, botoes=[BOTAO_AJUDA, {"id": "menu:", "rotulo": "Menu"}])]
        if p.consulta == "pessoa":
            return self._pessoa_cf(p.pessoa, p.meses, texto, nomes)
        if p.consulta == "destino":
            return self._destino_cf(p.destino, p.meses, texto, nomes)
        if p.consulta == "comparar" or (p.consulta == "resumo" and len(p.meses) > 1):
            return self._comparar_cf(p.meses, texto, nomes)
        meses = p.meses or self._fechados()[-1:]    # sem mês: o último fechado
        if not meses:
            return [mensagem("Ainda não há mês fechado para consultar."), self._menu_cf()]
        respostas, fechados = [], []
        for mes in meses:
            est = self.arm.estado_mes(mes)
            if cs.fechado(est):
                fechados.append(est)
            else:
                respostas += self._aberto(mes)
        if p.consulta == "resumo":
            for est in fechados:
                dados = cs.resumo(est, self._conferencias(est))
                respostas.append(mensagem(self._responder(texto, dados, nomes) or dados,
                                          botoes=[_botao_pacote(est["mes"])]))
        elif len(fechados) == 1:
            est = fechados[0]
            dados = "\n\n".join([cs.lista(est)]
                                + [cs.detalhe(est, d) for d in est["divergencias"]])
            resposta = self._responder(texto, dados, nomes)
            if resposta and est["divergencias"]:
                resposta += "\n" + italico("Para ver os itens e a nota de uma, escolha nas opções.")
            respostas.append(mensagem(resposta or cs.lista(est), botoes=[
                {"id": f"div:{est['mes']}:{d['id']}", "rotulo": dv.rotulo(d)}
                for d in est["divergencias"][:MAX_LISTA - 1]] + [_botao_pacote(est["mes"])]))
        elif fechados:      # divergências de vários meses: uma resposta só
            rec = cmp.recorrentes(fechados)
            dados = "\n\n".join(
                [cs.lista(est, opcoes=False) for est in fechados]
                + [cs.detalhe(est, d) for est in fechados for d in est["divergencias"]]
                + ["• Com divergência em mais de um mês: " + ("; ".join(rec) or "ninguém")])
            respostas.append(mensagem(
                self._responder(texto, dados, nomes)
                or "\n\n".join(cs.lista(est, opcoes=False) for est in fechados),
                botoes=[_botao_pacote(est["mes"]) for est in fechados[-MAX_BOTOES:]]))
        return respostas

    def _comparar_cf(self, meses: tuple[str, ...], texto: str,
                     nomes: tuple[tuple[str, bool], ...]) -> list[Mensagem]:
        """A relação entre meses fechados (`comparacao`). Sem mês: todos os
        fechados (até 12); um mês só: ele e o fechado anterior."""
        fechados = self._fechados()
        if not meses:
            escolhidos = fechados
        elif len(meses) == 1:
            escolhidos = [m for m in fechados if m < meses[0]][-1:] + list(meses)
        else:
            escolhidos = sorted(meses)
        respostas = [m for mes in escolhidos if mes not in fechados for m in self._aberto(mes)]
        ok = [mes for mes in escolhidos if mes in fechados]
        if len(ok) < 2:
            lista = ", ".join(mes_extenso(m) for m in fechados) or "nenhum"
            respostas.append(mensagem(
                f"Para comparar, preciso de {negrito('pelo menos dois meses fechados')}. "
                f"Meses fechados: {lista}."))
            return respostas
        ests = [self.arm.estado_mes(m) for m in ok]
        dados = cmp.comparar([(est, self._conferencias(est)) for est in ests])
        respostas.append(mensagem(self._responder(texto, dados, nomes) or dados,
                                  botoes=[_botao_pacote(m) for m in ok[-MAX_BOTOES:]]))
        return respostas

    def _destino_cf(self, destino: str, meses: tuple[str, ...], texto: str,
                    nomes: tuple[tuple[str, bool], ...]) -> list[Mensagem]:
        """Quanto entrou de um destino (ou de cada um, sem `destino`) nos meses
        fechados pedidos; sem mês, no último fechado (`arrecadacao`)."""
        meses = tuple(sorted(meses)) or tuple(self._fechados()[-1:])
        if not meses:
            return [mensagem("Ainda não há mês fechado para consultar."), self._menu_cf()]
        respostas, totais = [], []
        for mes in meses:
            est = self.arm.estado_mes(mes)
            if not cs.fechado(est):
                respostas += self._aberto(mes)
            elif (t := self._totais_destino(est)) is None:
                respostas.append(mensagem(f"Não consegui ler o {REGISTRO} de "
                                          f"{mes_extenso(mes)}."))
            else:
                totais.append((mes, t))
        if totais:
            dados = arr.texto(destino, totais)
            respostas.append(mensagem(self._responder(texto, dados, nomes) or dados,
                                      botoes=[_botao_pacote(m) for m, _ in totais[-MAX_BOTOES:]]))
        return respostas

    def _totais_destino(self, est: dict[str, Any]) -> arr.Totais | None:
        """Os totais por destino da planilha de entradas da versão atual."""
        entradas = self.arm.caminho(est["versoes"][-1]["arquivos"]["entradas"]["caminho"])
        try:
            return arr.totais(entradas, destinos.carregar(self.cadastro_destinos))
        except Exception as erro:       # sinaliza e segue
            log.warning("não li os destinos de %s: %s", est["mes"], erro)
            return None

    def _responder(self, pergunta: str, dados: str,
                   nomes: tuple[tuple[str, bool], ...]) -> str:
        """A resposta da IA à pergunta do CF, com os `dados`; "" sem IA, sem
        pergunta (clique) ou se a IA falhar (aí vão os dados)."""
        if not pergunta:
            return ""
        try:
            return self.ia.responder(ContextoResposta(pergunta, dados, nomes))
        except Exception as erro:       # sinaliza e segue com os dados
            log.warning("a IA não respondeu ao CF: %s", erro)
            return ""

    def _fechados(self) -> list[str]:
        return [m for m in self.arm.meses() if cs.fechado(self.arm.estado_mes(m))]

    def _conferencias(self, est: dict[str, Any]) -> list[dict[str, Any]]:
        """As conferências de totais, do JSON ao lado da planilha da versão."""
        p = self.arm.caminho(est["versoes"][-1]["planilha"]).with_suffix(".json")
        try:
            return json.loads(p.read_text(encoding="utf-8"))["conferencias"]
        except (OSError, ValueError, KeyError) as erro:
            log.warning("sem as conferências de %s: %s", est["mes"], erro)
            return []

    def _situacao_cf(self, mes: str) -> list[Mensagem]:
        est = self.arm.estado_mes(mes)
        if not cs.fechado(est):
            return self._aberto(mes)
        return [mensagem(f"{negrito(mes_extenso(mes).capitalize() + ' está fechado')}: "
                         f"{cs.situacao(est)}.",
                         botoes=[_botao_pacote(mes)])]

    def _pessoa_cf(self, nome: str, meses: tuple[str, ...], texto: str = "",
                   nomes: tuple[tuple[str, bool], ...] = ()) -> list[Mensagem]:
        if not nome:
            return [mensagem(f"{negrito('De quem?')} "
                             + italico("Escreva o nome como aparece no registro de receitas."))]
        respostas, fechados = [], []
        for mes in meses or self._fechados():
            est = self.arm.estado_mes(mes)
            if cs.fechado(est):
                fechados.append(est)
            elif meses:
                respostas += self._aberto(mes)
        if fechados or not respostas:
            achadas = {est["mes"] for est, _ in cs.achar(nome, fechados)}
            dados = cs.da_pessoa(nome, fechados)
            resposta = self._responder(texto, dados, nomes) if achadas else ""
            respostas.append(mensagem(resposta or dados, botoes=[
                _botao_pacote(mes) for mes in sorted(achadas)[-MAX_BOTOES:]]))
        return respostas

    def _divergencia_cf(self, mes: str, did: str) -> list[Mensagem]:
        est = self.arm.estado_mes(mes)
        if not cs.fechado(est):
            return self._aberto(mes)
        d = next((d for d in est["divergencias"] if d["id"] == did), None)
        if d is None:       # a tesouraria reenviou os arquivos depois da lista
            return [mensagem("Essa divergência não está mais na versão atual do mês."),
                    mensagem(cs.lista(est))]
        return [mensagem(cs.detalhe(est, d), botoes=[_botao_pacote(mes)])]

    def _aberto(self, mes: str) -> list[Mensagem]:
        """A situação de um mês que não está fechado (com o menu, se a
        tesouraria nem terminou de enviar os arquivos)."""
        est = self.arm.estado_mes(mes)
        if est:
            return [mensagem(f"{negrito(mes_extenso(mes).capitalize() + ' ainda não foi fechado')}"
                             f": está com a tesouraria ({_pendencias(est)}).")]
        envio = self.arm.estado_geral().get("envio", {})
        if envio.get("entradas", {}).get("mes") == mes:
            texto = (f"{negrito(mes_extenso(mes).capitalize() + ' ainda não foi fechado')}: a "
                     "tesouraria começou a enviar os arquivos, mas ainda faltam "
                     f"{sum(t not in envio for t in TIPOS_ENVIO)}.")
        else:
            texto = (f"{negrito(mes_extenso(mes).capitalize() + ' ainda não foi fechado')}: a "
                     "tesouraria ainda não enviou os arquivos.")
        return [mensagem(texto), self._menu_cf()]

    def _menu_cf(self, saudar: bool = False) -> Mensagem:
        """Os meses e o que dá para pedir; com `saudar`, abre com a saudação
        (é o menu pedido, não a resposta a um mês que não está pronto)."""
        linhas = [self._saudacao("cf")] if saudar else []
        extras = [BOTAO_AJUDA] + self._extras if saudar else []
        meses = self.arm.meses()
        if not meses:
            linhas.append("Ainda não há mês conferido pela tesouraria. "
                          + italico("Quando houver, peça aqui (ex.: \"julho\")."))
            return mensagem("\n".join(linhas), botoes=extras)
        linhas.append(negrito("Meses:"))
        botoes = []
        for mes in reversed(meses[-MAX_LISTA:]):
            est = self.arm.estado_mes(mes)
            if est["situacao"] == "aguardando_respostas":
                sit = f"com a tesouraria ({_pendencias(est)})"
            else:
                sit = "pronto" if est["situacao"] == "pronto" else (
                    f"enviado em {data_br(est['entregas'][-1]['em'])}")
                botoes.append({"id": f"enviar:{mes}", "rotulo": mes_extenso(mes).capitalize()})
            linhas.append(f"• {negrito(mes_extenso(mes))}: {sit}")
        linhas.append(italico("Toque num mês para receber o pacote, ou pergunte (ex.: \"quanto "
                              "entrou de açaí em julho?\")."))
        return mensagem("\n".join(linhas),
                        botoes=botoes[:MAX_LISTA - len(extras)] + extras)

    def _enviar(self, mes: str) -> list[Mensagem]:
        est = self.arm.estado_mes(mes)
        if not cs.fechado(est):
            return self._aberto(mes)
        versao = est["versoes"][-1]
        r = est["resumo"]
        n = len(est["divergencias"])
        linhas = [f"📦 {negrito('Receitas de ' + mes_extenso(mes))} "
                  + italico(f"(versão {est['versao']})"),
                  f"{r['recibos']} recibos, {negrito(str(r['conformes']) + ' batem')} com os "
                  "extratos. " + (f"{n} divergência(s), todas com nota da tesouraria (aba "
                                  "Divergências)." if n else "Nenhuma divergência.")]
        linhas += [f"⚠️ [{a['extrato']}] {a['verificacao']}: {a['status']}"
                   for a in est["alertas"]]
        linhas.append("Seguem a planilha da conferência e os arquivos da tesouraria. " + italico(
            "Se o Conselho não aprovar, a tesouraria reenvia os arquivos e a conferência "
            "recomeça."))
        # cópia fixa da planilha entregue: uma correção depois regrava a da versão
        n = len(est["entregas"]) + 1
        planilha = self.arm.caminho(versao["planilha"])
        copia = planilha.parent / f"entrega{n}" / planilha.name
        copia.parent.mkdir(exist_ok=True)
        shutil.copy(planilha, copia)
        anexos = [{"nome": copia.name, "caminho": self.arm.relativo(copia)}]
        anexos += [{"nome": a["nome"], "caminho": a["caminho"]}
                   for a in versao["arquivos"].values()]
        est["situacao"] = "entregue"
        est["entregas"].append({"em": agora(), "versao": est["versao"],
                                "planilha": self.arm.relativo(copia),
                                **({"para": self._autor} if self._autor else {})})
        self.arm.salvar_estado_mes(est)
        m = mensagem("\n".join(linhas), anexos=anexos)
        m["entrega"] = {"mes": mes, "n": n}   # o canal desfaz se os arquivos não saírem
        return [m]
