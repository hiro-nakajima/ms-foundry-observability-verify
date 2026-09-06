param(
  [string]$ResourceGroup,
  [string]$Location,
  [string]$ParametersFile,
  [string]$DeploymentName,
  [string]$DeploymentMode,
  [switch]$WhatIfDeployment
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

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FunctionRoot = Split-Path -Parent $ScriptDir
$TemplateFile = Join-Path $FunctionRoot "infra\azure\main.bicep"

$ResourceGroup = Get-ConfigValue -Value $ResourceGroup -EnvironmentName "RESOURCE_GROUP" -DefaultValue "rg-ms-foundry-mcp"
$Location = Get-ConfigValue -Value $Location -EnvironmentName "LOCATION" -DefaultValue "canadaeast"
$ParametersFile = Get-ConfigValue -Value $ParametersFile -EnvironmentName "PARAMETERS_FILE" -DefaultValue (Join-Path $FunctionRoot "infra\azure\main.parameters.example.json")
$DeploymentName = Get-ConfigValue -Value $DeploymentName -EnvironmentName "DEPLOYMENT_NAME" -DefaultValue ("functions-mcp-selfhosted-azure-" + (Get-Date -Format "yyyyMMddHHmmss"))
$DeploymentMode = Get-ConfigValue -Value $DeploymentMode -EnvironmentName "DEPLOYMENT_MODE" -DefaultValue "Incremental"
$WhatIfValue = Get-ConfigValue -Value $null -EnvironmentName "WHAT_IF" -DefaultValue "false"
$RunWhatIf = $WhatIfDeployment -or ($WhatIfValue -eq "true")

if (-not (Test-Path $ParametersFile)) {
  throw "Parameters file not found: $ParametersFile"
}

Write-Host "Resource group : $ResourceGroup"
Write-Host "Location       : $Location"
Write-Host "Template file  : $TemplateFile"
Write-Host "Parameters     : $ParametersFile"
Write-Host "Deployment     : $DeploymentName"
Write-Host "Mode           : $DeploymentMode"
Write-Host "What-If        : $RunWhatIf"

if ($RunWhatIf) {
  $resourceGroupExists = $true
  try {
    az group show --name $ResourceGroup --output none | Out-Null
  }
  catch {
    $resourceGroupExists = $false
  }

  if (-not $resourceGroupExists) {
    throw "What-if requires an existing resource group: $ResourceGroup. Create it first or run without What-If for the initial deployment."
  }

  az deployment group what-if `
    --resource-group $ResourceGroup `
    --name $DeploymentName `
    --mode $DeploymentMode `
    --template-file $TemplateFile `
    --parameters "@$ParametersFile" `
    --parameters location=$Location

  Write-Host ""
  Write-Host "What-if completed. No resources were changed."
  exit 0
}

az group create `
  --name $ResourceGroup `
  --location $Location `
  --output none | Out-Null

az deployment group create `
  --resource-group $ResourceGroup `
  --name $DeploymentName `
  --mode $DeploymentMode `
  --template-file $TemplateFile `
  --parameters "@$ParametersFile" `
  --parameters location=$Location | Out-Null

$FunctionAppName = az deployment group show `
  --resource-group $ResourceGroup `
  --name $DeploymentName `
  --query "properties.outputs.functionAppName.value" `
  --output tsv

$FunctionAppUrl = az deployment group show `
  --resource-group $ResourceGroup `
  --name $DeploymentName `
  --query "properties.outputs.functionAppUrl.value" `
  --output tsv

$FunctionEndpoint = az deployment group show `
  --resource-group $ResourceGroup `
  --name $DeploymentName `
  --query "properties.outputs.functionEndpoint.value" `
  --output tsv

if (-not [string]::IsNullOrWhiteSpace($FunctionAppName)) {
  az resource update `
    --resource-group $ResourceGroup `
    --name $FunctionAppName `
    --resource-type Microsoft.Web/sites `
    --set properties.httpsOnly=true `
    --output none | Out-Null
}

Write-Host ""
Write-Host "Azure resource deployment completed."
Write-Host "Function App   : $FunctionAppName"
Write-Host "Function URL   : $FunctionAppUrl"
Write-Host "MCP Endpoint   : $FunctionEndpoint"
Write-Host "Next step:"
Write-Host "  1. Deploy Entra app with scripts/deploy-functions-entra-obo.ps1"
Write-Host "  2. Apply Entra settings with scripts/apply-function-entra-settings.ps1"
Write-Host "  3. Set FUNCTION_APP_URL above and deploy code with scripts/deploy-functions-zip.ps1 (remote build)"
