"""Destaques das mensagens (*negrito*, _itálico_), como no WhatsApp."""

import unittest

from conselho_fiscal.agente.formato import italico, negrito
from tests.apoio import sem_marcas


class TestFormato(unittest.TestCase):
    def test_marca_linha_a_linha_com_espacos_por_fora(self):
        self.assertEqual(negrito("Tudo certo"), "*Tudo certo*")
        self.assertEqual(negrito("  título  \nsegunda"), "  *título*  \n*segunda*")
        self.assertEqual(italico("Confirme.\n\nDepois."), "_Confirme._\n\n_Depois._")

    def test_tira_a_marca_de_dentro(self):
        self.assertEqual(negrito("ODIR *SOCIO"), "*ODIR SOCIO*")
        self.assertEqual(negrito(""), "")

    def test_sem_marcas(self):
        self.assertEqual(sem_marcas("*Tudo certo*: _confirme_. receitas_2026-07.xlsx"),
                         "Tudo certo: confirme. receitas_2026-07.xlsx")
