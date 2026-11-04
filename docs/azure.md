# Hospedagem no Azure

Decisões de 2026-10-15: Azure Container Apps com escala a zero, os dados no
**Azure Files** (montado como pasta, sem mudar o código), região **Brazil
South**. O contêiner sobe sem o simulador, com o endereço de saúde (`/saude`)
e, depois de [ligar o WhatsApp](#ligar-o-whatsapp), o webhook da Meta
(`/whatsapp`).

```
                 Azure (Brazil South)
  ┌───────────────────────────────────────────────────────────┐
  │  Container Registry ──imagem──► Container App (0 a 1 réplica)  │
  │                                   │  /saude e /whatsapp        │
  │                                   │  /dados ◄── Azure Files     │
  │                                   │     agente/  (estado, conversas, meses)
  │                                   │     cadastros/ (destinos, vínculos)
  │                                   └─► Gemini (só apelidos; chave em segredo)
  └───────────────────────────────────────────────────────────┘
```

## Por que assim

- **Azure Files:** o agente grava pastas e arquivos JSON; com o Azure Files
  montado em `/dados`, o código não muda (`CF_AGENTE_DIR=/dados/agente`,
  `CF_CADASTROS_DIR=/dados/cadastros`). Os arquivos podem ser vistos no
  portal ou montados no Windows para conferência e backup.
- **No máximo 1 réplica:** o estado são arquivos JSON, e dois contêineres
  gravando ao mesmo tempo poderiam se atrapalhar. O volume (dezenas de
  mensagens por mês) cabe com folga numa réplica.
- **Escala a zero:** sem uso, nenhum contêiner fica ligado. A primeira
  mensagem depois de um tempo parado demora alguns segundos a mais.
- **Brazil South:** os dados ficam no Brasil.

## O que entra na imagem

Só o código e o `cadastros/destinos.json` (semente do cadastro de destinos,
sem dados pessoais). O `.dockerignore` é uma lista do que **pode** entrar:
`dados/`, `agente_dados/`, `saidas/`, `cadastros/vinculos_confirmados.json`
e chaves ficam de fora. Na primeira vez, o contêiner copia a semente para
`/dados/cadastros/` (depois vale o do volume). Os vínculos confirmados
começam vazios; para levar os atuais, veja "Enviar os vínculos" abaixo.

O contêiner roda sem root (usuário 1000) e com o horário de Brasília. O
comando é:

```
conselho-fiscal agente --host 0.0.0.0 --porta 8000 --sem-simulador --cadastros-reais
```

O simulador não tem login: o agente **recusa** abri-lo em outro endereço
que não seja a própria máquina.

## Custo estimado (por mês)

| Recurso | Custo |
|---|---|
| Container Apps (consumo) | provavelmente zero: a cota gratuita mensal (vCPU-s, GiB-s e 2 milhões de requisições) cobre o uso |
| Azure Files (poucos GB) | centavos |
| Container Registry Basic | cerca de US$ 5 (o maior custo) |
| Log Analytics (logs do ambiente) | perto de zero com pouco log |

Confira os preços na calculadora do Azure na hora de criar. Alternativa
sem o Container Registry: publicar a imagem no GitHub Container Registry
(privado, sem custo) e dar ao Container App uma credencial de leitura.

## Passo a passo

### 0. Conta

1. Criar a assinatura do Azure em nome da associação (portal.azure.com).
2. Ative um **alerta de orçamento** (Cost Management → Budgets), por
   exemplo de R$ 50 por mês, para ser avisado se algo sair do previsto.

### 1. Ferramentas (no WSL)

```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
az login                                   # abre o navegador
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.Storage
az provider register --namespace Microsoft.ContainerRegistry
```

Sem o registro do `Microsoft.Storage`, os comandos de armazenamento
respondem `SubscriptionNotFound` (a assinatura existe; o serviço é que
não está ativado).

### 2. Nomes

Nomes de conta de armazenamento e de registro: só letras minúsculas e
números, únicos no Azure inteiro.

```bash
RG=meu-grupo
LOCAL=brazilsouth
SA=<sua-conta>              # conta de armazenamento (nome único no Azure)
ACR=<seu-registro>          # registro de imagens (nome único no Azure)
AMB=meu-ambiente            # ambiente do Container Apps
APP=elo-agente              # o contêiner
```

### 3. Grupo e armazenamento

```bash
az group create -n $RG -l $LOCAL
az storage account create -n $SA -g $RG -l $LOCAL --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false
az storage share-rm create --storage-account $SA -g $RG -n agente --quota 5
# arquivos apagados ficam recuperáveis por 30 dias
az storage account file-service-properties update --account-name $SA -g $RG \
  --enable-delete-retention true --delete-retention-days 30
```

### 4. Imagem (montada na nuvem, sem Docker local)

```bash
az acr create -n $ACR -g $RG -l $LOCAL --sku Basic
cd revenue-reconciliation-agent
az acr build -r $ACR -t conselho-fiscal:1 .
```

Em assinaturas novas, a Microsoft pode recusar a montagem na nuvem
(`TasksOperationsNotAllowed`; foi o caso em 2026-10-20). Nesse caso, monte
no Docker local e envie:

```bash
docker build --platform linux/amd64 -t $ACR.azurecr.io/conselho-fiscal:1 .
az acr login -n $ACR
docker push $ACR.azurecr.io/conselho-fiscal:1
```

A rede do WSL às vezes derruba conexões; se o `az acr login` ou o
`docker push` falhar com conexão encerrada, basta repetir.

### 5. Ambiente e volume

```bash
az containerapp env create -n $AMB -g $RG -l $LOCAL
CHAVE_SA=$(az storage account keys list -n $SA -g $RG --query "[0].value" -o tsv)
az containerapp env storage set -n $AMB -g $RG --storage-name agente \
  --azure-file-account-name $SA --azure-file-account-key "$CHAVE_SA" \
  --azure-file-share-name agente --access-mode ReadWrite
```

### 6. O contêiner

A chave do Gemini vai como segredo, lida do arquivo (nunca colada em chat
nem no histórico):

```bash
az containerapp create -n $APP -g $RG --environment $AMB \
  --image $ACR.azurecr.io/conselho-fiscal:1 \
  --registry-server $ACR.azurecr.io --registry-identity system \
  --target-port 8000 --ingress external \
  --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1Gi \
  --secrets "gemini-api-key=$(cat ~/.config/conselho-fiscal/gemini_api_key)" \
  --env-vars GEMINI_API_KEY=secretref:gemini-api-key
```

Se a conexão cair durante o `create` (a rede do WSL oscila), o app pode
ficar pela metade: criado com a imagem provisória
`mcr.microsoft.com/k8se/quickstart` e sem a permissão de ler o registro.
Para completar (foi o caso em 2026-10-20):

```bash
PID=$(az containerapp show -n $APP -g $RG --query identity.principalId -o tsv)
az role assignment create --assignee-object-id $PID --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope $(az acr show -n $ACR --query id -o tsv)
az containerapp registry set -n $APP -g $RG --server $ACR.azurecr.io --identity system
```

e, no `app.yaml` abaixo, troque também o `image` para
`$ACR.azurecr.io/conselho-fiscal:1`. Com a rede instável, o `update`
com `--no-wait` evita a queda durante o acompanhamento; o estado se
confere com `az containerapp show ... --query properties.provisioningState`.

Montar o Azure Files em `/dados` (a linha de comando não monta volumes;
exporta-se a configuração, acrescenta-se o volume e atualiza-se):

```bash
az containerapp show -n $APP -g $RG -o yaml > app.yaml
```

Em `app.yaml`, dentro de `properties.template`, acrescente (ou complete):

```yaml
    containers:
    - name: elo-agente
      # (manter o que já está: image, env, resources…)
      volumeMounts:
      - volumeName: dados
        mountPath: /dados
      probes:
      - type: Liveness
        httpGet: {path: /saude, port: 8000}
      - type: Readiness
        httpGet: {path: /saude, port: 8000}
    volumes:
    - name: dados
      storageType: AzureFile
      storageName: agente
      mountOptions: uid=1000,gid=1000,dir_mode=0750,file_mode=0640
```

```bash
az containerapp update -n $APP -g $RG --yaml app.yaml
rm app.yaml        # tem a configuração do app; não vai para o git
```

### 7. Conferir

```bash
URL=$(az containerapp show -n $APP -g $RG --query properties.configuration.ingress.fqdn -o tsv)
curl https://$URL/saude          # {"ok":true}
curl -o /dev/null -w "%{http_code}\n" https://$URL/        # 404: sem simulador
az containerapp logs show -n $APP -g $RG --tail 50
```

### Atualizar a versão

```bash
az acr build -r $ACR -t conselho-fiscal:2 .   # ou docker build + push, como no passo 4
az containerapp update -n $APP -g $RG --image $ACR.azurecr.io/conselho-fiscal:2
```

### Ligar o WhatsApp

Os segredos ficam em arquivos no WSL (`~/.config/conselho-fiscal/`,
`chmod 600`) e vão direto para o Azure, sem aparecer na tela
(variáveis em [agente.md](agente.md#whatsapp)):

```bash
D=~/.config/conselho-fiscal
az containerapp secret set -n $APP -g $RG --secrets \
  whatsapp-token="$(cat $D/whatsapp_token)" \
  whatsapp-app-secret="$(cat $D/whatsapp_app_secret)" \
  whatsapp-verify-token="$(cat $D/whatsapp_verify_token)"
az containerapp update -n $APP -g $RG --no-wait --set-env-vars \
  WHATSAPP_TOKEN=secretref:whatsapp-token \
  WHATSAPP_APP_SECRET=secretref:whatsapp-app-secret \
  WHATSAPP_VERIFY_TOKEN=secretref:whatsapp-verify-token \
  WHATSAPP_PHONE_NUMBER_ID=<id do número> \
  WHATSAPP_CONTATOS="5511999990000=tesouraria,cf" \
  WHATSAPP_GRAPH_VERSION=v25.0
```

Depois, no app da Meta (WhatsApp > Configuração), aponte o webhook para
`https://<endereço>/whatsapp`, com o mesmo verify token, e assine o campo
`messages`. Para conferir: `GET /whatsapp?hub.mode=subscribe&hub.verify_token=…&hub.challenge=123`
devolve `123`, e um `POST` sem assinatura dá 403.

### Enviar os vínculos confirmados (opcional)

```bash
az storage file upload --account-name $SA --account-key "$CHAVE_SA" --share-name agente \
  --source cadastros/vinculos_confirmados.json --path cadastros/vinculos_confirmados.json
```

### Apagar tudo

```bash
az group delete -n $RG        # apaga TODOS os recursos e os dados do grupo
```

## Testar a imagem localmente (Docker Desktop)

No Docker Desktop: Settings → Resources → WSL integration → ligar a
integração com esta distribuição. Depois:

```bash
cd revenue-reconciliation-agent
docker build -t conselho-fiscal:teste .
mkdir -p /tmp/cf-dados
docker run --rm -p 8000:8000 -v /tmp/cf-dados:/dados conselho-fiscal:teste
curl http://127.0.0.1:8000/saude          # em outro terminal
```

## Pontos de atenção

- **Gemini no plano gratuito:** os textos enviados podem ser usados pelo
  Google para melhorar os produtos. Já vai só o mínimo (apelidos, sem CPF);
  se o uso contínuo mostrar necessidade, avaliar o plano pago, que não usa os
  dados.
- **Backup:** o Azure Files guarda os apagados por 30 dias. Para cópias
  periódicas, dá para ativar o backup do compartilhamento (Recovery
  Services) ou baixar a pasta de tempos em tempos.
- **Acesso ao portal:** só quem precisa, com autenticação em dois fatores.
