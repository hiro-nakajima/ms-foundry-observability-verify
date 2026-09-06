param(
  [string]$McpEndpoint
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($McpEndpoint)) {
  $McpEndpoint = [Environment]::GetEnvironmentVariable("MCP_ENDPOINT")
}

if ([string]::IsNullOrWhiteSpace($McpEndpoint)) {
  throw "Usage: .\warmup-mcp-endpoint.ps1 -McpEndpoint https://<function-app-default-hostname>/mcp"
}

$body = @{
  jsonrpc = "2.0"
  id      = "warmup"
  method  = "tools/list"
  params  = @{}
} | ConvertTo-Json -Depth 3

Invoke-RestMethod `
  -Uri $McpEndpoint `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{ Accept = "application/json, text/event-stream" } `
  -Body $body | Out-Null

Write-Host "Warm-up completed: $McpEndpoint"
