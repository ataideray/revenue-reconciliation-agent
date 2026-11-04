"""Simulador web do agente: rotas e proteção dos arquivos."""

import unittest
from urllib.parse import quote

try:
    from fastapi.testclient import TestClient

    from conselho_fiscal.agente.web import criar_app, servir
except ImportError:          # dependências opcionais (pip install -e ".[agente,dev]")
    TestClient = None

from conselho_fiscal.agente import Agente
from conselho_fiscal.agente.armazenamento import Armazenamento
from tests.apoio import cadastros_temp, pasta_temp


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TestWeb(unittest.TestCase):
    def setUp(self):
        destinos, vinculos = cadastros_temp()
        self.arm = Armazenamento(pasta_temp("teste_web_"))
        self.cliente = TestClient(criar_app(Agente(self.arm, destinos, vinculos)))

    def test_pagina_e_conversa(self):
        self.assertIn("Elo, o agente do Conselho Fiscal", self.cliente.get("/").text)
        r = self.cliente.post("/api/mensagem/tesouraria", json={"texto": "oi"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("*envie* o registro de receitas da tesouraria", r.json()[0]["texto"])
        conversa = self.cliente.get("/api/conversa/tesouraria").json()
        self.assertEqual([m["de"] for m in conversa], ["tesouraria", "agente"])
        self.assertEqual(self.cliente.get("/api/conversa/outro").status_code, 404)
        self.assertEqual(self.cliente.post("/api/mensagem/cf", json={}).status_code, 400)

    def test_anexo_recusado(self):
        r = self.cliente.post("/api/anexo/tesouraria", content=b"abc",
                              headers={"X-Nome-Arquivo": quote("notas fiscais.txt")})
        self.assertIn("Não usei \"notas fiscais.txt\"", r.json()[0]["texto"])

    def test_arquivo_so_dentro_da_pasta_do_agente(self):
        (self.arm.base / "meses").mkdir()
        (self.arm.base / "meses" / "a.txt").write_text("ok")
        self.assertEqual(self.cliente.get("/api/arquivo/meses/a.txt").text, "ok")
        self.assertEqual(self.cliente.get("/api/arquivo/..%2F..%2Fetc%2Fpasswd").status_code, 403)
        self.assertEqual(self.cliente.get("/api/arquivo/meses/nada.txt").status_code, 404)


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TestServidor(unittest.TestCase):
    """Modo da nuvem: sem o simulador, só a saúde."""

    def setUp(self):
        destinos, vinculos = cadastros_temp()
        self.agente = Agente(Armazenamento(pasta_temp("teste_web_")), destinos, vinculos)

    def test_saude_e_sem_simulador(self):
        cliente = TestClient(criar_app(self.agente, simulador=False))
        self.assertEqual(cliente.get("/saude").json(), {"ok": True})
        for rota in ("/", "/api/conversa/cf", "/api/arquivo/estado.json", "/docs",
                     "/openapi.json"):
            self.assertEqual(cliente.get(rota).status_code, 404, rota)
        self.assertEqual(cliente.post("/api/mensagem/cf", json={"texto": "oi"}).status_code,
                         404)
        # com o simulador, a saúde também responde
        self.assertEqual(TestClient(criar_app(self.agente)).get("/saude").status_code, 200)

    def test_simulador_so_na_propria_maquina(self):
        with self.assertRaises(ValueError):
            servir(8000, self.agente, host="0.0.0.0")
