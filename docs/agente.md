# Agente: simulador local e WhatsApp

O agente, que se apresenta como **Elo** (`NOME_AGENTE`, em `agente.py`),
conversa com a **tesouraria** e com o **Conselho Fiscal (CF)**. Ele
roda num simulador web local, com as duas conversas lado a lado, e no
WhatsApp (seção no fim deste guia). As respostas da tesouraria são
botões, que confirmam as sugestões, ou texto livre, lido por um
interpretador: o Gemini lê o texto e o agente confere o que ele entendeu.
Sem IA, o texto vira a nota.

## Como rodar

```bash
pip install -e ".[agente]"              # fastapi e uvicorn
conselho-fiscal agente                  # abre em http://127.0.0.1:8000
conselho-fiscal agente --porta 8001 --pasta /outra/pasta
conselho-fiscal agente --cadastros-reais    # produção: grava nos cadastros reais
conselho-fiscal agente --ia nenhuma         # sem IA: o texto livre vira a nota
```

**IA:** sem `--ia`, o agente usa o Gemini se encontrar a chave (veja
abaixo). Sem chave, ele avisa no terminal e segue sem IA. Com `--ia
gemini`, a chave é obrigatória: sem ela, o agente não inicia. Ao iniciar,
o terminal mostra quem lê as respostas livres ("respostas livres: …").

No Windows, rode pelo WSL (o PowerShell não aceita `PYTHONPATH=src` na
frente do comando):

```powershell
wsl bash -c "cd '<pasta do projeto>' && PYTHONPATH=src python3 -m conselho_fiscal agente"
```

O servidor só aceita conexões da própria máquina, porque os dados têm nomes
e CPFs.

**Chave do Gemini:** crie a chave no Google AI Studio e grave-a, sozinha,
no arquivo `~/.config/conselho-fiscal/gemini_api_key` do WSL (fora do
repositório), ou defina `GEMINI_API_KEY`. O modelo padrão é
`gemini-3.5-flash-lite`; outro pode ser escolhido com `CF_IA_MODELO`. Se ele
não responder (sobrecarga ou rede), o agente tenta o modelo reserva,
`gemini-3.1-flash-lite`, que tem cota própria no plano gratuito
(`CF_IA_MODELO_RESERVA`; vazio desliga e repete o principal).

**Simulação isolada:** sem `--cadastros-reais`, o agente usa uma cópia dos
cadastros dentro da pasta de trabalho (`agente_dados/cadastros/`). Os
vínculos confirmados e os destinos novos da simulação não tocam os
cadastros reais.

**Recomeçar do zero:** pare o servidor (Ctrl+C), apague a pasta de trabalho
(padrão: `agente_dados/`, ou `CF_AGENTE_DIR`) e inicie de novo. Isso zera
as conversas, os meses e os cadastros da simulação.

**Destaques, como no WhatsApp** (`agente/formato.py`): *negrito* no título
da mensagem, nos nomes de pessoas, nos rótulos de seção ("Falta:",
"Pode ser que:", "Entendi:"), no valor de cada divergência e na situação
que importa ("está pronto", "Tudo certo"); _itálico_ no que a pessoa faz em
seguida ("Toque em \"Sim\" se for isso…") e nas observações. O que a
tesouraria escreve (as notas) e o que vai para a planilha ficam sem marcas.
O simulador mostra as duas marcas; nas respostas ao CF, a IA segue a mesma
regra (negrito no número ou na conclusão principal).

**Botões e listas, como no WhatsApp:** as opções seguem os limites do
WhatsApp, para o simulador mostrar o que funciona lá.
- Com até 3 opções, elas aparecem como botões de até 20 caracteres.
- Com mais de 3, viram uma lista: um botão "Ver opções" que abre até 10
  opções de até 24 caracteres.
- Nomes longos são cortados com "…". Na lista, o nome inteiro aparece
  embaixo, e nas mensagens ele também vem completo no texto.

## Menu, ajuda e quem fez o quê

Em qualquer ponto da conversa, dos dois lados (2026-10-23):
- **"oi", "menu", "bom dia"** mostram o menu: quem está falando, a situação
  do momento e as opções. Uma saudação no meio das perguntas **não vira
  nota**. Valem também "olá Elo", "oii", "bom diaa", "e aí", "opa", "salve",
  "oi, tudo bem?", "olá pessoal" (`SAUDACAO` em agente.py; 2026-10-26).
  "tudo bem" sozinho não é saudação (pode ser um "ok").
- **Saudação com pedido** ("oi, preciso de ajuda", "Bom dia! É a esposa
  dele"): a saudação sai e vale o resto (`sem_saudacao`); o histórico
  guarda a mensagem inteira.
  - Tesouraria: o mês em andamento ("Julho/2026: faltam 3 explicações",
    botão **Continuar julho**), o envio pela metade (o que chegou e o que
    falta) ou o mês pronto (botão **Corrigir uma nota**).
  - CF: os meses, com a situação de cada um; os prontos têm botão.
- **"ajuda", "como funciona"** (ou o botão **Como funciona**) explicam o
  fluxo em 4 passos (tesouraria) ou o que dá para pedir, com exemplos (CF).
- **Quando a regra não reconhece**, a IA diz se o texto é um pedido simples
  (`COMANDOS` em ia.py: menu, ajuda, trocar de papel; 2026-10-26):
  - tesouraria com pergunta aberta: na mesma chamada que interpreta a
    resposta (campo `comando`); só vale sem confirmação e com a resposta
    insuficiente (o que explica algo nunca é engolido), e não vira nota;
  - tesouraria sem pergunta aberta: uma chamada curta (`comando`, 6 s), só
    com o texto e os nomes trocados por apelidos; sem resposta, ou
    "nenhum", fica o menu com "Não entendi.";
  - CF: na mesma chamada que entende a pergunta (consultas `menu`, `ajuda`,
    `trocar_*`).
  A troca de papel volta marcada (`trocar_papel`) e o canal do WhatsApp faz
  a troca; na web fica o texto "use o botão Trocar de papel".
- **Quem fez:** com o nome que o canal guarda (WhatsApp), cada mensagem do
  histórico leva o `autor`, e o estado do mês registra quem enviou cada
  versão (`por`), quem escreveu cada nota e confirmou cada sugestão (`por`),
  quem aprovou a nota reescrita (`revisada_por`) e quem recebeu cada entrega
  (`para`). O nome fica só no histórico: a planilha do CF não muda. O
  simulador não tem nome.

## A conversa da tesouraria

1. **Arquivos.** A tesouraria envia a planilha de entradas (.xlsx) e os
   extratos do Cora e da Stone em **PDF**, em qualquer ordem. O agente:
   - identifica cada arquivo: a planilha pela aba "Receitas" e pelo mês dos
     recibos; os PDFs pelo texto de cada banco, e o mês deles pelo período
     impresso no extrato ("01/09/2026 a 30/09/2026");
   - confirma cada um e diz o que ainda falta. Nas mensagens, os arquivos
     não têm o nome do banco (2026-10-29): "✅ Registro de receitas da
     tesouraria — julho/2026", "✅ Extrato bancário (1 de 2) — julho/2026",
     "Falta: 1 extrato bancário (PDF)". O banco continua onde identifica um
     lançamento ou um valor: a página de cada Pix ("09/07/2026, Cora, pág.
     2"), os alertas de leitura ("[Cora] Leitura do PDF") e os totais por
     banco nas respostas ao CF;
   - se chegar um arquivo de outro mês, descarta os que esperavam (envio
     novo) e avisa quais;
   - recusa extrato em .xlsx e pede o PDF;
   - se chegar outro arquivo do mesmo tipo, substitui o anterior.
2. **Conferência.** Com os três arquivos, o agente roda a conferência de
   receitas e manda, numa mensagem só, o resultado (quantos recibos batem
   com os extratos), os alertas de leitura, se houver, e quantas
   divergências falta explicar ("8 divergências para explicar."). Sem a
   lista: cada divergência aparece só na sua pergunta.
3. **Uma a uma.** Para cada divergência, o agente mostra o que entrou no
   banco sem recibo e os recibos que não aparecem nos extratos, item por
   item, e as sugestões ("Pode ser que: o Pix de R$ 130,00 … pagou o recibo
   0814-2026 de …"). Quando cada item tem uma sugestão de vínculo só (e
   todas do mesmo lado), os dois vêm juntos, sem repetir o Pix: "Pode ser
   que paguem 2 recibos de HELIO…: 1) Pix de R$ 200,00 (…) → recibo
   0867-2026" (`divergencias.agrupar`). Conta ou recibo de empresa vem com
   "CNPJ" na frente do nome ("Divergência 1 de 4 — CNPJ ESTUDIO
   LUMEN LTDA", "Pix de CNPJ "LUMITECH""): pelo documento do Cora ou, sem ele,
   pelo nome (LTDA, S/A, ME, EPP, MEI, razão social de MEI com o CPF);
   veja `conciliacao.eh_cnpj`. Cada Pix diz a página do PDF do extrato onde está
   ("R$ 130,00 em 22/07/2026, Cora, pág. 2"), na pergunta, na sugestão e na
   confirmação. O critério da sugestão só aparece quando ela vem só do
   valor e há mais de um recibo possível ("_(só pelo valor; 3 recibos
   possíveis)_"); a planilha do CF guarda o critério inteiro. Depois de confirmar uma
   parte, a pergunta volta só com o que falta.
   - **Botão "Sim: …"** diz o que confirma ("Sim: recibo 0814", "Sim: Pix
     de 22/07", "Sim: devolução"; "Sim: todas" quando as sugestões não
     disputam o mesmo recibo ou Pix): a confirmação vira nota. Se for
     vínculo, ela vai também para o `vinculos_confirmados.json`. Como um
     vínculo explica as duas pontas (o recibo de uma pessoa e o Pix de
     outra), a outra divergência também pode ser resolvida.
     A mensagem diz qual e o que era ("Isso também resolve a divergência
     de *EVA OLMO GIRASOL* (Pix sem recibo: R$ 150,00).").
   - **Botão "Não"** ("Não é nenhuma" com mais de uma sugestão; escrever
     "não" vale o mesmo): nada é confirmado, as sugestões saem da pergunta
     (também da outra ponta) e o agente pede a explicação por escrito. A
     recusa fica em `recusadas` no estado do mês (com quem recusou); corrigir
     a divergência traz as sugestões de volta.
   - **Texto livre:** "Sim" ou "confirmo" valem como confirmação quando há
     uma única sugestão. O resto passa pelo interpretador (veja abaixo).
     Sem IA, o texto vira a nota da divergência para o CF.
   - **"Responder depois":** a divergência vai para o fim da fila.
4. **Fechamento.** Quando todas as divergências têm nota, o agente gera a
   planilha final, com as notas na aba Divergências, e avisa a tesouraria
   que está tudo certo. O CF não é avisado: ele pede quando quiser.

**Texto livre com IA** (o padrão, com a chave do Gemini). A IA só lê a resposta; o agente
confere e grava.
- **Confirmação no texto** ("a 1 tá certa, é a mãe dela"): o agente
  mostra "Entendi: ..." com **[Está certo]** e **[Não foi isso]**. Nada é
  gravado antes do clique, porque um vínculo vai para o cadastro e vale
  nos meses seguintes. Escrever "sim", "isso" ou "está certo" vale o
  clique em "Está certo"; "não" vale "Não foi isso". Número de sugestão inexistente, ou sugestões que
  disputam o mesmo item, fazem o agente pedir de novo.
  - Quando há vínculo, a IA também diz se a tesouraria contou que o recibo
    saiu com o nome errado (a mesma pessoa; campo `nome_errado`). Se não,
    o vínculo vai para o cadastro; se sim, não vai: a divergência se
    resolve e a nota vale, mas a conta não fica associada a outra pessoa
    (`"cadastro": false` na confirmação; o "corrigir" não mexe no
    cadastro). Os botões diretos ("Sim: recibo 0814") sempre guardam o
    vínculo. **O cadastro de vínculos não aparece na conversa** (desde
    2026-10-27): nem aviso, nem pergunta, nem botão. Os botões antigos
    ("Certo, sem vínculo", "Guardar vínculo") ainda valem se forem tocados
    numa mensagem anterior.
- **Relação simples, sem a IA** ("sim, é a esposa dele", "sim, a Carla é
  esposa do Danilo", "sim, é a empresa dele"): começa confirmando, diz a
  relação (esposa, marido, filho, filha, empresa, mãe, pai, irmão, irmã),
  não tem negação nem nada além disso, e as sugestões ligam todas a mesma
  conta à mesma pessoa. O agente confirma todas direto, sem "Entendi" e sem
  reescrita, com a nota "Segundo a tesouraria, CARLA JATOBA é a esposa
  de DANILO JATOBA." Nomes citados têm de ser da conta ou da
  pessoa ("ele"/"ela" valem); senão, a resposta passa pela IA.
- **Resposta que não explica** ("não sei", "ok"): o agente pede a
  explicação de novo, com **[Registrar assim mesmo]** e "Responder
  depois". Nunca trava a conversa.
- **"Sim" sozinho** a uma pergunta com várias sugestões (ou nenhuma), sem
  a IA entender o que foi confirmado: o agente pede de novo. "Sim" nunca
  vira a nota.
- **"Vou ver", "depois respondo":** a divergência vai para o fim da fila.
- **Explicação:** vira a nota, com o texto da tesouraria como foi escrito.
- **IA fora do ar ou com erro** (nem o modelo reserva respondeu): o
  agente avisa e pergunta **[Tentar de novo]**, **[Registrar assim]** (o
  texto vira a nota, como sem IA) ou "Responder depois". Nada é gravado
  antes, porque gravar só o texto deixaria uma confirmação de fora (ex.:
  "é a Marinilda" sem o vínculo). Se ela registrar assim e a IA voltar a
  responder na hora da reescrita, o agente interpreta o texto de novo
  (uma vez): achando uma confirmação, mostra "Agora consegui interpretar
  sua resposta… Entendi: …"; "Está certo" grava a confirmação e a nota
  reescrita, "Não foi isso" deixa a nota registrada.

**Avaliação da IA:** `python3 scripts/avaliar_ia.py` manda ao Gemini as
respostas de teste (`exemplo/casos_ia_2026-07.json`; junho com `--mes 2026-06`)
sobre as divergências do mês de exemplo e mostra o que ele entendeu errado. (No projeto original, a
mesma avaliação roda com 55 respostas sobre um mês real.) O erro
"CRÍTICO" é confirmar algo que a tesouraria não confirmou. Rode sempre que
mudar o modelo ou as instruções (`ia.INSTRUCOES`). Antes de enviar, o
script confere que nenhuma palavra dos nomes do mês está na pergunta.

A nota feita a partir de texto livre guarda, no `estado.json` do mês, o
texto original e quem interpretou (`interpretado_por`), para auditoria.

**Nota reescrita para o CF** (com IA): cada divergência que ganha nota
com texto da tesouraria recebe uma versão clara escrita pela IA, antes da
próxima pergunta. A nota só de confirmações (botão ou "sim") não é
reescrita: vale o texto padrão, em lista quando são várias ("Confirmado
pela tesouraria:" e um "•" por confirmação).

Quando a resposta confirma uma sugestão e explica ("a 1 tá certa, é a
empresa do Ivan"), a nota reescrita já aparece no "Entendi" ("• Nota para
o Conselho Fiscal: …"), e um clique em "Está certo" aprova as duas. Como a
nota já conta o que foi confirmado, a confirmação não se repete: fica só o
aviso do vínculo. Se a reescrita falhar nesse momento, o "Entendi" mostra
cada confirmação por extenso e a nota original, e a reescrita vem depois,
na revisão de sempre.

> Nota para o Conselho Fiscal — LEOPOLDO GIRASSOL LUAR:
> Recibos de LEOPOLDO GIRASSOL LUAR pagos por outras contas ou em dinheiro, segundo a tesouraria:
> • 0814-2026 (R$ 130,00): Pix da conta LUMIVERDE COMERCI (Cora, 22/07/2026)
> • 0864-2026 (R$ 150,00): pago em dinheiro
>
> [Está certo] [Manter a original]

- **"Está certo"** (ou "sim"): a versão reescrita vai para a planilha.
- **"Manter a original"** (ou "não"): vai a nota montada como hoje
  (confirmações + texto da tesouraria).
- **Texto escrito:** vira a nota como foi escrito.

O CF vê só a nota que ficou. O `estado.json` guarda também a nota montada
(`nota_montada`), como ficou (`redacao`) e quem redigiu (`redigida_por`).
O mês só fecha depois de todas as notas aprovadas; o CF vê "nota(s) a
aprovar" enquanto isso.

A IA só organiza o que já existe. O agente recusa a redação com um número
que não está nos fatos nem na resposta da tesouraria (uma soma feita pela
IA, um recibo inventado) ou com um apelido desconhecido. Recusada, ou com
a IA fora do ar, o agente avisa, mostra a nota original e pergunta
**[Tentar de novo]** ou **[Manter a original]** (o erro fica em
`erro_redacao`). Sem IA, não há redação.

**O que vai para o Gemini** (plano gratuito: pelos termos do Google, o que
é enviado pode ser usado para melhorar os produtos e lido por revisores):
- da divergência e das sugestões, só valores, datas, banco e número do
  recibo. Nomes de pessoas e de contas vão como apelidos (PESSOA_A,
  PESSOA_B), e o critério das sugestões não vai, porque cita pedaços de
  nomes;
- do extrato, nada além disso: nem a descrição, nem CPF;
- o texto da tesouraria, com os nomes de todas as divergências do mês
  trocados pelos apelidos e números com cara de CPF mascarados. Quando uma
  palavra está em dois nomes (ex.: "Odir" na conta "ODIR P J …" e na
  pessoa "ODIR VALERIO …"), vale a pessoa. **Um nome que não aparece em
  nenhuma divergência** (ex.: "a mãe dela, Noeli") **vai como foi
  escrito.**

**Corrigir uma nota:** a tesouraria escreve "corrigir" (aparece a lista
das divergências com nota) ou "corrigir" seguido do nome (ex.: "corrigir a
nota da lumi"). O pedido também vale no meio da frase ("me confundi, quero
corrigir Lumitech"), desde que o nome depois do verbo aponte alguma
divergência; sem isso, o texto segue como explicação ("vamos corrigir o
recibo no sistema"). Se o nome aponta várias (uma por recibo, como
"corrigir helio"), a lista mostra só as dessa pessoa. Também há o botão
"Corrigir uma nota" na mensagem de mês pronto. Corrigir é responder de novo, do zero:
- as confirmações daquela divergência são desfeitas, e o vínculo sai do
  cadastro, se foi o agente que o gravou naquele mês;
- a outra ponta de cada vínculo desfeito (ex.: o recibo do Ivan, quando se
  corrige a LUMITECH) também volta para a fila;
- a pergunta é feita de novo, com as sugestões.

Vale também depois da entrega ao CF. O mês volta para "com a tesouraria"
e, ao fechar de novo, o agente avisa que o CF recebeu uma versão anterior
e precisa pedir de novo (o CF não é avisado). A planilha que o CF recebeu
fica guardada numa cópia fixa (`entrega1/`, `entrega2/`, …), separada da
planilha regravada.

**Reenvio:** mandar os arquivos de novo abre uma nova versão do mês,
inclusive depois de entregue ao CF, e também no meio das respostas. Notas
de divergências que não mudaram são mantidas; as que mudaram voltam para a
fila. Arquivos idênticos aos da última versão não abrem versão nova.

**Corrigir um arquivo só:** quando chega um arquivo de um mês que já tem
conferência, o agente oferece **[Usar os da versão N]**: os outros dois
são copiados da última versão e a conferência roda na hora. O mês vem da
planilha de entradas, se ela veio; senão, do período do extrato; e, se
nem o período der para ler, é o mês em conversa. Um extrato de um mês
novo não recebe a oferta (é o começo de outro envio). A tesouraria também pode mandar os outros
arquivos, como antes.

## A conversa do CF

O CF pede um mês por texto ("julho", "07/2026", "2026-07", "pode me enviar
julho?") ou pelo botão do menu.
- **Mês pronto:** o agente envia a planilha da conferência e os arquivos da
  tesouraria, e o mês passa a "entregue". Aí termina o papel do agente.
- **Mês ainda com a tesouraria:** o agente diz que o mês ainda não foi
  fechado e quantas divergências estão sem nota.
- **Mês sem conferência:** o agente diz que o mês ainda não foi fechado,
  porque a tesouraria ainda não enviou os arquivos (ou quantos faltam). Um
  mês pedido só pelo nome ("julho") é o julho mais recente com
  conferência; se não houver, o último julho que já começou.

O menu mostra os 10 meses mais recentes com conferência; só os prontos ou
entregues têm botão.
- **Se o CF não aprovar:** a tesouraria reenvia os arquivos e o ciclo
  recomeça.

### Perguntas do CF

Uma mensagem que não é só o pedido de um mês é uma pergunta, atendida em
três passos:
1. a IA diz o que o CF quer: qual consulta, de que meses e de que pessoa.
   Ela recebe só o texto (com os nomes das divergências trocados por
   apelidos), a data de hoje e os meses com dados;
2. `agente/consultas.py` busca os dados do mês (tabela abaixo);
3. a IA escreve a resposta à pergunta só com esses dados, com os mesmos
   apelidos e sem CPF. Como na nota reescrita, uma resposta com número que
   não está nos dados (uma conta feita pela IA) é recusada, e o CF recebe
   os dados como estão. Pergunta específica recebe uma ou duas linhas;
   pergunta ampla ("compare", "como foi") recebe uma frase de conclusão e
   grupos com título em negrito (*Receitas*) e um item por linha. O código
   garante cada "• " e cada título numa linha própria.

| Consulta | Exemplo | Resposta |
|---|---|---|
| pacote | "manda junho e julho" | o pacote de cada mês (conta como entrega) |
| resumo | "valor total das divergências de junho" | total de receitas, Pix recebidos em cada banco (quantos e a soma), recibos, divergências com a soma dos recibos sem Pix e dos Pix sem recibo, alertas |
| divergencias | "quem teve divergência em julho?" | a lista, com os itens e as notas de todas para a IA; cada pessoa é uma opção que mostra os itens e a nota |
| pessoa | "o que houve com a Eva?" | os itens e a nota da tesouraria, em cada mês fechado (ou nos meses citados) |
| comparar | "qual a soma da receita de junho e julho?", "julho foi melhor que junho?", "média mensal de Pix na Stone" | a relação entre os meses (`agente/comparacao.py`): cada indicador mês a mês, com soma, média, diferença e variação entre meses seguidos, maior e menor (a partir de 3 meses) e quem teve divergência em mais de um mês |
| destino | "quanto arrecadamos com açaí em julho?", "quanto deu o bazar em junho e julho?", "quanto entrou por destino em julho?" | quanto entrou de cada destino (`agente/arrecadacao.py`), com os valores lançados nos recibos da planilha de entradas, lida como no pipeline: valor e número de recibos; o destino é achado sem acento e no singular, e "fundo" traz todos os destinos com essa palavra, cada um e a soma; com vários meses, variação, soma e média; sem destino, todos os do mês, do maior ao menor, e o total. Sem IA, uma pergunta que cita um mês e um destino dele também cai aqui |
| situacao | "julho já fechou?" | a situação do mês |
| menu / ajuda | "o que você faz?", "como te uso?" | o menu ou o "Como funciona" |
| trocar_tesouraria / trocar_cf / trocar | "quero entrar como tesouraria" | a troca de papel, pelo canal |
| outra | "compare com o orçamento" | o que o agente sabe responder, com exemplos |

- **Só meses fechados** (pronto ou entregue) são consultados. De um mês
  ainda com a tesouraria, o CF recebe só a situação, porque as notas
  ainda podem mudar.
- **Uma pergunta não envia o pacote** e não conta como entrega. A
  resposta traz o botão "Pacote <mês>".
- **Sem mês na pergunta:** resumo e lista usam o último mês fechado; a
  pessoa é procurada em todos os meses fechados; a comparação usa todos
  os meses fechados (até 12). Com um mês só, a comparação é com o mês
  fechado anterior.
- **"Deste mês" não é o mês atual por conta própria:** "desse mês", "neste
  mês", "mês atual" (sem outro mês citado) fazem o agente perguntar se é o
  mês atual ou um dos meses com dados, com um botão para cada. A escolha
  (botão ou o nome do mês por escrito) responde a pergunta guardada, com o
  mês no lugar de "deste mês"; qualquer outra mensagem a descarta.
- **Vários meses:** o resumo de dois ou mais meses vira a comparação, e a
  lista de divergências de vários meses vai numa resposta só, com quem
  aparece em mais de um mês.
- **A IA não faz conta:** as somas, médias, diferenças e variações são
  calculadas pelo código e vão prontas nos dados. Os indicadores da
  comparação: total de receitas, Pix recebidos em cada banco (soma e
  quantidade), recibos, conformes, divergentes, divergências, soma dos
  recibos sem Pix e dos Pix sem recibo.
- **Só as divergências ficam guardadas:** quem pagou sem divergência não
  aparece nas consultas, e o agente diz isso quando não acha a pessoa.
- **Sem IA, ou com a IA fora do ar:** uma pergunta que cita um mês recebe
  o resumo do mês; sem mês, o menu. Com a IA fora, o agente avisa. Se só a
  resposta falhar, vão os dados da consulta.
- **Soma dos Pix por banco:** só nos meses conferidos a partir de
  2026-10-13 (o JSON da conferência ganhou `valor_cora` e `valor_stone`).
  Num mês anterior, o resumo mostra só quantos Pix; para ter a soma, é
  preciso conferir o mês de novo.

## Onde ficam os dados

```
agente_dados/
  estado.json                 envio em andamento (arquivos incompletos)
  envio/                      arquivos à espera dos outros
  conversas/tesouraria.jsonl  histórico das conversas
  conversas/cf.jsonl
  cadastros/                  cópia dos cadastros (simulação)
  meses/2026-07/
    estado.json               situação, versões, divergências, notas e entregas
    v1/                       entradas, cora.pdf, stone.pdf e a planilha gerada
      entrega1/               cópia fixa da planilha que o CF recebeu
```

Situação do mês: `aguardando_respostas` → `pronto` → `entregue`. Um reenvio
volta para `aguardando_respostas`, ou direto para `pronto`, se nada mudou
nas divergências. Uma correção de nota volta para `aguardando_respostas`.

## WhatsApp

O canal usa a API oficial da Meta (WhatsApp Cloud API). O servidor recebe os
avisos em `/whatsapp` e só liga o canal quando acha toda a configuração:

| Variável | O que é |
|---|---|
| `WHATSAPP_TOKEN` | token permanente do usuário do sistema (ou o arquivo `whatsapp_token` em `~/.config/conselho-fiscal/`) |
| `WHATSAPP_APP_SECRET` | chave secreta do aplicativo, para conferir a assinatura dos avisos (ou o arquivo `whatsapp_app_secret`) |
| `WHATSAPP_VERIFY_TOKEN` | texto combinado com a Meta na verificação do endereço |
| `WHATSAPP_PHONE_NUMBER_ID` | identificação do número que envia |
| `WHATSAPP_CONTATOS` | quem fala com o agente e em qual papel: `5511999990000=tesouraria,cf;5511...=cf` |
| `WHATSAPP_GRAPH_VERSION` | versão da API (padrão `v25.0`) |

- Números fora de `WHATSAPP_CONTATOS` são ignorados (fica só o registro).
- Com `@nome` no fim do contato (`5511...=tesouraria,cf@segundo`), o número
  tem um espaço só dele (meses, envios e conversas em `<pasta>/espacos/nome`),
  útil para testar com dois números sem que a conversa de um siga no outro.
  Sem `@`, os números dividem os dados (o uso real: tesouraria e CF no mesmo
  espaço). Os cadastros (destinos e vínculos) são os mesmos para todos.
- **Primeiro contato:** o agente se apresenta e pergunta o nome, que fica
  guardado com o número (no estado do canal) e vai para o histórico de
  tudo o que a pessoa fizer. "Meu nome é …" troca. Um arquivo mandado antes
  do nome não é guardado: o agente pede para enviar de novo.
- O papel vem de `WHATSAPP_CONTATOS`, nunca do que a pessoa diz. Um número
  com os dois papéis escolhe por botão (**Tesouraria** ou **Conselho
  Fiscal**) depois do nome e troca pelo botão **Trocar de papel** do menu
  (ou com `#cf` e `#tesouraria`, ou por escrito: "troque para o conselho
  fiscal", "passa pra tesouraria", "quero trocar de papel"). A frase de troca
  é curta, tem um verbo de troca e só palavras de ligação; qualquer outra
  coisa segue como mensagem comum (não vira nota nem pergunta). Sem o papel
  pedido no cadastro, o agente avisa e não troca.
- Toda mensagem do agente começa com uma linha de cabeçalho, como o nome de
  quem escreve num grupo: `*Elo*`; para quem tem os dois papéis, com o
  papel da vez (`*Elo* · _Tesouraria_`, `*Elo* · _Conselho Fiscal_`). Uma
  linha em branco separa o cabeçalho do texto.
- Cada número é atendido uma mensagem por vez, do download ao envio das
  respostas, para elas chegarem na ordem em que as mensagens foram mandadas.
- Arquivos mandados juntos têm uma resposta só: o canal espera 4 s depois do
  último (`JANELA`) e responde com uma linha por arquivo e, no fim, o que
  falta ou o resultado da conferência. Um texto mandado antes do fim da
  espera faz os arquivos serem atendidos primeiro.
- Os arquivos chegam como documento (planilha e PDFs); foto ou áudio
  recebem o pedido de mandar como documento.
- O WhatsApp entrega o número brasileiro sem o 9. O agente responde
  primeiro no número com 9 e, se a Meta recusar, no número como chegou.
- No número de teste da Meta, só recebem mensagem os números da lista de
  destinatários permitidos (erro 131030): adicione cada contato em
  developers.facebook.com, no app, em **WhatsApp > Etapa 1. Experimente**,
  campo **Para**.
- As respostas usam a janela de 24 horas aberta pela mensagem do contato;
  mensagens que o agente iniciar sozinho vão precisar de modelos aprovados.
