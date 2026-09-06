param(
  [string]$ResourceGroup,
  [string]$FunctionAppName,
  [string]$EntraOutputFile
)

$ErrorActionPreference = "Stop"

function Get-ConfigValue {
  param(
    [string]$Value,
    [string]$EnvironmentName,
    [string]$DefaultValue = ""
  )

  if (-not [string]::IsNullOrWhiteSpace($Value)) {
    return $Value
  }

  $envValue = [Environment]::GetEnvironmentVariable($EnvironmentName)
  if (-not [string]::IsNullOrWhiteSpace($envValue)) {
    return $envValue
  }

  return $DefaultValue
}

function Get-RequiredConfigValue {
  param(
    [string]$Value,
    [string]$EnvironmentName
  )

  $resolved = Get-ConfigValue -Value $Value -EnvironmentName $EnvironmentName
  if ([string]::IsNullOrWhiteSpace($resolved)) {
    throw "Required value is missing: $EnvironmentName"
  }

  return $resolved
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FunctionRoot = Split-Path -Parent $ScriptDir

$ResourceGroup = Get-RequiredConfigValue -Value $ResourceGroup -EnvironmentName "RESOURCE_GROUP"
$FunctionAppName = Get-RequiredConfigValue -Value $FunctionAppName -EnvironmentName "FUNCTION_APP_NAME"
$EntraOutputFile = Get-ConfigValue -Value $EntraOutputFile -EnvironmentName "ENTRA_OUTPUT_FILE" -DefaultValue (Join-Path $FunctionRoot "infra\entra\obo-app.outputs.json")

if (-not (Test-Path $EntraOutputFile)) {
  throw "Entra output file not found: $EntraOutputFile"
}

$entra = Get-Content -Raw -Path $EntraOutputFile | ConvertFrom-Json -Depth 10
$entraTenantId = $entra.tenantId
$entraClientId = $entra.appId
$entraClientSecret = $entra.clientSecret
$entraApplicationIdUri = $entra.identifierUri

$expectedTokenAudiences = Get-ConfigValue -Value $null -EnvironmentName "EXPECTED_TOKEN_AUDIENCES" -DefaultValue "$entraApplicationIdUri,$entraClientId"
$expectedTenantId = Get-ConfigValue -Value $null -EnvironmentName "EXPECTED_TENANT_ID" -DefaultValue $entraTenantId
$graphScopes = Get-ConfigValue -Value $null -EnvironmentName "GRAPH_SCOPES" -DefaultValue "https://graph.microsoft.com/User.Read"
$graphBaseUrl = Get-ConfigValue -Value $null -EnvironmentName "GRAPH_BASE_URL" -DefaultValue "https://graph.microsoft.com/v1.0"
$oboMaxRetries = Get-ConfigValue -Value $null -EnvironmentName "OBO_MAX_RETRIES" -DefaultValue "2"
$oboRetryBackoffSeconds = Get-ConfigValue -Value $null -EnvironmentName "OBO_RETRY_BACKOFF_SECONDS" -DefaultValue "0.5"
$graphTimeoutSeconds = Get-ConfigValue -Value $null -EnvironmentName "GRAPH_TIMEOUT_SECONDS" -DefaultValue "15"
$graphMaxRetries = Get-ConfigValue -Value $null -EnvironmentName "GRAPH_MAX_RETRIES" -DefaultValue "2"
$graphRetryBackoffSeconds = Get-ConfigValue -Value $null -EnvironmentName "GRAPH_RETRY_BACKOFF_SECONDS" -DefaultValue "0.5"

az functionapp config appsettings set `
  --resource-group $ResourceGroup `
  --name $FunctionAppName `
  --settings `
    ENTRA_TENANT_ID=$entraTenantId `
    ENTRA_CLIENT_ID=$entraClientId `
    ENTRA_CLIENT_SECRET=$entraClientSecret `
    EXPECTED_TOKEN_AUDIENCES=$expectedTokenAudiences `
    EXPECTED_TENANT_ID=$expectedTenantId `
    GRAPH_SCOPES=$graphScopes `
    GRAPH_BASE_URL=$graphBaseUrl `
    OBO_MAX_RETRIES=$oboMaxRetries `
    OBO_RETRY_BACKOFF_SECONDS=$oboRetryBackoffSeconds `
    GRAPH_TIMEOUT_SECONDS=$graphTimeoutSeconds `
    GRAPH_MAX_RETRIES=$graphMaxRetries `
    GRAPH_RETRY_BACKOFF_SECONDS=$graphRetryBackoffSeconds `
  --output none | Out-Null

Write-Host "Applied Entra OBO settings to Function App."
Write-Host "Function App : $FunctionAppName"
Write-Host "ResourceGroup: $ResourceGroup"
