"""Cadastros: destinos (B9 e regras editáveis) e vínculos confirmados, com a
guarda de no máximo 2 anos."""

import json
import os
import unittest

from conselho_fiscal.cadastros import destinos, vinculos
from tests.apoio import CADASTRO_DESTINOS, pasta_temp


class TestChave(unittest.TestCase):
    def test_ignora_caixa_acento_traco_e_plural(self):
        for variantes, chave in [
            (["Fundo - Lampadas", "Fundo - lampadas", "Fundo - lampada", "fundo – Lâmpadas",
              "Fundo—Lampada", "  Fundo  -  lâmpada "], "fundo lampada"),
            (["Oferta", "Ofertas", "OFERTAS"], "oferta"),
            (["Alto falante", "Alto-falante", "alto  falantes"], "alto falante"),
        ]:
            self.assertEqual({destinos.chave(v) for v in variantes}, {chave})

    def test_destinos_diferentes_continuam_separados(self):
        self.assertEqual(len({destinos.chave(v) for v in [
            "Oferta", "Fundo reforma", "Fundo - lampadas", "Fundo reforma - Venda das Camisetas",
            "Anuidade", "Saldo de Anuidade"]}), 6)


class TestCadastroDestinos(unittest.TestCase):
    def test_cadastro_do_repositorio_e_coerente(self):
        cad = destinos.carregar(CADASTRO_DESTINOS)
        for k, c in cad["colunas"].items():
            self.assertEqual(destinos.chave(c["nome"]), k)
        for alvo in list(cad["apelidos"].values()) + list(cad["prefixos"].values()):
            self.assertIn(alvo, cad["colunas"])

    def test_resolver_apelidos_prefixos_e_novos(self):
        cad = destinos.carregar(CADASTRO_DESTINOS)
        self.assertIsNone(destinos.resolver("Total", cad))
        self.assertEqual(destinos.resolver("Pastel", cad), ("pastel", "Pastel"))
        cad["apelidos"]["pastel"] = "cantina"            # tesouraria: Pastel é Cantina
        cad["prefixos"]["rifa"] = "promocao"             # qualquer "Rifa…" é Promoções
        self.assertEqual(destinos.resolver("Pastel", cad), ("cantina", None))
        self.assertEqual(destinos.resolver("Rifa de Natal", cad), ("promocao", None))
        for desc, chave in [("Anuidade — Conselheira Flora", "anuidade"),
                            ("Retiro - Arrecadação Retiro de Inverno Jul - 2026", "retiro"),
                            ("Açaí — Açaí", "acai"), ("Espetinho de carne", "espetinho"),
                            ("Brechó", "brecho"), ("Lojinha", "lojinha"), ("Sopa", "oficina"),
                            ("Promoção Dia das Mães", "promocao"),
                            ("Saldo de Anuidade", "saldo de anuidade"),
                            ("Fundo reforma - Venda das Camisetas", "fundo reforma venda das camiseta")]:
            self.assertEqual(destinos.resolver(desc, cad)[0], chave, desc)

    def test_formato_antigo_e_convertido(self):
        caminho = os.path.join(pasta_temp(), "destinos.json")
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"cantina": "Cantina"}, f)
        cad = destinos.carregar(caminho)
        self.assertEqual(cad["colunas"], {"cantina": {"nome": "Cantina", "ultimo_uso": None}})
        self.assertEqual((cad["apelidos"], cad["prefixos"]), ({}, {}))

    def test_salvar_e_carregar(self):
        caminho = os.path.join(pasta_temp(), "destinos.json")
        cad = destinos.carregar(CADASTRO_DESTINOS)
        destinos.salvar(cad, caminho)
        self.assertEqual(destinos.carregar(caminho), cad)

    def test_guarda_de_dois_anos(self):
        cad = destinos.vazio()
        cad["colunas"] = {"a": {"nome": "A", "ultimo_uso": "2026-07"},
                          "b": {"nome": "B", "ultimo_uso": "2026-08"},
                          "c": {"nome": "C", "ultimo_uso": None}}
        self.assertEqual(destinos.limpar(cad, "2028-06"), [])
        self.assertEqual(destinos.limpar(cad, "2028-07"), ["A"])
        self.assertEqual(sorted(cad["colunas"]), ["b", "c"])


class TestVinculosConfirmados(unittest.TestCase):
    def test_registrar_e_guarda_de_dois_anos(self):
        caminho = os.path.join(pasta_temp(), "vinculos.json")
        self.assertEqual(vinculos.carregar(caminho), [])
        for mes in ("2026-06", "2026-07", "2026-07", "2026-08"):    # 2026-07 repetido: não duplica
            vinculos.registrar("EMPRESA X", "FULANO DE TAL", mes, caminho=caminho)
        self.assertEqual(len(vinculos.carregar(caminho)), 3)
        self.assertEqual(vinculos.limpar("2028-05", caminho), [])
        apagados = vinculos.limpar("2028-07", caminho)
        self.assertEqual([v["confirmado_em"] for v in apagados], ["2026-06", "2026-07"])
        self.assertEqual([v["confirmado_em"] for v in vinculos.carregar(caminho)], ["2026-08"])

    def test_remover_so_o_que_o_agente_gravou(self):
        caminho = os.path.join(pasta_temp(), "vinculos.json")
        vinculos.registrar("EMPRESA X", "FULANO", "2026-07", observacao="manual", caminho=caminho)
        vinculos.registrar("EMPRESA Y", "FULANO", "2026-07", observacao="agente", caminho=caminho)
        self.assertFalse(vinculos.remover("EMPRESA X", "FULANO", "2026-07", observacao="agente",
                                          caminho=caminho))
        self.assertTrue(vinculos.remover("EMPRESA Y", "FULANO", "2026-07", observacao="agente",
                                         caminho=caminho))
        self.assertEqual([v["nome_extrato"] for v in vinculos.carregar(caminho)], ["EMPRESA X"])
