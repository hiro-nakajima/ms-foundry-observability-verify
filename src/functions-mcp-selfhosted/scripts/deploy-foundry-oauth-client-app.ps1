param(
  [string]$ConfigFile
)

$ErrorActionPreference = "Stop"

function Get-ConfigValue {
  param(
    [string]$Value,
    [string]$EnvironmentName,
    [string]$DefaultValue = ""
  )

  if (-not [string]::IsNullOrWhiteSpace($Value)) { return $Value }
  $envValue = [Environment]::GetEnvironmentVariable($EnvironmentName)
  if (-not [string]::IsNullOrWhiteSpace($envValue)) { return $envValue }
  return $DefaultValue
}

function Resolve-RepoPath {
  param([string]$Path, [string]$Root)
  if ([System.IO.Path]::IsPathRooted($Path)) { return $Path }
  return (Join-Path $Root $Path)
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FunctionRoot = Split-Path -Parent $ScriptDir
$ConfigFile = Get-ConfigValue -Value $ConfigFile -EnvironmentName "CONFIG_FILE" -DefaultValue (Join-Path $FunctionRoot "infra\entra\foundry-oauth-client-app-config.example.json")

if (-not (Test-Path $ConfigFile)) {
  throw "Config file not found: $ConfigFile"
}

$config = Get-Content -Raw -Path $ConfigFile | ConvertFrom-Json -Depth 20
$displayName = [string]$config.displayName
$signInAudience = if ($config.signInAudience) { [string]$config.signInAudience } else { "AzureADMyOrg" }
$serverOutputFileRaw = if ($config.serverOutputFile) { [string]$config.serverOutputFile } else { "infra/entra/obo-app.outputs.json" }
$serverOutputFile = Resolve-RepoPath -Path $serverOutputFileRaw -Root $FunctionRoot
$serverAppId = Get-ConfigValue -Value ([string]$config.serverAppId) -EnvironmentName "SERVER_APP_ID"
$serverScopeName = Get-ConfigValue -Value ([string]$config.serverScopeName) -EnvironmentName "SERVER_SCOPE_NAME" -DefaultValue "access_as_user"
$preAuthorizeClient = if ($null -ne $config.preAuthorizeClient) { [bool]$config.preAuthorizeClient } else { $true }
$grantAdminConsent = if ($null -ne $config.grantAdminConsent) { [bool]$config.grantAdminConsent } else { $false }
$outputFileRaw = if ($config.outputFile) { [string]$config.outputFile } else { "infra/entra/foundry-oauth-client-app.outputs.json" }
$outputFile = Resolve-RepoPath -Path $outputFileRaw -Root $FunctionRoot

$redirectUris = @()
if ($config.redirectUris) { $redirectUris = @($config.redirectUris) }
$redirectUrisEnv = [Environment]::GetEnvironmentVariable("REDIRECT_URIS")
if (-not [string]::IsNullOrWhiteSpace($redirectUrisEnv)) {
  $redirectUris = @($redirectUrisEnv.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

$clientSecretConfig = $config.clientSecret
$createClientSecret = $true
$clientSecretDisplayName = "codex-foundry-oauth-client-secret"
$clientSecretYearsValid = 1
if ($clientSecretConfig) {
  if ($null -ne $clientSecretConfig.create) { $createClientSecret = [bool]$clientSecretConfig.create }
  if ($clientSecretConfig.displayName) { $clientSecretDisplayName = [string]$clientSecretConfig.displayName }
  if ($clientSecretConfig.yearsValid) { $clientSecretYearsValid = [int]$clientSecretConfig.yearsValid }
}

if ([string]::IsNullOrWhiteSpace($displayName)) {
  throw "displayName is required in $ConfigFile"
}

if ([string]::IsNullOrWhiteSpace($serverAppId)) {
  if (-not (Test-Path $serverOutputFile)) {
    throw "Server app ID is not set and server output file was not found: $serverOutputFile"
  }
  $serverOutput = Get-Content -Raw -Path $serverOutputFile | ConvertFrom-Json -Depth 10
  $serverAppId = [string]$serverOutput.appId
}

if ([string]::IsNullOrWhiteSpace($serverAppId)) {
  throw "serverAppId is required. Set .serverAppId, SERVER_APP_ID, or serverOutputFile."
}

New-Item -ItemType Directory -Path (Split-Path -Parent $outputFile) -Force | Out-Null

$serverApp = az ad app show --id $serverAppId -o json | ConvertFrom-Json -Depth 20
$serverObjectId = [string]$serverApp.id
$serverIdentifierUri = if ($serverApp.identifierUris -and $serverApp.identifierUris.Count -gt 0) { [string]$serverApp.identifierUris[0] } else { "api://$serverAppId" }
$serverScope = $serverApp.api.oauth2PermissionScopes | Where-Object { $_.value -eq $serverScopeName } | Select-Object -First 1
if (-not $serverScope) {
  throw "Could not resolve server delegated scope '$serverScopeName' from app $serverAppId"
}
$serverScopeId = [string]$serverScope.id

$existingApp = az ad app list --display-name $displayName --query "[0]" -o json | ConvertFrom-Json -Depth 20
$appId = [string]$existingApp.appId
$objectId = [string]$existingApp.id

if ([string]::IsNullOrWhiteSpace($appId)) {
  $createdApp = az ad app create --display-name $displayName --sign-in-audience $signInAudience -o json | ConvertFrom-Json -Depth 20
  $appId = [string]$createdApp.appId
  $objectId = [string]$createdApp.id
}

$clientPatchBody = @{
  identifierUris = @()
  api = @{
    requestedAccessTokenVersion = 2
    oauth2PermissionScopes = @()
  }
  web = @{
    redirectUris = $redirectUris
  }
} | ConvertTo-Json -Depth 20 -Compress

az rest `
  --method PATCH `
  --uri "https://graph.microsoft.com/v1.0/applications/$objectId" `
  --headers "Content-Type=application/json" `
  --body $clientPatchBody `
  --output none | Out-Null

try {
  az ad app permission add `
    --id $appId `
    --api $serverAppId `
    --api-permissions "$serverScopeId=Scope" `
    --output none | Out-Null
}
catch {
  Write-Host "Permission may already exist: $serverScopeName"
}

if ($preAuthorizeClient) {
  $currentServerApp = az rest --method GET --uri "https://graph.microsoft.com/v1.0/applications/$serverObjectId" -o json | ConvertFrom-Json -Depth 30
  $preAuthorizedApplications = @()
  if ($currentServerApp.api.preAuthorizedApplications) {
    $preAuthorizedApplications = @($currentServerApp.api.preAuthorizedApplications | Where-Object { $_.appId -ne $appId })
  }
  $preAuthorizedApplications += [pscustomobject]@{
    appId = $appId
    delegatedPermissionIds = @($serverScopeId)
  }
  $serverPatchBody = @{
    api = @{
      requestedAccessTokenVersion = if ($currentServerApp.api.requestedAccessTokenVersion) { $currentServerApp.api.requestedAccessTokenVersion } else { 2 }
      oauth2PermissionScopes = @($currentServerApp.api.oauth2PermissionScopes)
      preAuthorizedApplications = $preAuthorizedApplications
    }
  } | ConvertTo-Json -Depth 30 -Compress

  az rest `
    --method PATCH `
    --uri "https://graph.microsoft.com/v1.0/applications/$serverObjectId" `
    --headers "Content-Type=application/json" `
    --body $serverPatchBody `
    --output none | Out-Null
}

if ($grantAdminConsent) {
  az ad app permission admin-consent --id $appId --output none | Out-Null
}

$clientSecretValue = ""
if ($createClientSecret) {
  $clientSecretValue = az ad app credential reset `
    --id $appId `
    --append `
    --display-name $clientSecretDisplayName `
    --years $clientSecretYearsValid `
    --query password `
    -o tsv
}

$tenantId = az account show --query tenantId -o tsv
$scopeValue = "$serverIdentifierUri/$serverScopeName"

$outputObject = [ordered]@{
  tenantId = $tenantId
  appId = $appId
  objectId = $objectId
  displayName = $displayName
  serverAppId = $serverAppId
  serverObjectId = $serverObjectId
  serverIdentifierUri = $serverIdentifierUri
  serverScopeName = $serverScopeName
  serverScopeId = $serverScopeId
  scope = $scopeValue
  redirectUris = $redirectUris
  clientSecret = $clientSecretValue
}

$outputObject | ConvertTo-Json -Depth 20 | Set-Content -Path $outputFile -Encoding UTF8

Write-Host "Foundry OAuth client app deployment completed."
Write-Host "Client App ID : $appId"
Write-Host "Server App ID : $serverAppId"
Write-Host "Scope         : $scopeValue"
Write-Host "Redirect URIs : $($redirectUris -join ', ')"
Write-Host "Output file   : $outputFile"
