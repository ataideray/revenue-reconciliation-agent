# Decisões de projeto

As escolhas que moldaram o Elo, com o porquê de cada uma. No projeto
original, cada decisão e cada ajuste ficam registrados num diário de
tratativas; este é o resumo, sem os dados reais.

## 1. A IA não decide números

**Decisão:** tudo o que é número ou fato (ler os extratos, ligar recibo e
Pix, achar divergências, somar, comparar meses) é código determinístico. A
IA (Gemini) entra só onde há linguagem: entender a resposta livre da
tesouraria, redigir a nota para o Conselho Fiscal, entender e responder as
perguntas do CF e reconhecer pedidos simples.

**Por quê:** numa conferência fiscal, o resultado precisa ser reproduzível e
explicável. Os mesmos arquivos sempre dão a mesma planilha.

**Como é garantido:**
- toda chamada à IA pede um JSON num esquema fixo (saída estruturada), que o
  código valida;
- a nota ou a resposta que traz um número ausente dos dados é descartada;
- a IA só aponta sugestões que já existem ("confirmar a 1"); quem confere se
  a sugestão existe e se o item ainda está livre é o código.

## 2. Nada entre nomes diferentes é automático

**Decisão:** ligar o Pix de uma conta ao recibo de outra pessoa (o marido
que paga a anuidade da esposa, a empresa do associado) é sempre
**sugestão**, confirmada pela tesouraria. O mesmo vale para as possíveis
devoluções.

**Por quê:** um vínculo errado esconde uma divergência de verdade. As
sugestões vêm em ordem de força, do critério mais forte ao mais fraco:
1. conta já confirmada antes;
2. nome em comum ou parecido;
3. outro Pix da mesma conta com pista de nome;
4. valor único no mês;
5. só o valor, com vários recibos possíveis.

O critério só aparece para a tesouraria quando é o mais fraco, para não
poluir a pergunta.

**Confirmação em dois passos:** quando a tesouraria responde por escrito, o
Elo mostra o que entendeu ("Entendi: …") e só grava depois do clique. Há
também o botão "Não", para recusar a sugestão nas duas pontas.

A exceção é a resposta que já diz tudo: "sim, é a esposa dele" ou "sim, a
Carla é esposa do Danilo", quando todas as sugestões ligam a mesma conta à
mesma pessoa. Uma regra fixa confirma na hora, com a nota "Segundo a
tesouraria, …". Com negação, algo a mais ou outro nome, vale o caminho da
IA e do clique.

**O cadastro de vínculos não aparece na conversa:** guardar a conta para os
próximos meses é uma engrenagem interna. Se a tesouraria conta que o recibo
só saiu com o nome escrito errado (a mesma pessoa), o Elo resolve a
divergência sem guardar o vínculo, sem perguntar.

## 3. Sinalizar, não bloquear

**Decisão:** problemas de qualidade (uma página do PDF que não fechou, a aba
Resumo da planilha que não bate, a IA fora do ar) viram alertas visíveis, e o
processamento segue.

**Por quê:** a tesouraria e o CF precisam do resultado mesmo com um arquivo
imperfeito; esconder o problema seria pior do que mostrá-lo. Sem a IA, o
Elo continua funcionando: o texto da tesouraria vira a nota como foi
escrito.

## 4. Privacidade: o mínimo sai da máquina

**Decisão:** antes de qualquer texto ir à IA:
- nomes de pessoas e de contas viram apelidos (PESSOA_A, PESSOA_B…);
- números com cara de CPF são mascarados;
- a descrição do extrato não vai.

Na volta, os apelidos são trocados de novo pelos nomes. Um script de
avaliação confere que nenhum nome do mês aparece na pergunta antes de
enviá-la.

**Por quê:** os dados são de associados (nomes, CPFs, valores), e o plano
gratuito da IA pode usar o que recebe. Também por isso:
- os cadastros guardam no máximo 2 anos de dados;
- o simulador local só aceita conexões da própria máquina;
- o webhook do WhatsApp confere a assinatura de cada aviso.

## 5. O PDF do banco é a fonte oficial

**Decisão:** os extratos só valem no PDF do banco, e a leitura é conferida
contra o próprio PDF (saldos, totais e quantidade de lançamentos). Um
extrato em .xlsx sai como "não verificado". O mês dos extratos vem do
período impresso no PDF, e cada Pix guarda a página onde está, para o CF
achar o lançamento.

**Por quê:** uma planilha pode ser editada; o PDF do banco é o documento.

## 6. Uma pergunta por vez, na língua do dia a dia

**Decisão:** o Elo pergunta uma divergência por vez, em linguagem simples
("Entrou R$ 150,00 no banco sem recibo"), com botões para as respostas
comuns. O que já foi explicado por outra ponta sai da fila sozinho ("Isso
também resolve a divergência de…").

Uma pessoa com vários recibos sem Pix, pagos por contas diferentes, vira uma
divergência por recibo.

O resultado da conferência só diz quantas divergências há; cada uma
aparece na sua pergunta. Contas e recibos de empresa vêm com "CNPJ" na
frente do nome (pelo documento do extrato ou pelo nome: LTDA, S/A, ME…).

**Por quê:** quem responde é a tesouraria, pelo celular, entre outras
tarefas. No mês real usado nos testes, 147 recibos viraram 5 respostas.

## 7. Regras fixas antes da IA, IA quando a regra não reconhece

**Decisão:** comandos previsíveis são reconhecidos por regra fixa:
- saudações, menu e ajuda;
- "sim" e "não";
- "sim, é a esposa/o marido/a empresa dele" (veja a decisão 2);
- "corrigir", também no meio da frase ("me confundi, quero corrigir a
  Lumitech"), quando o nome depois do verbo aponta uma divergência;
- troca de papel ("troque para o conselho fiscal").

Do lado do CF, "deste mês" não vira o mês atual por conta própria: o Elo
pergunta se é o mês atual ou um dos meses com dados, com um botão para
cada.

Só o que a regra não reconhece vai para a IA, que diz se é um pedido simples
(menu, ajuda, troca de papel). Quando a IA já é chamada para interpretar a
resposta, isso vem no mesmo pedido, sem custo extra.

**Por quê:** a regra responde na hora, não custa nada e não falha; a IA
cobre as variações. Uma explicação nunca é engolida como comando: o
comando só vale quando o texto não confirma nem explica nada.

## 8. Canal separado do núcleo

**Decisão:** o núcleo (`receitas/`, `agente/agente.py`) não sabe se a
conversa vem do simulador web ou do WhatsApp. O canal do WhatsApp (API
oficial da Meta) cuida de:
- botões e listas;
- o cabeçalho "*Elo* · _Tesouraria_" em cada mensagem;
- uma fila por número, para as respostas saírem em ordem;
- juntar os arquivos que chegam em sequência, para responder uma vez só;
- um espaço separado para cada número.

**Por quê:** dá para testar todo o fluxo sem WhatsApp, e trocar de canal sem
mexer na conferência.

## 9. Hospedagem simples e barata

**Decisão:** um contêiner no Azure Container Apps, com escala a zero, e os
dados num compartilhamento do Azure Files montado como pasta. Imagens no
Azure Container Registry.

**Por quê:** é o volume de uma associação (poucas conversas por mês). Sem
banco de dados nem fila: o estado de cada mês é um JSON, fácil de auditar.
Detalhes e custos: [azure.md](azure.md).

## 10. Avaliar a IA antes de mudar o prompt

**Decisão:** `scripts/avaliar_ia.py` manda à IA um conjunto de respostas de
teste, com o resultado esperado de cada uma, e classifica os erros.

**Gravidade:** o erro "CRÍTICO" é confirmar algo que a tesouraria não
confirmou. Errar para o lado cauteloso (pedir de novo) é menos grave.

**Por quê:** os modelos mudam e o comportamento varia entre rodadas; a
avaliação mostra se uma mudança de instrução melhorou ou piorou.
