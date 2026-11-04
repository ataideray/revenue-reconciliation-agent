"""Pipeline de ponta a ponta com dados fictícios (roda sem dados reais e sem
pdftotext: os extratos entram como .xlsx já convertido, "não verificado")."""

import contextlib
import io
import json
import os
import unittest

from openpyxl import load_workbook

from conselho_fiscal.cli import main
from conselho_fiscal.extratos import exportar_xlsx
from conselho_fiscal.receitas import executar
from tests.apoio import cadastros_temp, pasta_temp, planilha_tesouraria


def transacao(banco, data, nome, entrada=0.0, saida=0.0):
    return {"banco": banco, "data": data, "tipo": "Entrada" if entrada else "Saída",
            "nome": nome, "documento": "", "categoria": "", "entrada": entrada,
            "saida": saida, "saldo": None}


class TestPipelineSintetico(unittest.TestCase):
    def setUp(self):
        self.pasta = pasta_temp("teste_sintetico_")
        self.entradas = planilha_tesouraria(os.path.join(self.pasta, "entradas.xlsx"), [
            ("02/07/2026", "0001-2026", "Ila Nadia Jasmim", [("Anuidade", 120)]),
            ("03/07/2026", "0002-2026", "Ivan Trigo Palha Luar", [("Anuidade", 150)]),
            ("04/07/2026", "0003-2026", "Nair de Canela Neve", [("Café", 30)]),
        ], {"Total de Receitas": 300, "Recibos Emitidos": 3,
            "Recibos de Sócios": 3, "Recibos de Não Sócios": 0})
        self.cora = os.path.join(self.pasta, "cora.xlsx")
        exportar_xlsx([transacao("Cora", "02/07/2026", "Transf Pix recebida ILA NADIA JASMIM", 120),
                       transacao("Cora", "05/07/2026", "Transf Pix recebida LUMITECH", 150)],
                      "Cora", self.cora)
        self.stone = os.path.join(self.pasta, "stone.xlsx")
        exportar_xlsx([transacao("Stone", "20/07/26", "NAIR DE CANELA NEVE SERENO", 300),
                       transacao("Stone", "04/07/26", "NAIR DE CANELA NEVE SERENO", 30),
                       transacao("Stone", "24/07/26", "NAIR DE CANELA NEVE SERENO", saida=300)],
                      "Stone", self.stone)
        self.destinos, self.vinculos = cadastros_temp()

    def test_executar(self):
        saida = os.path.join(self.pasta, "receitas.xlsx")
        st = executar(self.entradas, self.cora, self.stone, saida,
                      cadastro_destinos=self.destinos, vinculos_confirmados=self.vinculos)
        self.assertEqual((st["recibos"], st["conformes"], st["divergentes"], st["devolucoes"]),
                         (3, 2, 1, 1))
        r = st["resultado"]
        self.assertEqual(r["mes_referencia"], "2026-07")
        self.assertEqual([(s["nome_no_extrato"], s["recibo"], s["criterio"])
                          for s in r["sugestoes_vinculo"]],
                         [("LUMITECH", "0002-2026", "valor único no mês (sem pista de nome)")])
        with open(st["saida_json"], encoding="utf-8") as f:
            self.assertEqual(json.load(f)["formato"], "conferencia-receitas/3")
        div = load_workbook(saida)["Divergências"]
        self.assertEqual(div["A1"].value,
                         "LEITURA DOS EXTRATOS: 0 verificação(ões) OK, 2 não verificada(s)")
        self.assertTrue(div["A4"].value.startswith("PLANILHA DA TESOURARIA: OK"))

    def test_uma_divergencia_por_recibo(self):
        """Só recibos sem Pix, mais de um: uma divergência por recibo; com Pix
        sobrando, fica uma só (2026-10-26)."""
        entradas = planilha_tesouraria(os.path.join(self.pasta, "e2.xlsx"), [
            ("02/07/2026", "0001-2026", "Leopoldo Luar", [("Anuidade", 130)]),
            ("03/07/2026", "0002-2026", "Leopoldo Luar", [("Anuidade", 170)]),
            ("04/07/2026", "0003-2026", "Bia Pedra", [("Café", 30)]),
            ("05/07/2026", "0004-2026", "Bia Pedra", [("Café", 40)]),
        ], {"Total de Receitas": 370, "Recibos Emitidos": 4,
            "Recibos de Sócios": 4, "Recibos de Não Sócios": 0})
        exportar_xlsx([transacao("Cora", "02/07/2026", "Transf Pix recebida BIA PEDRA", 50)],
                      "Cora", self.cora)
        exportar_xlsx([transacao("Stone", "10/07/26", "MARILENE", 130)], "Stone", self.stone)
        st = executar(entradas, self.cora, self.stone, os.path.join(self.pasta, "r2.xlsx"),
                      cadastro_destinos=self.destinos, vinculos_confirmados=self.vinculos)
        divs = {d["id"]: d for d in st["resultado"]["divergencias"]}
        self.assertEqual(set(divs), {"DIV-LEOPOLDO-LUAR-0001-2026", "DIV-LEOPOLDO-LUAR-0002-2026",
                                     "DIV-BIA-PEDRA", "DIV-MARILENE"})
        g = divs["DIV-LEOPOLDO-LUAR-0001-2026"]
        self.assertEqual((g["recibo"], g["total_recibos"], g["total_extrato"], g["tipo"]),
                         ("0001-2026", 130, 0, "Sem extrato (só recibo)"))
        self.assertEqual([s["div_recibo"] for s in g["sugestoes_vinculo"]],
                         ["DIV-LEOPOLDO-LUAR-0001-2026"])        # a sugestão aponta a parte
        self.assertEqual(divs["DIV-LEOPOLDO-LUAR-0002-2026"]["sugestoes_vinculo"], [])
        self.assertEqual(len(divs["DIV-BIA-PEDRA"]["recibos_sem_pix"]), 2)   # Pix sobrando
        aba = [r for r in load_workbook(os.path.join(self.pasta, "r2.xlsx"))["Divergências"]
               .iter_rows(values_only=True) if r[0] and "LEOPOLDO" in str(r[0])]
        self.assertEqual([r[0] for r in aba], ["LEOPOLDO LUAR (recibo 0001-2026)",
                                               "LEOPOLDO LUAR (recibo 0002-2026)"])

    def test_linha_de_comando(self):
        saida = os.path.join(self.pasta, "cli.xlsx")
        os.environ["CF_CADASTROS_DIR"] = os.path.dirname(self.destinos)
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(["receitas", self.entradas, self.cora, self.stone, saida]), 0)
        finally:
            del os.environ["CF_CADASTROS_DIR"]
        self.assertIn("1 divergentes", out.getvalue())
        self.assertTrue(os.path.exists(saida) and os.path.exists(saida[:-5] + ".json"))
