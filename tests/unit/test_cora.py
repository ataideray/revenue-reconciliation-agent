"""Leitura do extrato Cora e conferência contra o próprio PDF (B2)."""

import unittest

from conselho_fiscal.extratos import cora

TEXTO = """
Saldo inicial disponível                     R$ 100,00
Total de entradas                          + R$ 80,00
Total de saídas                            - R$ 30,00
Saldo final disponível                       R$ 150,00
02/06/2026                    Saldo do dia R$ 150,00
    Transf Pix recebida   FULANO DE T…   123.456.789-00   + R$ 50,00
01/06/2026                    Saldo do dia R$ 100,00
    Transf Pix recebida   BELTRANO D…    987.654.321-00   + R$ 30,00
    Transf Pix enviada    CICLANO S…     111.222.333-44   - R$ 30,00
"""


class TestCora(unittest.TestCase):
    def status(self, verif):
        return {v["verificacao"]: v["status"] for v in verif}

    def test_leitura_completa(self):
        transacoes = cora.ler_transacoes(TEXTO)
        self.assertEqual([(t["data"], t["nome"], t["documento"], t["entrada"], t["saida"])
                          for t in transacoes], [
            ("02/06/2026", "Transf Pix recebida FULANO DE T", "123.456.789-00", 50.0, 0.0),
            ("01/06/2026", "Transf Pix recebida BELTRANO D", "987.654.321-00", 30.0, 0.0),
            ("01/06/2026", "Transf Pix enviada CICLANO S", "111.222.333-44", 0.0, 30.0),
        ])
        self.assertEqual(set(self.status(cora.verificar_leitura(TEXTO, transacoes)).values()), {"OK"})

    def test_transacao_perdida_aponta_o_dia(self):
        transacoes = [t for t in cora.ler_transacoes(TEXTO) if t["entrada"] != 50.0]
        verif = cora.verificar_leitura(TEXTO, transacoes)
        st = self.status(verif)
        self.assertEqual(st["Total de entradas (PDF × lido)"], "ALERTA")
        self.assertEqual(st["Total de saídas (PDF × lido)"], "OK")
        saldo = next(v for v in verif if v["verificacao"] == "Saldo do dia (dia a dia)")
        self.assertIn("02/06/2026", saldo["detalhe"])
        self.assertNotIn("01/06/2026", saldo["detalhe"])
