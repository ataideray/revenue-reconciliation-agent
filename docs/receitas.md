# Conferência de receitas: guia de uso

Cruza a planilha de lançamentos da tesouraria com os extratos do Cora e da
Stone e gera:

- **uma planilha** para o Conselho Fiscal, com 3 abas;
- **um JSON** com o mesmo nome, para o agente.

## 1. Arquivos do mês

| Arquivo | O que é | Formato |
|---|---|---|
| Lançamentos | recibos emitidos (colunas Data, Número, Nome, Descrição, Valor) e a aba Resumo | `.xlsx`, aba "Receitas" |
| Extrato Cora | extrato do mês | **PDF do banco** |
| Extrato Stone | extrato do mês | **PDF do banco** |

O PDF do banco é a fonte oficial da conferência, porque não pode ser
editado. Um extrato já convertido em `.xlsx` também é aceito, para uso
manual, mas a leitura dele sai como **"não verificada"**.

## 2. Como rodar

```bash
conselho-fiscal receitas exemplo/2026-07/entradas.xlsx exemplo/2026-07/cora.xlsx \
                         exemplo/2026-07/stone.xlsx saidas/receitas_2026-07.xlsx
```

Opções:

```bash
--aba NomeDaAba          # se a aba de lançamentos não se chamar "Receitas"
--intermediarios PASTA   # grava também os extratos lidos e os lançamentos por recibo em .xlsx
```

## 3. O que aparece no terminal

```
[1/2] Lançamentos: 148 recibos
       Colunas de recurso: Anuidade, Cantina, Retiro, …
[2/2] Conciliação com os extratos:
       Recibos conciliados: 147
       Entradas Cora/Stone: 89 / 59
       Pessoas: 78 (OK por pessoa: 71)
       Compatibilidade: 141 conformes, 6 divergentes
       Possíveis devoluções (a confirmar com a tesouraria): 1
       Sugestões de vínculo (a confirmar com a tesouraria): 6
       Conferências automáticas (extratos e planilha da tesouraria): OK
```

Quando uma conferência automática falha, o pipeline **não para**: gera tudo
normalmente e imprime `ATENÇÃO: N alerta(s) nas conferências automáticas`.
Isso acontece em dois casos:

- a leitura de um extrato não bate com os totais e saldos impressos no PDF.
  Nesse caso, parte das divergências pode ser erro de leitura;
- a aba Resumo, ou o total de algum recibo, não bate com os lançamentos.

## 4. Regras da conferência

- **Conforme:** o recibo casou com um Pix de mesmo valor da mesma pessoa, ou
  com **2 Pix** da mesma pessoa que somam o valor (`Conforme (2 Pix)`). Esse
  segundo caso acontece quando o tesoureiro lança dois Pix da mesma coisa
  num recibo só.
- **Divergente:** recibo sem Pix correspondente.
- **Possível devolução:** Pix sem recibo seguido de uma saída de mesmo
  valor para a mesma pessoa. O pipeline **não retira** o Pix sozinho: ele
  continua nos totais e a pessoa aparece em Divergências, com a sugestão
  de devolução. O agente confirma com a tesouraria, e a resposta vai para a
  "Nota da tesouraria" (decisão de 2026-10-08). Um Pix com sugestão de
  devolução não recebe sugestão de vínculo.
- **Sugestão de vínculo:** o pipeline **nunca liga sozinho** um Pix de uma
  conta com outro nome (empresa, parente) ao recibo de alguém. Ele sugere a
  ligação, com um critério. O agente confirma com a tesouraria, e a resposta
  vai para a "Nota da tesouraria". Critérios, do mais forte para o mais
  fraco:
  1. conta já confirmada pela tesouraria em mês anterior;
  2. nome em comum (ex.: Verde) ou nome parecido (ex.: Girasol ≈ Girassol);
  3. outro Pix da mesma conta tem pista de nome com a pessoa;
  4. valor único no mês;
  5. mesmo valor, com vários recibos possíveis.
- **Continuam automáticas** só as ligações dentro da **mesma pessoa**: nome
  cortado pelo banco, acentos, ordem dos nomes e 2 Pix para um recibo.
- **Não sócio:** nome terminado em `*` na planilha da tesouraria.

## 5. A planilha de saída

1. **Receitas (reordenada):** os recibos na ordem real dos extratos (Cora,
   depois Stone), com todas as colunas de recurso e mais as colunas:
   - `compatibilidade_extrato`;
   - `Sugestão de vínculo`: a sugestão para o recibo sem Pix ou, quando a
     tesouraria já explicou a divergência da pessoa, a nota dela.

   Essa aba confere só cada recibo; os totais por pessoa ficam na aba
   seguinte.
2. **Conferência por Pessoa:** os totais de cada pessoa, com `Status` e
   `Diferença`. Quando a divergência da pessoa tem nota da tesouraria, o
   status ganha o complemento "- nota da tesouraria na aba Divergências"
   (ex.: "Divergência de valor - nota da tesouraria na aba Divergências").
3. **Divergências:** no topo ficam as conferências automáticas, uma linha
   por grupo:
   - **LEITURA DOS EXTRATOS** (6 verificações). No Cora: totais de entradas
     e saídas e o saldo de cada dia. Na Stone: nº de transações, cadeia de
     saldos e cabeçalho/rodapé descartados;
   - **PLANILHA DA TESOURARIA** (6 verificações): aba Resumo × aba Receitas,
     o total de cada recibo e os rendimentos: a soma da coluna Rendimentos
     (todos os recibos; a tesouraria lança um por rendimento ou um pelo
     mês) = a soma dos "Rendimento automático" de até R$ 2,00 dos extratos.
     Os dois lados ficam fora da conciliação recibo × Pix; acima de R$ 2,00,
     o lançamento é tratado como Pix sem nome e vira divergência.

   Cada linha fica **verde** (OK), **vermelha** (com uma linha por alerta,
   dizendo onde conferir) ou **amarela** (não verificada). Abaixo vem uma
   linha por divergência (veja abaixo), com as colunas **Pix sem recibo (no
   extrato)** (valor, banco, data e página do PDF de cada um, para achar o
   lançamento), **Sugestão (a confirmar)** e **Nota da tesouraria**. A
   sugestão pode ser um vínculo ou uma possível devolução, e também diz a
   página ("Pix R$ 130,00 (Cora, 22/07/2026, pág. 2) ↔ recibo …").

   A página vem do PDF: o `pdftotext` separa as páginas, e cada transação
   lida guarda a sua (`pagina`; não existe em extrato já convertido para
   .xlsx). No JSON, `pix_sem_recibo[].pagina`, `sugestoes_vinculo[].pix_pagina`
   e `devolucoes_possiveis[].entrada_pagina`/`saida_pagina`.

## 6. O JSON (para o agente)

- `formato`, `gerado_em` e `mes_referencia`;
- `arquivos`: nome e SHA-256 de cada arquivo recebido, para identificar a
  versão conferida;
- `resumo`, `conferencias` e `alertas`;
- `divergencias`, uma por pessoa que não fecha, com:
  - `id` **estável** (`DIV-<NOME>`), para reaproveitar explicações num
    reenvio;
  - **uma por recibo** quando a pessoa só tem recibos sem Pix, mais de um,
    e nenhum Pix sobrando (`por_recibo`; 2026-10-26): cada recibo pode ter
    sido pago por uma conta diferente (no exemplo, os recibos 0037 e 0038 do
    Helio Sabiá, pagos pela Marta Sabiá e pela Loja Boa Vista). Cada uma
    tem `recibo`, o `id` `DIV-<NOME>-<RECIBO>`, os totais do próprio recibo
    e só as sugestões dele; na planilha, "HELIO SABIA (recibo
    0037-2026)". Com Pix sobrando, fica uma só (o Pix pode explicar mais de
    um recibo);
  - `recibos_sem_pix` e `pix_sem_recibo`;
  - `sugestoes_vinculo` e `devolucoes_possiveis`;
  - `nota_tesouraria`;
- `sugestoes_vinculo`, `devolucoes` (possíveis devoluções, com o `div` da
  pessoa), `destinos_novos` e
  `limpeza_cadastros`.

## 7. Cadastros (`cadastros/`)

**`destinos.json`**: em que coluna cai cada descrição. É editável:

- `colunas`: nome fixo de cada coluna e mês do último uso. Para corrigir
  um nome, edite só o `"nome"`;
- `apelidos`: descrição **exata** → coluna. Ex.: `"sopa": "oficina"`.
  Para mandar "Pastel" para Cantina, acrescente `"pastel": "cantina"`;
- `prefixos`: descrição que **começa** com → coluna. Ex.: `"anuidade"`
  pega "Anuidade — Conselheira Flora";
- use as chaves sem acento, minúsculas e no singular. Grafias que diferem
  só em maiúsculas, acentos, espaços, traços ou plural são a mesma coisa;
- uma descrição nova vira coluna nova, com o nome usado no mês, e o
  terminal avisa (`Destinos NOVOS cadastrados…`).

**`vinculos_confirmados.json`**: ligações confirmadas pela tesouraria. É
preenchido pelo agente. Nos meses seguintes, cada ligação vira o critério 1
de sugestão, mas continua precisando de confirmação. Contém dados pessoais.
O arquivo vem vazio neste repositório e é versionado: antes de usar dados
reais com `--cadastros-reais`, acrescente-o ao `.gitignore` ou defina
`CF_CADASTROS_DIR` (abaixo), para os nomes não irem para um commit.

**Guarda de 2 anos:** contada a partir do mês da conferência, e não da data
do computador:
- colunas sem uso há 24 meses são apagadas;
- vínculos confirmados com 24 meses ou mais são apagados;
- apelidos e prefixos são regras e não expiram.

Para os cadastros ficarem em outro lugar (ex.: o armazenamento do
servidor), defina `CF_CADASTROS_DIR`.

## 8. Problemas comuns

**`FileNotFoundError: pdftotext`:** instale o poppler-utils
(`sudo apt install poppler-utils`).

**`ValueError: Colunas não encontradas`:** a aba de lançamentos não tem as
colunas Data/Nome/Descrição/Valor. Confira o nome da aba (`--aba`).

**`PermissionError` ao gravar a saída:** a planilha está aberta no Excel.
Feche e rode de novo.

**Muitas sugestões "mesmo valor (N recibos possíveis)":** é normal quando o
mesmo valor aparece para várias pessoas no mês. A tesouraria indica qual é
a correta.
