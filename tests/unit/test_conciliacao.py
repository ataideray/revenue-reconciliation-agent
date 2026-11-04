"""Conciliação: casamento na mesma pessoa, 2 Pix por recibo (B7) e sugestões
de vínculo e de devolução (B4), nunca aplicadas (decisões de 2026-10-06 e
2026-10-08)."""

import unittest

from conselho_fiscal.receitas import conciliacao as c
from conselho_fiscal.receitas.pessoas import agrupar, mesmo_nome


def montar(recibos, pix):
    recs = [{"celulas": [f"R{i}", n], "origem": n, "valor": v} for i, (n, v) in enumerate(recibos)]
    ents = [{"nome": n, "valor": v, "banco": b, "data": d} for n, v, b, d in pix]
    return agrupar(recs, ents)


def pessoa(pessoas, trecho):
    return next(p for p in pessoas.values() if trecho in p["nome"])


def compat(recibos, pix):
    pessoas = montar(recibos, [(n, v, "Cora", "10/07/2026") for n, v in pix])
    return {rec["celulas"][0]: rec["compat"] for _, rec in c.ordenar_recibos(pessoas)}


ILA, BRUNO = "ILA NADIA JASMIM", "BRUNO NUVEM CAJU"


class TestMesmoNome(unittest.TestCase):
    def test_variacoes_da_mesma_pessoa(self):
        self.assertTrue(mesmo_nome("NAYLA ESTER DA VER", "NAYLA ESTER DA VERDE ORVALHO"))
        self.assertTrue(mesmo_nome("NAIRA MANJERICAO", "NAIRA CAPIVARA MANJERICAO"))
        self.assertFalse(mesmo_nome("NOELI VERDE", "NOELI LARANJAL"))


class TestEntradas(unittest.TestCase):
    def test_rendimento_de_centavos_sai_e_suspeito_fica(self):
        t = {"banco": "Stone", "data": "01/07/26", "tipo": "Entrada", "documento": "",
             "categoria": "", "saida": 0.0, "saldo": None}
        transacoes = [{**t, "nome": "Rendimento automático", "entrada": 0.01},
                      {**t, "nome": "Rendimento automático", "entrada": 150.0},
                      {**t, "nome": "Transf Pix recebida FULANO", "entrada": 20.0}]
        with self.assertLogs("conselho_fiscal.receitas.conciliacao", "WARNING"):
            lista = c.entradas(transacoes)
        self.assertEqual([(e["nome"], e["valor"]) for e in lista],
                         [(c.NOME_RENDIMENTO_SUSPEITO, 150.0), ("FULANO", 20.0)])


class TestCnpj(unittest.TestCase):
    """Conta ou recibo de CNPJ (2026-10-28): pelo documento do Cora ou pelo nome."""

    def test_documento(self):
        self.assertTrue(c.eh_cnpj("12.345.678/0001-90", "LOJA"))
        self.assertFalse(c.eh_cnpj("123.456.789-09", "LOJA LTDA"))    # o documento manda

    def test_nome(self):
        for nome in ("ESTUDIO LUMEN LTDA", "Comercio Ltda.", "EMPRESA S/A", "EMPRESA S.A.",
                     "CASA DO PAO EPP", "LOJA BOA VISTA ME", "NOELI P J 12345678901",
                     "12.345.678 NOELI VERDE"):
            self.assertTrue(c.eh_cnpj(nome=nome), nome)
        for nome in ("MARIA DE SA", "ANA ME", "MEIRE AMORAS", "LUMITECH",
                     # a Stone cola o banco de quem pagou: o "S.A." é do banco
                     "OTAVIO PE DE SERRA Banco Bradesco S.A.",
                     "RENATO RIO CLARO NU PAGAMENTOS S.A. - 98765432100 INSTITUIÇÃO DE PAGAMENTO"):
            self.assertFalse(c.eh_cnpj(nome=nome), nome)
        self.assertTrue(c.eh_cnpj(nome="NOELI P J 12345678901 Banco do Brasil S.A."))

    def test_chega_a_divergencia_e_a_sugestao(self):
        t = {"banco": "Cora", "data": "10/07/2026", "tipo": "Entrada", "categoria": "",
             "saida": 0.0, "saldo": None}
        ents = c.entradas([{**t, "nome": "Transf Pix recebida LUMEN", "entrada": 275.0,
                            "documento": "12.345.678/0001-90"}])
        pessoas = agrupar([{"celulas": ["0001-2026", "EVANDRO"], "origem": "EVANDRO",
                            "valor": 275.0}], ents)
        sug = c.sugerir_vinculos(pessoas)
        div = c.detalhar_divergencias(c.ordenar_pessoas(pessoas), sug)
        lumen = next(d for d in div if d["pessoa"] == "LUMEN")
        self.assertTrue(lumen["cnpj"])
        self.assertTrue(lumen["pix_sem_recibo"][0]["cnpj"])
        self.assertEqual((sug[0]["pix_cnpj"], sug[0]["recibo_cnpj"]), (True, False))
        self.assertFalse(next(d for d in div if d["pessoa"] == "EVANDRO")["cnpj"])


class TestRendimentos(unittest.TestCase):
    """Coluna Rendimentos da planilha × 'Rendimento automático' dos extratos."""

    def setUp(self):
        t = {"banco": "Stone", "data": "01/07/26", "tipo": "Entrada", "documento": "",
             "categoria": "", "saida": 0.0, "saldo": None}
        self.stone = [{**t, "nome": "Rendimento automático", "entrada": 0.01},
                      {**t, "nome": "Rendimento automático", "entrada": 0.02},
                      {**t, "nome": "Rendimento automático", "entrada": 150.0},   # suspeito
                      {**t, "nome": "Transf Pix recebida FULANO", "entrada": 20.0}]

    def pivotado(self, *rendimentos):
        linhas = [{"Número": "1", "Origem": "FULANO", "Anuidade": 20.0, "Rendimentos": None}]
        linhas += [{"Número": str(i), "Origem": "RENDIMENTOS", "Anuidade": None,
                    "Rendimentos": v} for i, v in enumerate(rendimentos, start=2)]
        return {"colunas": ["Anuidade", "Rendimentos"], "linhas": linhas}

    def test_um_recibo_por_rendimento_ou_um_pelo_mes(self):
        for pivotado in (self.pivotado(0.01, 0.02), self.pivotado(0.03)):
            v = c.conferir_rendimentos(pivotado, [], self.stone)
            self.assertEqual((v["status"], v["esperado"], v["encontrado"]),
                             ("OK", "R$ 0,03", "R$ 0,03"))

    def test_rendimento_nao_lancado(self):
        v = c.conferir_rendimentos(self.pivotado(0.01), [], self.stone)
        self.assertEqual((v["status"], v["detalhe"]), (
            "ALERTA", "Extratos: Stone: 2 lançamento(s), R$ 0,03; Cora: nenhum. Planilha: 1 "
                      "recibo(s) na coluna Rendimentos."))
        sem_coluna = {"colunas": ["Anuidade"], "linhas": [{"Anuidade": 20.0}]}
        self.assertEqual(c.conferir_rendimentos(sem_coluna, [], [])["status"], "OK")


class TestDevolucoes(unittest.TestCase):
    def test_devolucao_e_so_sugestao_e_vira_divergencia(self):
        pessoas = montar([("NAIR DE CANELA NEVE", 30)],
                         [("NAIR DE CANELA NEVE SERENO", 300, "Stone", "20/07/26"),
                          ("NAIR DE CANELA NEVE SERENO", 30, "Stone", "04/07/26")])
        dev = c.sugerir_devolucoes(pessoas, [
            {"nome": "NAIR DE CANELA NEVE SERENO", "valor": 300, "banco": "Stone", "data": "24/07/26"}])
        self.assertEqual([(d["valor"], d["entrada_data"], d["div"]) for d in dev],
                         [(300, "20/07/26", "DIV-NAIR-DE-CANELA-NEVE-SERENO")])
        # nada é retirado: a pessoa continua divergente até a tesouraria confirmar
        self.assertEqual(c.status_pessoa(pessoa(pessoas, "NAIR")), ("Divergência de valor", -300))
        divs = c.detalhar_divergencias(c.ordenar_pessoas(pessoas), [], {}, dev)
        self.assertEqual([d["devolucoes_possiveis"] for d in divs], [c.publicas(dev)])
        self.assertNotIn("_pix", divs[0]["devolucoes_possiveis"][0])

    def test_pix_com_devolucao_nao_recebe_sugestao_de_vinculo(self):
        pessoas = montar([("BRUNO NUVEM CAJU", 100)],
                         [("ILA NADIA JASMIM", 100, "Cora", "10/06/2026")])
        self.assertEqual(len(c.sugerir_vinculos(pessoas)), 1)        # sem devolução: sugere
        dev = c.sugerir_devolucoes(pessoas, [
            {"nome": "ILA NADIA JASMIM", "valor": 100, "banco": "Cora", "data": "15/06/2026"}])
        self.assertEqual(len(dev), 1)
        self.assertEqual(c.sugerir_vinculos(pessoas, [], dev), [])

    def test_um_pix_so_e_sugerido_para_uma_saida(self):
        pessoas = montar([], [("ILA NADIA JASMIM", 100, "Cora", "10/06/2026")])
        saida = {"nome": "ILA NADIA JASMIM", "valor": 100, "banco": "Cora", "data": "15/06/2026"}
        self.assertEqual(len(c.sugerir_devolucoes(pessoas, [saida, dict(saida)])), 1)

    def test_pix_que_casa_com_recibo_nao_e_afetado(self):
        pessoas = montar([("TELMO OLIVAS ALECRIM SALVIA", 60)],
                         [("TELMO OLIVAS ALECRIM SALVIA", 60, "Stone", "05/06/26")])
        dev = c.sugerir_devolucoes(pessoas, [
            {"nome": "TELMO OLIVAS ALECRIM SALVIA", "valor": 60, "banco": "Stone", "data": "07/06/26"}])
        self.assertEqual(dev, [])

    def test_saida_antes_da_entrada_e_outra_pessoa_nao_contam(self):
        pessoas = montar([("ILA NADIA JASMIM", 50)],
                         [("ILA NADIA JASMIM", 50, "Cora", "10/06/2026"),
                          ("ILA NADIA JASMIM", 100, "Cora", "20/06/2026")])
        dev = c.sugerir_devolucoes(pessoas, [
            {"nome": "ILA NADIA JASMIM", "valor": 100, "banco": "Cora", "data": "15/06/2026"},
            {"nome": "NOELI LARANJAL", "valor": 100, "banco": "Cora", "data": "25/06/2026"}])
        self.assertEqual(dev, [])


class TestVariosPixUmRecibo(unittest.TestCase):
    def test_dois_pix_da_mesma_pessoa(self):
        self.assertEqual(compat([(ILA, 120)], [(ILA, 100), (ILA, 20)]), {"R0": "Conforme (2 Pix)"})

    def test_um_para_um_tem_prioridade(self):
        self.assertEqual(compat([(ILA, 120), (ILA, 20)], [(ILA, 120), (ILA, 100), (ILA, 20)]),
                         {"R0": "Conforme", "R1": "Conforme"})

    def test_ambiguo_outra_pessoa_e_tres_pix_nao_combinam(self):
        self.assertEqual(compat([(ILA, 100)], [(ILA, 30), (ILA, 70), (ILA, 40), (ILA, 60)]),
                         {"R0": "Divergente"})
        self.assertEqual(compat([(ILA, 120), (BRUNO, 30)], [(ILA, 100), (BRUNO, 20), (BRUNO, 30)])["R0"],
                         "Divergente")
        self.assertEqual(compat([(ILA, 120)], [(ILA, 50), (ILA, 50), (ILA, 20)]), {"R0": "Divergente"})


class TestSugestoes(unittest.TestCase):
    def sugestoes(self, recibos, pix, confirmados=()):
        pessoas = montar(recibos, [(n, v, "Cora", "10/07/2026") for n, v in pix])
        return {(s["nome_no_extrato"], s["recibo"]): s["criterio"]
                for s in c.sugerir_vinculos(pessoas, list(confirmados))}

    def test_criterios(self):
        recibos = [("MARILDA VERDE CORUJAS", 10), ("LEOPOLDO GIRASSOL LUAR", 150),
                   ("IVAN TRIGO PALHA LUAR", 130), ("ELIO PEDRO", 80), ("NOELI CLARA", 80)]
        pix = [("MARINILDA CEDRO DA VERDE", 10), ("EVA OLMO GIRASOL", 150),
               ("LUMITECH", 130), ("EMPRESA QUALQUER", 80)]
        self.assertEqual(self.sugestoes(recibos, pix), {
            ("MARINILDA CEDRO DA VERDE", "R0"): "nome em comum (Verde)",
            ("EVA OLMO GIRASOL", "R1"): "nome parecido (Girasol ≈ Girassol)",
            ("LUMITECH", "R2"): "valor único no mês (sem pista de nome)",
            ("EMPRESA QUALQUER", "R3"): "mesmo valor (2 recibos possíveis)",
            ("EMPRESA QUALQUER", "R4"): "mesmo valor (2 recibos possíveis)",
        })

    def test_conta_confirmada_e_o_criterio_mais_forte_mas_so_sugere(self):
        recibos, pix = [("LEOPOLDO GIRASSOL LUAR", 130)], [("LUMIVERDE COMERCI", 130)]
        conf = [{"nome_extrato": "LUMIVERDE COMERCI", "pessoa": "LEOPOLDO GIRASSOL LUAR",
                 "confirmado_em": "2026-06", "observacao": ""}]
        self.assertEqual(self.sugestoes(recibos, pix, conf),
                         {("LUMIVERDE COMERCI", "R0"): "conta já confirmada pela tesouraria (2026-06)"})
        self.assertEqual(compat(recibos, pix), {"R0": "Divergente"})

    def test_divergencias_com_sugestao_dos_dois_lados_e_nota(self):
        pessoas = montar([("IVAN TRIGO PALHA LUAR", 150)], [("LUMITECH", 150, "Cora", "22/06/2026")])
        sug = c.sugerir_vinculos(pessoas)
        divs = {d["id"]: d for d in c.detalhar_divergencias(
            c.ordenar_pessoas(pessoas), sug, {"DIV-LUMITECH": "Pago pela empresa do Ivan."})}
        self.assertEqual(set(divs), {"DIV-LUMITECH", "DIV-IVAN-TRIGO-PALHA-LUAR"})
        self.assertEqual(len(divs["DIV-LUMITECH"]["sugestoes_vinculo"]), 1)
        self.assertEqual(len(divs["DIV-IVAN-TRIGO-PALHA-LUAR"]["sugestoes_vinculo"]), 1)
        self.assertEqual(divs["DIV-LUMITECH"]["nota_tesouraria"], "Pago pela empresa do Ivan.")
        self.assertNotIn("_rec", divs["DIV-LUMITECH"]["sugestoes_vinculo"][0])

    def test_id_estavel(self):
        self.assertEqual(c.id_divergencia("Odir Valerio Cascata de Areia"),
                         "DIV-ODIR-VALERIO-CASCATA-DE-AREIA")
