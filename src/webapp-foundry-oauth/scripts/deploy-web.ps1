param(
  [string]$ResourceGroup = $env:RESOURCE_GROUP,
  [string]$WebApp = $env:WEB_APP,
  [string]$WebAppUrl = $env:WEB_APP_URL,
  [string]$ProjectEndpoint = $env:PROJECT_ENDPOINT,
  [Alias("AgentReferenceName")]
  [string]$AgentName = $(if ($env:AGENT_NAME) { $env:AGENT_NAME } else { $env:AGENT_REFERENCE_NAME }),
  [string]$ApimSubscriptionKey = $env:APIM_SUBSCRIPTION_KEY,
  [string]$CorsOrigins = $env:CORS_ORIGINS,
  [string]$PythonRuntime = $(if ($env:PYTHON_RUNTIME) { $env:PYTHON_RUNTIME } else { "PYTHON|3.14" })
)

$ErrorActionPreference = "Stop"

throw "Use scripts/package-procurement.py and the Bicep-managed App Service settings. See README.md. The legacy OAuth deployment is disabled."

function Assert-RequiredValue {
  param(
    [string]$Name,
    [string]$EnvName,
    [string]$Value
  )

  if ([string]::IsNullOrWhiteSpace($Value)) {
    throw "Missing required value: $Name. Pass -$Name or set the $EnvName environment variable."
  }
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

Assert-RequiredValue -Name "ResourceGroup" -EnvName "RESOURCE_GROUP" -Value $ResourceGroup
Assert-RequiredValue -Name "WebApp" -EnvName "WEB_APP" -Value $WebApp
Assert-RequiredValue -Name "WebAppUrl" -EnvName "WEB_APP_URL" -Value $WebAppUrl
Assert-RequiredValue -Name "ProjectEndpoint" -EnvName "PROJECT_ENDPOINT" -Value $ProjectEndpoint
Assert-RequiredValue -Name "AgentName" -EnvName "AGENT_NAME" -Value $AgentName
Assert-RequiredValue -Name "ApimSubscriptionKey" -EnvName "APIM_SUBSCRIPTION_KEY" -Value $ApimSubscriptionKey

$WebAppUrl = ConvertTo-HttpsOrigin -Name "WebAppUrl" -Value $WebAppUrl

if ([string]::IsNullOrWhiteSpace($CorsOrigins)) {
  $CorsOrigins = $WebAppUrl
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = Split-Path -Parent $ScriptDir
$ZipPath = Join-Path $ScriptDir "webapp.zip"
$StageDir = Join-Path $ScriptDir ".deploy-stage"

Write-Host "Resource group : $ResourceGroup"
Write-Host "Web App        : $WebApp"
Write-Host "Web App URL    : $WebAppUrl"
Write-Host "CORS origins   : $CorsOrigins"

Write-Host "Configuring app settings..."
az webapp config appsettings set `
  --resource-group $ResourceGroup `
  --name $WebApp `
  --settings `
    PROJECT_ENDPOINT=$ProjectEndpoint `
    AGENT_NAME=$AgentName `
    APIM_SUBSCRIPTION_KEY=$ApimSubscriptionKey `
    CORS_ORIGINS=$CorsOrigins `
    WEBSITES_PORT="8080" `
    SCM_DO_BUILD_DURING_DEPLOYMENT="true" `
    ENABLE_ORYX_BUILD="true"

Write-Host "App settings configured"

az webapp config set `
  --resource-group $ResourceGroup `
  --name $WebApp `
  --linux-fx-version $PythonRuntime

Write-Host "Python runtime configured"

if (Test-Path $ZipPath) {
  Remove-Item $ZipPath -Force
}

if (Test-Path $StageDir) {
  Remove-Item $StageDir -Recurse -Force
}

New-Item -ItemType Directory -Path $StageDir | Out-Null

Copy-Item (Join-Path $AppRoot "startup.sh") -Destination $StageDir
Copy-Item (Join-Path $AppRoot "backend\requirements.txt") -Destination (Join-Path $StageDir "requirements.txt")
Copy-Item (Join-Path $AppRoot "backend") -Destination $StageDir -Recurse

$ItemsToRemove = @(
  (Join-Path $StageDir "backend\.venv"),
  (Join-Path $StageDir "backend\__pycache__"),
  (Join-Path $StageDir "backend\.env")
)

foreach ($Item in $ItemsToRemove) {
  if (Test-Path $Item) {
    Remove-Item $Item -Recurse -Force
  }
}

Get-ChildItem -Path (Join-Path $StageDir "backend") -Filter ".env.*" -Force -ErrorAction SilentlyContinue |
  Remove-Item -Force

Write-Host "Creating deployment zip..."
Compress-Archive -Path (Join-Path $StageDir "*") -DestinationPath $ZipPath -Force
Write-Host "Zip created"

Write-Host "Deploying zip package..."
az webapp deployment source config-zip `
  --resource-group $ResourceGroup `
  --name $WebApp `
  --src $ZipPath

Write-Host "Code deployed"

Write-Host "Configuring startup command..."
az webapp config set `
  --resource-group $ResourceGroup `
  --name $WebApp `
  --startup-file "bash startup.sh"

Write-Host "Startup command configured"

if (Test-Path $StageDir) {
  Remove-Item $StageDir -Recurse -Force
}

Write-Host "Deployment completed"
