"""Planilha da tesouraria: uma linha por recibo, destinos e aba Resumo (N1)."""

import json
import os
import unittest

from conselho_fiscal.cadastros import destinos
from conselho_fiscal.receitas import lancamentos
from tests.apoio import CADASTRO_DESTINOS, pasta_temp, planilha_tesouraria

RECIBOS = [
    ("03/07/2026", "0832-2026", "Graziela Canario Verde Nuvem",
     [("Espetinho", 10), ("Retiro", 60), ("Anuidade", 120)]),
    ("04/07/2026", "0842-2026", "Nair de Canela Neve", [("Café", 30)]),
    ("05/07/2026", "0843-2026", "Fulano Visitante *", [("Fundo - lampadas", 50)]),
    ("06/07/2026", "0844-2026", "Beltrana Pedra", [("Fundo - Lampada", 25.5)]),
]
RESUMO_OK = {"Total de Receitas": 295.5, "Recibos Emitidos": 4,
             "Recibos de Sócios": 3, "Recibos de Não Sócios": 1}


class TestPivotar(unittest.TestCase):
    def setUp(self):
        self.caminho = planilha_tesouraria(os.path.join(pasta_temp(), "e.xlsx"), RECIBOS, RESUMO_OK)
        self.df = lancamentos.carregar(self.caminho)

    def test_uma_linha_por_recibo_com_colunas_fixas(self):
        p = lancamentos.pivotar(self.df, destinos.carregar(CADASTRO_DESTINOS), "2026-07")
        self.assertEqual(p["colunas"], ["Anuidade", "Espetinho", "Retiro", "Cafés",
                                        "Fundo - Lâmpadas"])
        graziela = p["linhas"][0]
        self.assertEqual((graziela["Origem"], graziela["Anuidade"], graziela["Espetinho"],
                          graziela["Retiro"]), ("GRAZIELA CANARIO VERDE NUVEM", 120, 10, 60))
        self.assertEqual(p["linhas"][2]["Origem"], "FULANO VISITANTE")   # '*' sai do nome
        self.assertEqual(p["linhas"][3]["Fundo - Lâmpadas"], 25.5)
        self.assertEqual(p["destinos_novos"], [])
        self.assertEqual(lancamentos.mes_referencia(self.df), "2026-07")
        recibos = lancamentos.recibos_para_conciliacao(p)
        self.assertEqual([r["valor"] for r in recibos], [190, 30, 50, 25.5])

    def test_ordem_preferida_vale_para_outra_grafia_no_cadastro(self):
        # a lista tem "Ofertas"; o cadastro grava "Oferta": continua antes de "Bazar"
        caminho = planilha_tesouraria(os.path.join(pasta_temp(), "e.xlsx"), [
            ("03/07/2026", "0832-2026", "Graziela Canario", [("Bazar", 10), ("Oferta", 20)])])
        cadastro = destinos.vazio()
        cadastro["colunas"]["oferta"] = {"nome": "Oferta", "ultimo_uso": None}
        p = lancamentos.pivotar(lancamentos.carregar(caminho), cadastro, "2026-07")
        self.assertEqual(p["colunas"], ["Oferta", "Bazar"])

    def test_destino_novo_e_cadastrado_e_fica_fixo(self):
        cad = destinos.carregar(CADASTRO_DESTINOS)
        p = lancamentos.pivotar(lancamentos.carregar(planilha_tesouraria(
            os.path.join(pasta_temp(), "a.xlsx"), [("01/08/2026", "1", "Ila", [("Rifa de Natal", 5)])])),
            cad, "2026-08")
        self.assertEqual(p["destinos_novos"], ["Rifa de Natal"])
        self.assertEqual(cad["colunas"]["rifa de natal"], {"nome": "Rifa de Natal", "ultimo_uso": "2026-08"})
        p = lancamentos.pivotar(lancamentos.carregar(planilha_tesouraria(
            os.path.join(pasta_temp(), "b.xlsx"), [("01/09/2026", "2", "Ila", [("RIFA DE NATAL", 5)])])),
            cad, "2026-09")
        self.assertEqual((p["destinos_novos"], p["colunas"]), ([], ["Rifa de Natal"]))

    def test_exportar_intermediario(self):
        p = lancamentos.pivotar(self.df, destinos.carregar(CADASTRO_DESTINOS))
        caminho = os.path.join(pasta_temp(), "f.xlsx")
        lancamentos.exportar_xlsx(p, caminho)
        self.assertTrue(os.path.getsize(caminho) > 0)


class TestConferirPlanilha(unittest.TestCase):
    def conferir(self, recibos, resumo):
        caminho = planilha_tesouraria(os.path.join(pasta_temp(), "e.xlsx"), recibos, resumo)
        return {v["verificacao"]: v for v in
                lancamentos.conferir_planilha(caminho, lancamentos.carregar(caminho))}

    def test_tudo_ok(self):
        v = self.conferir(RECIBOS, RESUMO_OK)
        self.assertEqual(len(v), 5)
        self.assertEqual({x["status"] for x in v.values()}, {"OK"})

    def test_erros_no_resumo_e_no_recibo(self):
        recibos = RECIBOS[:1] + [("04/07/2026", "0842-2026", "Nair de Canela Neve",
                                  [("Café", 30)], 40)] + RECIBOS[2:]
        v = self.conferir(recibos, {**RESUMO_OK, "Total de Receitas": 500,
                                    "Recibos de Não Sócios": 2})
        total = v["Total de receitas (Resumo × Receitas)"]
        self.assertEqual((total["status"], total["esperado"], total["encontrado"]),
                         ("ALERTA", "R$ 500,00", "R$ 305,50"))
        ns = v["Recibos de não sócios (Resumo × Receitas)"]
        self.assertEqual((ns["status"], ns["esperado"], ns["encontrado"]), ("ALERTA", "2", "1"))
        self.assertEqual(v["Recibos emitidos (Resumo × Receitas)"]["status"], "OK")
        recibo = v["Total de cada recibo = soma dos itens"]
        self.assertEqual(recibo["status"], "ALERTA")
        self.assertIn("0842-2026", recibo["detalhe"])

    def test_sem_aba_resumo(self):
        v = self.conferir(RECIBOS, None)
        self.assertEqual(v["Aba Resumo"]["status"], "NÃO VERIFICADO")
        self.assertEqual(v["Total de cada recibo = soma dos itens"]["status"], "OK")
        json.dumps(list(v.values()))      # serializável no JSON do resultado
