param(
  [string]$ServerAppId,
  [string]$ServerOutputFile,
  [string]$MatchPrefix = "https://global.consent.azure-apim.net/redirect/",
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

function Get-ConfigValue {
  param([string]$Value, [string]$EnvironmentName, [string]$DefaultValue = "")
  if (-not [string]::IsNullOrWhiteSpace($Value)) { return $Value }
  $envValue = [Environment]::GetEnvironmentVariable($EnvironmentName)
  if (-not [string]::IsNullOrWhiteSpace($envValue)) { return $envValue }
  return $DefaultValue
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FunctionRoot = Split-Path -Parent $ScriptDir
$ServerOutputFile = Get-ConfigValue -Value $ServerOutputFile -EnvironmentName "SERVER_OUTPUT_FILE" -DefaultValue (Join-Path $FunctionRoot "infra\entra\obo-app.outputs.json")
$ServerAppId = Get-ConfigValue -Value $ServerAppId -EnvironmentName "SERVER_APP_ID"
$matchPrefixEnv = [Environment]::GetEnvironmentVariable("MATCH_PREFIX")
if (-not [string]::IsNullOrWhiteSpace($matchPrefixEnv)) { $MatchPrefix = $matchPrefixEnv }
$dryRunEnv = [Environment]::GetEnvironmentVariable("DRY_RUN")
if ($dryRunEnv -eq "false") { $Apply = $true }

if ([string]::IsNullOrWhiteSpace($ServerAppId)) {
  if (-not (Test-Path $ServerOutputFile)) {
    throw "SERVER_APP_ID is not set and server output file was not found: $ServerOutputFile"
  }
  $serverOutput = Get-Content -Raw -Path $ServerOutputFile | ConvertFrom-Json -Depth 10
  $ServerAppId = [string]$serverOutput.appId
}

$serverApp = az ad app show --id $ServerAppId -o json | ConvertFrom-Json -Depth 20
$serverObjectId = [string]$serverApp.id
$currentApp = az rest --method GET --uri "https://graph.microsoft.com/v1.0/applications/$serverObjectId" -o json | ConvertFrom-Json -Depth 20
$currentRedirects = @()
if ($currentApp.web.redirectUris) { $currentRedirects = @($currentApp.web.redirectUris) }
$updatedRedirects = @($currentRedirects | Where-Object { -not $_.StartsWith($MatchPrefix) })
$removedRedirects = @($currentRedirects | Where-Object { $_.StartsWith($MatchPrefix) })

if ($removedRedirects.Count -eq 0) {
  Write-Host "No matching Foundry redirect URIs were found on server app $ServerAppId."
  exit 0
}

Write-Host "Server App ID : $ServerAppId"
Write-Host "Remove URIs   : $($removedRedirects -join ', ')"
Write-Host "Dry run       : $(-not $Apply)"

if (-not $Apply) {
  Write-Host "Dry run only. Pass -Apply or set DRY_RUN=false to apply."
  exit 0
}

$patchBody = @{ web = @{ redirectUris = $updatedRedirects } } | ConvertTo-Json -Depth 10 -Compress
az rest `
  --method PATCH `
  --uri "https://graph.microsoft.com/v1.0/applications/$serverObjectId" `
  --headers "Content-Type=application/json" `
  --body $patchBody `
  --output none | Out-Null

Write-Host "Removed matching Foundry redirect URIs from server app $ServerAppId."
