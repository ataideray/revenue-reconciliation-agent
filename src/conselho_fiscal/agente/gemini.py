"""Interpretador com o Gemini (API do Google AI Studio), pela API REST e
sem bibliotecas extras.

Chave: variável GEMINI_API_KEY ou o arquivo
~/.config/conselho-fiscal/gemini_api_key (fora do repositório). Modelo:
CF_IA_MODELO; modelo reserva: CF_IA_MODELO_RESERVA ("" desliga). Os padrões
estão abaixo.

Cada pedido tem duas tentativas: no modelo principal e, se ele não
responder (sobrecarga ou rede), no reserva, que tem cota própria no plano
gratuito (decisão de 2026-10-13, depois de um dia de Gemini instável).

Plano gratuito (decisão do usuário, 2026-10-09): pelos termos do Google, o
que é enviado no plano gratuito pode ser usado para melhorar os produtos e
lido por revisores. Por isso só vai o que `ia.para_ia`, `ia.para_redacao`,
`ia.para_pergunta`, `ia.para_resposta` e `ia.para_comando` montam: apelidos no lugar dos nomes,
sem CPF e sem a descrição do extrato.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from conselho_fiscal.agente.ia import (
    ESQUEMA,
    ESQUEMA_CF,
    ESQUEMA_COMANDO,
    ESQUEMA_NOTA,
    ESQUEMA_RESPOSTA,
    INSTRUCOES,
    INSTRUCOES_CF,
    INSTRUCOES_COMANDO,
    INSTRUCOES_NOTA,
    INSTRUCOES_RESPOSTA,
    Contexto,
    ContextoComando,
    ContextoNota,
    ContextoPergunta,
    ContextoResposta,
    Interpretacao,
    Pergunta,
    de_comando,
    de_ia,
    de_pergunta,
    de_redacao,
    de_resposta,
    para_comando,
    para_ia,
    para_pergunta,
    para_redacao,
    para_resposta,
)

# o 3.5 Flash-Lite acertou as respostas de conferência em ~1 s; o 3.8 Flash
# vivia sobrecarregado no plano gratuito (503 e demora) em 2026-10-09
MODELO_PADRAO = "gemini-3.5-flash-lite"
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
ARQUIVO_CHAVE = Path.home() / ".config" / "conselho-fiscal" / "gemini_api_key"
# na avaliação de 2026-10-13 (Gemini instável), o 3.1 Flash-Lite acertou os 43 casos que
# respondeu; o 3.5 Flash esbarrou na cota gratuita (429) em 33 de 53
MODELO_RESERVA = "gemini-3.1-flash-lite"
ESPERA = 15     # segundos por tentativa; depois de 2, o agente pergunta à tesouraria
# o pedido simples só troca o "Não entendi" por uma resposta melhor: não vale esperar muito
ESPERA_COMANDO = 6
SOBRECARGA = (429, 500, 503)    # o Google está ocupado: tenta no reserva
# a conexão caiu ou demorou demais (no plano gratuito acontece): tenta no reserva
FALHA_DE_REDE = (TimeoutError, urllib.error.URLError, http.client.RemoteDisconnected,
                 ConnectionError)


def chave() -> str | None:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    if ARQUIVO_CHAVE.exists():
        return ARQUIVO_CHAVE.read_text(encoding="utf-8").strip() or None
    return None


class Gemini:
    def __init__(self, chave_api: str, modelo: str | None = None,
                 reserva: str | None = None):
        self.chave = chave_api
        self.modelo = modelo or os.environ.get("CF_IA_MODELO") or MODELO_PADRAO
        if reserva is None:
            reserva = os.environ.get("CF_IA_MODELO_RESERVA", MODELO_RESERVA)
        self.reserva = reserva or self.modelo        # sem reserva: o mesmo, de novo
        self.nome = f"Gemini ({self.modelo})"
        self.ultimo = self.nome      # quem respondeu o último pedido (para auditoria)

    def interpretar(self, contexto: Contexto) -> Interpretacao:
        pergunta, apelidos = para_ia(contexto)
        return de_ia(self._chamar(INSTRUCOES, ESQUEMA, pergunta), apelidos)

    def redigir(self, contexto: ContextoNota) -> str:
        pedido, apelidos = para_redacao(contexto)
        return de_redacao(self._chamar(INSTRUCOES_NOTA, ESQUEMA_NOTA, pedido), apelidos, pedido)

    def entender(self, contexto: ContextoPergunta) -> Pergunta:
        pergunta, apelidos = para_pergunta(contexto)
        return de_pergunta(self._chamar(INSTRUCOES_CF, ESQUEMA_CF, pergunta), apelidos)

    def responder(self, contexto: ContextoResposta) -> str:
        pedido, apelidos = para_resposta(contexto)
        return de_resposta(self._chamar(INSTRUCOES_RESPOSTA, ESQUEMA_RESPOSTA, pedido),
                           apelidos, pedido)

    def comando(self, contexto: ContextoComando) -> str:
        pedido, _ = para_comando(contexto)
        return de_comando(self._chamar(INSTRUCOES_COMANDO, ESQUEMA_COMANDO, pedido,
                                       ESPERA_COMANDO))

    def _chamar(self, instrucoes: str, esquema: dict, texto: str, espera: int = ESPERA) -> str:
        """O texto (JSON no `esquema`) que o Gemini devolve."""
        corpo = {
            "systemInstruction": {"parts": [{"text": instrucoes}]},
            "contents": [{"role": "user", "parts": [{"text": texto}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                 "responseSchema": esquema},
        }
        for tentativa, modelo in enumerate((self.modelo, self.reserva), start=1):
            pedido = urllib.request.Request(
                URL.format(modelo=modelo), data=json.dumps(corpo).encode(), method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": self.chave})
            try:
                with urllib.request.urlopen(pedido, timeout=espera) as r:
                    resposta = json.load(r)
                self.ultimo = f"Gemini ({modelo})"
                break
            except urllib.error.HTTPError as erro:     # sem a chave na mensagem
                if tentativa == 1 and erro.code in SOBRECARGA:
                    if modelo == self.reserva:
                        time.sleep(2)
                    continue
                raise RuntimeError(f"Gemini respondeu {erro.code} ({erro.reason})") from None
            except FALHA_DE_REDE as erro:
                if tentativa == 1:
                    continue
                raise RuntimeError(f"sem resposta do Gemini ({erro})") from None
        try:
            return resposta["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise ValueError("resposta do Gemini sem texto") from None
