param(
  [string]$ConfigFile
)

$ErrorActionPreference = "Stop"

# Creates or updates App B: the MCP Server API / Functions OBO app registration.
# Foundry OAuth client app registration is managed by deploy-foundry-oauth-client-app.ps1.

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

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FunctionRoot = Split-Path -Parent $ScriptDir
$ConfigFile = Get-ConfigValue -Value $ConfigFile -EnvironmentName "CONFIG_FILE" -DefaultValue (Join-Path $FunctionRoot "infra\entra\obo-app-config.example.json")

if (-not (Test-Path $ConfigFile)) {
  throw "Config file not found: $ConfigFile"
}

$config = Get-Content -Raw -Path $ConfigFile | ConvertFrom-Json -Depth 10
$displayName = $config.displayName
$signInAudience = if ($config.signInAudience) { $config.signInAudience } else { "AzureADMyOrg" }
$identifierUri = $config.identifierUri
$scope = $config.scope
$redirectUris = @()
if ($config.redirectUris) {
  $redirectUris = @($config.redirectUris)
}

$clientSecretConfig = $config.clientSecret
$createClientSecret = $true
$clientSecretDisplayName = "codex-obo-secret"
$clientSecretYearsValid = 1
if ($clientSecretConfig) {
  if ($null -ne $clientSecretConfig.create) {
    $createClientSecret = [bool]$clientSecretConfig.create
  }
  if ($clientSecretConfig.displayName) {
    $clientSecretDisplayName = $clientSecretConfig.displayName
  }
  if ($clientSecretConfig.yearsValid) {
    $clientSecretYearsValid = [int]$clientSecretConfig.yearsValid
  }
}

$grantAdminConsent = $false
if ($null -ne $config.grantAdminConsent) {
  $grantAdminConsent = [bool]$config.grantAdminConsent
}

$outputFileRaw = if ($config.outputFile) { [string]$config.outputFile } else { "infra/entra/obo-app.outputs.json" }
$outputFile = if ([System.IO.Path]::IsPathRooted($outputFileRaw)) { $outputFileRaw } else { Join-Path $FunctionRoot $outputFileRaw }
New-Item -ItemType Directory -Path (Split-Path -Parent $outputFile) -Force | Out-Null

$existingApp = az ad app list --display-name $displayName --query "[0]" -o json | ConvertFrom-Json
$appId = $existingApp.appId
$objectId = $existingApp.id

if ([string]::IsNullOrWhiteSpace($appId)) {
  $createdApp = az ad app create --display-name $displayName --sign-in-audience $signInAudience -o json | ConvertFrom-Json
  $appId = $createdApp.appId
  $objectId = $createdApp.id
}

if ([string]::IsNullOrWhiteSpace($identifierUri)) {
  $identifierUri = "api://$appId"
}

$currentApp = az rest --method GET --uri "https://graph.microsoft.com/v1.0/applications/$objectId" -o json | ConvertFrom-Json -Depth 20
$existingScope = $currentApp.api.oauth2PermissionScopes | Where-Object { $_.value -eq $scope.name } | Select-Object -First 1
$scopeId = if ($existingScope) { $existingScope.id } else { [guid]::NewGuid().ToString() }

$patchBody = @{
  identifierUris = @($identifierUri)
  api = @{
    requestedAccessTokenVersion = 2
    oauth2PermissionScopes = @(
      @{
        id = $scopeId
        value = $scope.name
        type = "User"
        isEnabled = $true
        adminConsentDisplayName = $scope.adminConsentDisplayName
        adminConsentDescription = $scope.adminConsentDescription
        userConsentDisplayName = $scope.userConsentDisplayName
        userConsentDescription = $scope.userConsentDescription
      }
    )
  }
  web = @{
    redirectUris = $redirectUris
  }
} | ConvertTo-Json -Depth 20 -Compress

az rest `
  --method PATCH `
  --uri "https://graph.microsoft.com/v1.0/applications/$objectId" `
  --headers "Content-Type=application/json" `
  --body $patchBody `
  --output none | Out-Null

$graphAppId = "00000003-0000-0000-c000-000000000000"
$graphPermissions = @()
if ($config.graphDelegatedPermissions) {
  $graphPermissions = @($config.graphDelegatedPermissions)
}

foreach ($permission in $graphPermissions) {
  $permissionId = az ad sp show `
    --id $graphAppId `
    --query "oauth2PermissionScopes[?value=='$permission'].id | [0]" `
    -o tsv

  if ([string]::IsNullOrWhiteSpace($permissionId)) {
    throw "Could not resolve Graph delegated permission: $permission"
  }

  try {
    az ad app permission add `
      --id $appId `
      --api $graphAppId `
      --api-permissions "$permissionId=Scope" `
      --output none | Out-Null
  }
  catch {
    Write-Host "Permission may already exist: $permission"
  }
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
$scopeValue = "$identifierUri/$($scope.name)"

$outputObject = [ordered]@{
  tenantId = $tenantId
  appId = $appId
  objectId = $objectId
  identifierUri = $identifierUri
  scope = $scopeValue
  clientSecret = $clientSecretValue
}

$outputObject | ConvertTo-Json -Depth 10 | Set-Content -Path $outputFile -Encoding UTF8

Write-Host "Entra MCP Server API / Functions OBO app deployment completed."
Write-Host "App ID     : $appId"
Write-Host "Identifier : $identifierUri"
Write-Host "Scope      : $scopeValue"
Write-Host "Output file: $outputFile"
