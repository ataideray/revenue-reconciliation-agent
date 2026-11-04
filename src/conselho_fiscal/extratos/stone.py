"""Leitura do extrato Stone (PDF -> transações) e conferência da leitura.

No `pdftotext -layout`, cada transação da Stone ocupa algumas linhas: o nome
do pagador (às vezes quebrado acima da linha da data), a linha
'DD/MM/AA Tipo … R$ valor R$ saldo' e a linha de categoria
('Transferência | Pix', 'Rendimento', 'Pagamento'), que é sempre a última.
"""

from __future__ import annotations

import re

from conselho_fiscal.comum.texto import espacos_simples
from conselho_fiscal.comum.valores import brl, valor_extrato
from conselho_fiscal.extratos.modelo import Transacao, Verificacao

DATA_RE = re.compile(r"(\d{2}/\d{2}/\d{2})\s+(Entrada|Sa[ií]da)")
VALOR_RE = re.compile(r"(-\s*)?R\$\s*([\d.]+,\d{2})\s+R\$\s*([\d.]+,\d{2})")
# alternativa: valor e saldo separados pela categoria (quebra de linha)
VALOR_PARTIDO_RE = re.compile(
    r"(-\s*)?R\$\s*([\d.]+,\d{2})\s+Transferência \| Pix\s+R\$\s*([\d.]+,\d{2})")
CATEGORIA_RE = re.compile(r"(Transferência \| Pix|Rendimento|Pagamento)")
# linha que começa com a categoria: é sempre a ÚLTIMA linha de uma transação
LINHA_CATEGORIA = re.compile(r"^(Transferência \| Pix|Pagamento|Rendimento|automático)\b")
LINHA_SO_CATEGORIA = re.compile(r"^(Transferência \| Pix|Pagamento|Rendimento|automático)$")

# Cabeçalho/rodapé reconhecidos pela LINHA INTEIRA (espaços normalizados),
# nunca pelo começo da linha: um pagador "DATAVALE…" ou "Contabilidade…" não
# pode ser confundido com "DATA TIPO…" ou "Conta" (B6). Nada aqui depende de
# dados da associação.
PERIODO_RE = re.compile(r"^Período: de \d{2}/\d{2}/\d{4} a \d{2}/\d{2}/\d{4}$")
CABECALHO_PAGINA = (
    re.compile(r"^Extrato de conta( corrente)?$"),
    re.compile(r"^corrente$"),
    re.compile(r"^Emitido em \d{1,2} \w+ \d{4} às \d{2}:\d{2}:\d{2}( Página \d+ de \d+)?$"),
    re.compile(r"^Página \d+ de \d+$"),
    PERIODO_RE,
    re.compile(r"^DATA TIPO DESCRIÇÃO VALOR SALDO( CONTRAPARTE)?$"),
)
# início do rodapé final (comprovante, ouvidoria, contatos): sem transações depois
INICIO_RODAPE = "Informações do Comprovante"
# rendimento automático genuíno é sempre centavos; acima disso, é sinal de
# Pix com nome perdido na leitura
LIMIAR_RENDIMENTO = 2.00


def filtrar_linhas(texto: str) -> tuple[list[str], list[tuple[str, str]], bool]:
    """Remove cabeçalho e rodapé sem tocar nas transações.

    Retorna (linhas mantidas, linhas descartadas com o motivo, layout
    reconhecido). Cabeçalho da conta: tudo antes do 1º 'Período: de … a …'.
    Rodapé final: de 'Informações do Comprovante' até o fim, se não houver
    transação depois. Entre os dois, só linhas que batem INTEIRAS com
    CABECALHO_PAGINA. Sem os marcadores, nada é cortado nessa zona e o layout
    é dado como não reconhecido (vira alerta, não erro).
    """
    brutas = texto.splitlines()
    compactas = [espacos_simples(ln) for ln in brutas]
    ini = next((i for i, c in enumerate(compactas) if PERIODO_RE.match(c)), None)
    fim = next((i for i, c in enumerate(compactas)
                if c == INICIO_RODAPE and i > (ini or 0)
                and not any(DATA_RE.search(x) for x in compactas[i:])), None)
    reconhecido = ini is not None and fim is not None
    ini = 0 if ini is None else ini
    fim = len(brutas) if fim is None else fim

    mantidas, descartadas = [], []
    for i, c in enumerate(compactas):
        if i < ini:
            if c:
                descartadas.append(("cabeçalho da conta", c))
        elif i >= fim:
            if c:
                descartadas.append(("rodapé final", c))
        elif any(rx.match(c) for rx in CABECALHO_PAGINA):
            descartadas.append(("cabeçalho de página", c))
        else:
            mantidas.append(brutas[i].strip())
    return mantidas, descartadas, reconhecido


def _transacao_completa(linhas: list[str]) -> bool:
    junto = " ".join(linhas)
    return bool(DATA_RE.search(junto)
                and (VALOR_RE.search(junto) or VALOR_PARTIDO_RE.search(junto)))


def _separar_transacoes(paragrafo: list[str]) -> list[list[str]]:
    """Corta o parágrafo logo após a linha de categoria de uma transação já
    completa, desde que reste outra data adiante. A Stone nem sempre põe
    linha em branco entre transações; sem isso, só a 1ª era lida (B1)."""
    partes, atual = [], []
    for i, s in enumerate(paragrafo):
        atual.append(s)
        if (LINHA_CATEGORIA.match(s) and _transacao_completa(atual)
                and DATA_RE.search(" ".join(paragrafo[i + 1:]))):
            partes.append(atual)
            atual = []
    if atual:
        partes.append(atual)
    return partes


def extrair_blocos(texto: str) -> list[list[str]]:
    """Agrupa o texto do extrato em blocos de linhas, um por transação."""
    linhas, _, _ = filtrar_linhas(texto)

    paragrafos, atual = [], []
    for s in linhas:
        if s == "":
            if atual:
                paragrafos.append(atual)
                atual = []
        else:
            atual.append(s)
    if atual:
        paragrafos.append(atual)

    partes = [parte for p in paragrafos for parte in _separar_transacoes(p)]

    # funde partes até formar um bloco completo (transação cortada por quebra
    # de página); categoria solta no início pertence à transação anterior
    blocos, buf = [], []
    for p in partes:
        while not buf and blocos and p and LINHA_SO_CATEGORIA.match(p[0]):
            blocos[-1].append(p[0])
            p = p[1:]
        buf += p
        if _transacao_completa(buf):
            blocos.append(list(buf))
            buf = []
    if buf:
        blocos.append(buf)
    return blocos


def _pagina(bloco: list[str], paginas: list[str], desde: int) -> int | None:
    """A página (índice em `paginas`) da linha da data da transação, a partir
    de `desde` (as transações vêm em ordem); None se não achar."""
    linha = next((s for s in bloco if DATA_RE.search(s)), None)
    if linha is None:
        return None
    for i in list(range(desde, len(paginas))) + list(range(desde)):
        if linha in paginas[i]:
            return i
    return None


def ler_transacoes(texto: str) -> list[Transacao]:
    """Texto do PDF (pdftotext -layout) -> transações, na ordem do extrato."""
    transacoes: list[Transacao] = []
    paginas = texto.split("\f")          # o pdftotext separa as páginas com \f
    atual = 0
    for bloco in extrair_blocos(texto):
        junto = " ".join(bloco)
        mv = VALOR_RE.search(junto) or VALOR_PARTIDO_RE.search(junto)
        md = DATA_RE.search(junto)
        if not mv or not md:
            continue
        negativo = mv.group(1) is not None
        valor = valor_extrato(mv.group(2))

        categoria = ""
        mc = CATEGORIA_RE.search(junto)
        if mc:
            categoria = "Transferência Pix" if mc.group(1).startswith("Transfer") else mc.group(1)

        # nome = texto sem data+tipo, valores e categoria
        nome = DATA_RE.sub(" ", junto)
        nome = VALOR_PARTIDO_RE.sub(" ", nome)
        nome = VALOR_RE.sub(" ", nome)
        nome = CATEGORIA_RE.sub(" ", nome)
        nome = re.sub(r"\s+", " ", nome).strip()
        if categoria == "Rendimento":
            nome = (f"[REVISAR — possível Pix não identificado, R$ {valor:.2f}]"
                    if valor > LIMIAR_RENDIMENTO else "Rendimento automático")

        i = _pagina(bloco, paginas, atual)
        atual = atual if i is None else i
        transacoes.append({
            "banco": "Stone", "data": md.group(1),
            "tipo": "Saída" if md.group(2).startswith("Sa") else "Entrada",
            "nome": nome, "documento": "", "categoria": categoria,
            "entrada": 0.0 if negativo else valor,
            "saida": valor if negativo else 0.0,
            "saldo": valor_extrato(mv.group(3)),
            "pagina": None if i is None else i + 1,
        })
    return transacoes


def quebras_saldo(transacoes: list[Transacao]) -> list[Transacao]:
    """Transações (em ordem cronológica) em que saldo anterior + movimento
    não dá o saldo impresso: indicam transação perdida ou lida errado."""
    cronologica = transacoes[::-1]
    return [atual for anterior, atual in zip(cronologica, cronologica[1:])
            if abs(anterior["saldo"] + atual["entrada"] - atual["saida"] - atual["saldo"]) > 0.01]


def saldo_fecha(transacoes: list[Transacao]) -> bool:
    return not quebras_saldo(transacoes)


def verificar_leitura(texto: str, transacoes: list[Transacao]) -> list[Verificacao]:
    """Confere a leitura contra o próprio PDF.

    1) Nº de transações no PDF (linhas 'DD/MM/AA Entrada|Saída') × lidas.
    2) Só cabeçalho e rodapé foram descartados, e o layout foi reconhecido.
    3) Cadeia de saldos; num ALERTA, aponta onde ela quebra.
    """
    n_pdf, n_lido = len(DATA_RE.findall(texto)), len(transacoes)
    verif: list[Verificacao] = [{
        "grupo": "extratos", "extrato": "Stone", "verificacao": "Nº de transações (PDF × lido)",
        "status": "OK" if n_pdf == n_lido else "ALERTA",
        "esperado": str(n_pdf), "encontrado": str(n_lido),
        "detalhe": "" if n_pdf == n_lido else
        f"{abs(n_pdf - n_lido)} transação(ões) do PDF não foram lidas — "
        "as divergências do mês podem ser erro de leitura.",
    }]

    _, descartadas, reconhecido = filtrar_linhas(texto)
    suspeitas = [c for _, c in descartadas if DATA_RE.search(c) or "R$" in c]
    detalhe = ""
    if not reconhecido:
        detalhe += ("Layout do PDF não reconhecido (faltou 'Período:' ou 'Informações do "
                    "Comprovante'): conferir os nomes dos pagadores. ")
    if suspeitas:
        detalhe += "Linhas descartadas com data/valor: " + "; ".join(suspeitas[:5])
    verif.append({
        "grupo": "extratos", "extrato": "Stone", "verificacao": "Cabeçalho/rodapé descartados",
        "status": "OK" if reconhecido and not suspeitas else "ALERTA",
        "esperado": "só cabeçalho e rodapé",
        "encontrado": f"{len(descartadas)} linha(s) descartada(s)",
        "detalhe": detalhe,
    })

    quebras = quebras_saldo(transacoes)
    pontos = [f"{t['data']} {t['nome'][:30]} ({brl(t['entrada'] - t['saida'])}, "
              f"saldo {brl(t['saldo'])})" for t in quebras[:10]]
    if len(quebras) > 10:
        pontos.append(f"… e mais {len(quebras) - 10}")
    verif.append({
        "grupo": "extratos", "extrato": "Stone", "verificacao": "Cadeia de saldos",
        "status": "ALERTA" if quebras else "OK",
        "esperado": "saldo fecha em todas as transações",
        "encontrado": f"{len(quebras)} quebra(s)" if quebras else "fecha",
        "detalhe": ("Conferir no PDF, logo antes de: " + "; ".join(pontos)) if quebras else "",
    })
    return verif
