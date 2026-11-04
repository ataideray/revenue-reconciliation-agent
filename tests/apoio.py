"""Funções de apoio comuns aos testes."""

from __future__ import annotations

import atexit
import os
import re
import shutil
import tempfile

from openpyxl import Workbook, load_workbook

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CADASTRO_DESTINOS = os.path.join(RAIZ, "cadastros", "destinos.json")

_PASTAS: list[str] = []


def pasta_temp(prefixo: str = "teste_") -> str:
    """Pasta temporária apagada ao fim da execução dos testes."""
    d = tempfile.mkdtemp(prefix=prefixo)
    _PASTAS.append(d)
    return d


@atexit.register
def _apagar_pastas() -> None:
    for d in _PASTAS:
        shutil.rmtree(d, ignore_errors=True)


def opcoes(mensagem: dict) -> list[dict]:
    """Opções de uma mensagem do agente: os botões ou os itens da lista."""
    return mensagem["botoes"] + (mensagem["lista"]["itens"] if mensagem.get("lista") else [])


def sem_marcas(texto: str) -> str:
    """O texto sem o *negrito* e o _itálico_ (como o simulador os reconhece)."""
    texto = re.sub(r"\*([^*\n]+)\*", r"\1", texto)
    return re.sub(r"(^|[^\w])_([^_\n]+)_(?!\w)", r"\1\2", texto, flags=re.M)


def conferir_whatsapp(teste, mensagens: list[dict]) -> list[dict]:
    """As mensagens respeitam os limites do WhatsApp: até 3 botões de até 20
    caracteres, ou uma lista de até 10 opções de até 24 (descrição até 72), e
    as marcas fecham na mesma linha, sem espaço por dentro. Devolve cópias
    com o texto sem as marcas, para os testes conferirem o conteúdo (a
    formatação tem testes próprios)."""
    for m in mensagens:
        for linha in m["texto"].split("\n"):
            teste.assertEqual(linha.count("*") % 2, 0, linha)
            teste.assertNotRegex(linha, r"(^|\s)\*\s|\s\*($|[\s.,:;])", linha)
        teste.assertLessEqual(len(m["botoes"]), 3, m["texto"])
        teste.assertTrue(all(len(b["rotulo"]) <= 20 for b in m["botoes"]), m["botoes"])
        if m.get("lista"):
            teste.assertEqual(m["botoes"], [])
            teste.assertLessEqual(len(m["lista"]["abrir"]), 20)
            teste.assertLessEqual(len(m["lista"]["itens"]), 10)
            for item in m["lista"]["itens"]:
                teste.assertLessEqual(len(item["rotulo"]), 24, item)
                teste.assertLessEqual(len(item.get("descricao", "")), 72, item)
    return [dict(m, texto=sem_marcas(m["texto"])) for m in mensagens]


def cadastros_temp() -> tuple[str, str]:
    """Cópia do cadastro de destinos e um cadastro de vínculos vazio: nenhum
    teste altera os cadastros reais."""
    d = pasta_temp("teste_cadastros_")
    destinos = shutil.copy(CADASTRO_DESTINOS, d)
    vinculos = os.path.join(d, "vinculos_confirmados.json")
    with open(vinculos, "w", encoding="utf-8") as f:
        f.write("[]\n")
    return destinos, vinculos


def abas(caminho: str) -> dict[str, list[tuple]]:
    """Conteúdo (valores) de todas as abas de uma planilha."""
    wb = load_workbook(caminho)
    return {nome: list(wb[nome].iter_rows(values_only=True)) for nome in wb.sheetnames}


def planilha_tesouraria(caminho: str, recibos: list[tuple], resumo: dict | None = None) -> str:
    """Monta uma planilha de lançamentos fictícia no formato da tesouraria.

    recibos: [(data, numero, nome, [(descricao, valor), ...]), ...]; o Total
    é a soma dos itens, a menos que o recibo traga um 5º elemento (total).
    resumo: {"Total de Receitas": x, ...}; None = sem aba Resumo.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Receitas"
    ws.append(["Data", "Número", "Nome", "Descrição", "Valor"])
    for r in recibos:
        data, numero, nome, itens = r[:4]
        total = r[4] if len(r) > 4 else sum(v for _, v in itens)
        ws.append([data, numero, nome, "Total", total])
        for desc, valor in itens:
            ws.append([None, None, None, desc, valor])
        ws.append([None, None, None, None, None])
    if resumo is not None:
        wr = wb.create_sheet("Resumo")
        wr.append(["Indicador", "Valor"])
        for k, v in resumo.items():
            wr.append([k, v])
    wb.save(caminho)
    return caminho
