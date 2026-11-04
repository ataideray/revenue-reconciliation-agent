"""Linha de comando: a escolha da IA do agente."""

import unittest
from unittest import mock

from conselho_fiscal.agente.gemini import Gemini
from conselho_fiscal.cli import escolher_ia, main


class TestEscolherIA(unittest.TestCase):
    def test_padrao_e_o_gemini_com_chave(self):
        with mock.patch("conselho_fiscal.agente.gemini.chave", return_value="k"):
            for escolha in (None, "gemini"):
                ia, erro = escolher_ia(escolha)
                self.assertIsInstance(ia, Gemini)
                self.assertIsNone(erro)
            self.assertEqual(escolher_ia("nenhuma"), (None, None))

    def test_sem_chave(self):
        with mock.patch("conselho_fiscal.agente.gemini.chave", return_value=None):
            with self.assertLogs(level="WARNING") as aviso:
                self.assertEqual(escolher_ia(None), (None, None))     # avisa e segue sem IA
            self.assertIn("Falta a chave do Gemini", aviso.output[0])
            ia, erro = escolher_ia("gemini")                          # pedida: não inicia
            self.assertIsNone(ia)
            self.assertIn("Não iniciei: falta a chave do Gemini", erro)


class TestAgenteNaRede(unittest.TestCase):
    def test_simulador_fora_da_propria_maquina_e_recusado(self):
        with mock.patch("conselho_fiscal.agente.web.servir") as servir, \
                mock.patch("builtins.print") as saida:
            self.assertEqual(main(["agente", "--host", "0.0.0.0"]), 1)
        servir.assert_not_called()
        self.assertIn("Use --sem-simulador", saida.call_args[0][0])
