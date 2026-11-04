"""WhatsApp (Cloud API da Meta): configuração, assinatura, conversão das
mensagens, o canal e o webhook, com uma Meta de mentira."""

import hashlib
import hmac
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from conselho_fiscal.agente import Agente
from conselho_fiscal.agente import whatsapp as wa
from conselho_fiscal.agente.agente import mensagem
from conselho_fiscal.agente.armazenamento import Armazenamento
from tests.apoio import cadastros_temp, pasta_temp

try:
    from fastapi.testclient import TestClient

    from conselho_fiscal.agente.web import criar_app
except ImportError:          # dependências opcionais (pip install -e ".[agente,dev]")
    TestClient = None

EU = "5511999990000"
OUTRO = "5511988887777"
SEM_NOVE = "551199990000"     # como a Meta às vezes manda o número do Brasil
SEGREDO = "segredo-de-teste"


class MetaFalsa:
    """Registra o que seria enviado à Meta."""

    def __init__(self, cfg=None):
        self.cfg = cfg or wa.Config("tok", SEGREDO, "123", "verifica", {EU: ("tesouraria",)})
        self.enviadas, self.lidas, self.subidas = [], [], []
        self.arquivos: dict[str, bytes] = {}
        self.falhar_subida = False
        self.fora_da_lista: set[str] = set()     # formas do número que a Meta recusa

    def enviar(self, para, conteudo):
        if para in self.fora_da_lista:
            raise wa.ErroMeta("Meta respondeu 400: fora da lista", wa.FORA_DA_LISTA)
        self.enviadas.append((para, conteudo))

    def marcar_lida(self, mensagem_id):
        self.lidas.append(mensagem_id)

    def baixar(self, midia_id):
        return self.arquivos[midia_id]

    def subir(self, nome, conteudo):
        if self.falhar_subida:
            raise RuntimeError("Meta respondeu 500")
        self.subidas.append((nome, conteudo))
        return f"midia-{len(self.subidas)}"

    def brutos(self):
        """Os textos enviados, sozinhos ou no corpo das opções, como saíram."""
        return [c["text"]["body"] if c["type"] == "text" else c["interactive"]["body"]["text"]
                for _, c in self.enviadas if c["type"] in ("text", "interactive")]

    def cabecalhos(self):
        return [t.split("\n", 1)[0] for t in self.brutos()]

    def textos(self):
        """Os textos sem o cabeçalho ("*Elo*…"), que toda mensagem tem."""
        return [t.split("\n\n", 1)[1] for t in self.brutos()]


def texto(corpo, de=SEM_NOVE, mid="m1"):
    return {"from": de, "id": mid, "type": "text", "text": {"body": corpo}}


class TestConfiguracao(unittest.TestCase):
    def test_numero(self):
        self.assertEqual(wa.numero("11999990000"), EU)
        self.assertEqual(wa.numero("+55 (11) 99999-0000"), EU)
        self.assertEqual(wa.numero(SEM_NOVE), EU)            # o 9 que a Meta tira
        self.assertEqual(wa.numero("551132221234"), "551132221234")   # fixo fica
        self.assertEqual(wa.numero("15550001234"), "15550001234")

    def test_contatos(self):
        c = wa.ler_contatos(f"{EU}=tesouraria, cf; 11988887777=cf\n")
        self.assertEqual(c, {EU: ("tesouraria", "cf"), "5511988887777": ("cf",)})
        for errado in (f"{EU}=presidente", f"{EU}=", "=cf", f"{EU}=cf@", f"{EU}=cf@a b"):
            with self.assertRaises(ValueError):
                wa.ler_contatos(errado)

    def test_espacos(self):
        texto = f"{EU}=tesouraria,cf; 11988887777=tesouraria,cf@Teste"
        self.assertEqual(wa.ler_contatos(texto), {EU: ("tesouraria", "cf"),
                                                  OUTRO: ("tesouraria", "cf")})
        self.assertEqual(wa.ler_espacos(texto), {OUTRO: "teste"})

    def test_config(self):
        pasta = Path(pasta_temp("teste_wa_"))
        with mock.patch.object(wa, "PASTA_SEGREDOS", pasta), \
                mock.patch.dict(os.environ, {}, clear=True):
            cfg, falta = wa.config()
            self.assertIsNone(cfg)
            self.assertIn("WHATSAPP_TOKEN", falta)
            (pasta / "whatsapp_token").write_text("tok\n")
            (pasta / "whatsapp_app_secret").write_text("seg\n")
            os.environ.update(WHATSAPP_PHONE_NUMBER_ID="123", WHATSAPP_VERIFY_TOKEN="v",
                              WHATSAPP_CONTATOS=f"{EU}=cf; {OUTRO}=cf@teste")
            cfg, falta = wa.config()
        self.assertIsNone(falta)
        self.assertEqual((cfg.token, cfg.segredo, cfg.versao), ("tok", "seg", wa.VERSAO_PADRAO))
        self.assertEqual(cfg.contatos, {EU: ("cf",), OUTRO: ("cf",)})
        self.assertEqual(cfg.espacos, {OUTRO: "teste"})

    def test_assinatura(self):
        corpo = b'{"a": 1}'
        boa = "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
        self.assertTrue(wa.assinatura_ok(corpo, boa, SEGREDO))
        self.assertFalse(wa.assinatura_ok(corpo + b" ", boa, SEGREDO))
        self.assertFalse(wa.assinatura_ok(corpo, boa, "outro"))
        self.assertFalse(wa.assinatura_ok(corpo, None, SEGREDO))


class TestTipos(unittest.TestCase):
    """Sem a tabela do sistema (como na imagem, Python 3.12), o .xlsx ainda sai certo."""

    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def setUp(self):
        sem_sistema = mock.patch.object(wa.mimetypes, "guess_type", return_value=(None, None))
        sem_extensao = mock.patch.object(wa.mimetypes, "guess_extension", return_value=None)
        sem_sistema.start(), sem_extensao.start()
        self.addCleanup(mock.patch.stopall)

    def test_tipo_pelo_nome(self):
        self.assertEqual(wa.tipo_do_arquivo("receitas_2026-06.XLSX"), self.XLSX)
        self.assertEqual(wa.tipo_do_arquivo("cora.pdf"), "application/pdf")
        self.assertEqual(wa.tipo_do_arquivo("x.bin"), "application/octet-stream")

    def test_extensao_pelo_tipo(self):
        self.assertEqual(wa.extensao_do_tipo(self.XLSX), ".xlsx")
        self.assertEqual(wa.extensao_do_tipo("application/pdf; charset=binary"), ".pdf")
        self.assertEqual(wa.extensao_do_tipo("image/heic"), "")

    def test_subir_planilha_com_o_tipo_certo(self):
        meta = wa.Meta(wa.Config("t", "s", "123", "v"))
        with mock.patch.object(meta, "_chamar", return_value=b'{"id": "m1"}') as chamar:
            self.assertEqual(meta.subir("entradas.xlsx", b"planilha"), "m1")
        corpo = chamar.call_args.args[1]
        self.assertIn(f"Content-Type: {self.XLSX}".encode(), corpo)
        self.assertNotIn(b"octet-stream", corpo)


class TestConverter(unittest.TestCase):
    def test_so_texto(self):
        self.assertEqual(wa.converter(mensagem("Olá")),
                         [{"type": "text", "text": {"body": "Olá"}}])

    def test_texto_longo_em_partes(self):
        partes = wa.converter(mensagem("\n".join(["x" * 100] * 100)))
        self.assertEqual(len(partes), 3)
        self.assertTrue(all(len(p["text"]["body"]) <= wa.MAX_TEXTO for p in partes))

    def test_botoes_com_o_texto(self):
        m = mensagem("Confirma?", botoes=[{"id": "ia_ok", "rotulo": "Está certo"},
                                          {"id": "ia_nao", "rotulo": "Não"}])
        [b] = wa.converter(m, "*Elo* · _Conselho Fiscal_")
        i = b["interactive"]
        self.assertEqual((i["type"], i["body"]["text"]), ("button", "*Elo* · _Conselho Fiscal_\n\nConfirma?"))
        self.assertEqual([x["reply"] for x in i["action"]["buttons"]],
                         [{"id": "ia_ok", "title": "Está certo"}, {"id": "ia_nao", "title": "Não"}])

    def test_texto_longo_separado_dos_botoes(self):
        m = mensagem("y" * 2000, botoes=[{"id": "a", "rotulo": "A"}])
        t, b = wa.converter(m)
        self.assertEqual(t["text"]["body"], "y" * 2000)
        self.assertEqual(b["interactive"]["body"]["text"], "Escolha uma opção:")

    def test_lista(self):
        m = mensagem("Qual?", botoes=[{"id": f"d{i}", "rotulo": f"Pessoa com nome comprido {i}"}
                                      for i in range(5)])
        [b] = wa.converter(m)
        i = b["interactive"]
        self.assertEqual(i["type"], "list")
        self.assertEqual(i["action"]["button"], "Ver opções")
        linhas = i["action"]["sections"][0]["rows"]
        self.assertEqual(len(linhas), 5)
        self.assertTrue(all(len(r["title"]) <= 24 for r in linhas))
        self.assertIn("description", linhas[0])

    def test_anexos_entre_o_texto_e_as_opcoes(self):
        m = mensagem("Pacote", anexos=[{"nome": "a.xlsx", "caminho": "x/a.xlsx"}],
                     botoes=[{"id": "b", "rotulo": "B"}])
        tipos = [c.get("type", "anexo") for c in wa.converter(m)]
        self.assertEqual(tipos, ["text", "anexo", "interactive"])


class TestCanal(unittest.TestCase):
    def setUp(self):
        destinos, vinculos = cadastros_temp()
        self.arm = Armazenamento(pasta_temp("teste_wa_"))
        self.agente = Agente(self.arm, destinos, vinculos)
        self.meta = MetaFalsa()

    def canal(self, contatos=None, agentes=None, nome="Ila"):
        """O canal; com `nome`, os números já se apresentaram (primeiro
        contato feito)."""
        contatos = contatos or {EU: ("tesouraria",)}
        canal = wa.WhatsApp(self.agente, self.meta, contatos, agentes)
        for num in contatos if nome else ():
            canal._guardar_nome(num, nome)
        return canal

    def test_texto_da_tesouraria(self):
        self.canal().processar(texto("oi"))
        self.assertEqual(self.meta.lidas, ["m1"])
        self.assertEqual({p for p, _ in self.meta.enviadas}, {EU})     # o número com o 9
        self.assertTrue(self.meta.textos()[0].startswith("Oi, *Ila*! Você está como "
                                                         "*Tesouraria*."))
        self.assertIn("*envie* o registro de receitas da tesouraria", self.meta.textos()[0])
        conversa = self.agente.conversa("tesouraria")
        self.assertEqual([m["de"] for m in conversa], ["tesouraria", "agente"])
        self.assertEqual(conversa[0]["autor"], "Ila")                    # quem escreveu

    def test_toda_mensagem_comeca_com_o_nome_do_agente(self):
        canal = self.canal()                                  # um papel só: sem o papel
        canal.processar(texto("oi", mid="m1"))
        canal.processar({"from": SEM_NOVE, "id": "m2", "type": "image", "image": {"id": "x"}})
        with mock.patch.object(self.agente, "receber", side_effect=RuntimeError("x")), \
                self.assertLogs("conselho_fiscal.agente.whatsapp", "ERROR"):
            canal.processar(texto("oi", mid="m3"))
        longa = mensagem("x" * (wa.MAX_TEXTO + 10))
        with mock.patch.object(self.agente, "receber", return_value=[longa]):
            canal.processar(texto("oi", mid="m4"))
        self.assertEqual(set(self.meta.cabecalhos()), {"*Elo*"})
        self.assertEqual(len(self.meta.brutos()), 5)            # a longa saiu em duas partes
        self.assertTrue(all(len(t) <= wa.MAX_TEXTO for t in self.meta.brutos()))
        self.assertEqual(self.meta.textos()[1:3], [wa.SO_DOCUMENTO, wa.FALHA])

    def test_primeiro_contato_pede_o_nome(self):
        canal = self.canal(nome=None)
        canal.processar(texto("oi", mid="m1"))
        self.assertEqual(self.meta.textos(), [wa.BOAS_VINDAS])
        self.assertTrue(wa.BOAS_VINDAS.startswith("👋 Olá! Sou o *Elo*, o assistente do "
                                                  "Conselho Fiscal."))
        self.assertEqual(self.agente.conversa("tesouraria"), [])        # ainda não conversou
        canal.processar(texto("bom dia", mid="m2"))                      # não é nome
        self.assertEqual(self.meta.textos()[-1], wa.NOME_DE_NOVO)
        canal.processar(texto("ila pedra", mid="m3"))
        self.assertTrue(self.meta.textos()[-1].startswith("Oi, *Ila Pedra*!"))
        self.assertEqual(canal._nome(EU), "Ila Pedra")
        canal.processar(texto("meu nome é Ila Clara", mid="m4"))       # troca o nome
        self.assertTrue(self.meta.textos()[-1].startswith("Oi, *Ila Clara*!"))

    def test_documento_antes_do_nome(self):
        self.meta.arquivos["mid1"] = b"abc"
        canal = self.canal(nome=None)
        for i in (1, 2):                                   # dois juntos: um pedido de nome só
            canal.processar({"from": SEM_NOVE, "id": f"m{i}", "type": "document",
                             "document": {"id": "mid1", "filename": "a.pdf",
                                          "mime_type": "application/pdf"}})
        canal.esvaziar()
        self.assertEqual(self.meta.textos(), [wa.BOAS_VINDAS + wa.REENVIAR])
        self.assertFalse((self.arm.base / "envio").exists())           # nada guardado

    def test_dois_papeis_escolhe_por_botao(self):
        canal = self.canal({EU: ("tesouraria", "cf")}, nome=None)
        canal.processar(texto("oi", mid="m1"))
        canal.processar(texto("Ila", mid="m2"))
        escolha = self.meta.enviadas[-1][1]["interactive"]
        self.assertIn("Como você quer seguir?", escolha["body"]["text"])
        self.assertEqual([b["reply"]["id"] for b in escolha["action"]["buttons"]],
                         ["papel:tesouraria", "papel:cf"])
        canal.processar({"from": SEM_NOVE, "id": "m3", "type": "interactive",
                         "interactive": {"type": "button_reply", "button_reply":
                                         {"id": "papel:cf", "title": "Conselho Fiscal"}}})
        menu = self.meta.textos()[-1]
        self.assertTrue(menu.startswith("Oi, *Ila*! Você está como *Conselho Fiscal*."))
        self.assertEqual(self.meta.cabecalhos()[-1], "*Elo* · _Conselho Fiscal_")
        botoes = [b["reply"]["title"] for b in
                  self.meta.enviadas[-1][1]["interactive"]["action"]["buttons"]]
        self.assertEqual(botoes, ["Como funciona", "Trocar de papel"])

    def test_espaco_proprio(self):
        """Cada número com o seu espaço: a conversa de um não segue no outro."""
        destinos, vinculos = cadastros_temp()
        outro = Agente(Armazenamento(pasta_temp("teste_wa_")), destinos, vinculos)
        canal = self.canal({EU: ("tesouraria",), OUTRO: ("tesouraria",)}, {OUTRO: outro})
        canal.processar(texto("oi", de=EU, mid="m1"))
        canal.processar(texto("bom dia", de=OUTRO, mid="m2"))
        self.assertEqual([m["texto"] for m in self.agente.conversa("tesouraria")
                          if m["de"] == "tesouraria"], ["oi"])
        self.assertEqual([m["texto"] for m in outro.conversa("tesouraria")
                          if m["de"] == "tesouraria"], ["bom dia"])
        self.assertEqual(canal._nome(OUTRO), "Ila")      # o nome fica no canal, para os dois
        self.assertEqual({p for p, _ in self.meta.enviadas}, {EU, OUTRO})

    def test_forma_do_aviso_quando_a_meta_recusa_a_do_cadastro(self):
        self.meta.fora_da_lista = {EU}
        canal = self.canal()
        canal.processar(texto("oi", mid="m1"))
        canal.processar(texto("oi", mid="m2"))
        self.assertEqual({p for p, _ in self.meta.enviadas}, {SEM_NOVE})
        self.assertEqual(canal._destino, {EU: SEM_NOVE})        # lembra a que funcionou

    def test_fora_da_lista_nas_duas_formas_vai_para_o_log(self):
        self.meta.fora_da_lista = {EU, SEM_NOVE}
        with self.assertLogs("conselho_fiscal.agente.whatsapp", "ERROR"):
            self.canal().processar(texto("oi"))
        self.assertEqual(self.meta.enviadas, [])

    def test_aviso_repetido_e_ignorado(self):
        canal = self.canal()
        canal.processar(texto("oi"))
        n = len(self.meta.enviadas)
        canal.processar(texto("oi"))
        self.assertEqual(len(self.meta.enviadas), n)

    def test_numero_desconhecido_e_ignorado(self):
        with self.assertLogs("conselho_fiscal.agente.whatsapp", "WARNING"):
            self.canal().processar(texto("oi", de="5511900000000"))
        self.assertEqual((self.meta.enviadas, self.meta.lidas), ([], []))
        self.assertEqual(self.agente.conversa("tesouraria"), [])

    def test_troca_de_papel(self):
        canal = self.canal({EU: ("tesouraria", "cf")})
        canal.processar(texto("oi", mid="m1"))
        self.assertEqual(self.meta.cabecalhos()[-1], "*Elo* · _Tesouraria_")
        canal.processar(texto("#CF", mid="m2"))
        self.assertTrue(self.meta.textos()[-1].startswith("Oi, *Ila*! Você está como "
                                                          "*Conselho Fiscal*."))
        canal.processar(texto("oi", mid="m3"))
        self.assertEqual(self.meta.cabecalhos()[-1], "*Elo* · _Conselho Fiscal_")
        self.assertEqual(len(self.agente.conversa("cf")), 3)            # menu, oi e menu
        canal.processar({"from": SEM_NOVE, "id": "m4", "type": "interactive",
                         "interactive": {"type": "button_reply", "button_reply":
                                         {"id": "papel:trocar", "title": "Trocar de papel"}}})
        self.assertIn("Como você quer seguir?", self.meta.textos()[-1])
        # o papel da vez fica guardado
        self.assertEqual(self.arm.estado_canal("whatsapp", {})["papel"], {EU: "cf"})

    def test_troca_so_para_quem_tem_os_dois_papeis(self):
        self.canal().processar(texto("#cf"))
        self.assertEqual(len(self.agente.conversa("cf")), 0)
        self.assertIn("não está cadastrado como *Conselho Fiscal*", self.meta.textos()[-1])

    def test_troca_de_papel_por_escrito(self):
        canal = self.canal({EU: ("tesouraria", "cf")})
        canal.processar(texto("troque para o conselho fiscal", mid="m1"))
        self.assertTrue(self.meta.textos()[-1].startswith("Oi, *Ila*! Você está como "
                                                          "*Conselho Fiscal*."))
        canal.processar(texto("Passa pra tesouraria, por favor", mid="m2"))
        self.assertIn("Você está como *Tesouraria*", self.meta.textos()[-1])
        canal.processar(texto("quero trocar de papel", mid="m3"))
        self.assertIn("Como você quer seguir?", self.meta.textos()[-1])
        self.assertEqual(len(self.agente.conversa("cf")), 1)            # só o menu

    def test_troca_entendida_pela_ia(self):
        canal = self.canal({EU: ("tesouraria", "cf")})
        m = {"de": "agente", "texto": "Você está como Tesouraria.", "anexos": [], "botoes": [],
             "trocar_papel": "cf"}
        with mock.patch.object(self.agente, "receber", return_value=[m]):
            canal.processar(texto("quero ver como o conselho", mid="m1"))
        self.assertIn("Você está como *Conselho Fiscal*", self.meta.textos()[-1])
        self.assertEqual(self.arm.estado_canal("whatsapp", {})["papel"], {EU: "cf"})

    def test_saudacao_antes_do_nome(self):
        canal = self.canal(nome=None)
        canal.processar(texto("oi", mid="m1"))                         # pede o nome
        canal.processar(texto("Oi, sou a Bia", mid="m2"))
        self.assertEqual(canal._nome(EU), "Bia")

    def test_pede_troca(self):
        casos = {"troque para o conselho fiscal": "cf", "muda pro CF": "cf",
                 "quero ser da tesouraria": "tesouraria", "como conselho fiscal": "cf",
                 "Volta para a Tesouraria!": "tesouraria", "trocar de papel": "trocar",
                 "conselho fiscal": None, "trocar": None,
                 "a tesouraria trocou o recibo do conselho": None,
                 "foi pago pela tesouraria para o conselho": None,
                 "quanto o conselho fiscal recebeu em julho?": None}
        for frase, esperado in casos.items():
            self.assertEqual(wa.pede_troca(frase), esperado, frase)

    def test_documento(self):
        self.meta.arquivos["mid1"] = b"abc"
        canal = self.canal()
        canal.processar({"from": SEM_NOVE, "id": "m1", "type": "document",
                         "document": {"id": "mid1", "filename": "notas fiscais.txt",
                                      "mime_type": "text/plain"}})
        self.assertEqual(self.meta.textos(), [])           # espera outros arquivos
        canal.esvaziar()
        self.assertIn('Não usei "notas fiscais.txt"', self.meta.textos()[0])
        self.assertEqual(self.agente.conversa("tesouraria")[0]["anexos"],
                         [{"nome": "notas fiscais.txt"}])

    def test_imagem_pede_documento(self):
        self.canal().processar({"from": SEM_NOVE, "id": "m1", "type": "image",
                                "image": {"id": "x"}})
        self.assertEqual(self.meta.textos(), [wa.SO_DOCUMENTO])

    def test_botao(self):
        with mock.patch.object(self.agente, "receber", return_value=[]) as receber:
            self.canal().processar({"from": SEM_NOVE, "id": "m1", "type": "interactive",
                                    "interactive": {"type": "button_reply", "button_reply":
                                                    {"id": "ia_ok", "title": "Está certo"}}})
            self.canal().processar({"from": SEM_NOVE, "id": "m2", "type": "interactive",
                                    "interactive": {"type": "list_reply", "list_reply":
                                                    {"id": "d3", "title": "Fulana"}}})
        self.assertEqual(receber.call_args_list, [
            mock.call("tesouraria", botao="ia_ok", rotulo="Está certo", autor="Ila", extras=[]),
            mock.call("tesouraria", botao="d3", rotulo="Fulana", autor="Ila", extras=[])])

    def test_anexo_enviado_como_documento(self):
        (self.arm.base / "meses").mkdir()
        (self.arm.base / "meses" / "a.xlsx").write_bytes(b"planilha")
        m = mensagem("Pacote", anexos=[{"nome": "a.xlsx", "caminho": "meses/a.xlsx"}])
        with mock.patch.object(self.agente, "receber", return_value=[m]):
            self.canal().processar(texto("julho"))
        self.assertEqual(self.meta.subidas, [("a.xlsx", b"planilha")])
        self.assertEqual(self.meta.enviadas[-1][1],
                         {"type": "document", "document": {"id": "midia-1", "filename": "a.xlsx"}})

    def test_falha_ao_subir_anexo_avisa(self):
        (self.arm.base / "a.xlsx").write_bytes(b"x")
        self.meta.falhar_subida = True
        m = mensagem("Pacote", anexos=[{"nome": "a.xlsx", "caminho": "a.xlsx"}])
        with mock.patch.object(self.agente, "receber", return_value=[m]), \
                self.assertLogs("conselho_fiscal.agente.whatsapp", "WARNING"):
            self.canal().processar(texto("julho"))
        self.assertIn("Não consegui enviar o arquivo *a.xlsx*", self.meta.textos()[-1])

    def test_entrega_sem_arquivo_e_desfeita(self):
        (self.arm.base / "a.xlsx").write_bytes(b"x")
        m = mensagem("Pacote", anexos=[{"nome": "a.xlsx", "caminho": "a.xlsx"}])
        m["entrega"] = {"mes": "2026-06", "n": 1}
        with mock.patch.object(self.agente, "receber", return_value=[m]), \
                mock.patch.object(self.agente, "entrega_falhou") as falhou:
            self.canal().processar(texto("junho", mid="e1"))
            falhou.assert_not_called()                              # chegou: fica registrada
            self.meta.falhar_subida = True
            with self.assertLogs("conselho_fiscal.agente.whatsapp", "WARNING"):
                self.canal().processar(texto("junho", mid="e2"))
        falhou.assert_called_once_with({"mes": "2026-06", "n": 1})

    def test_entrega_desfeita_se_o_envio_cai(self):
        m = mensagem("Pacote")
        m["entrega"] = {"mes": "2026-06", "n": 1}
        with mock.patch.object(self.agente, "receber", return_value=[m]), \
                mock.patch.object(self.agente, "entrega_falhou") as falhou, \
                mock.patch.object(wa.WhatsApp, "_enviar", side_effect=wa.ErroMeta("x", 1)), \
                self.assertLogs("conselho_fiscal.agente.whatsapp", "ERROR"):
            self.canal().processar(texto("junho"))
        falhou.assert_called_once_with({"mes": "2026-06", "n": 1})

    def documento(self, mid, nome):
        self.meta.arquivos[f"midia-{mid}"] = nome.encode()
        return {"from": SEM_NOVE, "id": mid, "type": "document",
                "document": {"id": f"midia-{mid}", "filename": nome,
                             "mime_type": "application/pdf"}}

    def test_arquivos_juntos_tem_uma_resposta_so(self):
        canal = self.canal()
        canal.janela = 0.2
        with mock.patch.object(self.agente, "receber_arquivos",
                               return_value=[mensagem("✅ três")]) as juntos:
            for mid, nome in (("a", "entradas.xlsx"), ("b", "cora.pdf"), ("c", "stone.pdf")):
                canal.processar(self.documento(mid, nome))
            self.assertEqual(self.meta.textos(), [])
            import time
            time.sleep(0.5)                                # a espera acaba sozinha
        juntos.assert_called_once_with([("entradas.xlsx", b"entradas.xlsx"),
                                        ("cora.pdf", b"cora.pdf"), ("stone.pdf", b"stone.pdf")],
                                       "Ila", [])
        self.assertEqual(self.meta.textos(), ["✅ três"])
        self.assertEqual(self.meta.lidas, ["a", "b", "c"])  # lidos na hora

    def test_texto_depois_dos_arquivos_espera_eles(self):
        canal = self.canal()
        canal.janela = 60                                   # a espera não acabaria
        eco = lambda papel, texto=None, **_: [mensagem(f"resposta à {texto}")]  # noqa: E731
        with mock.patch.object(self.agente, "receber_arquivos",
                               return_value=[mensagem("✅ dois")]), \
                mock.patch.object(self.agente, "receber", side_effect=eco):
            canal.processar(self.documento("a", "cora.pdf"))
            canal.processar(self.documento("b", "stone.pdf"))
            canal.processar(texto("oi", mid="t"))
        self.assertEqual(self.meta.textos(), ["✅ dois", "resposta à oi"])
        self.assertEqual(canal._lotes, {})

    def test_respostas_na_ordem_das_mensagens(self):
        """Caso real (2026-10-23): planilha e Cora seguidos; a resposta do Cora
        saiu antes, porque o envio da primeira ainda não tinha terminado."""
        import threading
        import time
        canal = self.canal()
        enviar = self.meta.enviar

        def enviar_devagar(para, conteudo):
            if "primeira" in json.dumps(conteudo, ensure_ascii=False):
                time.sleep(0.3)                     # a Meta demorou na primeira
            enviar(para, conteudo)

        def eco(papel, texto=None, **_):
            return [mensagem(f"resposta à {texto}")]

        with mock.patch.object(self.meta, "enviar", enviar_devagar), \
                mock.patch.object(self.agente, "receber", side_effect=eco):
            a = threading.Thread(target=canal.processar, args=(texto("primeira", mid="a"),))
            a.start()
            time.sleep(0.05)
            b = threading.Thread(target=canal.processar, args=(texto("segunda", mid="b"),))
            b.start()
            a.join()
            b.join()
        self.assertEqual(self.meta.textos(), ["resposta à primeira", "resposta à segunda"])

    def test_erro_no_agente_avisa_e_nao_levanta(self):
        with mock.patch.object(self.agente, "receber", side_effect=RuntimeError("x")), \
                self.assertLogs("conselho_fiscal.agente.whatsapp", "ERROR"):
            self.canal().processar(texto("oi"))
        self.assertEqual(self.meta.textos(), [wa.FALHA])

    def test_mensagens_e_status(self):
        aviso = {"entry": [{"changes": [{"value": {
            "messages": [texto("oi")],
            "statuses": [{"id": "s1", "status": "failed", "errors": [{"code": 131047}]},
                         {"id": "s2", "status": "delivered"}]}}]}]}
        with self.assertLogs("conselho_fiscal.agente.whatsapp", "WARNING") as logs:
            self.assertEqual(self.canal().mensagens(aviso), [texto("oi")])
        self.assertEqual(len(logs.records), 1)


@unittest.skipIf(TestClient is None, "fastapi/httpx não instalados")
class TestWebhook(unittest.TestCase):
    def setUp(self):
        destinos, vinculos = cadastros_temp()
        self.agente = Agente(Armazenamento(pasta_temp("teste_wa_")), destinos, vinculos)
        self.meta = MetaFalsa()
        canal = wa.WhatsApp(self.agente, self.meta, self.meta.cfg.contatos)
        canal._guardar_nome(EU, "Ila")
        self.cliente = TestClient(criar_app(self.agente, simulador=False, whatsapp=canal))

    def assinar(self, corpo: bytes) -> dict[str, str]:
        return {"X-Hub-Signature-256": "sha256=" + hmac.new(
            SEGREDO.encode(), corpo, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}

    def test_verificacao(self):
        q = {"hub.mode": "subscribe", "hub.verify_token": "verifica", "hub.challenge": "42"}
        r = self.cliente.get("/whatsapp", params=q)
        self.assertEqual((r.status_code, r.text), (200, "42"))
        q["hub.verify_token"] = "errado"
        self.assertEqual(self.cliente.get("/whatsapp", params=q).status_code, 403)

    def test_aviso_assinado_e_processado(self):
        corpo = json.dumps({"entry": [{"changes": [{"value": {
            "messages": [texto("oi")]}}]}]}).encode()
        r = self.cliente.post("/whatsapp", content=corpo, headers=self.assinar(corpo))
        self.assertEqual(r.json(), {"ok": True})
        self.assertIn("*envie* o registro de receitas da tesouraria", self.meta.textos()[0])

    def test_assinatura_errada_e_recusada(self):
        corpo = json.dumps({"entry": []}).encode()
        cab = self.assinar(corpo)
        r = self.cliente.post("/whatsapp", content=corpo + b" ", headers=cab)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.cliente.post("/whatsapp", content=corpo).status_code, 403)
        self.assertEqual(self.meta.enviadas, [])

    def test_sem_whatsapp_nao_ha_webhook(self):
        cliente = TestClient(criar_app(self.agente, simulador=False))
        self.assertEqual(cliente.get("/whatsapp").status_code, 404)


if __name__ == "__main__":
    unittest.main()
