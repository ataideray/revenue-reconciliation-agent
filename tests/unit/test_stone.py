"""Leitura do extrato Stone (B1, B6) com textos no formato do pdftotext -layout."""

import unittest

from conselho_fiscal.extratos import stone

CABECALHO = """             Extrato de conta corrente
             Emitido em 14 setembro 2026 às 16:34:25                Página 1 de 1

Dados da conta
   Nome                                                Documento
   ASSOCIACAO VILA DAS FLORES                     12.345.678/0001-90

Período: de 01/07/2026 a 31/07/2026
 DATA        TIPO DESCRIÇÃO                         VALOR         SALDO          CONTRAPARTE
"""
RODAPE = """
Informações do Comprovante
Código da autenticação
00000000-1111-4222-8333-444444444444
"""


def extrato(corpo: str) -> str:
    return CABECALHO + corpo + RODAPE


class TestSepararTransacoes(unittest.TestCase):
    def test_varias_transacoes_sem_linha_em_branco(self):
        texto = extrato("""                  99887766 ODIR VALERIO CASCATA
 10/06/26 Entrada DE AREIA          R$ 20,00      R$ 3.658,55
                  Transferência | Pix
                  99887766 ODIR VALERIO CASCATA
 10/06/26 Entrada DE AREIA          R$ 120,00     R$ 3.638,55
                  Transferência | Pix
 10/06/26 Saída      PIX Marketplace  - R$ 312,40   R$ 3.208,55
                  Transferência | Pix
""")
        self.assertEqual([(t["nome"], t["entrada"], t["saida"]) for t in stone.ler_transacoes(texto)], [
            ("99887766 ODIR VALERIO CASCATA DE AREIA", 20.0, 0.0),
            ("99887766 ODIR VALERIO CASCATA DE AREIA", 120.0, 0.0),
            ("PIX Marketplace", 0.0, 312.4),
        ])

    def test_rendimento_com_valor_na_linha_seguinte(self):
        texto = extrato(""" 12/06/26 Entrada Rendimento
                  Rendimento
                             automático             R$ 0,01       R$ 3.838,57
                  TELMO OLIVAS ALECRIM
 11/06/26 Entrada SALVIA            R$ 130,00     R$ 3.838,56
                  Transferência | Pix
""")
        self.assertEqual([(t["categoria"], t["nome"], t["entrada"]) for t in stone.ler_transacoes(texto)], [
            ("Rendimento", "Rendimento automático", 0.01),
            ("Transferência Pix", "TELMO OLIVAS ALECRIM SALVIA", 130.0),
        ])


class TestFiltroCabecalho(unittest.TestCase):
    """B6: nomes que começam com 'DATA', 'Conta', 'ASSOCIACAO VILA'… não podem
    ser cortados (o saldo fecharia mesmo assim)."""

    CORPO = """                  DATAVALE EMPRESA DE TECNOLOGIA
 05/07/26 Entrada E INFORMACOES                     R$ 300,00     R$ 1.950,00
                  Transferência | Pix

                  Contabilidade Pedra Camomila
 04/07/26 Entrada Ltda                              R$ 250,00     R$ 1.650,00
                  Transferência | Pix
            Extrato          de    conta
            Emitido em 14 setembro 2026 às 16:34:25
                                                corrente
                                                                     Página 2 de 2

Período: de 01/07/2026 a 31/07/2026
 DATA   TIPO   DESCRIÇÃO    VALOR   SALDO   CONTRAPARTE
                  ASSOCIACAO VILA DAS
 03/07/26 Entrada FLORES                            R$ 1.000,00   R$ 1.400,00
                  Transferência | Pix

                  Instituição Beneficente Sol
 02/07/26 Entrada do Caminho                        R$ 200,00     R$ 400,00
                  Transferência | Pix

 01/07/26 Entrada NOELI PEDRA                       R$ 200,00     R$ 200,00
                  Transferência | Pix
"""

    def test_nomes_completos_e_verificacoes_ok(self):
        texto = extrato(self.CORPO)
        transacoes = stone.ler_transacoes(texto)
        self.assertEqual([t["nome"] for t in transacoes], [
            "DATAVALE EMPRESA DE TECNOLOGIA E INFORMACOES",
            "Contabilidade Pedra Camomila Ltda",
            "ASSOCIACAO VILA DAS FLORES",
            "Instituição Beneficente Sol do Caminho",
            "NOELI PEDRA",
        ])
        self.assertEqual({v["status"] for v in stone.verificar_leitura(texto, transacoes)}, {"OK"})

    def test_layout_nao_reconhecido_gera_alerta_e_nao_para(self):
        texto = extrato(self.CORPO).replace("Período:", "Periodo").replace(
            "Informações do Comprovante", "Comprovante")
        transacoes = stone.ler_transacoes(texto)
        self.assertEqual(len(transacoes), 5)
        v = {x["verificacao"]: x for x in stone.verificar_leitura(texto, transacoes)}
        self.assertEqual(v["Cabeçalho/rodapé descartados"]["status"], "ALERTA")
        self.assertIn("Layout do PDF não reconhecido", v["Cabeçalho/rodapé descartados"]["detalhe"])

    def test_transacao_perdida_gera_alerta_com_local(self):
        texto = extrato(self.CORPO)
        transacoes = stone.ler_transacoes(texto)
        faltando = transacoes[:2] + transacoes[3:]
        v = {x["verificacao"]: x for x in stone.verificar_leitura(texto, faltando)}
        self.assertEqual(v["Nº de transações (PDF × lido)"]["status"], "ALERTA")
        self.assertEqual(v["Cadeia de saldos"]["status"], "ALERTA")
        self.assertIn("04/07/26", v["Cadeia de saldos"]["detalhe"])
