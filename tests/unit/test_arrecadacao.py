"""Quanto entrou por destino: leitura da planilha, busca do destino e texto."""

import json
import os
import unittest

from conselho_fiscal.agente import arrecadacao as arr
from conselho_fiscal.cadastros import destinos
from tests.apoio import cadastros_temp, pasta_temp, planilha_tesouraria

JULHO = {"Anuidade": (270.0, 2), "Açaí": (65.0, 3), "Fundo reforma": (100.0, 1),
         "Fundo reforma - Venda das Camisetas": (512.0, 1)}
JUNHO = {"Anuidade": (300.0, 3), "Fundo reforma": (50.0, 1)}


class TestTotais(unittest.TestCase):
    def test_soma_por_destino_sem_mexer_no_cadastro(self):
        pasta = pasta_temp("teste_arrecadacao_")
        entradas = planilha_tesouraria(os.path.join(pasta, "entradas.xlsx"), [
            ("02/07/2026", "0001-2026", "Ila", [("Anuidade", 120), ("Açaí", 20)]),
            ("03/07/2026", "0002-2026", "Ivan", [("Anuidades", 150)]),
            ("04/07/2026", "0003-2026", "Nair", [("Pastel na praça", 30), ("Acai", 15.5)]),
        ])
        caminho, _ = cadastros_temp()
        with open(caminho, encoding="utf-8") as f:
            antes = f.read()
        cadastro = destinos.carregar(caminho)
        copia = json.dumps(cadastro, sort_keys=True)
        t = arr.totais(entradas, cadastro)
        self.assertEqual(t["Anuidade"], (270.0, 2))
        self.assertEqual(t["Açaí"], (35.5, 2))
        self.assertEqual(t["Pastel na praça"], (30.0, 1))           # destino novo também
        self.assertEqual(json.dumps(cadastro, sort_keys=True), copia)
        with open(caminho, encoding="utf-8") as f:
            self.assertEqual(f.read(), antes)


class TestBusca(unittest.TestCase):
    def test_achar(self):
        nomes = list(JULHO)
        self.assertEqual(arr.achar("açaís", nomes), ["Açaí"])
        self.assertEqual(arr.achar("ACAI", nomes), ["Açaí"])
        self.assertEqual(arr.achar("fundo", nomes),
                         ["Fundo reforma", "Fundo reforma - Venda das Camisetas"])
        self.assertEqual(arr.achar("fundo reforma", nomes),
                         ["Fundo reforma", "Fundo reforma - Venda das Camisetas"])
        self.assertEqual(arr.achar("anuidade", ["Anuidade", "Saldo de Anuidade"]),
                         ["Anuidade", "Saldo de Anuidade"])
        self.assertEqual(arr.achar("rifa", nomes), [])
        self.assertEqual(arr.achar("", nomes), [])

    def test_citado(self):
        nomes = list(JULHO)
        self.assertEqual(arr.citado("Quanto arrecadamos com açaí no mês de julho?", nomes),
                         "Açaí")
        self.assertEqual(arr.citado("quantas anuidades em julho?", nomes), "Anuidade")
        self.assertEqual(arr.citado("quanto veio da venda das camisetas do fundo reforma?", nomes),
                         "Fundo reforma - Venda das Camisetas")             # o de mais palavras
        self.assertIsNone(arr.citado("resuma julho", nomes))


class TestTexto(unittest.TestCase):
    def test_um_mes(self):
        t = arr.texto("açaí", [("2026-07", JULHO)])
        self.assertIn("• Açaí: R$ 65,00 (3 recibos)", t)
        self.assertIn(arr.ORIGEM, t)

    def test_varios_destinos_somados(self):
        t = arr.texto("fundo", [("2026-07", JULHO)])
        self.assertIn("• Fundo reforma: R$ 100,00 (1 recibo)", t)
        self.assertIn("• Fundo reforma + Fundo reforma - Venda das Camisetas: R$ 612,00 (2 recibos)",
                      t)

    def test_varios_meses(self):
        t = arr.texto("anuidade", [("2026-07", JULHO), ("2026-06", JUNHO)])
        self.assertIn("• Anuidade: R$ 300,00 (junho/2026) → R$ 270,00 (julho/2026): queda de "
                      "R$ 30,00 (-10,0%) · soma R$ 570,00 · média R$ 285,00 · recibos: 3 → 2", t)
        t = arr.texto("açaí", [("2026-06", JUNHO), ("2026-07", JULHO)])
        self.assertIn("R$ 0,00 (junho/2026) → R$ 65,00 (julho/2026)", t)  # sem recibo: zero

    def test_destino_que_nao_existe(self):
        t = arr.texto("rifa", [("2026-07", JULHO)])
        self.assertIn("*Nenhum recibo com o destino \"rifa\"* em julho/2026.", t)
        self.assertIn("*Destinos de julho/2026:* Anuidade, Açaí,", t)

    def test_todos_os_destinos(self):
        t = arr.texto("", [("2026-07", JULHO)])
        self.assertIn("*Receitas por destino — julho/2026*\n"
                      "• Fundo reforma - Venda das Camisetas: R$ 512,00 (1 recibo)\n"
                      "• Anuidade: R$ 270,00 (2 recibos)", t)          # do maior ao menor
        self.assertIn("• Total: R$ 947,00", t)
