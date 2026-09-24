// ---------------------------------------------------------------------------
// Suporte Omnis - infraestrutura no Azure
//
// Cria: Function App (Flex Consumption, Python 3.12), Storage, Application
// Insights, Key Vault com os segredos, e PostgreSQL Flexible Server.
// Execute pelo script scripts/deploy.ps1.
// ---------------------------------------------------------------------------

targetScope = 'resourceGroup'

@description('Prefixo curto usado no nome dos recursos (letras minúsculas e números).')
@minLength(3)
@maxLength(12)
param prefix string = 'omnissup'

@description('Região dos recursos.')
param location string = resourceGroup().location

@description('Caixa de email monitorada.')
param mailboxAddress string = 'suporte@dataomnis.com.br'

@description('Emails da equipe que recebe os atendimentos complexos, separados por vírgula.')
param escalationRecipients string

@description('Tenant do Microsoft Entra ID onde está a caixa de email.')
param graphTenantId string = subscription().tenantId

@description('Client ID do aplicativo registrado para acessar a Graph API.')
param graphClientId string

@secure()
@description('Client Secret do aplicativo registrado para acessar a Graph API.')
param graphClientSecret string

@secure()
@description('Chave da API da Anthropic.')
param anthropicApiKey string

@description('Modelo do Claude usado pelo agente.')
param claudeModel string = 'claude-opus-5'

@description('Usuário administrador do PostgreSQL.')
param postgresAdminUser string = 'omnisadmin'

@secure()
@description('Senha do administrador do PostgreSQL.')
param postgresAdminPassword string

@description('true = modo simulação (não envia emails nem grava no banco).')
param dryRun bool = true

@description('Ignora emails recebidos antes desta data (ISO 8601).')
param processSince string = ''

var suffix = uniqueString(resourceGroup().id)
var names = {
  storage: take('${prefix}st${suffix}', 24)
  logs: '${prefix}-logs-${suffix}'
  insights: '${prefix}-ai-${suffix}'
  keyVault: take('${prefix}-kv-${suffix}', 24)
  plan: '${prefix}-plan-${suffix}'
  functionApp: '${prefix}-func-${suffix}'
  postgres: '${prefix}-pg-${suffix}'
}
var databaseName = 'suporte_omnis'
var deploymentContainer = 'deploymentpackage'

// IDs de papéis internos do Azure
var roles = {
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  storageTableDataContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
}

// ------------------------------------------------------------------ Observabilidade

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.logs
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: names.insights
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// ------------------------------------------------------------------ Storage

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: names.storage
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }

  resource blobService 'blobServices' = {
    name: 'default'

    resource container 'containers' = {
      name: deploymentContainer
    }
  }
}

// ------------------------------------------------------------------ PostgreSQL

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: names.postgres
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32 }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
    authConfig: { passwordAuth: 'Enabled' }
  }

  resource database 'databases' = {
    name: databaseName
    properties: {
      charset: 'UTF8'
      collation: 'en_US.utf8'
    }
  }

  // 0.0.0.0 é a regra especial que libera apenas serviços do próprio Azure.
  resource allowAzure 'firewallRules' = {
    name: 'AllowAzureServices'
    properties: {
      startIpAddress: '0.0.0.0'
      endIpAddress: '0.0.0.0'
    }
  }
}

// ------------------------------------------------------------------ Key Vault

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: names.keyVault
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
  }

  resource anthropicSecret 'secrets' = {
    name: 'anthropic-api-key'
    properties: { value: anthropicApiKey }
  }

  resource graphSecret 'secrets' = {
    name: 'graph-client-secret'
    properties: { value: graphClientSecret }
  }

  resource databaseSecret 'secrets' = {
    name: 'database-url'
    properties: {
      value: 'postgresql://${postgresAdminUser}:${uriComponent(postgresAdminPassword)}@${postgres.properties.fullyQualifiedDomainName}:5432/${databaseName}?sslmode=require'
    }
  }
}

// ------------------------------------------------------------------ Function App

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: names.plan
  location: location
  kind: 'functionapp'
  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: names.functionApp
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deploymentContainer}'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
      runtime: {
        name: 'python'
        version: '3.12'
      }
    }
  }
}

resource appSettings 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: functionApp
  name: 'appsettings'
  properties: {
    AzureWebJobsStorage__accountName: storage.name
    APPLICATIONINSIGHTS_CONNECTION_STRING: insights.properties.ConnectionString
    MAILBOX_ADDRESS: mailboxAddress
    ESCALATION_RECIPIENTS: escalationRecipients
    GRAPH_TENANT_ID: graphTenantId
    GRAPH_CLIENT_ID: graphClientId
    GRAPH_CLIENT_SECRET: '@Microsoft.KeyVault(SecretUri=${keyVault::graphSecret.properties.secretUri})'
    ANTHROPIC_API_KEY: '@Microsoft.KeyVault(SecretUri=${keyVault::anthropicSecret.properties.secretUri})'
    DATABASE_URL: '@Microsoft.KeyVault(SecretUri=${keyVault::databaseSecret.properties.secretUri})'
    CLAUDE_MODEL: claudeModel
    DRY_RUN: string(dryRun)
    PROCESS_SINCE: processSince
  }
  dependsOn: [
    kvSecretsUser
    storageRoles
  ]
}

// ------------------------------------------------------------------ Permissões da identidade

resource kvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, functionApp.id, roles.keyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleId in [
    roles.storageBlobDataOwner
    roles.storageQueueDataContributor
    roles.storageTableDataContributor
  ]: {
    scope: storage
    name: guid(storage.id, functionApp.id, roleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
      principalId: functionApp.identity.principalId
      principalType: 'ServicePrincipal'
    }
  }
]

// ------------------------------------------------------------------ Saídas

output functionAppName string = functionApp.name
output keyVaultName string = keyVault.name
output postgresServerName string = postgres.name
output postgresHost string = postgres.properties.fullyQualifiedDomainName
output databaseName string = databaseName
