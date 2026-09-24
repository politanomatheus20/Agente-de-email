<#
.SYNOPSIS
    Permite que o GitHub Actions publique o agente no Azure sem guardar senhas.

.DESCRIPTION
    Cria uma identidade no Entra ID com credencial federada (OIDC) para o
    repositório do GitHub e dá a ela permissão de publicar no Function App.
    Ao final, mostra os valores para cadastrar no GitHub.

.EXAMPLE
    .\scripts\setup-github-deploy.ps1 -SubscriptionId "xxxx" -GitHubRepo "grupodata/suporte-omnis"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $SubscriptionId,
    [Parameter(Mandatory)] [string] $GitHubRepo,
    [string] $ResourceGroup = "rg-suporte-omnis",
    [string] $Branch = "main"
)

$ErrorActionPreference = "Stop"

az account set --subscription $SubscriptionId
$tenantId = az account show --query tenantId -o tsv
$functionApp = az deployment group show --resource-group $ResourceGroup --name "suporte-omnis" `
    --query properties.outputs.functionAppName.value -o tsv
$functionAppId = az functionapp show -g $ResourceGroup -n $functionApp --query id -o tsv

Write-Host "Criando a identidade de deploy do GitHub..." -ForegroundColor Cyan
$appId = az ad app create --display-name "github-deploy-suporte-omnis" --query appId -o tsv
az ad sp create --id $appId --only-show-errors | Out-Null

$credential = @{
    name      = "github-$($Branch)"
    issuer    = "https://token.actions.githubusercontent.com"
    subject   = "repo:$($GitHubRepo):ref:refs/heads/$Branch"
    audiences = @("api://AzureADTokenExchange")
} | ConvertTo-Json -Compress
$credentialFile = New-TemporaryFile
Set-Content -Path $credentialFile -Value $credential -Encoding utf8
az ad app federated-credential create --id $appId --parameters "@$credentialFile" --only-show-errors | Out-Null
Remove-Item $credentialFile -Force

Write-Host "Dando permissão de publicação apenas no Function App..." -ForegroundColor Cyan
Start-Sleep -Seconds 15
az role assignment create --assignee $appId --role "Website Contributor" --scope $functionAppId --only-show-errors | Out-Null

Write-Host ""
Write-Host "Cadastre no GitHub (Settings > Secrets and variables > Actions):" -ForegroundColor Green
Write-Host "  Secrets:"
Write-Host "    AZURE_CLIENT_ID       = $appId"
Write-Host "    AZURE_TENANT_ID       = $tenantId"
Write-Host "    AZURE_SUBSCRIPTION_ID = $SubscriptionId"
Write-Host "  Variables:"
Write-Host "    AZURE_FUNCTIONAPP_NAME = $functionApp"
