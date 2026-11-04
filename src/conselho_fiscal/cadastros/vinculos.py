"""Cadastro de vínculos confirmados pela tesouraria (vinculos_confirmados.json).

Nenhum vínculo entre nomes diferentes é automático (decisão de 2026-10-06).
Quando a tesouraria confirma que Pix de uma conta (ex.: uma empresa) pagaram
recibos de uma pessoa, a confirmação é guardada aqui e, nos meses seguintes,
vira o critério mais forte de SUGESTÃO — continua precisando de confirmação.
Contém dados pessoais: cada confirmação é apagada após 2 anos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from conselho_fiscal import config
from conselho_fiscal.cadastros import MESES_GUARDA
from conselho_fiscal.comum.valores import indice_mes


class VinculoConfirmado(TypedDict):
    nome_extrato: str
    pessoa: str
    confirmado_em: str      # AAAA-MM
    observacao: str


def carregar(caminho: str | Path | None = None) -> list[VinculoConfirmado]:
    caminho = caminho or config.caminho_vinculos_confirmados()
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _salvar(vinculos: list[VinculoConfirmado], caminho: str | Path) -> None:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(vinculos, f, ensure_ascii=False, indent=2)
        f.write("\n")


def registrar(nome_extrato: str, pessoa: str, mes: str, observacao: str = "",
              caminho: str | Path | None = None) -> None:
    """Para o agente: a tesouraria confirmou que Pix da conta `nome_extrato`
    pagaram recibo de `pessoa` no mês `mes` (AAAA-MM). A mesma confirmação
    (conta, pessoa e mês) não é gravada duas vezes."""
    caminho = caminho or config.caminho_vinculos_confirmados()
    vinculos = carregar(caminho)
    if any((v["nome_extrato"], v["pessoa"], v["confirmado_em"]) == (nome_extrato, pessoa, mes)
           for v in vinculos):
        return
    vinculos.append({"nome_extrato": nome_extrato, "pessoa": pessoa,
                     "confirmado_em": mes, "observacao": observacao})
    _salvar(vinculos, caminho)


def remover(nome_extrato: str, pessoa: str, mes: str, observacao: str | None = None,
            caminho: str | Path | None = None) -> bool:
    """Para o agente: desfaz o registro de uma confirmação (a tesouraria
    corrigiu a resposta). Com `observacao`, só apaga o registro com essa
    observação (o que o próprio agente gravou). Retorna se apagou algo."""
    caminho = caminho or config.caminho_vinculos_confirmados()
    vinculos = carregar(caminho)

    def alvo(v: VinculoConfirmado) -> bool:
        return ((v["nome_extrato"], v["pessoa"], v["confirmado_em"]) == (nome_extrato, pessoa, mes)
                and (observacao is None or v["observacao"] == observacao))

    restantes = [v for v in vinculos if not alvo(v)]
    if len(restantes) == len(vinculos):
        return False
    _salvar(restantes, caminho)
    return True


def limpar(mes: str | None, caminho: str | Path | None = None,
           meses: int = MESES_GUARDA) -> list[VinculoConfirmado]:
    """Apaga confirmações com `meses` meses ou mais, contados a partir do mês
    da conferência (ex.: em 2028-07 somem as de 2026-07 e anteriores).
    Retorna as confirmações apagadas."""
    if not mes:
        return []
    caminho = caminho or config.caminho_vinculos_confirmados()
    vinculos = carregar(caminho)
    limite = indice_mes(mes) - meses
    apagados = [v for v in vinculos if indice_mes(v["confirmado_em"]) <= limite]
    if apagados:
        _salvar([v for v in vinculos if indice_mes(v["confirmado_em"]) > limite], caminho)
    return apagados
