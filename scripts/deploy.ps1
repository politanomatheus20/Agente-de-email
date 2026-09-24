<#
.SYNOPSIS
    Cria toda a infraestrutura no Azure e publica o agente de suporte.

.DESCRIPTION
    1. Entra no Azure e seleciona a assinatura.
    2. Cria o grupo de recursos.
    3. Provisiona Function App, PostgreSQL, Key Vault, Storage e Application Insights.
    4. Publica o código do agente.

    As tabelas do banco são criadas automaticamente na primeira execução do agente.
    Execute a partir da raiz do projeto. Pode ser executado de novo para atualizar.

.EXAMPLE
    .\scripts\deploy.ps1 -SubscriptionId "xxxx" -GraphClientId "yyyy"

.EXAMPLE
    .\scripts\deploy.ps1 -SubscriptionId "xxxx" -GraphClientId "yyyy" -DryRun $false
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $SubscriptionId,
    [Parameter(Mandatory)] [string] $GraphClientId,
    [string] $GraphTenantId = "",
    [string] $ResourceGroup = "rg-suporte-omnis",
    [string] $Location = "brazilsouth",
    [string] $Prefix = "omnissup",
    [string] $EscalationRecipients = "matheus.gavioli@datagroup.global,thiago.dourado@grupodata.com.br",
    [bool] $DryRun = $true,
    [switch] $CodeOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Read-Secret([string] $prompt) {
    $secure = Read-Host -Prompt $prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function New-StrongPassword {
    $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!#%*-_"
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return "Pg1!" + (-join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] }))
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI não encontrado. Instale em https://aka.ms/installazurecliwindows"
}

Write-Host "Entrando no Azure..." -ForegroundColor Cyan
# No Windows PowerShell 5.1, redirecionar o stderr de um programa com
# ErrorActionPreference=Stop interrompe o script. Por isso o "Continue" temporário.
$ErrorActionPreference = "Continue"
az account show --output none 2>$null
$loggedIn = $LASTEXITCODE -eq 0
$ErrorActionPreference = "Stop"
if (-not $loggedIn) { az login --only-show-errors | Out-Null }
az account set --subscription $SubscriptionId

if (-not $CodeOnly) {
    Write-Host "Criando o grupo de recursos $ResourceGroup em $Location..." -ForegroundColor Cyan
    az group create --name $ResourceGroup --location $Location --only-show-errors | Out-Null

    $graphSecret = Read-Secret "Cole o GRAPH_CLIENT_SECRET"
    $anthropicKey = Read-Secret "Cole a chave da API da Anthropic"
    $pgPassword = New-StrongPassword
    if (-not $GraphTenantId) { $GraphTenantId = az account show --query tenantId -o tsv }

    # Parâmetros sensíveis vão por arquivo temporário para não aparecerem no histórico.
    $paramsFile = New-TemporaryFile
    try {
        @{
            '$schema' = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"
            contentVersion = "1.0.0.0"
            parameters = @{
                prefix                = @{ value = $Prefix }
                escalationRecipients  = @{ value = $EscalationRecipients }
                graphTenantId         = @{ value = $GraphTenantId }
                graphClientId         = @{ value = $GraphClientId }
                graphClientSecret     = @{ value = $graphSecret }
                anthropicApiKey       = @{ value = $anthropicKey }
                postgresAdminPassword = @{ value = $pgPassword }
                dryRun                = @{ value = $DryRun }
                processSince          = @{ value = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
            }
        } | ConvertTo-Json -Depth 5 | Set-Content -Path $paramsFile -Encoding utf8

        Write-Host "Provisionando a infraestrutura (leva de 5 a 10 minutos)..." -ForegroundColor Cyan
        az deployment group create `
            --resource-group $ResourceGroup `
            --name "suporte-omnis" `
            --template-file (Join-Path $root "infra\main.bicep") `
            --parameters "@$paramsFile" `
            --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Falha ao provisionar a infraestrutura." }
    }
    finally {
        Remove-Item $paramsFile -Force -ErrorAction SilentlyContinue
    }
}

$functionApp = az deployment group show --resource-group $ResourceGroup --name "suporte-omnis" `
    --query properties.outputs.functionAppName.value -o tsv

Write-Host "Empacotando o código..." -ForegroundColor Cyan
$package = Join-Path ([IO.Path]::GetTempPath()) "suporte-omnis.zip"
$staging = Join-Path ([IO.Path]::GetTempPath()) "suporte-omnis-build"
Remove-Item $staging, $package -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $staging | Out-Null
foreach ($item in @("function_app.py", "host.json", "requirements.txt", "omnis_support", "knowledge")) {
    Copy-Item -Path (Join-Path $root $item) -Destination $staging -Recurse
}
Get-ChildItem $staging -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
# O Compress-Archive do Windows PowerShell 5.1 grava caminhos com "\", que o Linux
# do Azure não entende. O tar.exe do Windows 10/11 gera um zip compatível.
tar.exe -a -c -f $package -C $staging function_app.py host.json requirements.txt omnis_support knowledge
if ($LASTEXITCODE -ne 0) { throw "Falha ao empacotar o código." }

Write-Host "Publicando no Function App $functionApp..." -ForegroundColor Cyan
az functionapp deployment source config-zip `
    --resource-group $ResourceGroup --name $functionApp `
    --src $package --build-remote true --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Falha ao publicar o código." }

Remove-Item $staging, $package -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Pronto! O agente roda a cada 30 minutos." -ForegroundColor Green
if ($DryRun) {
    Write-Host "Modo SIMULAÇÃO ativo: nada é enviado. Acompanhe os logs e, quando estiver tudo certo:" -ForegroundColor Yellow
    Write-Host "  az functionapp config appsettings set -g $ResourceGroup -n $functionApp --settings DRY_RUN=false"
}
Write-Host "Logs: portal do Azure > $functionApp > Monitor (ou Application Insights > Logs)."
