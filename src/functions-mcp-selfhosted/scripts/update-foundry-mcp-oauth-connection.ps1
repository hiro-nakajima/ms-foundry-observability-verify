param(
  [string]$SubscriptionId,
  [string]$ResourceGroup,
  [string]$FoundryAccountName,
  [string]$FoundryProjectName,
  [string]$ConnectionName,
  [string]$ClientOutputFile,
  [string]$ApiVersion = "2025-04-01-preview",
  [string]$ClientSecret
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

function Get-RequiredConfigValue {
  param([string]$Value, [string]$EnvironmentName)
  $resolved = Get-ConfigValue -Value $Value -EnvironmentName $EnvironmentName
  if ([string]::IsNullOrWhiteSpace($resolved)) { throw "Required value is missing: $EnvironmentName" }
  return $resolved
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FunctionRoot = Split-Path -Parent $ScriptDir

$SubscriptionId = Get-RequiredConfigValue -Value $SubscriptionId -EnvironmentName "SUBSCRIPTION_ID"
$ResourceGroup = Get-RequiredConfigValue -Value $ResourceGroup -EnvironmentName "RESOURCE_GROUP"
$FoundryAccountName = Get-RequiredConfigValue -Value $FoundryAccountName -EnvironmentName "FOUNDRY_ACCOUNT_NAME"
$FoundryProjectName = Get-RequiredConfigValue -Value $FoundryProjectName -EnvironmentName "FOUNDRY_PROJECT_NAME"
$ConnectionName = Get-RequiredConfigValue -Value $ConnectionName -EnvironmentName "CONNECTION_NAME"
$ClientOutputFile = Get-ConfigValue -Value $ClientOutputFile -EnvironmentName "CLIENT_OUTPUT_FILE" -DefaultValue (Join-Path $FunctionRoot "infra\entra\foundry-oauth-client-app.outputs.json")
$ClientSecret = Get-ConfigValue -Value $ClientSecret -EnvironmentName "CLIENT_SECRET"

if (-not (Test-Path $ClientOutputFile)) {
  throw "Client app output file not found: $ClientOutputFile"
}

$clientOutput = Get-Content -Raw -Path $ClientOutputFile | ConvertFrom-Json -Depth 20
$tenantId = [string]$clientOutput.tenantId
$clientId = [string]$clientOutput.appId
if ([string]::IsNullOrWhiteSpace($ClientSecret)) { $ClientSecret = [string]$clientOutput.clientSecret }
$scope = [string]$clientOutput.scope

if ([string]::IsNullOrWhiteSpace($ClientSecret)) {
  throw "Client secret is missing. Set CLIENT_SECRET or use an output file that contains clientSecret."
}

$authUrl = "https://login.microsoftonline.com/$tenantId/oauth2/v2.0/authorize"
$tokenUrl = "https://login.microsoftonline.com/$tenantId/oauth2/v2.0/token"
$connectionUrl = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$FoundryAccountName/projects/$FoundryProjectName/connections/$ConnectionName`?api-version=$ApiVersion"

$currentConnection = az rest --method GET --url $connectionUrl -o json | ConvertFrom-Json -Depth 30
$props = $currentConnection.properties
$target = [string]$props.target
$redirectUrl = [string]$props.redirectUrl
$connectorName = [string]$props.connectorName

if ([string]::IsNullOrWhiteSpace($target)) {
  throw "Current Foundry connection target is missing for $ConnectionName"
}

$properties = [ordered]@{}
foreach ($property in $props.PSObject.Properties) {
  if ($property.Name -ne "error") {
    $properties[$property.Name] = $property.Value
  }
}

$properties["authType"] = "OAuth2"
$properties["category"] = if ($properties["category"]) { $properties["category"] } else { "RemoteTool" }
$properties["target"] = $target
$properties["credentials"] = [ordered]@{
  tenantId = $tenantId
  clientId = $clientId
  clientSecret = $ClientSecret
  authUrl = $authUrl
}
$properties["authorizationUrl"] = $authUrl
$properties["tokenUrl"] = $tokenUrl
$properties["refreshUrl"] = $tokenUrl
$properties["scopes"] = @($scope)
if (-not $properties["metadata"]) { $properties["metadata"] = @{ type = "custom_MCP" } }
if ($null -eq $properties["isSharedToAll"]) { $properties["isSharedToAll"] = $false }
if ($null -eq $properties["useWorkspaceManagedIdentity"]) { $properties["useWorkspaceManagedIdentity"] = $false }
if (-not $properties["peRequirement"]) { $properties["peRequirement"] = "NotRequired" }
if (-not $properties["peStatus"]) { $properties["peStatus"] = "NotApplicable" }
if (-not $properties["group"]) { $properties["group"] = "GenericProtocol" }
if ($null -eq $properties["useCustomConnector"]) { $properties["useCustomConnector"] = $false }
if (-not [string]::IsNullOrWhiteSpace($redirectUrl)) { $properties["redirectUrl"] = $redirectUrl }
if (-not [string]::IsNullOrWhiteSpace($connectorName)) { $properties["connectorName"] = $connectorName }

$requestBody = @{ properties = $properties } | ConvertTo-Json -Depth 30 -Compress

az rest `
  --method PUT `
  --url $connectionUrl `
  --headers "Content-Type=application/json" `
  --body $requestBody `
  --output none | Out-Null

Write-Host "Foundry MCP OAuth connection updated."
Write-Host "Connection : $ConnectionName"
Write-Host "Target     : $target"
Write-Host "Client ID  : $clientId"
Write-Host "Scope      : $scope"
Write-Host "Redirect   : $redirectUrl"
