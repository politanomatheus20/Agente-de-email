# Guia de deploy no Azure

Este guia é para quem tem acesso de administrador ao Azure e ao Microsoft 365 da empresa.
Tudo está automatizado em scripts. O tempo total é de cerca de 30 minutos.

## O que será criado

| Recurso | Para que serve | Custo aproximado |
|---|---|---|
| Function App (Flex Consumption) | Executa o agente a cada 10 minutos | Poucos reais por mês |
| PostgreSQL Flexible Server B1ms | Guarda os chamados | O maior custo; confira no portal |
| Key Vault | Guarda as chaves e senhas | Centavos |
| Storage Account | Exigido pelo Function App | Centavos |
| Application Insights | Logs e alertas | Baixo, retenção de 30 dias |

O uso da API do Claude é cobrado à parte pela Anthropic.

## Pré-requisitos

- Azure CLI instalado: https://aka.ms/installazurecliwindows
- Permissão de **Owner** na assinatura do Azure. É necessária para criar as permissões
  da identidade do Function App.
- Permissão de **Administrador Global** no Microsoft 365, só para o passo 1.
- A chave da API da Anthropic.

Todos os comandos abaixo rodam no PowerShell, a partir da pasta do projeto.

## Passo 1: dar ao agente acesso à caixa de email

```powershell
.\scripts\setup-graph-app.ps1
```

Entre com a conta de administrador do Microsoft 365 quando o navegador abrir.
Anote os três valores exibidos no final.

> Se o Microsoft 365 e o Azure estiverem em tenants diferentes, rode este script no
> tenant do Microsoft 365. No passo 2, informe esse tenant em `-GraphTenantId`.

### Recomendado: restringir o acesso só à caixa de suporte

Por padrão, a permissão da Graph vale para todas as caixas da empresa. Para limitar à
caixa de suporte, rode no Exchange Online PowerShell:

```powershell
Connect-ExchangeOnline
New-DistributionGroup -Name "Agente Suporte Omnis - Escopo" -Type Security -Members suporte@dataomnis.com.br
New-ApplicationAccessPolicy -AppId <GRAPH_CLIENT_ID> `
  -PolicyScopeGroupId "Agente Suporte Omnis - Escopo" `
  -AccessRight RestrictAccess `
  -Description "Agente de suporte acessa apenas suporte@"
```

## Passo 2: criar a infraestrutura e publicar o agente

```powershell
.\scripts\deploy.ps1 -SubscriptionId "<ID da assinatura>" -GraphClientId "<GRAPH_CLIENT_ID>"
```

O script pede o `GRAPH_CLIENT_SECRET` e a chave da Anthropic, sem mostrar na tela.
A senha do PostgreSQL é gerada automaticamente e fica guardada apenas no Key Vault.

Parâmetros opcionais:

| Parâmetro | Padrão |
|---|---|
| `-ResourceGroup` | `rg-suporte-omnis` |
| `-Location` | `brazilsouth` |
| `-GraphTenantId` | tenant da assinatura do Azure |
| `-EscalationRecipients` | Caio, Matheus e Thiago |
| `-DryRun` | `$true` |
| `-CodeOnly` | publica só o código, sem mexer na infraestrutura |

## Passo 3: validar em modo simulação

O agente sobe em **modo simulação**. Ele lê e classifica os emails, mas só registra nos
logs o que faria.

1. Envie alguns emails de teste para suporte@dataomnis.com.br.
2. Espere até 10 minutos.
3. No portal do Azure, abra o Function App e vá em **Monitor** ou **Log stream**.
4. Confira as classificações e decisões nos logs.

## Passo 4: ligar de verdade

```powershell
az functionapp config appsettings set -g rg-suporte-omnis -n <nome do Function App> --settings DRY_RUN=false
```

O nome do Function App aparece no final do passo 2. A partir daqui o agente responde,
encaminha e grava no banco. Ele ignora emails recebidos antes do deploy.

## Passo 5 (opcional): deploy automático pelo GitHub

Depois de subir o código para o GitHub:

```powershell
.\scripts\setup-github-deploy.ps1 -SubscriptionId "<ID>" -GitHubRepo "<organizacao>/<repositorio>"
```

Cadastre no GitHub os valores exibidos, em **Settings > Secrets and variables > Actions**.
Crie também o environment `production` em **Settings > Environments**. A partir daí,
todo push na `main` que passar nos testes é publicado automaticamente.

## Acessar o banco de dados

O banco só aceita conexões de serviços do Azure. Para consultar do seu computador,
libere o seu IP temporariamente:

```powershell
az postgres flexible-server firewall-rule create -g rg-suporte-omnis -n <servidor> `
  --rule-name meu-ip --start-ip-address <seu IP> --end-ip-address <seu IP>
```

A connection string completa está no Key Vault, no segredo `database-url`.
Remova a regra quando terminar.

## Manutenção

- **Client Secret da Graph expira em 1 ano.** Gere outro com
  `az ad app credential reset --id <GRAPH_CLIENT_ID> --years 1` e atualize o segredo
  `graph-client-secret` no Key Vault.
- **Base de conhecimento:** edite os arquivos em `knowledge/` e publique de novo.
- **Alertas:** crie no Application Insights um alerta para execuções com falha da
  função `check_support_inbox`.
