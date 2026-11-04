# Arquitetura

## Princípios

1. **A IA não faz conta.** Todos os números vêm deste pacote, que dá sempre o
   mesmo resultado para os mesmos arquivos. O agente só conduz a
   conversa, explica as divergências e registra as respostas.
2. **Sinalizar, não bloquear.** Problemas de qualidade (leitura do PDF,
   aba Resumo) viram alertas visíveis e o processamento segue.
3. **Nada entre nomes diferentes é automático.** Ligar o Pix de uma conta
   ao recibo de outra pessoa é sempre sugestão, confirmada pela tesouraria.
   O mesmo vale para as devoluções (decisão de 2026-10-08).
4. **O PDF do banco é a fonte oficial.** Um extrato em `.xlsx` só serve para
   uso manual e sai como "não verificado".
5. **Dados pessoais com acesso restrito e com prazo.** No projeto original,
   os dados reais ficam num repositório privado, de acesso restrito; esta
   versão pública usa só dados fictícios (`exemplo/`). Os cadastros guardam
   no máximo 2 anos. Para a IA (Gemini, plano gratuito) vai o mínimo: nomes como
   apelidos, sem CPF e sem a descrição do extrato (`agente.ia.para_ia`).
   Nas perguntas do CF, a IA recebe o texto e, para escrever a resposta,
   os dados da consulta (`agente.consultas`), com os mesmos apelidos.

## Fluxo de dados

```
entradas.xlsx ──► receitas.lancamentos ─┬─ conferir_planilha ─────────────┐
                    (pivotar + cadastro  │                                  │ verificações
                     de destinos)        └─ recibos_para_conciliacao ─┐     │
                                                                      │     │
cora.pdf  ─┐                                                          ▼     │
stone.pdf ─┴► extratos.ler_extrato ── transações ──► receitas.conciliacao ◄─┘
               (+ verificações da leitura)     entradas/saídas, agrupar por pessoa,
                                               casar, sugerir devoluções e vínculos
                                                              │
                                     ┌────────────────────────┴───────────┐
                                     ▼                                    ▼
                         receitas.relatorio (xlsx)            receitas.resultado (JSON)
```

`receitas.pipeline.executar` amarra tudo isso. Os dados passam de uma etapa
para a outra **em memória**. Os arquivos intermediários (extratos lidos,
lançamentos por recibo) só são gravados com `pasta_intermediarios`.

## Módulos

| Módulo | Responsabilidade |
|---|---|
| `comum.texto` / `comum.valores` | normalização de texto, valores em R$, datas e meses |
| `comum.pdf` | `pdftotext -layout`, sem arquivo intermediário |
| `comum.planilha` | estilos das planilhas geradas |
| `extratos.modelo` | tipos `Transacao` (formato único dos bancos) e `Verificacao` |
| `extratos.cora` / `extratos.stone` | texto do PDF → transações, e conferência da leitura contra o PDF |
| `extratos.planilha` | exportar transações para .xlsx e ler de volta (uso manual) |
| `cadastros.destinos` | em que coluna cai cada descrição (colunas, apelidos, prefixos), com guarda de 2 anos |
| `cadastros.vinculos` | vínculos confirmados pela tesouraria, com guarda de 2 anos |
| `receitas.lancamentos` | planilha da tesouraria: uma linha por recibo e conferência da aba Resumo |
| `receitas.pessoas` | quando dois nomes são da mesma pessoa; agrupamento de recibos e Pix |
| `receitas.conciliacao` | casamento recibo × Pix, sugestões de vínculo e de devolução, divergências |
| `receitas.relatorio` | planilha final de 3 abas |
| `receitas.resultado` | JSON para o agente |
| `receitas.pipeline` | `executar(...)`: o ponto de entrada único |
| `agente.agente` | `Agente.receber(papel, texto/botão/arquivo)`: a conversa da tesouraria e do CF |
| `agente.divergencias` | o que perguntar, sugestões disponíveis e quando uma divergência fica explicada; as frases das divergências e das sugestões |
| `agente.ia` | interpretação das respostas livres da tesouraria: interface `Interpretador`, `SemIA` (padrão do `Agente`; a linha de comando usa o Gemini quando há chave), o que vai para a IA (`para_ia`, com apelidos) e a leitura da resposta (`de_ia`); a nota reescrita para o CF (`para_redacao`, `de_redacao`, que recusa número fora dos fatos); o que o CF pergunta (`para_pergunta`, `de_pergunta`) e a resposta a ele (`para_resposta`, `de_resposta`, conferida como a nota) |
| `agente.arrecadacao` | quanto entrou por destino (açaí, bazar…) nos meses fechados: lê a planilha de entradas da versão com `lancamentos.pivotar` (numa cópia do cadastro de destinos, que a consulta não altera), acha o destino pedido e monta os dados com variação, soma e média |
| `agente.formato` | destaques das mensagens no formato do WhatsApp (`negrito`, `italico`), marcados linha a linha; a convenção está no módulo e em [agente.md](agente.md) |
| `agente.comparacao` | relação entre meses fechados: cada indicador mês a mês com soma, média, diferença e variação (calculadas aqui, não pela IA) e quem teve divergência em mais de um mês |
| `agente.consultas` | o lado do CF: o mês pedido (`reconhecer_mes`, `so_pedido`) e os dados que respondem às perguntas sobre um mês fechado (resumo, lista, detalhe, pessoa) |
| `agente.gemini` | adaptador do Gemini (API REST, sem bibliotecas extras) |
| `agente.avaliacao` | comparação do que a IA entendeu com o esperado, para `scripts/avaliar_ia.py` |
| `agente.arquivos` | identifica a planilha de entradas e os PDFs do Cora e da Stone, com o mês (dos recibos ou do período do extrato) |
| `agente.armazenamento` | estado dos meses, versões, conversas, arquivos e o estado de cada canal (`canais/`); pasta local, no Azure montada do Azure Files |
| `agente.whatsapp` | canal do WhatsApp pela API oficial da Meta: confere a assinatura do aviso, baixa documentos, converte botões e listas, envia e ignora mensagens repetidas ou de números fora de `WHATSAPP_CONTATOS`; no primeiro contato, pergunta o nome e, a quem tem os dois papéis, qual seguir |
| `agente.web` | servidor web (FastAPI): o simulador local (só em 127.0.0.1, sem login) e o modo da nuvem, sem o simulador e com `/saude` (`--host 0.0.0.0 --sem-simulador`; `Dockerfile` e [azure.md](azure.md)) |
| `cli` | comandos `receitas`, `extrato` e `agente` (com a escolha da IA, `escolher_ia`) |
| `config` | caminhos dos cadastros (`CF_CADASTROS_DIR`) e da pasta do agente (`CF_AGENTE_DIR`) |

O pipeline de **saídas** (próxima etapa) vai reaproveitar `extratos`, que já
devolve as saídas no formato `Transacao`, além de `comum` e `cadastros`. Ele
deve ganhar um pacote próprio, `conselho_fiscal.saidas`.

## Pontos de integração do agente

Já usados por `conselho_fiscal.agente` (fluxo em [agente.md](agente.md)).
As mensagens do agente já saem no formato do WhatsApp: `botoes` (até 3,
com rótulo de até 20 caracteres) ou `lista` (`abrir` e até 10 `itens`, com
rótulo de até 24 e `descricao` de até 72). A regra fica em
`agente.agente.mensagem`.

O canal fica de fora do núcleo: o simulador web e o WhatsApp
(`agente.whatsapp`) chamam a mesma função, `Agente.receber`.

| O agente precisa | Usa |
|---|---|
| rodar a conferência de um envio | `conselho_fiscal.receitas.executar(entradas, cora, stone, saida, notas=…)` |
| saber o que perguntar à tesouraria | `stats["resultado"]["divergencias"]`: id estável, recibos sem Pix, Pix sem recibo, `sugestoes_vinculo` com critério e `devolucoes_possiveis` |
| avisar sobre problemas de leitura | `stats["alertas"]` e `resultado["conferencias"]` |
| identificar a versão conferida | `resultado["arquivos"][…]["sha256"]` |
| registrar a resposta da tesouraria | passar `notas={id: texto}` no próximo `executar`; elas vão para a planilha e o JSON |
| lembrar uma confirmação de vínculo | `conselho_fiscal.cadastros.vinculos.registrar(nome_extrato, pessoa, mes)` |
| avisar destinos novos | `stats["destinos_novos"]` |
| exigir o PDF dos extratos | `agente.arquivos.identificar`: reconhece o PDF de cada banco pelo texto e recusa extrato em .xlsx |
| entender a resposta livre | `Agente(..., interpretador=…)`: um `agente.ia.Interpretador` recebe o `Contexto` (divergência, sugestões numeradas, o que já foi confirmado, texto) e devolve a `Interpretacao`; o agente confere antes de gravar |

No servidor, aponte `CF_CADASTROS_DIR` para o armazenamento persistente, já
que os cadastros acumulam informação mês a mês.

## Testes

- `tests/unit/`: dados fictícios, sem dependências externas. Inclui o
  pipeline de ponta a ponta com extratos em .xlsx.
- No projeto original há também testes de integração com os meses reais,
  comparados célula a célula com planilhas de referência. Eles não estão
  nesta versão pública, porque os dados têm nomes e CPFs.
- Os testes usam **cópias** dos cadastros: nunca alteram os arquivos reais.
