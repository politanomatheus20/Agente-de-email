<#
.SYNOPSIS
    Registra o aplicativo que dá ao agente acesso à caixa suporte@dataomnis.com.br.

.DESCRIPTION
    Cria o registro de aplicativo no Microsoft Entra ID, concede as permissões
    Mail.ReadWrite e Mail.Send da Microsoft Graph, pede o consentimento do
    administrador e gera um Client Secret.

    Precisa ser executado por um Administrador Global ou Administrador de
    Funções Privilegiadas do tenant do Microsoft 365 onde a caixa de email está.

.EXAMPLE
    .\scripts\setup-graph-app.ps1
#>
[CmdletBinding()]
param(
    [string] $AppName = "Agente Suporte Omnis",
    [int] $SecretYears = 1
)

$ErrorActionPreference = "Stop"

$graphApiId = "00000003-0000-0000-c000-000000000000"
$mailReadWrite = "e2a3a72e-5f79-4c64-b1b1-878b674786c9"   # Mail.ReadWrite (aplicativo)
$mailSend = "b633e1c5-b582-4048-a93e-9f11b44c7e96"        # Mail.Send (aplicativo)

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI não encontrado. Instale em https://aka.ms/installazurecliwindows"
}

Write-Host "Entrando no tenant do Microsoft 365..." -ForegroundColor Cyan
az login --allow-no-subscriptions --only-show-errors | Out-Null
$tenantId = az account show --query tenantId -o tsv

Write-Host "Criando o registro de aplicativo '$AppName'..." -ForegroundColor Cyan
$appId = az ad app create --display-name $AppName --sign-in-audience AzureADMyOrg --query appId -o tsv
az ad sp create --id $appId --only-show-errors | Out-Null

Write-Host "Adicionando as permissões Mail.ReadWrite e Mail.Send..." -ForegroundColor Cyan
az ad app permission add --id $appId --api $graphApiId `
    --api-permissions "$mailReadWrite=Role" "$mailSend=Role" --only-show-errors

Write-Host "Aguardando a propagação no Entra ID..." -ForegroundColor Cyan
Start-Sleep -Seconds 20
az ad app permission admin-consent --id $appId --only-show-errors

Write-Host "Gerando o Client Secret (válido por $SecretYears ano)..." -ForegroundColor Cyan
$secret = az ad app credential reset --id $appId --display-name "agente-suporte" `
    --years $SecretYears --query password -o tsv --only-show-errors

Write-Host ""
Write-Host "Aplicativo criado com sucesso. Guarde estes valores:" -ForegroundColor Green
Write-Host "  GRAPH_TENANT_ID     = $tenantId"
Write-Host "  GRAPH_CLIENT_ID     = $appId"
Write-Host "  GRAPH_CLIENT_SECRET = $secret"
Write-Host ""
Write-Host "O secret não será exibido novamente. Anote a data de expiração para renovar." -ForegroundColor Yellow
Write-Host "Recomendado: restrinja o aplicativo à caixa de suporte (veja docs/DEPLOY.md)." -ForegroundColor Yellow
