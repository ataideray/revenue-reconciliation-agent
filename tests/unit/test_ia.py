"""O que vai para a IA (só o mínimo, com apelidos) e o adaptador do Gemini,
com a rede simulada."""

import io
import json
import unittest
import urllib.error
from unittest import mock

from conselho_fiscal.agente import avaliacao
from conselho_fiscal.agente import divergencias as dv
from conselho_fiscal.agente.gemini import Gemini
from conselho_fiscal.agente.ia import (
    Apelidos,
    Contexto,
    ContextoComando,
    ContextoNota,
    ContextoPergunta,
    ContextoResposta,
    Interpretacao,
    Pergunta,
    de_comando,
    de_ia,
    de_pergunta,
    de_redacao,
    de_resposta,
    para_comando,
    para_ia,
    para_pergunta,
    para_redacao,
    para_resposta,
)

NOMES = ("IVAN", "TRIGO", "PALHA", "LUAR", "LUMITECH", "NAIR", "CANELA", "SERENO")


def contexto(texto):
    """LUMITECH: Pix sem recibo, com sugestão de vínculo ao recibo do Ivan e
    uma devolução já confirmada (fictícia) para a Nair."""
    sug = {"pix_de": "LUMITECH", "nome_no_extrato": "LUMITECH", "valor": 150.0,
           "pix_banco": "Cora", "pix_data": "05/07/2026", "recibo": "0002-2026",
           "recibo_de": "IVAN TRIGO PALHA LUAR", "criterio": "nome parecido (Palha ≈ Palh)",
           "forca": 2, "div_pix": "DIV-LUMITECH", "div_recibo": "DIV-IVAN-TRIGO-PALHA-LUAR"}
    dev = {"pessoa": "LUMITECH", "valor": 30.0, "entrada_banco": "Stone",
           "entrada_data": "04/07/26", "saida_nome": "NAIR DE CANELA NEVE SERENO",
           "saida_banco": "Stone", "saida_data": "06/07/26", "div": "DIV-LUMITECH"}
    d = {"id": "DIV-LUMITECH", "pessoa": "LUMITECH", "tipo": "Sem recibo (só extrato)",
         "total_recibos": 0.0, "total_extrato": 180.0, "diferenca": -180.0,
         "recibos_sem_pix": [],
         "pix_sem_recibo": [{"valor": 150.0, "banco": "Cora", "data": "05/07/2026",
                             "nome_no_extrato": "LUMITECH"},
                            {"valor": 30.0, "banco": "Stone", "data": "04/07/26",
                             "nome_no_extrato": "LUMITECH"}],
         "sugestoes_vinculo": [sug], "devolucoes_possiveis": [dev]}
    ivan = {"id": "DIV-IVAN-TRIGO-PALHA-LUAR", "recibos_sem_pix": [{"numero": "0002-2026",
                                                                    "valor": 150.0}],
            "pix_sem_recibo": []}
    todas = {d["id"]: d, ivan["id"]: ivan}
    ops = dv.opcoes(d, [], todas)
    vinculo, devolucao = ops
    return Contexto(d, [vinculo], [devolucao], texto)


class TestApelidos(unittest.TestCase):
    def test_troca_e_desfaz(self):
        ap = Apelidos()
        self.assertEqual(ap("IVAN TRIGO PALHA LUAR"), "PESSOA_A")
        self.assertEqual(ap("Ivan Trigo Palha Luar"), "PESSOA_A")         # mesmo nome
        self.assertEqual(ap("NAIR DE CANELA NEVE SERENO"), "PESSOA_B")
        self.assertEqual(ap.trocar("o Pix é do Ivan Trigo, cpf 123.456.789-09, e da Nair"),
                         "o Pix é do PESSOA_A, cpf [CPF], e da PESSOA_B")
        self.assertEqual(ap.trocar("a mãe dela, Noeli, pagou 12345678909"),
                         "a mãe dela, Noeli, pagou [CPF]")      # nome desconhecido fica
        self.assertEqual(ap.desfazer("é da PESSOA_A; PESSOA_Z não existe"),
                         "é da IVAN TRIGO PALHA LUAR; PESSOA_Z não existe")

    def test_nome_de_pessoa_passa_na_frente_de_conta(self):
        # avaliação de 2026-10-09: "é a empresa do Odir" virava a própria conta "ODIR P J …"
        ap = Apelidos()
        conta = ap("ODIR P J 12345678909", conta=True)
        pessoa = ap("ODIR VALERIO CASCATA DE AREIA")
        self.assertEqual(ap.trocar("é a empresa do Odir"), f"é a empresa do {pessoa}")
        self.assertEqual(ap.trocar("o P J 12345678909"), "o P J [CPF]")   # CPF antes
        self.assertEqual(ap.desfazer(conta), "ODIR P J 12345678909")

    def test_palavras_curtas_e_comuns_nao_viram_apelido(self):
        ap = Apelidos()
        ap("NAIR DE CANELA")
        self.assertEqual(ap.trocar("de quem é?"), "de quem é?")


class TestParaIA(unittest.TestCase):
    def test_so_o_minimo(self):
        texto, ap = para_ia(contexto("a 1 tá certa, a empresa é do Ivan"))
        for nome in NOMES:
            self.assertNotIn(nome, texto.upper())
        self.assertNotIn("parecido", texto)                     # critério não vai
        self.assertIn("1) vínculo: o Pix R$ 150,00 (Cora, 05/07/2026) da conta PESSOA_A "
                      "pagou o recibo 0002-2026 de PESSOA_C", texto)
        self.assertIn("- devolução: o Pix R$ 30,00 (Stone, 04/07/26) foi devolvido a "
                      "PESSOA_B", texto)
        self.assertIn('Resposta da tesouraria: "a 1 tá certa, a empresa é do PESSOA_C"', texto)

    def test_nomes_de_outras_divergencias_tambem_viram_apelido(self):
        ctx = contexto("quem pagou foi o Leopoldo, irmão da Eva")
        ctx = Contexto(ctx.divergencia, ctx.sugestoes, ctx.ja_confirmado, ctx.texto,
                       (("LEOPOLDO GIRASSOL LUAR", False), ("EVA OLMO GIRASOL", True)))
        texto, _ = para_ia(ctx)
        self.assertIn('"quem pagou foi o PESSOA_D, irmão da PESSOA_E"', texto)

    def test_pergunta_com_apelido_inventado_e_descartada(self):
        # simulador (2026-10-09): "PESSOA_TESOURARIA, de quem é o Pix…?"
        ap = Apelidos()
        ap("MARILENE LUCIMARA")
        resposta = {"confirmar": [], "explicacao": "", "suficiente": False, "adiar": False}
        it = de_ia(json.dumps(dict(resposta, pergunta="De quem é o Pix de PESSOA_A?")), ap)
        self.assertEqual(it.pergunta, "De quem é o Pix de MARILENE LUCIMARA?")
        it = de_ia(json.dumps(dict(resposta, pergunta="PESSOA_TESOURARIA, de quem é?")), ap)
        self.assertEqual(it.pergunta, "")                   # o agente usa a pergunta padrão

    def test_nome_errado(self):
        resposta = {"confirmar": [1], "explicacao": "o nome do recibo saiu errado",
                    "suficiente": True, "adiar": False, "pergunta": ""}
        self.assertFalse(de_ia(json.dumps(resposta), Apelidos()).nome_errado)   # padrão
        it = de_ia(json.dumps(dict(resposta, nome_errado=True)), Apelidos())
        self.assertTrue(it.nome_errado)

    def test_comando(self):
        resposta = {"confirmar": [], "explicacao": "", "suficiente": False, "adiar": False,
                    "pergunta": ""}
        self.assertEqual(de_ia(json.dumps(resposta), Apelidos()).comando, "nenhum")
        it = de_ia(json.dumps(dict(resposta, comando="ajuda")), Apelidos())
        self.assertEqual(it.comando, "ajuda")
        it = de_ia(json.dumps(dict(resposta, comando="apagar tudo")), Apelidos())
        self.assertEqual(it.comando, "nenhum")                 # fora da lista: nada
        self.assertEqual(de_comando('{"comando": "trocar_cf"}'), "trocar_cf")
        self.assertEqual(de_comando('{"comando": "x"}'), "nenhum")
        with self.assertRaises(ValueError):
            de_comando("não é json")

    def test_para_comando_troca_os_nomes(self):
        texto, _ = para_comando(ContextoComando("a Marilene Lucimara pediu o menu", "tesouraria",
                                                (("MARILENE LUCIMARA", False),)))
        self.assertNotIn("Marilene", texto)
        self.assertIn("da tesouraria", texto)

    def test_resposta_fora_do_formato(self):
        ap = Apelidos()
        for ruim in ("não é json", "[1, 2]", '{"confirmar": [1]}', '{"suficiente": true, '
                     '"confirmar": ["um"]}'):
            with self.assertRaises(ValueError):
                de_ia(ruim, ap)


class TestRedacao(unittest.TestCase):
    def pedido(self, respostas=("é a empresa do Ivan",)):
        ctx = contexto("x")
        confirmada = {k: v for k, v in ctx.sugestoes[0].items() if k not in ("id", "rotulo")}
        return para_redacao(ContextoNota(ctx.divergencia, [confirmada], list(respostas)))

    def test_pedido_so_com_apelidos(self):
        pedido, _ = self.pedido()
        for nome in NOMES:
            self.assertNotIn(nome, pedido.upper())
        self.assertIn("Confirmado pela tesouraria:\n- vínculo: o Pix R$ 150,00", pedido)
        self.assertIn('A tesouraria escreveu: "é a empresa do PESSOA_B"', pedido)
        self.assertIn("não escreveu nada", self.pedido(())[0])

    def test_confere_os_numeros(self):
        pedido, ap = self.pedido()

        def redigida(nota):
            return de_redacao(json.dumps({"nota": nota}), ap, pedido)

        self.assertEqual(redigida("Segundo a tesouraria, o Pix de R$ 150,00 (05/07) pagou o "
                                  "recibo 0002-2026 de PESSOA_B, dona da empresa; os 2 Pix…"),
                         "Segundo a tesouraria, o Pix de R$ 150,00 (05/07) pagou o recibo "
                         "0002-2026 de IVAN TRIGO PALHA LUAR, dona da empresa; os 2 Pix…")
        self.assertEqual(redigida("Pix de R$ 150 do recibo 0002."), "Pix de R$ 150 do recibo 0002.")
        self.assertEqual(redigida("• Pix de R$ 150 do recibo 0002."),
                         "Pix de R$ 150 do recibo 0002.")              # um item: sem "•"
        for ruim in ("Os Pix somam R$ 330,00.",        # conta da IA
                     "O recibo 0815-2026 foi pago.",   # recibo inventado
                     "É de PESSOA_Z.", ""):            # apelido inventado, vazia
            with self.assertRaises(ValueError, msg=ruim):
                redigida(ruim)
        with self.assertRaises(ValueError):
            de_redacao("não é json", ap, pedido)


class TestPerguntaCF(unittest.TestCase):
    def pedido(self, texto):
        return para_pergunta(ContextoPergunta(
            texto, "2026-10-13", ("2026-06", "2026-07"),
            (("NAIR DE CANELA NEVE SERENO", False), ("LUMITECH", True))))

    def test_so_apelidos_e_sem_cpf(self):
        pedido, _ = self.pedido("a Nair (cpf 123.456.789-00) pagou a LUMITECH?")
        self.assertNotIn("NAIR", pedido.upper())
        self.assertNotIn("LUMITECH", pedido.upper())
        self.assertIn('"a PESSOA_A (cpf [CPF]) pagou a PESSOA_B?"', pedido)
        self.assertIn("Hoje: 2026-10-13\nMeses com dados: 2026-06, 2026-07", pedido)

    def test_resposta(self):
        _, ap = self.pedido("o que houve com a Nair?")

        def lida(**r):
            return de_pergunta(json.dumps(dict({"meses": [], "pessoa": ""}, **r)), ap)

        self.assertEqual(lida(consulta="pessoa", meses=["2026-07", "julho", "2026-13"],
                              pessoa="PESSOA_A"),
                         Pergunta("pessoa", ("2026-07",), "NAIR DE CANELA NEVE SERENO"))
        self.assertEqual(lida(consulta="pessoa", pessoa="Noeli"), Pergunta("pessoa", (), "Noeli"))
        self.assertEqual(lida(consulta="pessoa", pessoa="PESSOA_Z"), Pergunta("pessoa"))
        self.assertEqual(lida(consulta="destino", meses=["2026-07"], destino=" açaí "),
                         Pergunta("destino", ("2026-07",), destino="açaí"))
        for ruim in ('{"consulta": "apagar"}', "[]", "não é json"):
            with self.assertRaises(ValueError, msg=ruim):
                de_pergunta(ruim, ap)


class TestRespostaCF(unittest.TestCase):
    def test_apelidos_e_numeros(self):
        pedido, ap = para_resposta(ContextoResposta(
            "o que houve com a Nair?",
            "*NAIR DE CANELA NEVE SERENO* — Divergência de valor\nPix sem recibo: R$ 300,00 "
            "(Stone, 20/07/26)\nNota da tesouraria: a Nair (cpf 123.456.789-00) pagou duas vezes",
            (("NAIR DE CANELA NEVE SERENO", False),)))
        self.assertNotIn("NAIR", pedido.upper())
        self.assertIn("[CPF]", pedido)

        def lida(texto):
            return de_resposta(json.dumps({"resposta": texto}), ap, pedido)

        self.assertEqual(lida("Segundo a tesouraria, PESSOA_A pagou R$ 300,00 duas vezes."),
                         "Segundo a tesouraria, NAIR DE CANELA NEVE SERENO pagou R$ 300,00 "
                         "duas vezes.")
        self.assertEqual(lida("Pix sem recibo: • R$ 300,00 (Stone) • nenhum outro"),
                         "Pix sem recibo:\n• R$ 300,00 (Stone)\n• nenhum outro")
        self.assertEqual(lida("• um\n• dois"), "• um\n• dois")
        self.assertEqual(lida("Caiu. *Receitas*\n• R$ 300,00 *Pix*\n• um\n\n*Recibos*\n• dois"),
                         "Caiu.\n\n*Receitas*\n• R$ 300,00\n\n*Pix*\n• um\n\n*Recibos*\n"
                         "• dois")
        # valor ou pessoa em negrito no fim de um item não vira título
        self.assertEqual(lida("*Pix*\n• Total: *R$ 300,00*\n• De *PESSOA_A*\n• fim"),
                         "*Pix*\n• Total: *R$ 300,00*\n• De *NAIR DE CANELA NEVE SERENO*\n"
                         "• fim")
        for ruim in ("Ela pagou R$ 600,00.", "É de PESSOA_Z.", ""):
            with self.assertRaises(ValueError, msg=ruim):
                lida(ruim)


def resposta_gemini(conteudo):
    corpo = {"candidates": [{"content": {"parts": [{"text": json.dumps(conteudo)}]}}]}
    return io.BytesIO(json.dumps(corpo).encode())


class TestGemini(unittest.TestCase):
    def test_pedido_e_resposta(self):
        enviado = {}

        def urlopen(pedido, timeout):
            enviado.update(url=pedido.full_url, chave=pedido.get_header("X-goog-api-key"),
                           corpo=pedido.data.decode())
            return resposta_gemini({"confirmar": [1], "explicacao": "a empresa é do PESSOA_C",
                                    "suficiente": True, "adiar": False, "pergunta": ""})

        with mock.patch("urllib.request.urlopen", urlopen):
            it = Gemini("chave-teste", "modelo-x").interpretar(
                contexto("a 1 tá certa, a empresa é do Ivan"))
        self.assertEqual(it.confirmar, (1,))
        self.assertEqual(it.explicacao, "a empresa é do IVAN TRIGO PALHA LUAR")
        self.assertIn("models/modelo-x:generateContent", enviado["url"])
        self.assertEqual(enviado["chave"], "chave-teste")
        self.assertNotIn("chave-teste", enviado["corpo"])
        for nome in NOMES:
            self.assertNotIn(nome, enviado["corpo"].upper())

    def test_erro_http_sem_a_chave_na_mensagem(self):
        chamadas = []

        def urlopen(pedido, timeout):
            chamadas.append(1)
            raise urllib.error.HTTPError(pedido.full_url, 429, "Too Many Requests", {}, None)

        with mock.patch("urllib.request.urlopen", urlopen), mock.patch("time.sleep"):
            with self.assertRaises(RuntimeError) as erro:
                Gemini("chave-teste").interpretar(contexto("x"))
        self.assertEqual(str(erro.exception), "Gemini respondeu 429 (Too Many Requests)")
        self.assertEqual(len(chamadas), 2)                     # tentou mais uma vez

    def test_queda_de_rede_tenta_de_novo_e_depois_desiste(self):
        respostas = [TimeoutError("The read operation timed out"),
                     resposta_gemini({"confirmar": [], "explicacao": "oferta",
                                      "suficiente": True, "adiar": False, "pergunta": ""})]

        def urlopen(pedido, timeout):
            r = respostas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with mock.patch("urllib.request.urlopen", urlopen):
            self.assertEqual(Gemini("k").interpretar(contexto("oferta")).explicacao, "oferta")
            respostas[:] = [TimeoutError("t1"), TimeoutError("t2")]
            with self.assertRaisesRegex(RuntimeError, "sem resposta do Gemini"):
                Gemini("k").interpretar(contexto("oferta"))

    def test_sem_resposta_do_principal_tenta_o_reserva(self):
        urls = []
        respostas = [urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None),
                     resposta_gemini({"confirmar": [], "explicacao": "oferta",
                                      "suficiente": True, "adiar": False, "pergunta": ""})]

        def urlopen(pedido, timeout):
            urls.append(pedido.full_url)
            r = respostas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        ia = Gemini("k", "principal", reserva="reserva")
        with mock.patch("urllib.request.urlopen", urlopen), mock.patch("time.sleep") as espera:
            self.assertEqual(ia.interpretar(contexto("oferta")).explicacao, "oferta")
        self.assertEqual([u.split("/models/")[1] for u in urls],
                         ["principal:generateContent", "reserva:generateContent"])
        self.assertEqual((ia.nome, ia.ultimo), ("Gemini (principal)", "Gemini (reserva)"))
        espera.assert_not_called()                     # outro modelo: sem esperar
        self.assertEqual(Gemini("k", "principal", reserva="").reserva, "principal")

    def test_sobrecarga_tenta_de_novo(self):
        respostas = [urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None),
                     resposta_gemini({"confirmar": [], "explicacao": "oferta",
                                      "suficiente": True, "adiar": False, "pergunta": ""})]

        def urlopen(pedido, timeout):
            r = respostas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with mock.patch("urllib.request.urlopen", urlopen), mock.patch("time.sleep"):
            it = Gemini("chave-teste").interpretar(contexto("oferta"))
        self.assertEqual(it.explicacao, "oferta")


class TestAvaliacao(unittest.TestCase):
    def caso(self, aceitos, suficiente=True, adiar=False, contem=(), vazia=False):
        return avaliacao.Caso("X", "t", tuple(frozenset(a) for a in aceitos), suficiente,
                              adiar, contem, vazia)

    def test_gravidades(self):
        comparar = avaliacao.comparar
        caso = self.caso([[1]])
        self.assertEqual(comparar(caso, Interpretacao(confirmar=(1,)), 2), [])
        p = comparar(caso, Interpretacao(confirmar=(1, 2)), 2)
        self.assertEqual(p, [(avaliacao.CRITICO, "confirmou [2] sem a tesouraria confirmar")])
        p = comparar(caso, Interpretacao(confirmar=()), 2)
        self.assertEqual(avaliacao.mais_grave(p), avaliacao.ERRO)     # cauteloso: erro
        p = comparar(caso, Interpretacao(confirmar=(1, 5)), 2)          # 5 não existe
        self.assertEqual(avaliacao.mais_grave(p), avaliacao.AVISO)
        p = comparar(self.caso([[1], []]), Interpretacao(), 2)          # duas leituras aceitas
        self.assertEqual(p, [])
        p = comparar(self.caso([[]], suficiente=None, adiar=True), Interpretacao(adiar=True), 1)
        self.assertEqual(p, [])
        p = comparar(self.caso([[]], contem=("oferta",)), Interpretacao(explicacao="x"), 1)
        self.assertEqual(avaliacao.mais_grave(p), avaliacao.AVISO)
        p = [(avaliacao.AVISO, "a"), (avaliacao.ERRO, "b")]
        self.assertEqual(avaliacao.mais_grave(p), avaliacao.ERRO)
