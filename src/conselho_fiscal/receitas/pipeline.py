"""Pipeline de conferência de receitas: um único ponto de entrada (`executar`)
para o terminal, os testes e o agente.

    planilha da tesouraria ─┐
    extrato Cora (PDF) ─────┼─► conferências ─► conciliação ─► planilha + JSON
    extrato Stone (PDF) ────┘

As conferências automáticas nunca interrompem: os ALERTAS aparecem no topo
da aba Divergências, em stats['alertas'] e no JSON.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from conselho_fiscal import config
from conselho_fiscal.cadastros import destinos, vinculos
from conselho_fiscal.extratos import exportar_xlsx, ler_extrato
from conselho_fiscal.receitas import conciliacao, lancamentos, relatorio, resultado
from conselho_fiscal.receitas.pessoas import agrupar


def executar(entradas: str, cora: str, stone: str, saida: str, *, aba: str = "Receitas",
             notas: dict[str, str] | None = None,
             cadastro_destinos: str | Path | None = None,
             vinculos_confirmados: str | Path | None = None,
             saida_json: str | None = None,
             pasta_intermediarios: str | None = None) -> dict[str, Any]:
    """Roda a conferência do mês e grava a planilha (`saida`) e o JSON.

    entradas: planilha de lançamentos da tesouraria (.xlsx)
    cora, stone: extratos (PDF do banco; .xlsx já convertido sai "não verificado")
    notas: {id da divergência: nota da tesouraria}, fornecidas pelo agente
    cadastro_destinos, vinculos_confirmados: caminhos dos cadastros (padrão: config)
    saida_json: padrão = mesmo nome da planilha, com .json
    pasta_intermediarios: se informada, grava ali os extratos lidos e os
        lançamentos por recibo em .xlsx, para conferência manual

    Retorna as estatísticas, com o resultado estruturado em stats['resultado'].
    """
    cadastro_destinos = cadastro_destinos or config.caminho_destinos()
    vinculos_confirmados = vinculos_confirmados or config.caminho_vinculos_confirmados()

    df = lancamentos.carregar(entradas, aba)
    mes = lancamentos.mes_referencia(df)
    # guarda de 2 anos: vínculos antigos saem ANTES de gerar as sugestões
    vinculos_apagados = vinculos.limpar(mes, vinculos_confirmados)

    transacoes_cora, verif_cora = ler_extrato(cora, "Cora")
    transacoes_stone, verif_stone = ler_extrato(stone, "Stone")
    verificacoes = lancamentos.conferir_planilha(entradas, df) + verif_cora + verif_stone

    cadastro = destinos.carregar(cadastro_destinos)
    antes = json.dumps(cadastro, sort_keys=True)
    pivotado = lancamentos.pivotar(df, cadastro, mes)
    verificacoes.append(conciliacao.conferir_rendimentos(pivotado, transacoes_cora,
                                                         transacoes_stone))
    # colunas sem uso há 24 meses saem DEPOIS de marcar o uso deste mês
    colunas_apagadas = destinos.limpar(cadastro, mes)
    if json.dumps(cadastro, sort_keys=True) != antes:
        destinos.salvar(cadastro, cadastro_destinos)

    if pasta_intermediarios:
        os.makedirs(pasta_intermediarios, exist_ok=True)
        lancamentos.exportar_xlsx(pivotado, os.path.join(pasta_intermediarios,
                                                         "entradas_formatadas.xlsx"))
        exportar_xlsx(transacoes_cora, "Cora", os.path.join(pasta_intermediarios, "cora.xlsx"))
        exportar_xlsx(transacoes_stone, "Stone", os.path.join(pasta_intermediarios, "stone.xlsx"))

    if os.path.dirname(saida):
        os.makedirs(os.path.dirname(saida), exist_ok=True)
    stats = conciliar(pivotado, transacoes_cora, transacoes_stone, saida, verificacoes,
                      notas, vinculos.carregar(vinculos_confirmados))
    stats.update({
        "pivotados": len(pivotado["linhas"]), "colunas": pivotado["colunas"],
        "verificacoes": verificacoes, "destinos_novos": pivotado["destinos_novos"],
        "mes_referencia": mes,
        "limpeza_cadastros": {"colunas_apagadas": colunas_apagadas,
                              "vinculos_apagados": len(vinculos_apagados)},
    })
    stats["resultado"] = resultado.montar(stats, entradas, cora, stone)
    stats["saida_json"] = saida_json or os.path.splitext(saida)[0] + ".json"
    resultado.salvar(stats["resultado"], stats["saida_json"])
    return stats


def conciliar(pivotado: lancamentos.Pivotado, transacoes_cora, transacoes_stone, saida: str,
              verificacoes, notas, confirmados) -> dict[str, Any]:
    """Concilia recibos × Pix e grava a planilha final."""
    recibos = lancamentos.recibos_para_conciliacao(pivotado)
    ent_cora = conciliacao.entradas(transacoes_cora)
    ent_stone = conciliacao.entradas(transacoes_stone)
    saidas = conciliacao.saidas(transacoes_cora) + conciliacao.saidas(transacoes_stone)

    pessoas = agrupar(recibos, ent_cora + ent_stone)
    # nem vínculo entre nomes diferentes nem devolução são automáticos: só sugestões
    devolucoes = conciliacao.sugerir_devolucoes(pessoas, saidas)
    sugestoes = conciliacao.sugerir_vinculos(pessoas, confirmados, devolucoes)

    ordenadas = conciliacao.ordenar_pessoas(pessoas)
    recibos_ordenados = conciliacao.ordenar_recibos(pessoas)
    relatorio.gerar(saida, pivotado["colunas"], recibos_ordenados, ordenadas, sugestoes,
                    verificacoes, devolucoes, notas)

    conformes = sum(1 for _, rec in recibos_ordenados if rec["compat"].startswith("Conforme"))
    return {
        "recibos": len(recibos_ordenados), "pessoas": len(ordenadas),
        "ok": sum(1 for p in ordenadas if conciliacao.status_pessoa(p)[0] == "OK"),
        "conformes": conformes, "divergentes": len(recibos_ordenados) - conformes,
        "ent_cora": len(ent_cora), "ent_stone": len(ent_stone),
        "valor_cora": round(sum(e["valor"] for e in ent_cora), 2),
        "valor_stone": round(sum(e["valor"] for e in ent_stone), 2),
        "sugestoes": len(sugestoes), "devolucoes": len(devolucoes),
        "alertas": [v for v in verificacoes if v["status"] == "ALERTA"],
        "detalhes": {
            "divergencias": conciliacao.detalhar_divergencias(ordenadas, sugestoes, notas,
                                                              devolucoes),
            "devolucoes": conciliacao.publicas(devolucoes),
            "sugestoes_vinculo": conciliacao.publicas(sugestoes),
        },
    }
