"""Servidor web do agente.

  - Simulador local: as conversas da tesouraria e do CF lado a lado, com
    envio de arquivos, botões e listas de opções (nos limites do WhatsApp).
    Não tem login, então só escuta na própria máquina
    (127.0.0.1): os dados têm nomes e CPFs.

        conselho-fiscal agente            # http://127.0.0.1:8000

  - Servidor (Azure, decisão de 2026-10-15): sem o simulador, com o endereço
    de saúde (`/saude`) e, com a configuração do WhatsApp, o webhook
    da Meta (`/whatsapp`; veja `agente/whatsapp.py`).

        conselho-fiscal agente --host 0.0.0.0 --sem-simulador --cadastros-reais
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from conselho_fiscal.agente.agente import PAPEIS, Agente
from conselho_fiscal.agente.whatsapp import WhatsApp, assinatura_ok

PAGINA = Path(__file__).with_name("static") / "index.html"
MAX_ANEXO = 50 * 1024 * 1024        # 50 MB
LOCAIS = ("127.0.0.1", "localhost", "::1")


class Entrada(BaseModel):
    texto: str | None = None
    botao: str | None = None
    rotulo: str | None = None


def criar_app(agente: Agente | None = None, simulador: bool = True,
              whatsapp: WhatsApp | None = None) -> FastAPI:
    """O app. Sem o simulador (`simulador=False`), só `/saude` e, com o
    `whatsapp`, o webhook da Meta."""
    agente = agente or Agente()
    app = FastAPI(title="Elo, o agente do Conselho Fiscal", docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.get("/saude")
    def saude() -> dict[str, bool]:
        """Para a sonda do Azure: o servidor responde e a pasta de dados existe."""
        if not agente.arm.base.is_dir():
            raise HTTPException(503, "pasta de dados indisponível")
        return {"ok": True}

    if whatsapp:
        cfg = whatsapp.meta.cfg

        @app.get("/whatsapp", response_class=PlainTextResponse)
        def verificar(request: Request) -> str:
            """A Meta confirma o webhook com o texto combinado no painel."""
            q = request.query_params
            if q.get("hub.mode") != "subscribe" or q.get("hub.verify_token") != cfg.verificacao:
                raise HTTPException(403, "verificação recusada")
            return q.get("hub.challenge", "")

        @app.post("/whatsapp")
        async def aviso(request: Request, tarefas: BackgroundTasks) -> dict[str, bool]:
            """Responde à Meta na hora e processa depois (a conferência leva
            alguns segundos e a Meta repete o aviso se a resposta demorar)."""
            corpo = await request.body()
            if not assinatura_ok(corpo, request.headers.get("x-hub-signature-256"),
                                 cfg.segredo):
                raise HTTPException(403, "assinatura inválida")
            try:
                dados = json.loads(corpo)
            except ValueError as erro:
                raise HTTPException(400, "corpo inválido") from erro
            for msg in whatsapp.mensagens(dados):
                tarefas.add_task(whatsapp.processar, msg)
            return {"ok": True}

    if not simulador:
        return app

    def checar(papel: str) -> None:
        if papel not in PAPEIS:
            raise HTTPException(404, f"papel desconhecido: {papel}")

    @app.get("/", response_class=HTMLResponse)
    def pagina() -> str:
        return PAGINA.read_text(encoding="utf-8")

    @app.get("/api/conversa/{papel}")
    def conversa(papel: str) -> list[dict]:
        checar(papel)
        return agente.conversa(papel)

    @app.post("/api/mensagem/{papel}")
    def mensagem(papel: str, entrada: Entrada) -> list[dict]:
        checar(papel)
        if not (entrada.texto or entrada.botao):
            raise HTTPException(400, "mensagem vazia")
        return agente.receber(papel, texto=entrada.texto, botao=entrada.botao,
                              rotulo=entrada.rotulo)

    @app.post("/api/anexo/{papel}")
    async def anexo(papel: str, request: Request) -> list[dict]:
        """Corpo = conteúdo do arquivo; nome no cabeçalho X-Nome-Arquivo."""
        checar(papel)
        nome = unquote(request.headers.get("x-nome-arquivo", "")).strip()
        conteudo = await request.body()
        if not nome or not conteudo:
            raise HTTPException(400, "arquivo sem nome ou vazio")
        if len(conteudo) > MAX_ANEXO:
            raise HTTPException(413, "arquivo maior que 50 MB")
        # o pipeline leva alguns segundos: fora do laço de eventos
        return await run_in_threadpool(agente.receber, papel, anexo=(nome, conteudo))

    @app.get("/api/arquivo/{caminho:path}")
    def arquivo(caminho: str) -> FileResponse:
        try:
            p = agente.arm.caminho(caminho)
        except ValueError as erro:
            raise HTTPException(403, str(erro)) from erro
        if not p.is_file():
            raise HTTPException(404, "arquivo não encontrado")
        return FileResponse(p, filename=p.name)

    return app


def servir(porta: int = 8000, agente: Agente | None = None, host: str = "127.0.0.1",
           simulador: bool = True, whatsapp: WhatsApp | None = None) -> None:
    """O simulador não tem login: fora da própria máquina, só sem ele."""
    if simulador and host not in LOCAIS:
        raise ValueError(f"o simulador não tem login e não pode escutar em {host}; "
                         "use --sem-simulador")
    import uvicorn
    uvicorn.run(criar_app(agente, simulador, whatsapp), host=host, port=porta)
