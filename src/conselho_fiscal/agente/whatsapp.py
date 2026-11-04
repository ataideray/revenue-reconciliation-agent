"""WhatsApp (Cloud API da Meta), pela API REST e sem bibliotecas extras
(decisão de 2026-10-21).

A Meta avisa cada mensagem chamando o webhook (`/whatsapp`, em `web.py`);
este módulo confere a assinatura, ignora avisos repetidos, descobre o papel
pelo número, baixa os anexos, chama `Agente.receber` (o mesmo do simulador)
e manda as respostas: texto, botões (até 3), lista (até 10) e documentos.

Configuração (variáveis de ambiente; os segredos também podem estar em
arquivos de ~/.config/conselho-fiscal/, fora do repositório):
  WHATSAPP_TOKEN            token permanente de Usuário do Sistema
                            (ou o arquivo whatsapp_token)
  WHATSAPP_APP_SECRET       Chave Secreta do Aplicativo: confere a assinatura
                            de cada aviso (ou o arquivo whatsapp_app_secret)
  WHATSAPP_PHONE_NUMBER_ID  identificador do número na Meta
  WHATSAPP_VERIFY_TOKEN     texto combinado com o painel da Meta (Webhooks)
  WHATSAPP_CONTATOS         quem fala com o agente: "5511999990000=tesouraria,cf;
                            5511988887777=cf". Número fora da lista é ignorado.
                            Com "@nome" no fim ("5511...=tesouraria,cf@segundo"),
                            o número tem um espaço só dele: meses, envios e
                            conversas à parte (em <pasta>/espacos/nome). Sem
                            "@", todos compartilham os dados da pasta principal.
  WHATSAPP_GRAPH_VERSION    versão da API (padrão abaixo)

Primeiro contato (2026-10-23): o agente se apresenta e pergunta o nome, que
fica guardado com o número e vai para o histórico de tudo o que a pessoa
fizer ("meu nome é …" troca). O papel vem do cadastro (WHATSAPP_CONTATOS),
nunca do que a pessoa diz; um número com os dois papéis escolhe por botão
como quer seguir e troca pelo botão "Trocar de papel" do menu (ou com "#cf"
e "#tesouraria"). Toda mensagem do agente começa com o nome dele ("*Elo*"),
como num grupo; para quem tem os dois papéis, com o papel da vez ("*Elo* ·
_Tesouraria_").

Só há respostas a quem escreveu (dentro da janela de 24 h da Meta): o agente
não inicia conversa, então não precisa de modelos de mensagem.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import logging
import mimetypes
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from conselho_fiscal.agente.agente import (
    NOME_AGENTE,
    PAPEIS,
    Agente,
    Mensagem,
    mensagem,
    pede_ajuda,
    pede_menu,
    sem_saudacao,
)
from conselho_fiscal.agente.formato import italico, negrito
from conselho_fiscal.comum.texto import norm_maiusculo

VERSAO_PADRAO = "v25.0"
GRAPH = "https://graph.facebook.com/{versao}"
PASTA_SEGREDOS = Path.home() / ".config" / "conselho-fiscal"
MAX_TEXTO = 4096          # limite de uma mensagem de texto
MAX_CORPO = 1024          # limite do texto de botões e listas
MAX_ANEXO = 50 * 1024 * 1024
ESPERA = 30               # segundos por chamada à Meta
TENTATIVAS = 3            # a rede às vezes derruba a conexão: repete
MAX_VISTOS = 500          # avisos já tratados que ficam guardados
JANELA = 4.0              # segundos à espera de outros arquivos do mesmo número
TROCA = {"#TESOURARIA": "tesouraria", "#CF": "cf"}
# trocar de papel por escrito ("troque para o conselho fiscal", "passa pra
# tesouraria", "quero ser CF"; 2026-10-26): o pedido tem um verbo de troca (ou
# "como"/"modo") e só palavras de ligação; frase com outra coisa segue adiante
VERBOS_TROCA = {"TROCA", "TROQUE", "TROCAR", "TROCO", "MUDA", "MUDE", "MUDAR", "PASSA", "PASSE",
                "PASSAR", "ALTERNA", "ALTERNE", "ALTERNAR", "VOLTA", "VOLTE", "VOLTAR", "VAI",
                "VA", "IR", "ENTRA", "ENTRE", "ENTRAR", "QUERO", "SER", "SOU", "COMO", "MODO",
                "USAR", "USA", "USE", "FICAR", "FICA", "FIQUE"}
LIGACAO_TROCA = {"PARA", "PRA", "PRO", "P", "O", "A", "DO", "DA", "DE", "AO", "NO", "NA", "EM",
                 "ME", "EU", "MIM", "PAPEL", "POR", "FAVOR", "PF", "PFV", "AGORA", "PODE",
                 "PODERIA", "VOCE", "VC", "QUE", "E", "OK", "TA", "FISCAL", "AQUI"}
ALVOS_TROCA = {"TESOURARIA": "tesouraria", "CONSELHO": "cf", "CF": "cf"}
NOME_LONGO = {"tesouraria": "Tesouraria", "cf": "Conselho Fiscal"}
BOTAO_TROCAR = {"id": "papel:trocar", "rotulo": "Trocar de papel"}
BOAS_VINDAS = ("👋 Olá! Sou o " + negrito(NOME_AGENTE) + ", o assistente do Conselho Fiscal.\n"
               "Ligo os recibos do registro de receitas da tesouraria aos Pix dos extratos "
               "bancários e levo o "
               "resultado ao Conselho Fiscal.\n"
               + negrito("Como você se chama?") + " "
               + italico("(seu nome fica no histórico do que você fizer aqui)"))
NOME_DE_NOVO = "Me diga só o seu nome, por favor (ex.: " + negrito("Noeli Pedra") + ")."
REENVIAR = "\n\n" + italico("Depois, envie o arquivo de novo.")
MEU_NOME = re.compile(r"^\s*(?:meu nome (?:é|e)|me chame de|me chamo)\s+(.+)$", re.I)
SO_DOCUMENTO = ("Só consigo ler *o registro de receitas da tesouraria (.xlsx)* e *os extratos "
                "bancários em PDF*, "
                "enviados como documento (📎 → Documento).")
FALHA = "⚠️ *Tive um problema ao processar sua mensagem.* _Tente de novo em instantes._"
FALHA_DE_REDE = (TimeoutError, urllib.error.URLError, http.client.RemoteDisconnected,
                 ConnectionError)

FORA_DA_LISTA = 131030     # número de teste: destinatário fora da lista de permitidos

# Tipos dos arquivos que o agente troca. O `mimetypes` do Python 3.12 (o da
# imagem) não conhece .xlsx, e a Meta recusa application/octet-stream.
TIPOS = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".pdf": "application/pdf",
    ".csv": "text/plain",
    ".txt": "text/plain",
}

log = logging.getLogger(__name__)


def tipo_do_arquivo(nome: str) -> str:
    """Tipo (MIME) pelo nome do arquivo."""
    return (TIPOS.get(Path(nome).suffix.lower()) or mimetypes.guess_type(nome)[0]
            or "application/octet-stream")


def extensao_do_tipo(tipo: str) -> str:
    """Extensão pelo tipo (MIME), para documento que chega sem nome."""
    tipo = tipo.split(";")[0].strip().lower()
    for extensao, t in TIPOS.items():
        if t == tipo:
            return extensao
    return mimetypes.guess_extension(tipo) or ""


class ErroMeta(RuntimeError):
    def __init__(self, mensagem: str, codigo: int | None = None):
        super().__init__(mensagem)
        self.codigo = codigo


# ---------- configuração ----------

def _segredo(variavel: str, arquivo: str) -> str | None:
    if os.environ.get(variavel):
        return os.environ[variavel].strip()
    p = PASTA_SEGREDOS / arquivo
    if p.exists():
        return p.read_text(encoding="utf-8").strip() or None
    return None


def numero(texto: str) -> str:
    """Número só com dígitos, com o 55 e o 9 do celular. A Meta às vezes manda
    o número do Brasil sem o 9 (551199990000); o cadastro pode vir sem o 55."""
    n = re.sub(r"\D", "", texto)
    if len(n) == 10 or (len(n) == 11 and n[2] == "9"):     # DDD + fixo ou celular
        n = "55" + n
    if n.startswith("55") and len(n) == 12 and n[4] in "6789":
        n = n[:4] + "9" + n[4:]
    return n


def _itens(texto: str) -> list[tuple[str, tuple[str, ...], str]]:
    """(número, papéis, espaço) de cada contato de WHATSAPP_CONTATOS."""
    itens = []
    for item in re.split(r"[;\n]", texto or ""):
        if not item.strip():
            continue
        num, _, resto = item.partition("=")
        papeis, _, espaco = resto.partition("@")
        lista = tuple(p.strip().lower() for p in papeis.split(",") if p.strip())
        errados = [p for p in lista if p not in PAPEIS]
        espaco = espaco.strip().lower()
        if (not num.strip() or not lista or errados
                or ("@" in resto and not re.fullmatch(r"[a-z0-9_-]+", espaco))):
            raise ValueError(f"contato inválido em WHATSAPP_CONTATOS: {item.strip()!r}")
        itens.append((numero(num), lista, espaco))
    return itens


def nome_valido(texto: str) -> str | None:
    """O nome escrito pela pessoa, limpo; None se não parece um nome (uma
    saudação, um número, uma frase)."""
    t = " ".join(texto.split()).strip(" .!,;")
    t = re.sub(r"^(?:sou (?:a |o )?|é (?:a |o )?|eu sou (?:a |o )?)", "", t, flags=re.I)
    if (not 2 <= len(t) <= 40 or len(t.split()) > 5 or pede_menu(t) or pede_ajuda(t)
            or not re.fullmatch(r"[^\W\d_]+(?:[ '.-][^\W\d_]+)*\.?", t)):
        return None
    return t if any(c.isupper() for c in t) else t.title()


def pede_troca(texto: str) -> str | None:
    """O papel pedido numa frase curta de troca ("troque para o conselho
    fiscal" -> "cf"); "trocar de papel", sem dizer qual, dá "trocar"."""
    palavras = re.findall(r"[A-Z]+", norm_maiusculo(texto))
    if not palavras or len(palavras) > 10:
        return None
    alvos = {ALVOS_TROCA[p] for p in palavras if p in ALVOS_TROCA}
    if (len(alvos) > 1 or not set(palavras) & VERBOS_TROCA
            or not set(palavras) <= VERBOS_TROCA | LIGACAO_TROCA | set(ALVOS_TROCA)):
        return None
    if alvos:
        return alvos.pop()
    return "trocar" if set(palavras) & {"TROCA", "TROQUE", "TROCAR", "MUDA", "MUDE", "MUDAR",
                                        "ALTERNA", "ALTERNE", "ALTERNAR"} and "PAPEL" in palavras \
        else None


def ler_contatos(texto: str) -> dict[str, tuple[str, ...]]:
    """"5511999990000=tesouraria,cf; 5511988887777=cf" -> {número: papéis}."""
    return {num: papeis for num, papeis, _ in _itens(texto)}


def ler_espacos(texto: str) -> dict[str, str]:
    """{número: espaço} dos contatos com "@espaço" (os outros usam a pasta principal)."""
    return {num: espaco for num, _, espaco in _itens(texto) if espaco}


@dataclass
class Config:
    token: str
    segredo: str
    numero_id: str
    verificacao: str
    contatos: dict[str, tuple[str, ...]] = field(default_factory=dict)
    versao: str = VERSAO_PADRAO
    espacos: dict[str, str] = field(default_factory=dict)     # número -> espaço próprio


def config() -> tuple[Config | None, str | None]:
    """(config, o que falta). Sem tudo preenchido, o WhatsApp fica desligado."""
    valores = {
        "WHATSAPP_TOKEN": _segredo("WHATSAPP_TOKEN", "whatsapp_token"),
        "WHATSAPP_APP_SECRET": _segredo("WHATSAPP_APP_SECRET", "whatsapp_app_secret"),
        "WHATSAPP_PHONE_NUMBER_ID": os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        "WHATSAPP_VERIFY_TOKEN": os.environ.get("WHATSAPP_VERIFY_TOKEN", "").strip(),
        "WHATSAPP_CONTATOS": os.environ.get("WHATSAPP_CONTATOS", "").strip(),
    }
    faltam = [k for k, v in valores.items() if not v]
    if faltam:
        return None, ", ".join(faltam)
    return Config(valores["WHATSAPP_TOKEN"], valores["WHATSAPP_APP_SECRET"],
                  valores["WHATSAPP_PHONE_NUMBER_ID"], valores["WHATSAPP_VERIFY_TOKEN"],
                  ler_contatos(valores["WHATSAPP_CONTATOS"]),
                  os.environ.get("WHATSAPP_GRAPH_VERSION", "").strip() or VERSAO_PADRAO,
                  ler_espacos(valores["WHATSAPP_CONTATOS"])), None


def assinatura_ok(corpo: bytes, cabecalho: str | None, segredo: str) -> bool:
    """Confere o X-Hub-Signature-256: só a Meta conhece a Chave Secreta."""
    if not cabecalho or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(cabecalho[len("sha256="):], esperado)


# ---------- a API da Meta ----------

class Meta:
    """Chamadas à Graph API: enviar, subir e baixar arquivos, marcar como lida."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base = GRAPH.format(versao=cfg.versao)

    def _chamar(self, url: str, dados: bytes | None = None,
                tipo: str | None = None) -> bytes:
        cabecalhos = {"Authorization": f"Bearer {self.cfg.token}"}
        if tipo:
            cabecalhos["Content-Type"] = tipo
        for tentativa in range(1, TENTATIVAS + 1):
            pedido = urllib.request.Request(url, data=dados, headers=cabecalhos,
                                            method="POST" if dados is not None else "GET")
            try:
                with urllib.request.urlopen(pedido, timeout=ESPERA) as r:
                    return r.read()
            except urllib.error.HTTPError as erro:     # sem o token na mensagem
                detalhe = erro.read().decode("utf-8", "replace")[:500]
                try:
                    codigo = json.loads(detalhe)["error"]["code"]
                except (ValueError, KeyError, TypeError):
                    codigo = None
                raise ErroMeta(f"Meta respondeu {erro.code}: {detalhe}", codigo) from None
            except FALHA_DE_REDE as erro:
                if tentativa == TENTATIVAS:
                    raise ErroMeta(f"sem resposta da Meta ({erro})") from None
                time.sleep(tentativa)
        raise AssertionError("inalcançável")

    def _json(self, caminho: str, corpo: dict[str, Any]) -> dict[str, Any]:
        r = self._chamar(f"{self.base}/{caminho}", json.dumps(corpo).encode(),
                         "application/json")
        return json.loads(r)

    def enviar(self, para: str, conteudo: dict[str, Any]) -> None:
        self._json(f"{self.cfg.numero_id}/messages",
                   {"messaging_product": "whatsapp", "recipient_type": "individual",
                    "to": para, **conteudo})

    def marcar_lida(self, mensagem_id: str) -> None:
        self._json(f"{self.cfg.numero_id}/messages",
                   {"messaging_product": "whatsapp", "status": "read",
                    "message_id": mensagem_id})

    def baixar(self, midia_id: str) -> bytes:
        info = json.loads(self._chamar(f"{self.base}/{midia_id}"))
        if int(info.get("file_size") or 0) > MAX_ANEXO:
            raise ValueError("arquivo maior que 50 MB")
        return self._chamar(info["url"])

    def subir(self, nome: str, conteudo: bytes) -> str:
        """Sobe um arquivo para a Meta e devolve o id para enviar como documento."""
        mime = tipo_do_arquivo(nome)
        fronteira = uuid.uuid4().hex
        partes = []
        for chave, valor in (("messaging_product", "whatsapp"), ("type", mime)):
            partes.append(f"--{fronteira}\r\nContent-Disposition: form-data; "
                          f"name=\"{chave}\"\r\n\r\n{valor}\r\n".encode())
        nome_seguro = nome.replace('"', "'")
        partes.append(f"--{fronteira}\r\nContent-Disposition: form-data; name=\"file\"; "
                      f"filename=\"{nome_seguro}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
                      + conteudo + b"\r\n")
        partes.append(f"--{fronteira}--\r\n".encode())
        r = self._chamar(f"{self.base}/{self.cfg.numero_id}/media", b"".join(partes),
                         f"multipart/form-data; boundary={fronteira}")
        return json.loads(r)["id"]


# ---------- de mensagem do agente para o WhatsApp ----------

def _partes(texto: str, limite: int = MAX_TEXTO) -> list[str]:
    """Texto longo em pedaços, quebrando nas linhas."""
    pedacos, atual = [], ""
    for linha in texto.split("\n"):
        while len(linha) > limite:
            if atual:
                pedacos.append(atual)
                atual = ""
            pedacos.append(linha[:limite])
            linha = linha[limite:]
        junto = f"{atual}\n{linha}" if atual else linha
        if len(junto) > limite:
            pedacos.append(atual)
            atual = linha
        else:
            atual = junto
    if atual:
        pedacos.append(atual)
    return pedacos or [""]


def _interativo(m: Mensagem, corpo: str) -> dict[str, Any] | None:
    if m.get("botoes"):
        return {"type": "interactive", "interactive": {
            "type": "button", "body": {"text": corpo},
            "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"],
                                                                "title": b["rotulo"]}}
                                   for b in m["botoes"]]}}}
    if m.get("lista"):
        linhas = []
        for item in m["lista"]["itens"]:
            linha = {"id": item["id"], "title": item["rotulo"]}
            if item.get("descricao"):
                linha["description"] = item["descricao"]
            linhas.append(linha)
        return {"type": "interactive", "interactive": {
            "type": "list", "body": {"text": corpo},
            "action": {"button": m["lista"]["abrir"],
                       "sections": [{"title": "Opções", "rows": linhas}]}}}
    return None


def cabecalho(papel: str | None = None) -> str:
    """A linha de cima de toda mensagem, como o nome de quem escreve num
    grupo: "*Elo*", e o papel da vez para quem tem os dois ("*Elo* ·
    _Tesouraria_"; 2026-10-26). Uma linha em branco separa do texto."""
    return negrito(NOME_AGENTE) + (f" · {italico(NOME_LONGO[papel])}" if papel else "")


def com_cabecalho(texto: str, cab: str) -> str:
    return f"{cab}\n\n{texto}" if cab else texto       # uma linha em branco entre os dois


def converter(m: Mensagem, cab: str = "") -> list[dict[str, Any]]:
    """Uma mensagem do agente vira uma ou mais mensagens do WhatsApp, na ordem:
    o texto, os documentos (marcados com "anexo") e, por último, as opções.
    O texto vai junto com as opções quando cabe no limite delas e não há
    documentos entre os dois. Cada mensagem com texto leva o cabeçalho `cab`."""
    texto = m.get("texto") or ""
    opcoes = bool(m.get("botoes") or m.get("lista"))
    saida: list[dict[str, Any]] = []
    junto = opcoes and not m.get("anexos") and len(com_cabecalho(texto, cab)) <= MAX_CORPO
    if not junto and texto.strip():
        saida += [{"type": "text", "text": {"body": com_cabecalho(p, cab)}}
                  for p in _partes(texto, MAX_TEXTO - len(cab) - 2)]
    saida += [{"anexo": a} for a in m.get("anexos", [])]
    if opcoes:
        saida.append(_interativo(m, com_cabecalho(texto if junto else "Escolha uma opção:", cab)))
    return saida


# ---------- o canal ----------

class WhatsApp:
    def __init__(self, agente: Agente, meta: Meta, contatos: dict[str, tuple[str, ...]],
                 agentes: dict[str, Agente] | None = None):
        """`agente` atende os números sem espaço próprio e guarda o estado do
        canal; `agentes` dá o agente de cada número com espaço próprio."""
        self.agente = agente
        self.meta = meta
        self.contatos = contatos
        self.agentes = agentes or {}
        # um número é atendido uma mensagem por vez, do download ao envio das
        # respostas: senão a resposta de uma pode sair antes da anterior (2026-10-23)
        self._filas: dict[str, threading.Lock] = {}
        # arquivos mandados juntos viram um lote, com uma resposta só: o canal
        # espera `janela` segundos depois do último (2026-10-23)
        self.janela = JANELA
        self._lotes: dict[str, dict[str, Any]] = {}
        self._trava = threading.Lock()
        self._destino: dict[str, str] = {}     # número -> forma que a Meta aceitou

    def _enviar(self, para: tuple[str, ...], conteudo: dict[str, Any]) -> None:
        """Envia para o número do cadastro (com o 9) e, se a Meta recusar por
        estar fora da lista do número de teste, para a forma que veio no aviso
        (a Meta às vezes manda o número do Brasil sem o 9)."""
        num = para[0]
        formas = sorted(dict.fromkeys(para), key=lambda f: f != self._destino.get(num, num))
        for i, forma in enumerate(formas):
            try:
                self.meta.enviar(forma, conteudo)
                self._destino[num] = forma
                return
            except ErroMeta as erro:
                if erro.codigo != FORA_DA_LISTA or i == len(formas) - 1:
                    raise

    # estado do canal: avisos já tratados, o papel da vez e o nome de cada número
    def _estado(self) -> dict[str, Any]:
        est = self.agente.arm.estado_canal("whatsapp", {"vistos": [], "papel": {}})
        est.setdefault("nomes", {})
        est.setdefault("pedindo_nome", [])
        return est

    def _nome(self, num: str) -> str | None:
        return self._estado()["nomes"].get(num)

    def _guardar_nome(self, num: str, nome: str | None, pedindo: bool = False) -> None:
        with self._trava:
            est = self._estado()
            if nome:
                est["nomes"][num] = nome
            est["pedindo_nome"] = [n for n in est["pedindo_nome"] if n != num] + (
                [num] if pedindo else [])
            self.agente.arm.salvar_estado_canal("whatsapp", est)

    def _ja_visto(self, mensagem_id: str) -> bool:
        with self._trava:
            est = self._estado()
            if mensagem_id in est["vistos"]:
                return True
            est["vistos"] = (est["vistos"] + [mensagem_id])[-MAX_VISTOS:]
            self.agente.arm.salvar_estado_canal("whatsapp", est)
            return False

    def _papel(self, num: str) -> str:
        papeis = self.contatos[num]
        papel = self._estado()["papel"].get(num)
        return papel if papel in papeis else papeis[0]

    def _trocar(self, num: str, papel: str) -> None:
        with self._trava:
            est = self._estado()
            est["papel"][num] = papel
            self.agente.arm.salvar_estado_canal("whatsapp", est)

    def mensagens(self, aviso: dict[str, Any]) -> list[dict[str, Any]]:
        """As mensagens recebidas num aviso da Meta (os status só vão para o log)."""
        recebidas = []
        for entrada in aviso.get("entry", []):
            for mudanca in entrada.get("changes", []):
                valor = mudanca.get("value", {})
                recebidas += valor.get("messages", [])
                for st in valor.get("statuses", []):
                    if st.get("status") == "failed":
                        log.warning("WhatsApp: mensagem %s não entregue: %s",
                                    st.get("id"), st.get("errors"))
        return recebidas

    def processar(self, msg: dict[str, Any]) -> None:
        """Uma mensagem recebida: nunca levanta exceção (sinalizar, não bloquear)."""
        origem = msg.get("from", "")
        para = (numero(origem), origem)
        try:
            if not msg.get("id") or self._ja_visto(msg["id"]):
                return
            num = para[0]
            if num not in self.contatos:
                log.warning("WhatsApp: mensagem de número fora dos contatos (final %s)",
                            num[-4:])
                return
            self._marcar_lida(msg["id"])
            if msg.get("type") == "document":
                self._juntar(para, num, msg)
                return
            with self._fila(num):
                self._esvaziar_lote(num)        # os arquivos que esperavam vêm antes
                self._atender(para, num, msg)
        except Exception:
            self._falhou(para, msg.get("id"))

    def _marcar_lida(self, mensagem_id: str) -> None:
        try:
            self.meta.marcar_lida(mensagem_id)
        except Exception as erro:          # só a confirmação de leitura
            log.warning("WhatsApp: não marquei como lida: %s", erro)

    def _falhou(self, para: tuple[str, ...], mensagem_id: str | None) -> None:
        log.exception("WhatsApp: erro ao processar a mensagem %s", mensagem_id)
        try:
            self._enviar(para, {"type": "text",
                                "text": {"body": com_cabecalho(FALHA, cabecalho())}})
        except Exception:
            log.exception("WhatsApp: não consegui avisar a falha")

    def _fila(self, num: str) -> threading.Lock:
        with self._trava:
            return self._filas.setdefault(num, threading.Lock())

    # ---------- arquivos mandados juntos ----------

    def _juntar(self, para: tuple[str, ...], num: str, msg: dict[str, Any]) -> None:
        """Guarda o arquivo no lote do número e (re)começa a espera."""
        with self._trava:
            lote = self._lotes.setdefault(num, {"para": para, "msgs": [], "timer": None})
            lote["msgs"].append(msg)
            if lote["timer"]:
                lote["timer"].cancel()
            lote["timer"] = threading.Timer(self.janela, self._fim_da_espera, (num, lote))
            lote["timer"].daemon = True
            lote["timer"].start()

    def esvaziar(self) -> None:
        """Atende já os lotes que esperam (testes e encerramento)."""
        with self._trava:
            nums = list(self._lotes)
        for num in nums:
            with self._fila(num):
                self._esvaziar_lote(num)

    def _fim_da_espera(self, num: str, lote: dict[str, Any]) -> None:
        with self._fila(num):
            self._esvaziar_lote(num, lote)

    def _esvaziar_lote(self, num: str, so: dict[str, Any] | None = None) -> None:
        """Atende o lote do número (chamado com a fila do número). Com `so`,
        só se o lote ainda for esse (uma espera antiga não atende o novo)."""
        with self._trava:
            lote = self._lotes.get(num)
            if not lote or (so is not None and lote is not so):
                return
            del self._lotes[num]
        lote["timer"].cancel()
        para, msgs = lote["para"], lote["msgs"]
        try:
            if len(msgs) == 1 or not self._nome(num) or self._papel(num) != "tesouraria":
                # um arquivo só, o CF ou o primeiro contato (que pede o nome uma vez)
                for msg in msgs if self._nome(num) else msgs[:1]:
                    self._atender(para, num, msg)
                return
            agente = self.agentes.get(num, self.agente)
            respostas = agente.receber_arquivos([self._baixar(m) for m in msgs],
                                                self._nome(num), self._extras(num))
            for m in respostas:
                self._responder(agente, para, m, self._cabecalho(num, "tesouraria"))
        except Exception:
            self._falhou(para, ", ".join(m.get("id", "") for m in msgs))

    def _baixar(self, msg: dict[str, Any]) -> tuple[str, bytes]:
        doc = msg["document"]
        nome = doc.get("filename") or f"arquivo{extensao_do_tipo(doc.get('mime_type', ''))}"
        return nome, self.meta.baixar(doc["id"])

    def _extras(self, num: str) -> list[dict[str, str]]:
        return [BOTAO_TROCAR] if len(self.contatos[num]) > 1 else []

    def _cabecalho(self, num: str, papel: str) -> str:
        """O papel só aparece para quem tem os dois."""
        return cabecalho(papel if len(self.contatos[num]) > 1 else None)

    def _avisar(self, para: tuple[str, ...], num: str, m: Mensagem) -> None:
        """Mensagem do próprio canal (boas-vindas, escolha do papel)."""
        self._responder(self.agentes.get(num, self.agente), para, m, cabecalho())

    def _menu(self, para: tuple[str, ...], num: str) -> None:
        agente, papel = self.agentes.get(num, self.agente), self._papel(num)
        for m in agente.menu(papel, self._nome(num), self._extras(num)):
            self._responder(agente, para, m, self._cabecalho(num, papel))

    def _escolher_papel(self, para: tuple[str, ...], num: str, texto: str) -> None:
        self._avisar(para, num, mensagem(texto, botoes=[
            {"id": f"papel:{p}", "rotulo": NOME_LONGO[p]} for p in self.contatos[num]]))

    def _pedido_de_troca(self, para: tuple[str, ...], num: str, troca: str) -> bool:
        """Troca de papel pedida por escrito. True se a mensagem foi tratada."""
        papeis = self.contatos[num]
        if troca == "trocar":
            if len(papeis) < 2:
                return False
            self._escolher_papel(para, num, negrito("Como você quer seguir?"))
        elif troca in papeis:
            if len(papeis) < 2:
                return False                # só tem esse: segue como mensagem comum
            self._trocar(num, troca)
            self._menu(para, num)
        else:
            self._avisar(para, num, mensagem(
                f"Este número não está cadastrado como {negrito(NOME_LONGO[troca])}. "
                + italico("Quem cuida do cadastro pode incluir.")))
        return True

    def _identificar(self, para: tuple[str, ...], num: str, tipo: str | None,
                     texto: str | None) -> bool:
        """Nome do número: pergunta no primeiro contato e guarda a resposta;
        "meu nome é …" troca. True se a mensagem foi tratada aqui."""
        novo = None
        if texto and (m := MEU_NOME.match(texto)):
            novo = nome_valido(m.group(1))
        elif not self._nome(num) and texto and num in self._estado()["pedindo_nome"]:
            novo = nome_valido(texto)
        if novo:
            primeira = not self._nome(num)
            self._guardar_nome(num, novo)
            if primeira and len(self.contatos[num]) > 1:
                self._escolher_papel(para, num, (
                    f"Prazer, {negrito(novo)}! Este número pode agir como "
                    f"{negrito('Tesouraria')} (envia os arquivos e explica as diferenças) ou "
                    f"como {negrito('Conselho Fiscal')} (recebe o pacote e faz perguntas). "
                    + negrito("Como você quer seguir?")))
            else:
                self._menu(para, num)
            return True
        if self._nome(num):
            return False
        pedindo = num in self._estado()["pedindo_nome"]
        self._guardar_nome(num, None, pedindo=True)
        texto_aviso = NOME_DE_NOVO if pedindo and tipo == "text" else BOAS_VINDAS
        self._avisar(para, num, mensagem(texto_aviso + (REENVIAR if tipo == "document" else "")))
        return True

    def _atender(self, para: tuple[str, ...], num: str, msg: dict[str, Any]) -> None:
        tipo = msg.get("type")
        texto = msg["text"]["body"] if tipo == "text" else None
        pedido = sem_saudacao(texto) if texto else None    # "oi, meu nome é Ila"
        if self._identificar(para, num, tipo, pedido):
            return
        if tipo == "text":
            troca = TROCA.get(norm_maiusculo(pedido).replace(" ", "")) or pede_troca(pedido)
            if troca and self._pedido_de_troca(para, num, troca):
                return
            entrada: dict[str, Any] = {"texto": texto}
        elif tipo == "interactive":
            i = msg["interactive"]
            r = i.get("button_reply") or i.get("list_reply") or {}
            botao = r.get("id") or ""
            if botao.startswith("papel:"):
                escolha = botao.split(":", 1)[1]
                if escolha in self.contatos[num]:
                    self._trocar(num, escolha)
                    self._menu(para, num)
                elif len(self.contatos[num]) > 1:
                    self._escolher_papel(para, num, negrito("Como você quer seguir?"))
                return
            entrada = {"botao": botao, "rotulo": r.get("title")}
        elif tipo == "button":                  # resposta a um modelo de mensagem
            entrada = {"texto": msg["button"].get("text", "")}
        elif tipo == "document":
            entrada = {"anexo": self._baixar(msg)}
        else:
            self._enviar(para, {"type": "text",
                                "text": {"body": com_cabecalho(SO_DOCUMENTO, cabecalho())}})
            return
        papel = self._papel(num)
        agente = self.agentes.get(num, self.agente)
        respostas = agente.receber(papel, **entrada, autor=self._nome(num),
                                   extras=self._extras(num))
        for m in respostas:
            if m.get("trocar_papel"):           # a IA entendeu um pedido de troca
                if not self._pedido_de_troca(para, num, m["trocar_papel"]):
                    self._menu(para, num)
                continue
            self._responder(agente, para, m, self._cabecalho(num, papel))

    def _responder(self, agente: Agente, para: tuple[str, ...], m: Mensagem,
                   cab: str) -> None:
        completa = False
        try:
            completa = self._mandar(agente, para, m, cab)
        finally:
            if not completa and m.get("entrega"):
                # sem os arquivos, o mês não conta como enviado ao CF
                agente.entrega_falhou(m["entrega"])

    def _mandar(self, agente: Agente, para: tuple[str, ...], m: Mensagem,
                cab: str) -> bool:
        """Manda a mensagem; False se algum anexo não saiu."""
        completa = True
        for conteudo in converter(m, cab):
            if "anexo" in conteudo:
                a = conteudo["anexo"]
                try:
                    midia = self.meta.subir(a["nome"],
                                            agente.arm.caminho(a["caminho"]).read_bytes())
                    self._enviar(para, {"type": "document",
                                            "document": {"id": midia, "filename": a["nome"]}})
                except Exception as erro:
                    log.warning("WhatsApp: não enviei o anexo %s: %s", a["nome"], erro)
                    completa = False
                    aviso = (f"⚠️ Não consegui enviar o arquivo *{a['nome']}*. "
                             "_Peça de novo em instantes._")
                    self._enviar(para, {"type": "text",
                                        "text": {"body": com_cabecalho(aviso, cab)}})
            else:
                self._enviar(para, conteudo)
        return completa
