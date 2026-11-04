import unittest

from conselho_fiscal.comum.texto import norm, vazio
from conselho_fiscal.comum.valores import (
    brl,
    data_ordenavel,
    indice_mes,
    mesmo_valor,
    valor_extrato,
    valor_planilha,
)


class TestValores(unittest.TestCase):
    def test_valor_planilha_aceita_formatos(self):
        for entrada, esperado in [(125, 125.0), ("125.50", 125.5), ("125,50", 125.5),
                                  ("R$ 1.250,00", 1250.0), ("1,250.00", 1250.0),
                                  ("", 0.0), (None, 0.0), (float("nan"), 0.0)]:
            self.assertEqual(valor_planilha(entrada), esperado, entrada)

    def test_valor_extrato_e_brl(self):
        self.assertEqual(valor_extrato("1.234,56"), 1234.56)
        self.assertEqual(brl(1234.5), "R$ 1.234,50")
        self.assertTrue(mesmo_valor(10.004, 10.0))
        self.assertFalse(mesmo_valor(10.01, 10.0))

    def test_datas_e_meses(self):
        self.assertEqual(data_ordenavel("20/07/26"), (2026, 7, 20))
        self.assertEqual(data_ordenavel("20/07/2026"), (2026, 7, 20))
        self.assertIsNone(data_ordenavel(None))
        self.assertEqual(indice_mes("2028-07") - indice_mes("2026-07"), 24)


class TestTexto(unittest.TestCase):
    def test_norm_e_vazio(self):
        self.assertEqual(norm("  Fundo   Lâmpadas "), "fundo lampadas")
        self.assertTrue(vazio(None) and vazio(" ") and vazio(float("nan")))
        self.assertFalse(vazio("x"))
