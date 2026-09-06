param(
  [string]$ResourceGroup,
  [string]$FunctionAppName,
  [string]$FunctionAppUrl,
  [string]$VendoredPackagesDir,
  [string]$BuildRemote
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

function ConvertTo-HttpsOrigin {
  param(
    [string]$Name,
    [string]$Value
  )

  $normalizedValue = $Value.Trim().TrimEnd("/")
  $parsedUri = $null
  $isValid = [Uri]::TryCreate($normalizedValue, [UriKind]::Absolute, [ref]$parsedUri)

  if (
    -not $isValid -or
    $parsedUri.Scheme -ne "https" -or
    $parsedUri.AbsolutePath -ne "/" -or
    -not [string]::IsNullOrEmpty($parsedUri.Query) -or
    -not [string]::IsNullOrEmpty($parsedUri.Fragment)
  ) {
    throw "$Name must be an HTTPS origin without a path, query, or fragment: $Value"
  }

  return $normalizedValue
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FunctionRoot = Split-Path -Parent $ScriptDir
$ZipPath = Join-Path $ScriptDir "functions-mcp-selfhosted.zip"
$StageDir = Join-Path $ScriptDir ".deploy-stage-functions"

$ResourceGroup = Get-RequiredConfigValue -Value $ResourceGroup -EnvironmentName "RESOURCE_GROUP"
$FunctionAppName = Get-RequiredConfigValue -Value $FunctionAppName -EnvironmentName "FUNCTION_APP_NAME"
$FunctionAppUrl = Get-RequiredConfigValue -Value $FunctionAppUrl -EnvironmentName "FUNCTION_APP_URL"
$VendoredPackagesDir = Get-ConfigValue -Value $VendoredPackagesDir -EnvironmentName "VENDORED_PACKAGES_DIR"
$BuildRemote = Get-ConfigValue -Value $BuildRemote -EnvironmentName "BUILD_REMOTE" -DefaultValue "true"
$FunctionAppUrl = ConvertTo-HttpsOrigin -Name "FunctionAppUrl" -Value $FunctionAppUrl
$McpEndpoint = "$FunctionAppUrl/mcp"

if ($BuildRemote -notin @("true", "false")) {
  throw "BUILD_REMOTE must be true or false."
}

Write-Host "Resource group : $ResourceGroup"
Write-Host "Function App   : $FunctionAppName"
Write-Host "Function URL   : $FunctionAppUrl"
Write-Host "MCP Endpoint   : $McpEndpoint"
Write-Host "Zip path       : $ZipPath"

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
if (Test-Path $StageDir) { Remove-Item $StageDir -Recurse -Force }
New-Item -ItemType Directory -Path $StageDir | Out-Null

$itemsToCopy = @(
  "mcp_server.py",
  "host.json",
  "requirements.txt",
  "mcp_handler"
)

foreach ($item in $itemsToCopy) {
  $source = Join-Path $FunctionRoot $item
  if (Test-Path $source) {
    Copy-Item $source -Destination $StageDir -Recurse
  }
}

if (-not [string]::IsNullOrWhiteSpace($VendoredPackagesDir)) {
  $BuildRemote = "false"
  Write-Host "Vendored packages: $VendoredPackagesDir"
  $sitePackagesDir = Join-Path $StageDir ".python_packages/lib/site-packages"
  New-Item -ItemType Directory -Path $sitePackagesDir -Force | Out-Null
  Copy-Item (Join-Path $VendoredPackagesDir "*") -Destination $sitePackagesDir -Recurse -Force
}

Write-Host "Remote build   : $BuildRemote"

Get-ChildItem -Path $StageDir -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue |
  Remove-Item -Force

Get-ChildItem -Path $StageDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force

Compress-Archive -Path (Join-Path $StageDir "*") -DestinationPath $ZipPath -Force

az functionapp deployment source config-zip `
  --resource-group $ResourceGroup `
  --name $FunctionAppName `
  --src $ZipPath `
  --build-remote $BuildRemote `
  --output none | Out-Null

if (Test-Path $StageDir) { Remove-Item $StageDir -Recurse -Force }

Write-Host "Zip deployment completed."
Write-Host "MCP Endpoint : $McpEndpoint"
