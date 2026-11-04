"""Relação entre meses: soma, média, diferença e variação calculadas pelo código."""

import unittest

from conselho_fiscal.agente import comparacao as cmp


def mes(m, receitas, divergentes, valor_cora=100.0, pessoas=()):
    resumo = {"ent_cora": 1, "ent_stone": 1, "valor_cora": valor_cora, "valor_stone": 50.0,
              "recibos": 10, "conformes": 10 - divergentes, "divergentes": divergentes}
    if valor_cora is None:
        del resumo["valor_cora"]
    divs = [{"pessoa": p, "recibos_sem_pix": [], "pix_sem_recibo": []} for p in pessoas]
    conf = [{"verificacao": "Total de receitas (Resumo × Receitas)",
             "encontrado": receitas}]
    return {"mes": m, "resumo": resumo, "divergencias": divs}, conf


class TestComparacao(unittest.TestCase):
    def test_tres_meses(self):
        texto = cmp.comparar([mes("2026-08", "R$ 1.500,00", 3, pessoas=["Ila"]),
                              mes("2026-06", "R$ 1.000,00", 0, pessoas=["ILA", "Bia"]),
                              mes("2026-07", "R$ 1.200,50", 2, pessoas=["Bia"])])
        self.assertTrue(texto.startswith("*Comparação: junho/2026, julho/2026 e "
                                         "agosto/2026*"))
        self.assertIn("*Receitas*\n• Total no registro de receitas: R$ 1.000,00 (junho/2026) → "
                      "R$ 1.200,50 (julho/2026) → R$ 1.500,00 (agosto/2026) · junho/2026 → "
                      "julho/2026: aumento de R$ 200,50 (+20,1%); julho/2026 → agosto/2026: "
                      "aumento de R$ 299,50 (+24,9%) · maior: agosto/2026; menor: junho/2026 · "
                      "soma R$ 3.700,50 · média R$ 1.233,50", texto)
        # todos iguais: sem maior e menor
        self.assertIn("• Emitidos: 10 (junho/2026) → 10 (julho/2026) → 10 (agosto/2026) · "
                      "junho/2026 → julho/2026: igual; julho/2026 → agosto/2026: igual · "
                      "soma 30 · média 10\n", texto)
        # anterior zero: sem percentual
        self.assertIn("junho/2026 → julho/2026: aumento de 2; julho/2026 → agosto/2026: "
                      "aumento de 1 (+50,0%)", texto)
        self.assertIn("*Com divergência em mais de um mês*\n• ILA (junho/2026, agosto/2026)\n"
                      "• Bia (junho/2026, julho/2026)", texto)

    def test_mes_sem_o_dado(self):
        texto = cmp.comparar([mes("2026-06", "R$ 10,00", 1, valor_cora=None),
                              mes("2026-07", "R$ 10,00", 1)])
        self.assertIn("*Pix recebidos no Cora*\n• Valor: sem o dado em junho/2026", texto)
        self.assertTrue(texto.endswith("*Com divergência em mais de um mês*\n• ninguém"))
