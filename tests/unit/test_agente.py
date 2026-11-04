"""Agente com dados fictícios: a conversa da tesouraria e do CF.

Os extratos fictícios são .xlsx (sem pdftotext); nos testes, eles passam
pela identificação como se fossem os PDFs dos bancos.
"""

import os
import re
import unittest
from datetime import date
from unittest import mock

from openpyxl import load_workbook

from conselho_fiscal.agente import Agente
from conselho_fiscal.agente import divergencias as dv
from conselho_fiscal.agente.agente import (
    COMO_FUNCIONA,
    mensagem,
    pede_ajuda,
    pede_menu,
    reconhecer_mes,
    sem_saudacao,
    so_confirma,
)
from conselho_fiscal.agente.armazenamento import Armazenamento
from conselho_fiscal.agente.arquivos import Identificacao, identificar, mes_do_periodo
from conselho_fiscal.agente.consultas import cita_mes_corrente, com_mes, so_pedido
from conselho_fiscal.agente.ia import Interpretacao, Pergunta
from conselho_fiscal.cadastros import vinculos
from conselho_fiscal.extratos import exportar_xlsx
from tests.apoio import (
    cadastros_temp,
    conferir_whatsapp,
    opcoes,
    pasta_temp,
    planilha_tesouraria,
    sem_marcas,
)
from tests.unit.test_pipeline_sintetico import transacao


def identificar_teste(caminho, nome):
    """Extratos fictícios em .xlsx fazem o papel dos PDFs dos bancos; o mês
    do período, quando o teste quer, vem no nome ("cora_2026-08.xlsx")."""
    m = re.search(r"\d{4}-\d{2}", nome)
    if nome.startswith("cora"):
        return Identificacao("Cora", mes=m and m.group())
    if nome.startswith("stone"):
        return Identificacao("Stone", mes=m and m.group())
    return identificar(caminho, nome)


class BaseConversa(unittest.TestCase):
    """Julho fictício com 3 divergências, na ordem do extrato:
    LUMITECH (Pix sem recibo; sugestão: recibo 0002 do Ivan), Nair (possível
    devolução) e Ivan (recibo sem Pix; mesma sugestão, do outro lado)."""

    def setUp(self):
        self.pasta = pasta_temp("teste_agente_")
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
        destinos, self.vinculos = cadastros_temp()
        self.arm = Armazenamento(pasta_temp("teste_agente_base_"))
        self.agente = Agente(self.arm, destinos, self.vinculos)
        receber = self.agente.receber          # toda resposta passa pelos limites do WhatsApp
        self.agente.receber = lambda *a, **k: conferir_whatsapp(self, receber(*a, **k))

    def enviar(self, caminho, nome=None):
        with open(caminho, "rb") as f:
            return self.agente.receber("tesouraria", anexo=(nome or os.path.basename(caminho),
                                                           f.read()))

    def enviar_tudo(self):
        self.enviar(self.entradas)
        self.enviar(self.cora)
        return self.enviar(self.stone)

    def clicar(self, resposta, rotulo, papel="tesouraria"):
        b = next(b for b in opcoes(resposta) if b["rotulo"] == rotulo)
        return self.agente.receber(papel, botao=b["id"], rotulo=rotulo)

    def estado(self):
        return self.arm.estado_mes("2026-07")


@mock.patch("conselho_fiscal.agente.agente.identificar", identificar_teste)
class TestConversa(BaseConversa):

    def test_destaques(self):
        """As mensagens guardadas (como saem no WhatsApp) trazem as marcas."""
        r = self.enviar_tudo()
        conversa = [m["texto"] for m in self.agente.conversa("tesouraria") if m["de"] == "agente"]
        lista, pergunta = conversa[-2], conversa[-1]
        self.assertTrue(lista.startswith("✅ *Extrato bancário (2 de 2)*\n\n📊 *Julho/2026 conferido* "
                                         "_(versão 1)_\n3 recibos: *2 batem* com os extratos."))
        # só a contagem: as divergências vêm uma por vez, nas perguntas
        self.assertTrue(lista.endswith("\n\n*3 divergências para explicar.* _Vou perguntar uma "
                                       "por vez; sua resposta vai como nota para o Conselho "
                                       "Fiscal._"))
        self.assertNotIn("LUMITECH", lista)
        # cada Pix já ligado à sua sugestão (2026-10-28); sem critério
        self.assertEqual(pergunta, "\n".join([
            "*Divergência 1 de 3 — LUMITECH*",
            "Entrou *R$ 150,00* no banco *sem recibo*.",
            "",
            "*Pode ser que pague um recibo de IVAN TRIGO PALHA LUAR:*",
            "1) Pix de R$ 150,00 (05/07/2026, Cora) → *recibo 0002-2026*",
            "",
            "_Toque em \"Sim\" se for isso, ou escreva a explicação._"]))
        self.assertEqual(r[1]["texto"], sem_marcas(pergunta))
        self.assertEqual([b["rotulo"] for b in r[1]["botoes"]],
                         ["Sim: recibo 0002", "Não", "Responder depois"])

    def test_nao_recusa_a_sugestao_nas_duas_pontas(self):
        r = self.enviar_tudo()
        r = self.clicar(r[1], "Não")
        self.assertEqual(r[0]["texto"], "Certo, não é isso. Escreva a explicação: ela vai "
                                        "como nota para o Conselho Fiscal.")
        self.assertEqual(vinculos.carregar(self.vinculos), [])
        self.assertEqual(self.estado()["fila"][0], self.estado()["divergencias"][0]["id"])
        # a outra ponta (o recibo do Ivan) também perde a sugestão
        r = self.clicar(r[0], "Responder depois")           # NAIR
        r = self.clicar(r[0], "Responder depois")
        self.assertIn("IVAN", r[0]["texto"])
        self.assertNotIn("Pode ser que", r[0]["texto"])
        self.assertNotIn("Não", [b["rotulo"] for b in r[0]["botoes"]])
        self.assertEqual(len(self.estado()["recusadas"]), 1)

    def test_nao_escrito_recusa_a_sugestao(self):
        self.enviar_tudo()
        r = self.agente.receber("tesouraria", texto="Não")
        self.assertIn("Certo, não é isso.", r[0]["texto"])
        self.assertEqual(vinculos.carregar(self.vinculos), [])

    def test_pede_o_que_falta_e_recusa_extrato_em_xlsx(self):
        r = self.agente.receber("tesouraria", anexo=("Extrato Stone.xlsx", b"x"))
        self.assertIn("precisa vir no PDF do banco", r[0]["texto"])
        self.assertEqual(os.listdir(self.arm.base / "envio"), [])     # descartado
        r = self.enviar(self.entradas)
        self.assertEqual(r[0]["texto"], "✅ Registro de receitas da tesouraria — julho/2026\n"
                         "Falta: 2 extratos bancários (PDF).")

    def test_fluxo_completo_ate_o_cf(self):
        r = self.enviar_tudo()
        self.assertIn("3 recibos: 2 batem", r[0]["texto"])           # resultado e lista
        self.assertIn("3 divergências para explicar", r[0]["texto"])
        self.assertIn("LUMITECH", r[1]["texto"])

        # CF pede antes da hora
        r_cf = self.agente.receber("cf", texto="pode me enviar julho?")
        self.assertIn("ainda não foi fechado: está com a tesouraria", r_cf[0]["texto"])

        # confirmar o vínculo explica as duas pontas (LUMITECH e Ivan)
        r = self.clicar(r[1], "Sim: recibo 0002")
        self.assertIn("Isso também resolve a divergência de IVAN TRIGO PALHA LUAR (recibo sem Pix: R$ 150,00)", r[1]["texto"])
        self.assertIn("NAIR", r[2]["texto"])
        self.assertEqual([v["nome_extrato"] for v in vinculos.carregar(self.vinculos)],
                         ["LUMITECH"])

        # "sim" com uma única sugestão confirma a devolução
        r = self.agente.receber("tesouraria", texto="Sim")
        self.assertIn("foi devolvido", r[0]["texto"])
        self.assertIn("Tudo certo: julho/2026 está pronto. As 3 divergência(s) têm nota.",
                      r[-1]["texto"])
        self.assertEqual(self.estado()["situacao"], "pronto")

        # a planilha final tem as notas
        planilha = self.arm.caminho(r[-1]["anexos"][0]["caminho"])
        notas = {row[0]: row[7] for row in load_workbook(planilha)["Divergências"]
                 .iter_rows(values_only=True) if row[0]}
        self.assertIn("pagou o recibo 0002-2026", notas["IVAN TRIGO PALHA LUAR"])
        self.assertIn("foi devolvido", notas["NAIR DE CANELA NEVE SERENO"])
        status = {row[1]: row[7] for row in load_workbook(planilha)["Conferência por Pessoa"]
                  .iter_rows(min_row=2, values_only=True)}
        self.assertEqual(status["NAIR DE CANELA NEVE SERENO"],
                         "Divergência de valor - nota da tesouraria na aba Divergências")
        self.assertEqual(status["ILA NADIA JASMIM"], "OK")
        principal = load_workbook(planilha)["Receitas (reordenada)"]
        iv = [c.value for c in principal[1]].index("Sugestão de vínculo")
        self.assertIn("pagou o recibo 0002-2026", next(
            row[iv] for row in principal.iter_rows(min_row=2, values_only=True)
            if row[0] == "0002-2026"))                     # a nota no lugar da sugestão

        # CF pede pelo botão do menu e recebe o pacote
        menu = self.agente.receber("cf", texto="oi")[0]
        r = self.clicar(menu, "Julho/2026", papel="cf")
        self.assertEqual([a["nome"] for a in r[0]["anexos"]],
                         ["receitas_2026-07.xlsx", "entradas.xlsx", "cora.xlsx", "stone.xlsx"])
        self.assertIn("3 recibos, 2 batem com os extratos. 3 divergência(s)", r[0]["texto"])
        self.assertEqual(self.estado()["situacao"], "entregue")

    def test_cf_pede_mes_ainda_nao_fechado(self):
        r = self.agente.receber("cf", texto="me envie agosto de 2026")
        self.assertEqual(r[0]["texto"], "Agosto/2026 ainda não foi fechado: a tesouraria ainda "
                                        "não enviou os arquivos.")
        self.assertIn("Ainda não há mês conferido pela tesouraria", r[1]["texto"])
        self.enviar(self.entradas)                                 # julho: só a planilha
        r = self.agente.receber("cf", texto="julho de 2026")
        self.assertIn("começou a enviar os arquivos, mas ainda faltam 2", r[0]["texto"])

    def test_avisa_destino_novo(self):
        planilha_tesouraria(self.entradas, [
            ("02/07/2026", "0001-2026", "Ila Nadia Jasmim",
             [("Anuidade", 100), ("Rifa de Natal", 20)]),
        ], {"Total de Receitas": 120, "Recibos Emitidos": 1,
            "Recibos de Sócios": 1, "Recibos de Não Sócios": 0})
        r = self.enviar_tudo()
        self.assertIn("Destinos novos (viraram colunas na planilha): Rifa de Natal",
                      r[0]["texto"])

    def test_nota_livre_responder_depois_e_botao_antigo(self):
        r = self.enviar_tudo()
        pergunta_vm = r[1]
        r = self.clicar(pergunta_vm, "Responder depois")
        self.assertIn("NAIR", r[0]["texto"])
        r = self.clicar(pergunta_vm, "Sim: recibo 0002")                 # botão de pergunta anterior
        self.assertIn("pergunta anterior", r[0]["texto"])
        r = self.agente.receber("tesouraria", texto="Valor devolvido por engano.")
        self.assertEqual(r[0]["texto"],
                         "✅ Anotado para NAIR DE CANELA NEVE SERENO: Valor devolvido por "
                         "engano.")
        self.assertEqual(self.estado()["notas"]["DIV-NAIR-DE-CANELA-NEVE-SERENO"]["texto"],
                         "Valor devolvido por engano.")
        self.assertEqual(self.estado()["fila"], ["DIV-IVAN-TRIGO-PALHA-LUAR", "DIV-LUMITECH"])

    def test_corrigir_depois_da_entrega(self):
        r = self.enviar_tudo()
        self.clicar(r[1], "Sim: recibo 0002")                            # LUMITECH e Ivan
        self.agente.receber("tesouraria", texto="Sim")               # Nair
        entregue = self.agente.receber("cf", texto="julho")[0]["anexos"][0]["caminho"]
        nota_nair = self.estado()["notas"]["DIV-NAIR-DE-CANELA-NEVE-SERENO"]

        r = self.agente.receber("tesouraria", texto="Corrigir a nota da lumi")
        self.assertIn("Reabri LUMITECH.\nDesfiz:\n• Confirmado pela tesouraria", r[0]["texto"])
        self.assertIn("Isso também reabre: IVAN TRIGO PALHA LUAR.", r[0]["texto"])
        self.assertIn("já recebeu este mês", r[0]["texto"])
        self.assertIn("LUMITECH", r[1]["texto"])
        est = self.estado()
        self.assertEqual((est["situacao"], est["fila"], est["confirmadas"][0]["tipo"]),
                         ("aguardando_respostas", ["DIV-LUMITECH", "DIV-IVAN-TRIGO-PALHA-LUAR"],
                          "devolucao"))
        self.assertEqual(est["notas"]["DIV-NAIR-DE-CANELA-NEVE-SERENO"], nota_nair)
        self.assertEqual(vinculos.carregar(self.vinculos), [])        # saiu do cadastro

        r = self.clicar(r[1], "Sim: recibo 0002")                        # responde de novo
        self.assertIn("Isso também resolve a divergência de IVAN TRIGO PALHA LUAR (recibo sem Pix: R$ 150,00)", r[1]["texto"])
        self.assertIn("precisa pedir de novo", r[-1]["texto"])
        self.assertEqual(self.estado()["situacao"], "pronto")
        self.assertEqual(len(vinculos.carregar(self.vinculos)), 1)
        # a planilha que o CF recebeu é uma cópia fixa, separada da regravada
        self.assertTrue(self.arm.caminho(entregue).exists())
        self.assertNotEqual(entregue, self.estado()["versoes"][-1]["planilha"])

    def test_corrigir_pela_lista_e_sem_nota(self):
        r = self.enviar_tudo()
        self.clicar(r[1], "Sim: recibo 0002")                            # LUMITECH e Ivan
        r = self.agente.receber("tesouraria", texto="corrigir")
        self.assertEqual([b["rotulo"] for b in r[0]["botoes"]],
                         ["LUMITECH", "IVAN TRIGO PALHA LU…"])     # botão: até 20 caracteres
        self.assertIn("2. IVAN TRIGO PALHA LUAR", r[0]["texto"])     # o nome inteiro no texto
        r = self.clicar(r[0], "IVAN TRIGO PALHA LU…")
        self.assertIn("Reabri IVAN TRIGO PALHA LUAR.", r[0]["texto"])
        self.assertIn("Isso também reabre: LUMITECH.", r[0]["texto"])
        self.assertNotIn("já recebeu", r[0]["texto"])
        self.assertEqual(self.estado()["fila"], ["DIV-IVAN-TRIGO-PALHA-LUAR", "DIV-LUMITECH",
                                                 "DIV-NAIR-DE-CANELA-NEVE-SERENO"])
        # divergência ainda sem nota: só passa para a frente da fila
        r = self.agente.receber("tesouraria", texto="corrigir nair")
        self.assertIn("ainda está sem nota", r[0]["texto"])
        self.assertEqual(self.estado()["fila"][0], "DIV-NAIR-DE-CANELA-NEVE-SERENO")

    def test_corrigir_no_meio_da_frase(self):
        r = self.enviar_tudo()
        self.clicar(r[1], "Sim: recibo 0002")                            # LUMITECH e Ivan
        r = self.agente.receber("tesouraria", texto="Me confundi, quero corrigir Lumitech")
        self.assertIn("Reabri LUMITECH", r[0]["texto"])
        self.assertEqual(self.estado()["fila"][0], "DIV-LUMITECH")
        # sem nome de divergência depois do verbo, é explicação, não pedido
        self.agente.receber("tesouraria", texto="Sim")                   # confirma de novo
        self.assertEqual(self.estado()["fila"], ["DIV-NAIR-DE-CANELA-NEVE-SERENO"])
        self.agente.receber("tesouraria", texto="vamos corrigir o recibo no sistema")
        self.assertIn("DIV-NAIR-DE-CANELA-NEVE-SERENO", self.estado()["notas"])

    def test_corrigir_nome_com_varias_divergencias(self):
        """Um nome com uma divergência por recibo: a lista só com as dele."""
        est = {"mes": "2026-06", "notas": {"G1": {}, "G2": {}, "L": {}}, "divergencias": [
            {"id": "G1", "pessoa": "HELIO SABIA", "recibo": "0560-2026"},
            {"id": "G2", "pessoa": "HELIO SABIA", "recibo": "0706-2026"},
            {"id": "L", "pessoa": "EVA OLMO"}]}
        for busca in ("a nota de Helio", "helio"):
            r = self.agente._corrigir(est, busca=[busca])
            self.assertEqual([b["id"] for b in r[0]["botoes"]], ["corrigir:G1", "corrigir:G2"])
            self.assertIn("1. *HELIO SABIA (recibo 0560-2026)*\n2. *HELIO SABIA (recibo "
                          "0706-2026)*", r[0]["texto"])

    def test_reenvio(self):
        r = self.enviar_tudo()
        self.clicar(r[1], "Sim: recibo 0002")
        self.agente.receber("tesouraria", texto="Sim")
        self.agente.receber("cf", texto="julho")

        # os mesmos arquivos: nada muda
        r = self.enviar_tudo()
        self.assertIn("iguais aos da versão 1", r[-2]["texto"])
        self.assertEqual(self.estado()["versao"], 1)

        # entradas regravadas (outro arquivo, mesmo conteúdo): versão 2, notas mantidas
        wb = load_workbook(self.entradas)
        wb.save(self.entradas)
        r = self.enviar_tudo()
        self.assertIn("(versão 2, mês reaberto)", r[0]["texto"])
        self.assertIn("Tudo certo", r[-1]["texto"])
        self.assertEqual(self.estado()["situacao"], "pronto")
        self.assertEqual(len(self.estado()["notas"]), 3)


@mock.patch("conselho_fiscal.agente.agente.identificar", identificar_teste)
class TestReenvioParcial(BaseConversa):
    """Correção de um arquivo só, no meio das respostas (decisão de 2026-10-13)."""

    def test_usa_os_outros_da_versao_atual(self):
        r = self.enviar_tudo()
        self.clicar(r[1], "Sim: recibo 0002")                          # LUMITECH e Ivan
        corrigida = planilha_tesouraria(os.path.join(self.pasta, "entradas_corrigida.xlsx"), [
            ("02/07/2026", "0001-2026", "Ila Nadia Jasmim", [("Anuidade", 120)]),
            ("03/07/2026", "0002-2026", "Ivan Trigo Palha Luar", [("Anuidade", 150)]),
            ("04/07/2026", "0003-2026", "Nair de Canela Neve", [("Café", 330)]),
        ], {"Total de Receitas": 600, "Recibos Emitidos": 3,
            "Recibos de Sócios": 3, "Recibos de Não Sócios": 0})
        r = self.enviar(corrigida)
        self.assertIn("Falta: 2 extratos bancários (PDF).", r[0]["texto"])
        self.assertIn("posso usar os outros da versão 1 de julho/2026", r[0]["texto"])
        oferta = r[0]

        r = self.clicar(oferta, "Usar os da versão 1")
        self.assertEqual(r[0]["texto"], "Usei da versão 1: \"cora.xlsx\", \"stone.xlsx\".")
        self.assertIn("versão 2", r[1]["texto"])
        est = self.estado()
        self.assertEqual(est["versao"], 2)
        self.assertIn("DIV-LUMITECH", est["notas"])                  # não mudou: nota mantida
        self.assertEqual(self.arm.estado_geral()["envio"], {})
        # os arquivos copiados ficam na versão 2; os da versão 1 continuam lá
        v1, v2 = est["versoes"]
        self.assertTrue(self.arm.caminho(v1["arquivos"]["Cora"]["caminho"]).exists())
        self.assertEqual(v1["sha256"]["Cora"], v2["sha256"]["Cora"])
        self.assertNotEqual(v1["sha256"]["entradas"], v2["sha256"]["entradas"])

        r = self.clicar(oferta, "Usar os da versão 1")              # botão antigo
        self.assertIn("pergunta anterior", r[0]["texto"])

    def test_extrato_sozinho_usa_o_mes_em_conversa(self):
        self.enviar_tudo()
        r = self.enviar(self.cora)
        self.assertIn("posso usar os outros da versão 1 de julho/2026", r[0]["texto"])
        r = self.clicar(r[0], "Usar os da versão 1")
        self.assertIn("iguais aos da versão 1", r[1]["texto"])     # nada mudou

    def test_extrato_de_outro_mes_nao_oferece_os_do_mes_anterior(self):
        """Com o mês no período do PDF, o extrato de agosto é envio novo, não
        correção de julho (2026-10-23)."""
        self.enviar_tudo()
        r = self.enviar(self.cora, "cora_2026-08.xlsx")
        self.assertEqual(r[0]["texto"], "✅ Extrato bancário (1 de 2) — agosto/2026\n"
                         "Falta: o registro de receitas da tesouraria (.xlsx), 1 extrato bancário "
                         "(PDF).")
        self.assertEqual(opcoes(r[0]), [])
        r = self.enviar(self.stone, "stone_2026-08.xlsx")
        self.assertEqual(opcoes(r[0]), [])
        self.assertIn("Extrato bancário (2 de 2) — agosto/2026", r[0]["texto"])

    def test_extrato_do_mes_em_conversa_ainda_oferece(self):
        self.enviar_tudo()
        r = self.enviar(self.cora, "cora_2026-07.xlsx")
        self.assertIn("posso usar os outros da versão 1 de julho/2026", r[0]["texto"])

    def test_descarta_o_que_esperava_de_outro_mes(self):
        self.enviar(self.cora, "cora_2026-06.xlsx")
        r = self.enviar(self.stone, "stone_2026-07.xlsx")
        self.assertIn("Descartei o que esperava de outro mês: \"cora_2026-06.xlsx\" "
                      "(junho/2026).", r[0]["texto"])
        self.assertIn("Falta: o registro de receitas da tesouraria (.xlsx), 1 extrato bancário (PDF).",
                      r[0]["texto"])
        self.assertEqual(len(os.listdir(self.arm.base / "envio")), 1)
        self.enviar(self.entradas)
        r = self.enviar(self.cora, "cora_2026-07.xlsx")
        self.assertIn("(versão 1)", r[0]["texto"])                # julho completo: conferiu

    def test_tres_arquivos_juntos(self):
        anexos = [(os.path.basename(c), open(c, "rb").read())
                  for c in (self.entradas, self.cora, self.stone)]
        r = conferir_whatsapp(self, self.agente.receber_arquivos(anexos, autor="Ila"))
        self.assertTrue(r[0]["texto"].startswith(
            "✅ Registro de receitas da tesouraria — julho/2026\n✅ Extrato bancário (1 de 2)\n"
            "✅ Extrato bancário (2 de 2)\n\n"
            "📊 Julho/2026 conferido"))
        self.assertIn("Divergência 1 de 3", r[1]["texto"])
        self.assertEqual(len(r), 2)
        entrada = self.agente.conversa("tesouraria")[0]
        self.assertEqual(([a["nome"] for a in entrada["anexos"]], entrada["autor"]),
                         (["entradas.xlsx", "cora.xlsx", "stone.xlsx"], "Ila"))

    def test_dois_arquivos_juntos_dizem_o_que_falta_uma_vez(self):
        anexos = [(os.path.basename(c), open(c, "rb").read()) for c in (self.cora, self.stone)]
        r = conferir_whatsapp(self, self.agente.receber_arquivos(anexos))
        self.assertEqual([m["texto"] for m in r], [
            "✅ Extrato bancário (1 de 2)\n✅ Extrato bancário (2 de 2)\nFalta: o registro de receitas "
            "da tesouraria (.xlsx)."])

    def test_mes_sem_conferencia_nao_oferece(self):
        r = self.enviar(self.entradas)
        self.assertEqual(opcoes(r[0]), [])


class DataFixa(date):
    """Hoje é 27/10/2026, para os testes que dependem do mês atual."""

    @classmethod
    def today(cls):
        return cls(2026, 10, 27)


class IAFalsa:
    """Interpretador falso: devolve as interpretações (ou erros) na ordem dada
    e guarda os contextos recebidos. Redige as `notas` dadas, na ordem; sem
    elas, não redige. Entende as `perguntas` do CF dadas e responde com as
    `respostas_cf`, na ordem; sem elas, não responde."""
    nome = "IA falsa"

    def __init__(self, *respostas, notas=(), perguntas=(), respostas_cf=(), comandos=()):
        self.comandos, self.contextos_comando = list(comandos), []
        self.respostas, self.contextos = list(respostas), []
        self.notas, self.contextos_nota = list(notas), []
        self.perguntas, self.contextos_pergunta = list(perguntas), []
        self.respostas_cf, self.contextos_resposta = list(respostas_cf), []

    def interpretar(self, contexto):
        self.contextos.append(contexto)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def redigir(self, contexto):
        self.contextos_nota.append(contexto)
        r = self.notas.pop(0) if self.notas else ""
        if isinstance(r, Exception):
            raise r
        return r

    def entender(self, contexto):
        self.contextos_pergunta.append(contexto)
        r = self.perguntas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def comando(self, contexto):
        self.contextos_comando.append(contexto)
        return self.comandos.pop(0) if self.comandos else "nenhum"

    def responder(self, contexto):
        self.contextos_resposta.append(contexto)
        r = self.respostas_cf.pop(0) if self.respostas_cf else ""
        if isinstance(r, Exception):
            raise r
        return r


@mock.patch("conselho_fiscal.agente.agente.identificar", identificar_teste)
class TestInterpretacao(BaseConversa):
    """Texto livre passando pelo interpretador falso."""

    def com_ia(self, *respostas, notas=()):
        self.agente.ia = IAFalsa(*respostas, notas=notas)
        return self.agente.ia

    def texto(self, t):
        return self.agente.receber("tesouraria", texto=t)

    def vinculos_gravados(self):
        return [v["nome_extrato"] for v in vinculos.carregar(self.vinculos)]

    def test_confirmacao_pelo_texto_so_vale_com_o_clique(self):
        self.enviar_tudo()
        ia = self.com_ia(Interpretacao(confirmar=(1,), explicacao="a empresa é do Ivan"))
        r = self.texto("a 1 tá certa, a empresa é do Ivan")
        self.assertIn("Entendi:\n• confirma a 1:", r[0]["texto"])
        self.assertIn("• nota: a empresa é do Ivan", r[0]["texto"])
        self.assertEqual(self.vinculos_gravados(), [])                 # nada gravado ainda
        ctx = ia.contextos[0]
        self.assertEqual((ctx.divergencia["pessoa"], len(ctx.sugestoes), ctx.texto),
                         ("LUMITECH", 1, "a 1 tá certa, a empresa é do Ivan"))

        r = self.clicar(r[0], "Está certo")
        self.assertIn("Isso também resolve a divergência de IVAN TRIGO PALHA LUAR (recibo sem Pix: R$ 150,00)", r[1]["texto"])
        self.assertEqual(self.vinculos_gravados(), ["LUMITECH"])
        nota = self.estado()["notas"]["DIV-LUMITECH"]
        self.assertTrue(nota["texto"].startswith("Confirmado pela tesouraria"))
        self.assertTrue(nota["texto"].endswith("a empresa é do Ivan"))
        self.assertEqual((nota["texto_original"], nota["interpretado_por"]),
                         ("a 1 tá certa, a empresa é do Ivan", "IA falsa"))
        self.assertNotIn("pendente", self.estado())

    def test_resposta_que_so_confirma_nao_vira_nota(self):
        # avaliação da IA (2026-10-29): "as duas estão certas" ia parar no fim da nota
        self.enviar_tudo()
        ia = self.com_ia(Interpretacao(confirmar=(1,), explicacao="as duas estão certas"),
                         notas=["Nota reescrita."])
        r = self.texto("as duas estão certas")
        self.assertIn("Entendi:\n• confirma a 1:", r[0]["texto"])
        self.assertNotIn("nota", r[0]["texto"])
        self.assertEqual(ia.contextos_nota, [])                     # nem pede a redação
        self.clicar(r[0], "Está certo")
        self.assertFalse(any("as duas" in n["texto"] for n in self.estado()["notas"].values()))

    def test_so_confirma(self):
        for t in ("exatamente", "as duas estão certas", "a 1 e a 2", "é essa mesmo", "Isso!"):
            self.assertTrue(so_confirma(t), t)
        for t in ("é a esposa dele", "não, as duas estão erradas", "a 1, foi devolvido", ""):
            self.assertFalse(so_confirma(t), t)

    def test_sim_escrito_vale_o_clique(self):
        # no simulador (2026-10-09): "isso" escrito no lugar do clique confirmava a
        # sugestão direto e perdia a explicação do "Entendi"
        self.enviar_tudo()
        self.com_ia(Interpretacao(confirmar=(1,), explicacao="é a empresa do Ivan"),
                    Interpretacao(confirmar=(1,), explicacao="é a empresa do Ivan"))
        self.texto("sim, a empresa é do Ivan")       # fora da regra fixa: passa pela IA
        r = self.texto("Isso!")
        self.assertIn("Isso também resolve a divergência de IVAN TRIGO PALHA LUAR (recibo sem Pix: R$ 150,00)", r[1]["texto"])
        self.assertTrue(self.estado()["notas"]["DIV-LUMITECH"]["texto"]
                        .endswith("é a empresa do Ivan"))

        # e "não" escrito vale o "Não foi isso"
        self.texto("a 1, foi devolvido")
        r = self.texto("não")
        self.assertIn("Desconsiderei", r[0]["texto"])
        self.assertNotIn("DIV-NAIR-DE-CANELA-NEVE-SERENO", self.estado()["notas"])

    def test_nao_foi_isso_desconsidera(self):
        self.enviar_tudo()
        self.com_ia(Interpretacao(confirmar=(1,)))
        r = self.texto("acho que a 1")
        r = self.clicar(r[0], "Não foi isso")
        self.assertIn("Desconsiderei", r[0]["texto"])
        self.assertIn("LUMITECH", r[1]["texto"])                    # a mesma pergunta
        self.assertEqual(self.vinculos_gravados(), [])
        self.assertEqual(self.estado()["notas"], {})

    def test_numero_inexistente_pede_de_novo(self):
        self.enviar_tudo()
        self.com_ia(Interpretacao(confirmar=(5,)))
        r = self.texto("a 5")
        self.assertIn("Não entendi qual sugestão", r[0]["texto"])
        self.assertIn("LUMITECH", r[1]["texto"])
        self.assertEqual(self.estado()["notas"], {})

    def test_sim_sozinho_nunca_vira_nota(self):
        # "sim" a várias sugestões, com a IA sem confirmar nada e achando que explicou:
        # sem esta trava, "sim" ia para a planilha como a nota
        self.enviar_tudo()
        self.com_ia(Interpretacao(suficiente=True))
        with mock.patch.object(dv, "opcoes", return_value=[]):
            r = self.texto("Sim")
        self.assertIn("Não entendi o que está certo", r[0]["texto"])
        self.assertIn("LUMITECH", r[1]["texto"])                    # a mesma pergunta
        self.assertEqual(self.estado()["notas"], {})

    def test_resposta_insuficiente(self):
        self.enviar_tudo()
        self.com_ia(Interpretacao(suficiente=False, pergunta="De quem é o Pix?"),
                    Interpretacao(suficiente=False))
        r = self.texto("não lembro")
        self.assertEqual(r[0]["texto"], "De quem é o Pix?")
        self.assertEqual([b["rotulo"] for b in r[0]["botoes"]],
                         ["Registrar assim", "Responder depois"])
        self.assertEqual(self.estado()["notas"], {})

        r = self.texto("não sei")                # sem pergunta da IA: a padrão
        self.assertIn("Isso ainda não explica a divergência de LUMITECH", r[0]["texto"])
        r = self.clicar(r[0], "Registrar assim")
        self.assertEqual(r[0]["texto"], "✅ Anotado para LUMITECH: não sei")
        self.assertEqual(self.estado()["notas"]["DIV-LUMITECH"]["texto"], "não sei")

    def test_adiar(self):
        self.enviar_tudo()
        self.com_ia(Interpretacao(adiar=True, suficiente=False))
        r = self.texto("vou conferir com o banco")
        self.assertIn("volto nela no fim", r[0]["texto"])
        self.assertIn("NAIR", r[1]["texto"])
        self.assertEqual(self.estado()["fila"][-1], "DIV-LUMITECH")

    def test_adiar_a_ultima(self):
        r = self.enviar_tudo()
        self.clicar(r[1], "Sim: recibo 0002")                    # LUMITECH e Ivan: sobra a Nair
        self.com_ia(Interpretacao(adiar=True, suficiente=False, pergunta="De quem é?"))
        r = self.texto("vou ver com o banco")
        self.assertEqual(r[0]["texto"], "Combinado. É a última divergência: quando tiver a "
                                        "resposta, é só escrever aqui.")
        self.assertEqual([b["rotulo"] for b in r[0]["botoes"]], ["Registrar assim"])

    def test_ia_fora_do_ar_pergunta_antes_de_gravar(self):
        # simulador (2026-10-13): "nome do recibo errado, é marinilda" virou a nota sem
        # confirmar o vínculo, porque o Gemini não respondeu
        self.enviar_tudo()
        self.com_ia(TimeoutError("sem resposta"),
                    Interpretacao(confirmar=(1,), explicacao="é do Ivan"))
        r = self.texto("é do Ivan")
        self.assertIn("Não consegui interpretar", r[0]["texto"])
        self.assertEqual([b["rotulo"] for b in r[0]["botoes"]],
                         ["Tentar de novo", "Registrar assim", "Responder depois"])
        self.assertEqual(self.estado()["notas"], {})                  # nada gravado

        r = self.clicar(r[0], "Tentar de novo")                       # agora a IA responde
        self.assertIn("Entendi:\n• confirma a 1:", r[0]["texto"])
        self.assertEqual(self.agente.ia.contextos[1].texto, "é do Ivan")

    def test_ia_fora_do_ar_registrar_assim(self):
        self.enviar_tudo()
        self.com_ia(TimeoutError("sem resposta"))
        r = self.texto("Pix de um cliente da loja")
        r = self.clicar(r[0], "Registrar assim")
        self.assertEqual(r[0]["texto"], "✅ Anotado para LUMITECH: Pix de um cliente da loja")
        nota = self.estado()["notas"]["DIV-LUMITECH"]
        self.assertEqual((nota["interpretado_por"], nota["erro_ia"]), ("sem IA", "sem resposta"))

    def test_clique_antigo_de_entendi(self):
        self.enviar_tudo()
        self.com_ia(Interpretacao(confirmar=(1,)), Interpretacao(explicacao="x"))
        entendi = self.texto("a 1")[0]
        self.texto("na verdade é de um cliente")                   # texto novo: vira a nota
        r = self.clicar(entendi, "Está certo")
        self.assertIn("pergunta anterior", r[0]["texto"])
        self.assertEqual(self.vinculos_gravados(), [])


@mock.patch("conselho_fiscal.agente.agente.identificar", identificar_teste)
class TestPedidosSimples(BaseConversa):
    """Saudação antes do pedido e pedidos que só a IA reconhece (2026-10-26)."""

    def test_saudacao_sai_da_resposta(self):
        self.enviar_tudo()
        ia = self.agente.ia = IAFalsa(Interpretacao(explicacao="é a empresa do Ivan"))
        self.agente.receber("tesouraria", texto="Bom dia, Elo! É a empresa do Ivan")
        self.assertEqual(ia.contextos[0].texto, "É a empresa do Ivan")
        self.assertIn("Bom dia, Elo! É a empresa do Ivan",          # o histórico guarda tudo
                      [m["texto"] for m in self.agente.conversa("tesouraria")])

    def test_comando_no_meio_das_perguntas_nao_vira_nota(self):
        self.enviar_tudo()
        self.agente.ia = IAFalsa(Interpretacao(explicacao="me mostra as opções",
                                               suficiente=False, comando="menu"))
        r = self.agente.receber("tesouraria", texto="me mostra as opções")
        self.assertIn("Você está como Tesouraria", r[0]["texto"])
        self.assertEqual(self.estado()["notas"], {})

    def test_comando_fora_das_perguntas(self):
        ia = self.agente.ia = IAFalsa(comandos=["ajuda"])
        r = self.agente.receber("tesouraria", texto="não sei mexer nisso")
        self.assertTrue(r[0]["texto"].startswith("Como o Elo funciona"))
        self.assertEqual(ia.contextos_comando[0].papel, "tesouraria")
        self.agente.ia = IAFalsa()                                  # "nenhum": não entendi
        r = self.agente.receber("tesouraria", texto="xyz")
        self.assertTrue(r[0]["texto"].startswith("Não entendi."))

    def test_falha_da_ia_no_comando_cai_no_nao_entendi(self):
        self.agente.ia = IAFalsa()
        with mock.patch.object(self.agente.ia, "comando", side_effect=RuntimeError("503")):
            r = self.agente.receber("tesouraria", texto="xyz")
        self.assertTrue(r[0]["texto"].startswith("Não entendi."))

    def test_troca_pedida_ao_cf_vai_para_o_canal(self):
        self.agente.ia = IAFalsa(perguntas=[Pergunta("trocar_tesouraria")])
        r = self.agente.receber("cf", texto="quero entrar como a turma do caixa")
        self.assertEqual(r[0]["trocar_papel"], "tesouraria")
        self.assertIn("Você está como Conselho Fiscal", r[0]["texto"])


@mock.patch("conselho_fiscal.agente.agente.identificar", identificar_teste)
class TestNotaReescrita(BaseConversa):
    """A nota reescrita para o CF, aprovada pela tesouraria (decisão de 2026-10-09)."""

    def responder(self, *notas):
        """Envia os arquivos (pergunta da LUMITECH, uma sugestão) e responde por
        texto; a IA falsa redige as `notas`."""
        self.setUp()
        self.r = self.enviar_tudo()
        self.agente.ia = IAFalsa(Interpretacao(explicacao="cliente da loja"), notas=notas)
        return self.agente.receber("tesouraria", texto="Pix de um cliente da loja")

    def nota(self):
        return self.estado()["notas"]["DIV-LUMITECH"]

    def vinculos_gravados(self):
        return [v["nome_extrato"] for v in vinculos.carregar(self.vinculos)]

    def test_relacao_simples_passa_direto(self):
        """ "Sim, x é a empresa/esposa… de y": confirma e anota sem a IA, sem
        "Entendi" e sem revisão (2026-10-28)."""
        self.r = self.enviar_tudo()
        self.agente.ia = IAFalsa()            # interpretar ou redigir levantaria erro
        r = self.agente.receber("tesouraria", texto="Sim, a Lumitech é a empresa do Ivan")
        self.assertIn("Anotado:", r[0]["texto"])
        self.assertNotIn("Entendi", r[0]["texto"])
        self.assertIn("NAIR", r[-1]["texto"])                         # direto para a próxima
        self.assertEqual(self.agente.ia.contextos, [])
        self.assertEqual(self.agente.ia.contextos_nota, [])
        nota = self.nota()
        self.assertTrue(nota["texto"].endswith("Segundo a tesouraria, LUMITECH é a empresa de "
                                               "IVAN TRIGO PALHA LUAR."))
        self.assertEqual(nota["interpretado_por"], "regra")
        self.assertEqual(self.estado()["revisar"], [])
        self.assertEqual(self.vinculos_gravados(), ["LUMITECH"])

    def test_relacao_com_outro_nome_vai_para_a_ia(self):
        self.r = self.enviar_tudo()
        self.agente.ia = IAFalsa(Interpretacao(confirmar=(1,), explicacao="empresa da Noeli"))
        r = self.agente.receber("tesouraria", texto="Sim, é a empresa da Noeli")
        self.assertEqual(len(self.agente.ia.contextos), 1)
        self.assertIn("Entendi:", r[0]["texto"])

    def test_esta_certo(self):
        r = self.responder("Segundo a tesouraria, o Pix de R$ 150,00 é de um cliente da loja.")
        self.assertEqual(r[0]["texto"], "✅ Anotado para LUMITECH: Pix de um cliente da loja")
        self.assertIn("Nota para o Conselho Fiscal — LUMITECH:\nSegundo a tesouraria", r[1]["texto"])
        self.assertEqual(len(r), 2)                       # a próxima pergunta espera
        ctx = self.agente.ia.contextos_nota[0]
        self.assertEqual((ctx.divergencia["id"], ctx.respostas),
                         ("DIV-LUMITECH", ["Pix de um cliente da loja"]))
        self.assertEqual(self.estado()["situacao"], "aguardando_respostas")

        r = self.clicar(r[1], "Está certo")
        self.assertEqual(r[0]["texto"], "Nota de LUMITECH registrada.")
        self.assertIn("NAIR", r[1]["texto"])             # agora sim, a próxima
        nota = self.nota()
        self.assertTrue(nota["texto"].startswith("Segundo a tesouraria"))
        self.assertEqual((nota["nota_montada"], nota["redacao"], nota["redigida_por"]),
                         ("Pix de um cliente da loja", "aprovada", "IA falsa"))
        self.assertEqual(self.estado()["revisar"], [])

    def test_manter_a_original_ou_escrever(self):
        r = self.responder("Nota reescrita.")
        r = self.clicar(r[1], "Manter a original")
        self.assertEqual((self.nota()["texto"], self.nota()["redacao"]),
                         ("Pix de um cliente da loja", "original"))

        self.responder("Nota reescrita.")
        self.agente.receber("tesouraria", texto="não")             # "não" = manter
        self.assertEqual(self.nota()["redacao"], "original")

        self.responder("Nota reescrita.")
        r = self.agente.receber("tesouraria", texto="Pix de cliente da loja, sem recibo.")
        self.assertEqual(r[0]["texto"], "Nota de LUMITECH registrada.")
        self.assertEqual((self.nota()["texto"], self.nota()["redacao"]),
                         ("Pix de cliente da loja, sem recibo.", "escrita pela tesouraria"))

    def test_sem_ia_segue_direto(self):
        r = self.responder("")                                       # sem IA: não redige
        self.assertIn("NAIR", r[1]["texto"])
        self.assertEqual(self.estado()["revisar"], [])

    def test_ia_fora_pergunta(self):
        # simulador (2026-10-13): a nota da Marilene ficou sem redação, sem aviso
        r = self.responder(RuntimeError("Gemini respondeu 503"), "Nota reescrita.")
        self.assertIn("Não consegui reescrever a nota de LUMITECH", r[1]["texto"])
        self.assertTrue(r[1]["texto"].endswith("A nota original é:\nPix de um cliente da loja"))
        self.assertEqual(self.nota()["erro_redacao"], "Gemini respondeu 503")
        r = self.clicar(r[1], "Tentar de novo")
        self.assertIn("Nota para o Conselho Fiscal — LUMITECH:\nNota reescrita.", r[0]["texto"])
        self.assertNotIn("erro_redacao", self.nota())
        self.clicar(r[0], "Está certo")
        self.assertEqual(self.nota()["texto"], "Nota reescrita.")

        r = self.responder(RuntimeError("Gemini respondeu 503"))
        r = self.clicar(r[1], "Manter a original")
        self.assertIn("NAIR", r[1]["texto"])
        self.assertEqual((self.nota()["texto"], self.nota()["redacao"]),
                         ("Pix de um cliente da loja", "original"))

    def test_so_confirmacao_nao_e_reescrita(self):
        self.r = self.enviar_tudo()
        self.agente.ia = IAFalsa(notas=["não deveria ser usada"])
        r = self.clicar(self.r[1], "Sim: recibo 0002")
        self.assertIn("NAIR", r[-1]["texto"])                      # direto para a próxima
        self.assertEqual(self.agente.ia.contextos_nota, [])
        self.assertTrue(self.nota()["texto"].startswith("Confirmado pela tesouraria: o Pix"))

    def test_botao_antigo_e_cf_durante_a_revisao(self):
        r = self.responder("Nota reescrita.")
        r = self.clicar(self.r[1], "Sim: recibo 0002")                 # pergunta anterior
        self.assertIn("pergunta anterior", r[0]["texto"])
        self.assertIn("Nota para o Conselho Fiscal", r[1]["texto"])  # mostra de novo
        cf = self.agente.receber("cf", texto="julho")
        self.assertIn("1 nota a aprovar", cf[0]["texto"])

    def test_ultima_nota_aprovada_antes_de_fechar(self):
        self.clicar(self.enviar_tudo()[1], "Sim: recibo 0002")                     # sobra a Nair
        self.agente.ia = IAFalsa(Interpretacao(explicacao="foi devolvido"),
                                 notas=["O valor foi devolvido à NAIR."])
        r = self.agente.receber("tesouraria", texto="foi devolvido")
        self.assertIn("Nota para o Conselho Fiscal — NAIR", r[-1]["texto"])
        self.assertEqual(self.estado()["situacao"], "aguardando_respostas")
        r = self.agente.receber("tesouraria", texto="sim")
        self.assertIn("Tudo certo", r[1]["texto"])
        self.assertEqual(self.estado()["situacao"], "pronto")

    def test_confirmacao_e_nota_num_clique_so(self):
        # simulador (2026-10-13): confirmação com texto pedia duas aprovações seguidas
        self.r = self.enviar_tudo()
        self.agente.ia = IAFalsa(Interpretacao(confirmar=(1,), explicacao="a empresa é do Ivan"),
                                 notas=["Pix de R$ 150,00 da empresa do IVAN."])
        r = self.agente.receber("tesouraria", texto="a 1 tá certa, a empresa é do Ivan")
        # a nota já conta a confirmação: ela não se repete; o vínculo não aparece
        self.assertEqual(r[0]["texto"], "\n".join([
            "Entendi:",
            "• Nota para o Conselho Fiscal: Pix de R$ 150,00 da empresa do IVAN."]))
        self.assertEqual([b["rotulo"] for b in r[0]["botoes"]], ["Está certo", "Não foi isso"])
        ctx = self.agente.ia.contextos_nota[0]
        self.assertEqual([c["recibo"] for c in ctx.confirmadas], ["0002-2026"])  # já com a 1
        self.assertEqual(self.estado()["notas"], {})                  # nada antes do clique

        r = self.clicar(r[0], "Está certo")
        self.assertTrue(all("Nota para o Conselho" not in m["texto"] for m in r))
        self.assertIn("NAIR", r[-1]["texto"])                      # direto para a próxima
        nota = self.nota()
        self.assertEqual((nota["texto"], nota["redacao"], nota["redigida_por"]),
                         ("Pix de R$ 150,00 da empresa do IVAN.", "aprovada", "IA falsa"))
        self.assertTrue(nota["nota_montada"].startswith("Confirmado pela tesouraria"))
        self.assertEqual(self.estado()["revisar"], [])

    def test_certo_sem_vinculo(self):
        """O nome do recibo estava errado (a mesma pessoa): a divergência se
        resolve, mas a conta não fica associada a outra pessoa (2026-10-23).
        O botão saiu da conversa (2026-10-27); o de uma mensagem antiga vale."""
        self.r = self.enviar_tudo()
        self.agente.ia = IAFalsa(Interpretacao(confirmar=(1,), explicacao="nome errado no recibo"),
                                 notas=["O recibo saiu com o nome errado."])
        self.agente.receber("tesouraria", texto="a 1, o recibo saiu com o nome errado")
        r = self.agente.receber("tesouraria", botao="ia_sem:DIV-LUMITECH")
        self.assertNotIn("vínculo", r[0]["texto"])
        self.assertIn("Isso também resolve a divergência de IVAN TRIGO PALHA LUAR (recibo sem Pix: R$ 150,00)", r[1]["texto"])
        self.assertEqual(self.vinculos_gravados(), [])
        self.assertEqual(self.estado()["confirmadas"][0]["cadastro"], False)
        self.assertEqual(self.nota()["texto"], "O recibo saiu com o nome errado.")
        # corrigir depois não mexe no cadastro (não há o que desfazer)
        with mock.patch.object(vinculos, "remover") as remover:
            self.agente.receber("tesouraria", texto="corrigir LUMITECH")
        remover.assert_not_called()

    def test_ia_entende_nome_errado(self):
        """"O recibo saiu com o nome errado, é ela mesma": a IA já tira o
        vínculo, sem falar dele na conversa."""
        self.r = self.enviar_tudo()
        self.agente.ia = IAFalsa(Interpretacao(confirmar=(1,), explicacao="nome errado no recibo",
                                               nome_errado=True),
                                 notas=["O recibo saiu com o nome errado."])
        r = self.agente.receber("tesouraria", texto="a 1, o nome do recibo saiu errado")
        self.assertEqual(r[0]["texto"], "\n".join([
            "Entendi:", "• Nota para o Conselho Fiscal: O recibo saiu com o nome errado."]))
        self.assertEqual([b["rotulo"] for b in r[0]["botoes"]], ["Está certo", "Não foi isso"])
        self.agente.receber("tesouraria", texto="sim")               # o "Está certo"
        self.assertEqual(self.vinculos_gravados(), [])
        self.assertEqual(self.estado()["confirmadas"][0]["cadastro"], False)

    def test_guardar_vinculo_contra_a_ia(self):
        self.r = self.enviar_tudo()
        self.agente.ia = IAFalsa(Interpretacao(confirmar=(1,), explicacao="x", nome_errado=True),
                                 notas=["Nota."])
        self.agente.receber("tesouraria", texto="a 1")
        self.agente.receber("tesouraria", botao="ia_com:DIV-LUMITECH")  # botão antigo
        self.assertEqual(self.vinculos_gravados(), ["LUMITECH"])

    def test_sim_que_a_ia_deixou_passar(self):
        """Caso real (junho, 2026-10-23): "sim, é a esposa dele" com uma
        sugestão só; a IA não marcou a confirmação e o vínculo se perdia."""
        self.r = self.enviar_tudo()                                # LUMITECH: uma sugestão
        # (o texto exato do caso real hoje passa pela regra fixa; com algo a mais, pela IA)
        self.agente.ia = IAFalsa(Interpretacao(explicacao="sim, é a esposa dele há anos"),
                                 notas=["O Pix é da esposa dele."])
        r = self.agente.receber("tesouraria", texto="sim, é a esposa dele há anos")
        self.assertTrue(r[0]["texto"].startswith("Entendi:"))       # confirma, com o clique
        # o "sim" só responde à pergunta: não vai para a nota (o original fica no histórico)
        self.assertEqual(self.agente.ia.contextos_nota[0].respostas, ["é a esposa dele há anos"])
        self.assertIn("\n• nota", r[0]["texto"].lower())
        r = self.clicar(r[0], "Está certo")
        self.assertIn("Isso também resolve a divergência de IVAN TRIGO PALHA LUAR (recibo sem Pix: R$ 150,00)", r[1]["texto"])
        self.assertEqual(self.vinculos_gravados(), ["LUMITECH"])
        self.assertEqual(self.nota()["texto"], "O Pix é da esposa dele.")
        self.assertEqual(self.nota()["texto_original"], "sim, é a esposa dele há anos")
        self.assertTrue(self.nota()["nota_montada"].endswith(" é a esposa dele há anos"))

    def test_reinterpretacao_sem_vinculo(self):
        self.registrada_sem_ia(Interpretacao(confirmar=(1,), explicacao="nome errado"),
                               notas=["Nome errado no recibo."])
        r = self.agente.receber("tesouraria", botao="reint_sem:DIV-LUMITECH",
                                rotulo="Certo, sem vínculo")
        self.assertIn("Isso também resolve a divergência de IVAN TRIGO PALHA LUAR (recibo sem Pix: R$ 150,00)", r[1]["texto"])
        self.assertEqual(self.vinculos_gravados(), [])

    def test_confirmacao_com_redacao_que_falha(self):
        self.r = self.enviar_tudo()
        self.agente.ia = IAFalsa(Interpretacao(confirmar=(1,), explicacao="a empresa é do Ivan"),
                                 notas=[RuntimeError("503"), "Nota reescrita."])
        r = self.agente.receber("tesouraria", texto="a 1 tá certa, a empresa é do Ivan")
        self.assertIn("• confirma a 1: o Pix de R$ 150,00", r[0]["texto"])  # sem nota: por extenso
        self.assertTrue(r[0]["texto"].endswith("\n• nota: a empresa é do Ivan"))
        r = self.clicar(r[0], "Está certo")                         # a revisão de sempre
        self.assertIn("Nota para o Conselho Fiscal — LUMITECH:\nNota reescrita.", r[-1]["texto"])

    def registrada_sem_ia(self, *depois, notas=()):
        """LUMITECH: a IA não responde, a tesouraria registra assim; depois a
        IA volta e devolve `depois` (e redige `notas`)."""
        self.r = self.enviar_tudo()
        self.agente.ia = IAFalsa(TimeoutError("sem resposta"), *depois, notas=notas)
        r = self.agente.receber("tesouraria", texto="é a empresa do Ivan")
        return self.clicar(r[0], "Registrar assim")

    def test_reinterpreta_quando_a_ia_volta(self):
        # simulador (2026-10-13): "Registrar assim" deixou o vínculo de fora; a IA
        # voltou segundos depois, na reescrita
        r = self.registrada_sem_ia(Interpretacao(confirmar=(1,), explicacao="empresa do Ivan"),
                                   notas=["Pix da empresa do IVAN."])
        self.assertEqual(r[0]["texto"], "✅ Anotado para LUMITECH: é a empresa do Ivan")
        self.assertIn("Agora consegui interpretar sua resposta para LUMITECH.", r[1]["texto"])
        self.assertTrue(r[1]["texto"].endswith("\n• Nota para o Conselho Fiscal: Pix da empresa "
                                              "do IVAN."))
        self.assertEqual(self.vinculos_gravados(), [])

        outra = self.agente.receber("tesouraria", texto="hã?")       # mostra de novo
        self.assertIn("Agora consegui interpretar", outra[-1]["texto"])

        r = self.agente.receber("tesouraria", texto="sim")
        self.assertIn("Isso também resolve a divergência de IVAN TRIGO PALHA LUAR (recibo sem Pix: R$ 150,00)", r[1]["texto"])
        self.assertIn("NAIR", r[-1]["texto"])
        self.assertEqual(self.vinculos_gravados(), ["LUMITECH"])
        nota = self.nota()
        self.assertEqual((nota["texto"], nota["redacao"], nota["interpretado_por"]),
                         ("Pix da empresa do IVAN.", "aprovada", "IA falsa"))
        self.assertTrue(nota["nota_montada"].endswith("é a empresa do Ivan"))
        self.assertEqual(self.estado()["revisar"], [])

    def test_reinterpretacao_recusada_fica_a_nota(self):
        r = self.registrada_sem_ia(Interpretacao(confirmar=(1,)), notas=["", "Reescrita."])
        r = self.clicar(r[1], "Não foi isso")
        self.assertEqual(r[0]["texto"], "Desconsiderei; fica a nota que você registrou.")
        self.assertIn("Nota para o Conselho Fiscal — LUMITECH:\nReescrita.", r[1]["texto"])
        self.assertEqual(self.vinculos_gravados(), [])

    def test_reinterpretacao_sem_confirmacao_segue(self):
        r = self.registrada_sem_ia(Interpretacao(explicacao="x"), notas=["Reescrita."])
        self.assertIn("Nota para o Conselho Fiscal — LUMITECH:\nReescrita.", r[1]["texto"])

    def test_corrigir_tira_da_revisao(self):
        self.responder("Nota reescrita.")
        r = self.agente.receber("tesouraria", texto="corrigir lumitech")
        self.assertIn("Reabri LUMITECH", r[0]["texto"])
        self.assertEqual(self.estado()["revisar"], [])
        self.assertIn("LUMITECH", r[1]["texto"])


@mock.patch("conselho_fiscal.agente.agente.identificar", identificar_teste)
class TestPerguntasCF(BaseConversa):
    """O CF pergunta sobre um mês: a resposta vem dos dados, sem anexos, e
    só o pedido do mês envia o pacote."""

    def fechar_julho(self):
        r = self.enviar_tudo()
        self.clicar(r[1], "Sim: recibo 0002")                            # LUMITECH e Ivan
        self.agente.receber("tesouraria", texto="Sim")               # Nair
        self.assertEqual(self.estado()["situacao"], "pronto")

    def perguntar(self, texto, *perguntas, respostas=()):
        self.agente.ia = IAFalsa(perguntas=perguntas, respostas_cf=respostas)
        return self.agente.receber("cf", texto=texto)

    def test_sem_ia_pergunta_recebe_o_resumo_sem_o_pacote(self):
        self.fechar_julho()
        r = self.agente.receber("cf", texto="me diga o valor total das divergências de julho")
        self.assertEqual(r[0]["anexos"], [])
        self.assertIn("Receitas de julho/2026 — versão 1 (pronto, ainda não enviado",
                      r[0]["texto"])
        self.assertIn("• Total no registro de receitas: R$ 300,00\n"
                      "• Pix recebidos no Cora: 2, somando R$ 270,00\n"
                      "• Pix recebidos na Stone: 2, somando R$ 330,00", r[0]["texto"])
        self.assertIn("• 3 divergência(s), todas com nota da tesouraria\n"
                      "• Recibos sem Pix: 1, somando R$ 150,00\n"
                      "• Pix sem recibo: 2, somando R$ 450,00", r[0]["texto"])
        self.assertEqual(self.estado()["situacao"], "pronto")       # não conta como entrega
        r = self.clicar(r[0], "Pacote julho/2026", papel="cf")
        self.assertEqual(len(r[0]["anexos"]), 4)
        self.assertEqual(self.estado()["situacao"], "entregue")
        r = self.agente.receber("cf", texto="resuma julho")
        self.assertIn("(enviado ao Conselho Fiscal em ", r[0]["texto"])

    def test_destino_com_ia(self):
        self.fechar_julho()
        r = self.perguntar("quanto arrecadamos com anuidade em julho?",
                           Pergunta("destino", ("2026-07",), destino="anuidade"),
                           respostas=["Em julho, as anuidades somaram R$ 270,00."])
        self.assertEqual(r[0]["texto"], "Em julho, as anuidades somaram R$ 270,00.")
        dados = self.agente.ia.contextos_resposta[0].dados
        self.assertIn("• Anuidade: R$ 270,00 (2 recibos)", dados)
        self.assertEqual(r[0]["anexos"], [])                       # pergunta não envia o pacote
        self.assertEqual(self.estado()["situacao"], "pronto")

    def test_destino_sem_ia(self):
        self.fechar_julho()
        r = self.agente.receber("cf", texto="Quanto entrou de café em julho?")
        self.assertIn("• Cafés: R$ 30,00 (1 recibo)", r[0]["texto"])
        r = self.agente.receber("cf", texto="como foi julho?")                 # sem destino
        self.assertIn("Receitas de julho/2026 — versão 1", r[0]["texto"])

    @mock.patch("conselho_fiscal.agente.agente.date", DataFixa)
    def test_deste_mes_pergunta_qual(self):
        """ "Desse mês" não vira o mês atual: o agente pergunta qual, e a
        escolha responde a pergunta guardada."""
        self.fechar_julho()
        self.agente.ia = IAFalsa()              # não pode ser chamada antes da escolha
        r = self.agente.receber("cf", texto="quanto deu o açaí desse mês?")
        self.assertEqual(r[0]["texto"], "Você está falando de outubro/2026 (o mês atual) ou "
                                        "de outro mês? Meses com dados: julho/2026.")
        self.assertEqual([b["rotulo"] for b in opcoes(r[0])], ["Outubro/2026", "Julho/2026"])
        self.assertEqual(self.agente.ia.contextos_pergunta, [])
        self.agente.ia = IAFalsa(perguntas=[Pergunta("destino", ("2026-07",), destino="açaí")])
        r = self.clicar(r[0], "Julho/2026", papel="cf")
        self.assertEqual(self.agente.ia.contextos_pergunta[0].texto,
                         "quanto deu o açaí de julho de 2026?")
        self.assertEqual(r[0]["anexos"], [])
        # o mês atual, sem dados: diz que ainda não foi fechado
        r = self.agente.receber("cf", texto="como foi este mês?")
        self.agente.ia = IAFalsa(perguntas=[Pergunta("resumo", ("2026-10",))])
        r = self.clicar(r[0], "Outubro/2026", papel="cf")
        self.assertIn("Outubro/2026 ainda não foi fechado", r[0]["texto"])

    @mock.patch("conselho_fiscal.agente.agente.date", DataFixa)
    def test_deste_mes_respondido_por_escrito(self):
        self.fechar_julho()
        self.agente.receber("cf", texto="resumo do mês atual")
        self.agente.ia = IAFalsa(perguntas=[Pergunta("resumo", ("2026-07",))])
        r = self.agente.receber("cf", texto="julho")     # responde a pergunta, não envia o pacote
        self.assertEqual(self.agente.ia.contextos_pergunta[0].texto, "resumo do julho de 2026")
        self.assertEqual(r[0]["anexos"], [])
        self.assertEqual(self.estado()["situacao"], "pronto")
        # outra mensagem descarta a pergunta: "julho" volta a pedir o pacote
        self.agente.receber("cf", texto="nesse mês teve devolução?")
        self.agente.receber("cf", texto="menu")
        r = self.agente.receber("cf", texto="julho")
        self.assertEqual(len(r[0]["anexos"]), 4)

    def test_dica_no_fim_separada(self):
        """Linhas em itálico no fim (dicas) ficam a uma linha em branco do
        conteúdo; itálico no meio ou dentro da linha não muda."""
        self.assertEqual(mensagem("Pergunta\n_dica 1_\n_dica 2_")["texto"],
                         "Pergunta\n\n_dica 1_\n_dica 2_")
        for texto in ("Pergunta\n\n_dica_", "_só a dica_", "Certo. _Escreva a explicação._",
                      "_alerta_\nconteúdo"):
            self.assertEqual(mensagem(texto)["texto"], texto)

    def test_mes_corrente_no_texto(self):
        self.assertTrue(cita_mes_corrente("Quanto deu o açaí DESSE MÊS?"))
        self.assertTrue(cita_mes_corrente("como foi o mes atual"))
        self.assertFalse(cita_mes_corrente("como foi o mês passado?"))
        self.assertFalse(cita_mes_corrente("esse mesmo"))
        self.assertEqual(com_mes("nesse mês teve devolução?", "2026-07"),
                         "em julho de 2026 teve devolução?")
        self.assertEqual(com_mes("como foi este mês?", "2026-06"), "como foi junho de 2026?")

    def test_destino_de_mes_aberto(self):
        self.enviar_tudo()
        r = self.perguntar("quanto deu o açaí em julho?",
                           Pergunta("destino", ("2026-07",), destino="açaí"))
        self.assertIn("Julho/2026 ainda não foi fechado", r[0]["texto"])

    def test_entrega_que_nao_chegou_e_desfeita(self):
        self.fechar_julho()
        r = self.agente.receber("cf", texto="julho")
        self.assertEqual(r[0]["entrega"], {"mes": "2026-07", "n": 1})
        copia = self.agente.arm.caminho(self.estado()["entregas"][0]["planilha"])
        self.assertTrue(copia.exists())
        with self.assertLogs("conselho_fiscal.agente.agente", "WARNING"):
            self.agente.entrega_falhou(r[0]["entrega"])
        self.assertEqual(self.estado()["situacao"], "pronto")       # não consta como enviado
        self.assertEqual(self.estado()["entregas"], [])
        self.assertFalse(copia.exists())
        r = self.agente.receber("cf", texto="julho")                 # pede de novo
        self.assertEqual(len(r[0]["anexos"]), 4)
        self.assertEqual(r[0]["entrega"], {"mes": "2026-07", "n": 1})

    def test_falha_de_entrega_antiga_nao_desfaz_a_nova(self):
        self.fechar_julho()
        primeira = self.agente.receber("cf", texto="julho")[0]["entrega"]
        self.agente.receber("cf", texto="julho")
        self.agente.entrega_falhou(primeira)
        self.assertEqual(len(self.estado()["entregas"]), 2)
        self.assertEqual(self.estado()["situacao"], "entregue")

    def test_ia_responde_com_os_dados(self):
        self.fechar_julho()
        r = self.perguntar("quanto entrou na Stone em julho?", Pergunta("resumo", ("2026-07",)),
                           respostas=["Na Stone entraram 2 Pix, somando R$ 330,00."])
        self.assertEqual(r[0]["texto"], "Na Stone entraram 2 Pix, somando R$ 330,00.")
        self.assertEqual([b["rotulo"] for b in r[0]["botoes"]], ["Pacote julho/2026"])
        ctx = self.agente.ia.contextos_resposta[0]
        self.assertEqual(ctx.pergunta, "quanto entrou na Stone em julho?")
        self.assertIn("• Pix recebidos na Stone: 2, somando R$ 330,00", ctx.dados)
        # lista: a IA vê os itens e as notas; as opções continuam
        r = self.perguntar("quem pagou a mais?", Pergunta("divergencias", ("2026-07",)),
                           respostas=["• IVAN TRIGO PALHA LUAR: recibo sem Pix"])
        self.assertEqual(r[0]["texto"], "• IVAN TRIGO PALHA LUAR: recibo sem Pix\n\n"
                                        "Para ver os itens e a nota de uma, escolha nas opções.")
        self.assertIn("*Nota da tesouraria:* Confirmado",       # a IA vê as marcas
                      self.agente.ia.contextos_resposta[0].dados)
        self.assertEqual(len(opcoes(r[0])), 4)
        # a IA falha na resposta: vão os dados
        r = self.perguntar("o que houve com a nair?", Pergunta("pessoa", (), "Nair"),
                           respostas=[ValueError("resposta com número que não está nos fatos")])
        self.assertIn("NAIR DE CANELA NEVE SERENO", r[0]["texto"])
        # pessoa não achada: nem pergunta à IA
        r = self.perguntar("e a Noeli?", Pergunta("pessoa", (), "Noeli"), respostas=["x"])
        self.assertIn("Não encontrei divergência de Noeli", r[0]["texto"])
        self.assertEqual(self.agente.ia.contextos_resposta, [])

    def criar_junho(self):
        """Junho fechado, cópia de julho com outros números (a planilha é a de julho)."""
        est = dict(self.estado(), mes="2026-06", entregas=[], situacao="pronto")
        est["resumo"] = dict(est["resumo"], valor_cora=200.0, recibos=2)
        self.arm.salvar_estado_mes(est)

    def test_comparar_meses(self):
        self.fechar_julho()
        self.criar_junho()
        r = self.perguntar("qual a soma da receita de junho e julho?",
                           Pergunta("comparar", ("2026-06", "2026-07")),
                           respostas=["A soma é R$ 600,00 (R$ 300,00 em cada mês)."])
        self.assertEqual(r[0]["texto"], "A soma é R$ 600,00 (R$ 300,00 em cada mês).")
        self.assertEqual([b["rotulo"] for b in r[0]["botoes"]],
                         ["Pacote junho/2026", "Pacote julho/2026"])
        dados = self.agente.ia.contextos_resposta[0].dados
        self.assertIn("*Receitas*\n• Total no registro de receitas: R$ 300,00 (junho/2026) → R$ 300,00 "
                      "(julho/2026): igual · soma R$ 600,00 · média R$ 300,00", dados)
        self.assertIn("*Pix recebidos no Cora*\n• Valor: R$ 200,00 (junho/2026) → R$ 270,00 "
                      "(julho/2026): aumento de R$ 70,00 (+35,0%) · soma R$ 470,00 · média "
                      "R$ 235,00", dados)
        self.assertIn("• Emitidos: 2 (junho/2026) → 3 (julho/2026): aumento de 1 (+50,0%) · "
                      "soma 5 · média 2,5", dados)
        self.assertIn("*Com divergência em mais de um mês*\n• LUMITECH (junho/2026, "
                      "julho/2026)", dados)
        # um mês só: ele e o fechado anterior; resumo de dois meses também compara
        self.perguntar("compare julho com o anterior", Pergunta("comparar", ("2026-07",)),
                       respostas=["ok"])
        self.assertIn("*Comparação: junho/2026 e julho/2026*",
                      self.agente.ia.contextos_resposta[0].dados)
        r = self.perguntar("resuma junho e julho", Pergunta("resumo", ("2026-06", "2026-07")))
        self.assertTrue(r[0]["texto"].startswith("Comparação: junho/2026 e julho/2026"))

    def test_comparar_precisa_de_dois_meses_fechados(self):
        self.fechar_julho()
        r = self.perguntar("compare julho com agosto", Pergunta("comparar", ("2026-07",
                                                                             "2026-08")))
        self.assertIn("Agosto/2026 ainda não foi fechado", r[0]["texto"])
        self.assertEqual(r[-1]["texto"], "Para comparar, preciso de pelo menos dois meses "
                                         "fechados. Meses fechados: julho/2026.")

    def test_divergencias_de_varios_meses(self):
        self.fechar_julho()
        self.criar_junho()
        r = self.perguntar("quem teve divergência em junho e julho?",
                           Pergunta("divergencias", ("2026-06", "2026-07")),
                           respostas=["LUMITECH aparece nos dois meses."])
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["texto"], "LUMITECH aparece nos dois meses.")
        dados = self.agente.ia.contextos_resposta[0].dados
        self.assertIn("Divergências de junho/2026 (3)", dados)
        self.assertIn("Divergências de julho/2026 (3)", dados)
        self.assertIn("• Com divergência em mais de um mês: LUMITECH (junho/2026, julho/2026)",
                      dados)

    def test_pedido_do_mes_nao_passa_pela_ia(self):
        self.fechar_julho()
        r = self.perguntar("pode me enviar julho?")
        self.assertEqual(len(r[0]["anexos"]), 4)
        self.assertEqual(self.agente.ia.contextos_pergunta, [])

    def test_lista_e_detalhe_de_uma_divergencia(self):
        self.fechar_julho()
        r = self.perguntar("quem teve divergência em julho?",
                           Pergunta("divergencias", ("2026-07",)))
        ctx = self.agente.ia.contextos_pergunta[0]
        self.assertEqual((ctx.texto, ctx.meses), ("quem teve divergência em julho?",
                                                  ("2026-07",)))
        self.assertIn(("LUMITECH", True), ctx.nomes)
        self.assertIn("1. LUMITECH — Pix sem recibo: R$ 150,00", r[0]["texto"])
        self.assertEqual(r[0]["anexos"], [])
        r = self.clicar(r[0], "NAIR DE CANELA NEVE SER…", papel="cf")
        self.assertIn("NAIR DE CANELA NEVE SERENO", r[0]["texto"])
        self.assertIn("Nota da tesouraria: Confirmado pela tesouraria", r[0]["texto"])
        self.assertIn("foi devolvido", r[0]["texto"])

    def test_pessoa(self):
        self.fechar_julho()
        r = self.perguntar("o que houve com a nair?", Pergunta("pessoa", (), "Nair"))
        self.assertIn("Julho/2026\nRecibos: R$ 30,00 · Extratos: R$ 330,00\nEntrou R$ 300,00 no banco sem "
                      "recibo:", r[0]["texto"])
        self.assertEqual([b["rotulo"] for b in r[0]["botoes"]], ["Pacote julho/2026"])
        r = self.perguntar("e a Noeli Pedra?", Pergunta("pessoa", (), "Noeli Pedra"))
        self.assertIn("Não encontrei divergência de Noeli Pedra (julho/2026). Só guardo",
                      r[0]["texto"])
        r = self.perguntar("e aquela pessoa?", Pergunta("pessoa"))
        self.assertIn("De quem?", r[0]["texto"])

    def test_mes_aberto_responde_so_a_situacao(self):
        self.enviar_tudo()
        r = self.perguntar("quantas divergências teve julho?",
                           Pergunta("resumo", ("2026-07",)))
        self.assertEqual(r[0]["texto"], "Julho/2026 ainda não foi fechado: está com a "
                                        "tesouraria (faltam 3 explicações).")
        r = self.perguntar("o que houve com a nair em julho?",
                           Pergunta("pessoa", ("2026-07",), "Nair"))
        self.assertIn("ainda não foi fechado", r[0]["texto"])
        self.assertEqual(len(r), 1)

    def test_situacao_outra_e_falha_da_ia(self):
        self.fechar_julho()
        r = self.perguntar("julho já fechou?", Pergunta("situacao", ("2026-07",)))
        self.assertEqual(r[0]["texto"], "Julho/2026 está fechado: pronto, ainda não enviado ao "
                                        "Conselho Fiscal.")
        r = self.perguntar("compare julho com o orçamento", Pergunta("outra", ("2026-07",)))
        self.assertIn("Não sei responder isso.", r[0]["texto"])
        # sem mês na pergunta: o último mês fechado
        r = self.perguntar("quantos recibos teve?", Pergunta("resumo"))
        self.assertIn("Receitas de julho/2026", r[0]["texto"])
        # a IA falha: avisa e segue como sem IA (pergunta com mês -> resumo)
        r = self.perguntar("quanto deu julho?", RuntimeError("sem resposta do Gemini"))
        self.assertTrue(r[0]["texto"].startswith(
            "Não consegui ler a pergunta agora (falha na IA).\nReceitas de julho/2026"))
        self.assertEqual(self.estado()["situacao"], "pronto")


@mock.patch("conselho_fiscal.agente.agente.identificar", identificar_teste)
class TestMenu(BaseConversa):
    """Menu, "como funciona" e quem fez o quê (2026-10-23)."""

    def test_saudacao_no_meio_das_perguntas_mostra_o_menu(self):
        self.enviar_tudo()
        r = self.agente.receber("tesouraria", texto="oi, bom dia", autor="Ila")
        self.assertEqual(r[0]["texto"], "Oi, Ila! Você está como Tesouraria.\n"
                         "Julho/2026: faltam 3 explicações.\n\n"
                         "Para conferir um mês, envie o registro de receitas da tesouraria (.xlsx) e "
                         "os 2 extratos bancários em PDF (📎 → Documento).")
        self.assertEqual(self.estado()["notas"], {})                   # o "oi" não virou nota
        r = self.clicar(r[0], "Continuar julho")
        self.assertTrue(r[0]["texto"].startswith("Divergência 1 de 3 — LUMITECH"))

    def test_menu_com_envio_pela_metade_e_mes_pronto(self):
        self.enviar(self.cora)
        r = self.agente.receber("tesouraria", texto="menu")
        self.assertIn("Envio: recebi 1 extrato bancário; falta o registro de receitas da "
                      "tesouraria (.xlsx), 1 extrato bancário (PDF).", r[0]["texto"])
        self.assertEqual([b["rotulo"] for b in opcoes(r[0])], ["Como funciona"])
        self.enviar(self.entradas)
        r = self.clicar(self.enviar(self.stone)[1], "Sim: recibo 0002")
        self.agente.receber("tesouraria", texto="Sim")                  # Nair: devolução
        r = self.agente.receber("tesouraria", texto="oi")
        self.assertIn("Julho/2026: pronto; o Conselho Fiscal recebe quando pedir.", r[0]["texto"])
        self.assertEqual([b["rotulo"] for b in opcoes(r[0])], ["Corrigir uma nota", "Como funciona"])

    def test_texto_sem_sentido_fora_das_perguntas(self):
        r = self.agente.receber("tesouraria", texto="abacaxi")
        self.assertTrue(r[0]["texto"].startswith("Não entendi. Você está como Tesouraria."))

    def test_como_funciona(self):
        r = self.agente.receber("tesouraria", texto="como funciona?")
        self.assertEqual(r[0]["texto"], conferir_whatsapp(self, [
            {"texto": COMO_FUNCIONA["tesouraria"], "botoes": []}])[0]["texto"])
        r = self.agente.receber("cf", texto="ajuda")
        self.assertIn("Quando o mês fica pronto, você pede o pacote", r[0]["texto"])
        r = self.clicar(r[0], "Menu", papel="cf")
        self.assertTrue(r[0]["texto"].startswith("Você está como Conselho Fiscal.\n"
                                                 "Ainda não há mês conferido"))

    def test_menu_do_cf_com_extras_do_canal(self):
        self.enviar_tudo()
        trocar = {"id": "papel:trocar", "rotulo": "Trocar de papel"}
        r = self.agente.menu("cf", "Bia", [trocar])
        self.assertEqual(r[0]["texto"], "Oi, *Bia*! Você está como *Conselho Fiscal*.\n*Meses:*\n"
                         "• *julho/2026*: com a tesouraria (faltam 3 explicações)\n\n"
                         "_Toque num mês para receber o pacote, ou pergunte (ex.: \"quanto "
                         "entrou de açaí em julho?\")._")
        self.assertEqual([b["rotulo"] for b in opcoes(r[0])], ["Como funciona", "Trocar de papel"])
        self.assertEqual(self.agente.conversa("cf")[-1]["texto"], r[0]["texto"])  # no histórico

    def test_quem_fez_fica_nos_registros(self):
        for caminho in (self.entradas, self.cora, self.stone):
            with open(caminho, "rb") as f:
                r = self.agente.receber("tesouraria", anexo=(os.path.basename(caminho), f.read()),
                                        autor="Ila")
        b = next(b for b in opcoes(r[1]) if b["rotulo"] == "Sim: recibo 0002")
        self.agente.receber("tesouraria", botao=b["id"], rotulo=b["rotulo"], autor="Ila")
        self.agente.receber("tesouraria", texto="Valor devolvido.", autor="Caio")
        self.agente.receber("cf", texto="julho", autor="Bia")
        est = self.estado()
        self.assertEqual(est["versoes"][0]["por"], "Ila")
        self.assertEqual({c["por"] for c in est["confirmadas"]}, {"Ila"})
        self.assertEqual(est["notas"]["DIV-NAIR-DE-CANELA-NEVE-SERENO"]["por"], "Caio")
        self.assertEqual(est["entregas"][0]["para"], "Bia")
        self.assertEqual(self.agente.conversa("cf")[0]["autor"], "Bia")
        # só no histórico: a planilha do CF não leva os nomes
        planilha = self.arm.caminho(est["entregas"][0]["planilha"])
        textos = {str(c.value) for aba in load_workbook(planilha) for linha in aba.iter_rows()
                  for c in linha if c.value}
        self.assertFalse({"Ila", "Bia", "Caio"} & textos)


class TestConfirmacaoExplicita(unittest.TestCase):
    def test_comeco_da_resposta(self):
        from conselho_fiscal.agente.agente import confirmacao_explicita as c
        self.assertEqual(c("sim, é a esposa dele", 1), ((1,), "é a esposa dele"))
        self.assertEqual(c("a 1, é a esposa dele", 1), ((1,), "é a esposa dele"))
        self.assertEqual(c("a 2 tá certa", 2), ((2,), "tá certa"))
        self.assertEqual(c("isso", 1), ((1,), ""))
        for texto, n in (("Sim é a esposa dele", 2),     # duas sugestões: qual?
                         ("sim, mas não é dele", 1),     # negação
                         ("é a esposa dele", 1), ("a 3", 2), ("as 2", 2), ("simone pagou", 1)):
            self.assertEqual(c(texto, n), ((), texto), texto)


class TestSemConfirmacao(unittest.TestCase):
    def test_tira_so_o_que_responde_a_pergunta(self):
        from conselho_fiscal.agente.agente import sem_confirmacao as s
        self.assertEqual(s("sim, é a esposa dele"), "é a esposa dele")
        self.assertEqual(s("Isso. Foi oferta"), "Foi oferta")
        self.assertEqual(s("a 1, é a esposa dele"), "é a esposa dele")
        self.assertEqual(s("sim"), "sim")                          # sem nada depois: fica
        self.assertEqual(s("simone pagou"), "simone pagou")
        self.assertEqual(s("é a esposa dele"), "é a esposa dele")


class TestComandos(unittest.TestCase):
    def test_menu_e_ajuda(self):
        for t in ("oi", "Olá!", "bom dia", "menu", "oi, tudo bem?", "Boa tarde"):
            self.assertTrue(pede_menu(t), t)
        for t in ("sim", "ok", "não sei", "foi oferta", "", None, "bem"):
            self.assertFalse(pede_menu(t), t)
        for t in ("ajuda", "como funciona?", "o que você faz?"):
            self.assertTrue(pede_ajuda(t), t)
        self.assertFalse(pede_ajuda("como foi julho?"))

    def test_saudacoes(self):
        for t in ("olá Elo", "oi elo, bom dia", "bom diaa", "oii", "e aí", "eae", "opa",
                  "salve", "fala", "hello", "ola pessoal", "e ai, tudo bem?", "👋 oi"):
            self.assertTrue(pede_menu(t), t)
        for t in ("tudo bem", "tudo bem?", "boa parte foi em dinheiro", "oito reais",
                  "Hilda pagou", "fala com a Nair", "oi, preciso de ajuda"):
            self.assertFalse(pede_menu(t), t)
        self.assertTrue(pede_ajuda("preciso de ajuda"))
        self.assertTrue(pede_ajuda("me ajuda por favor"))

    def test_sem_saudacao(self):
        casos = {"oi, preciso de ajuda": "preciso de ajuda",
                 "Bom dia! Segue o extrato": "Segue o extrato",
                 "Olá Elo, é a esposa dele": "é a esposa dele",
                 "oi": "oi", "boa parte foi em dinheiro": "boa parte foi em dinheiro",
                 "fala com a Nair": "fala com a Nair", "Hilda pagou": "Hilda pagou"}
        for t, esperado in casos.items():
            self.assertEqual(sem_saudacao(t), esperado, t)


class TestTextosDasDivergencias(unittest.TestCase):
    def div(self, recibos, extrato, sem_pix=(), sem_recibo=()):
        return {"id": "D", "pessoa": "X", "tipo": "Divergência de valor",
                "total_recibos": recibos, "total_extrato": extrato,
                "diferenca": round(recibos - extrato, 2),
                "recibos_sem_pix": [{"numero": n, "valor": v} for n, v in sem_pix],
                "pix_sem_recibo": [{"valor": v, "banco": "Cora", "data": "02/07/2026",
                                    "nome_no_extrato": "X"} for v in sem_recibo]}

    def test_resumo_sem_sinal(self):
        self.assertEqual(dv.resumo(self.div(0, 150, sem_recibo=[150])),
                         "Pix sem recibo: R$ 150,00")
        self.assertEqual(dv.resumo(self.div(460, 0, sem_pix=[("0901-2026", 460)])),
                         "recibo sem Pix: R$ 460,00")
        self.assertEqual(dv.resumo(self.div(30, 330)), "R$ 300,00 a mais no banco que nos recibos")
        self.assertEqual(dv.resumo(self.div(380, 20)), "R$ 360,00 a menos no banco que nos recibos")

    def test_pagina_do_extrato(self):
        d = self.div(0, 50, sem_recibo=[50])
        d["pix_sem_recibo"][0]["pagina"] = 3
        self.assertIn("• R$ 50,00 em 02/07/2026, Cora, pág. 3", dv.descrever(d))
        sem_pagina = dict(d, pix_sem_recibo=[dict(d["pix_sem_recibo"][0], pagina=None)])
        # a página não muda a assinatura: as notas de antes continuam valendo
        self.assertEqual(dv.assinatura(d), dv.assinatura(sem_pagina))
        self.assertEqual(dv.assinatura(d), dv.assinatura(self.div(0, 50, sem_recibo=[50])))

    def test_criterio_so_quando_o_valor_tem_varios_recibos(self):
        def sugestao(criterio, forca):
            return {"pix_de": "X", "nome_no_extrato": "X", "valor": 50.0, "pix_banco": "Cora",
                    "pix_data": "02/07/2026", "recibo": "0010-2026", "recibo_de": "ILA",
                    "criterio": criterio, "forca": forca, "div_pix": "D", "div_recibo": "R"}
        d = self.div(0, 50, sem_recibo=[50])
        d["devolucoes_possiveis"] = []
        todas = {"D": d, "R": self.div(50, 0, sem_pix=[("0010-2026", 50)])}
        for criterio, forca, fim in (
                ("mesmo valor (3 recibos possíveis)", 5, " _(só pelo valor; 3 recibos possíveis)_"),
                ("valor único no mês (sem pista de nome)", 4, ""),
                ("nome em comum (Verde)", 2, "")):
            d["sugestoes_vinculo"] = [sugestao(criterio, forca)]
            [o] = dv.opcoes(d, [], todas)
            self.assertEqual(o["rotulo"], "o Pix de R$ 50,00 (02/07/2026, Cora) pagou o *recibo "
                             "0010-2026 de ILA*" + fim)
        d["sugestoes_vinculo"] = [dict(sugestao("nome em comum (Verde)", 2), pix_pagina=4)]
        [o] = dv.opcoes(d, [], todas)
        self.assertIn("(02/07/2026, Cora, pág. 4)", o["rotulo"])
        self.assertIn("(R$ 50,00, Cora, 02/07/2026, pág. 4) pagou o recibo", o["texto"])

    def test_descrever_so_o_que_falta(self):
        d = self.div(170, 20, sem_pix=[("0864-2026", 150), ("0874-2026", 20)], sem_recibo=[20])
        self.assertEqual(dv.descrever(d), "\n".join([
            "Recibos: R$ 170,00 · Extratos: R$ 20,00",
            "Entrou *R$ 20,00* no banco *sem recibo*:", "• R$ 20,00 em 02/07/2026, Cora",
            "*R$ 170,00 em recibo* que não aparece nos extratos:",
            "• recibo 0864-2026: R$ 150,00", "• recibo 0874-2026: R$ 20,00"]))
        conf = {"tipo": "vinculo", "div_recibo": "D", "recibo": "0864-2026",
                "div_pix": "OUTRA", "pix": "P:Stone|08/07/26|150.00"}
        self.assertEqual(dv.descrever(d, [conf]), "\n".join([      # sem os totais, sem o 0864
            "Entrou *R$ 20,00* no banco *sem recibo*:", "• R$ 20,00 em 02/07/2026, Cora",
            "*R$ 20,00 em recibo* que não aparece nos extratos:", "• recibo 0874-2026: R$ 20,00"]))


class TestDivergencias(unittest.TestCase):
    def div(self, id_, recibos=(), pix=(), sugestoes=(), devolucoes=()):
        return {"id": id_, "pessoa": id_, "tipo": "x", "total_recibos": 0, "total_extrato": 0,
                "diferenca": 0,
                "recibos_sem_pix": [{"numero": n, "valor": v} for n, v in recibos],
                "pix_sem_recibo": [{"valor": v, "banco": "Cora", "data": "01/07/2026",
                                    "nome_no_extrato": id_} for v in pix],
                "sugestoes_vinculo": list(sugestoes), "devolucoes_possiveis": list(devolucoes)}

    def sugestao(self, recibo, recibo_de, pix_de, valor):
        return {"pix_de": pix_de, "nome_no_extrato": pix_de, "valor": valor, "pix_banco": "Cora",
                "pix_data": "01/07/2026", "recibo": recibo, "recibo_de": recibo_de,
                "criterio": "c", "forca": 5, "div_pix": pix_de, "div_recibo": recibo_de}

    def test_pix_disputado_por_dois_recibos(self):
        s1, s2 = self.sugestao("R1", "ELIO", "EMPRESA", 80), self.sugestao("R2", "NOELI", "EMPRESA", 80)
        empresa = self.div("EMPRESA", pix=[80], sugestoes=[s1, s2])
        todas = {"EMPRESA": empresa, "ELIO": self.div("ELIO", recibos=[("R1", 80)], sugestoes=[s1]),
                 "NOELI": self.div("NOELI", recibos=[("R2", 80)], sugestoes=[s2])}
        ops = dv.opcoes(empresa, [], todas)
        self.assertEqual(len(ops), 2)
        self.assertFalse(dv.compativeis(ops))                        # sem "Confirmo todas"
        confirmadas = [ops[0]]
        self.assertTrue(dv.coberta(empresa, confirmadas))
        self.assertTrue(dv.coberta(todas["ELIO"], confirmadas))
        self.assertFalse(dv.coberta(todas["NOELI"], confirmadas))
        self.assertEqual(dv.opcoes(todas["NOELI"], confirmadas, todas), [])   # Pix já usado

    def test_nota_montada(self):
        s1, s2 = self.sugestao("R1", "ELIO", "EMPRESA", 80), self.sugestao("R2", "ELIO", "EMPRESA", 20)
        elio = self.div("ELIO", recibos=[("R1", 80), ("R2", 20)], sugestoes=[s1, s2])
        empresa = self.div("EMPRESA", pix=[80, 20], sugestoes=[s1, s2])
        ops = dv.opcoes(elio, [], {"ELIO": elio, "EMPRESA": empresa})
        um = dv.nota_montada(elio, ops[:1], "é a empresa dele")
        self.assertTrue(um.startswith("Confirmado pela tesouraria: o Pix de \"EMPRESA\""))
        self.assertTrue(um.endswith("de ELIO. é a empresa dele"))
        dois = dv.nota_montada(elio, ops, "é a empresa dele").split("\n")
        self.assertEqual(dois[0], "Confirmado pela tesouraria:")
        self.assertTrue(dois[1].startswith("• o Pix de \"EMPRESA\" (R$ 80,00"))
        self.assertTrue(dois[2].startswith("• o Pix de \"EMPRESA\" (R$ 20,00"))
        self.assertEqual(dois[3], "é a empresa dele")

    def test_assinatura_muda_com_o_conteudo(self):
        a = self.div("ILA", recibos=[("R1", 50)])
        self.assertEqual(dv.assinatura(a), dv.assinatura(dict(a, nota_tesouraria="x")))
        self.assertNotEqual(dv.assinatura(a), dv.assinatura(self.div("ILA", recibos=[("R1", 60)])))


class TestFormatoWhatsApp(unittest.TestCase):
    def test_botoes_ou_lista(self):
        from conselho_fiscal.agente.agente import mensagem
        tres = [{"id": str(i), "rotulo": f"Opção {i}"} for i in range(3)]
        self.assertEqual(mensagem("x", botoes=tres)["botoes"], tres)
        self.assertNotIn("lista", mensagem("x", botoes=tres))

        doze = [{"id": str(i), "rotulo": f"Opção {i}"} for i in range(11)]
        doze.append({"id": "longa", "rotulo": "NAIR DE CANELA NEVE SERENO DOS AMORAS"})
        m = mensagem("x", botoes=doze)
        self.assertEqual(m["botoes"], [])
        self.assertEqual(len(m["lista"]["itens"]), 10)               # o WhatsApp mostra 10
        longa = mensagem("x", botoes=doze[:3] + doze[-1:])["lista"]["itens"][-1]
        self.assertEqual(longa, {"id": "longa", "rotulo": "NAIR DE CANELA NEVE SER…",
                                 "descricao": "NAIR DE CANELA NEVE SERENO DOS AMORAS"})
        conferir_whatsapp(self, [m])


class TestCadastrosDaSimulacao(unittest.TestCase):
    def test_copia_uma_vez_e_nao_toca_os_reais(self):
        from conselho_fiscal import config
        arm = Armazenamento(pasta_temp("teste_cadastros_sim_"))
        destinos, vinc = arm.cadastros_proprios()
        self.assertEqual(destinos.read_bytes(), config.caminho_destinos().read_bytes())
        self.assertEqual(vinculos.carregar(vinc), [])
        vinculos.registrar("EMPRESA X", "FULANO", "2026-07", caminho=vinc)
        self.assertEqual(arm.cadastros_proprios(), (destinos, vinc))       # não recopia
        self.assertEqual(len(vinculos.carregar(vinc)), 1)
        self.assertNotEqual(vinc.resolve(), config.caminho_vinculos_confirmados().resolve())


class TestReconhecerMes(unittest.TestCase):
    def test_formatos(self):
        disponiveis = ["2025-07", "2026-06", "2026-07"]
        self.assertEqual(reconhecer_mes("me envia julho", disponiveis), "2026-07")
        self.assertEqual(reconhecer_mes("Julho de 2025", disponiveis), "2025-07")
        self.assertEqual(reconhecer_mes("dados de 06/2026", disponiveis), "2026-06")
        self.assertEqual(reconhecer_mes("2026-6", disponiveis), "2026-06")
        self.assertEqual(reconhecer_mes("oi", disponiveis), None)
        # mês sem dados: o último que já começou
        hoje = date(2026, 10, 9)
        self.assertEqual(reconhecer_mes("MARÇO", disponiveis, hoje), "2026-03")
        self.assertEqual(reconhecer_mes("novembro", disponiveis, hoje), "2025-11")

    def test_so_pedido(self):
        for texto in ("julho", "Julho/2026", "pode me enviar julho?", "2026-07",
                      "manda o pacote de julho de 2026, por favor"):
            self.assertTrue(so_pedido(texto), texto)
        for texto in ("valor total das divergências de julho", "junho e julho",
                      "quem teve divergência em julho?", "resuma julho"):
            self.assertFalse(so_pedido(texto), texto)


class TestPeriodoDoExtrato(unittest.TestCase):
    def test_mes_do_periodo(self):
        self.assertEqual(mes_do_periodo("EXTRATO DO PERIODO     01/09/2026 A 30/09/2026"),
                         "2026-09")                                        # Cora
        self.assertEqual(mes_do_periodo("PERIODO: DE 01/06/2026 A 30/06/2026"), "2026-06")
        self.assertIsNone(mes_do_periodo("PERIODO: DE 15/06/2026 A 14/07/2026"))  # dois meses
        self.assertIsNone(mes_do_periodo("EXTRATO DE CONTA CORRENTE"))


class TestModoDemo(unittest.TestCase):
    def test_extrato_xlsx_so_vale_no_modo_demo(self):
        pasta = pasta_temp("teste_demo_")
        caminho = os.path.join(pasta, "cora.xlsx")
        exportar_xlsx([transacao("Cora", "02/07/2026", "Transf Pix recebida X", 10)], "Cora",
                      caminho)
        self.assertEqual(identificar(caminho, "cora.xlsx").tipo, "extrato_xlsx")
        with mock.patch.dict(os.environ, {"CF_DEMO": "1"}):
            self.assertEqual(identificar(caminho, "cora.xlsx").tipo, "Cora")

    def test_extrato_xlsx_sem_alerta_no_modo_demo(self):
        from conselho_fiscal.extratos import ler_extrato
        caminho = os.path.join(pasta_temp("teste_demo_"), "stone.xlsx")
        exportar_xlsx([transacao("Stone", "02/07/26", "X", 10)], "Stone", caminho)
        transacoes, alertas = ler_extrato(caminho, "Stone")
        self.assertEqual(alertas[0]["status"], "NÃO VERIFICADO")
        with mock.patch.dict(os.environ, {"CF_DEMO": "1"}):
            self.assertEqual(ler_extrato(caminho, "Stone"), (transacoes, []))
