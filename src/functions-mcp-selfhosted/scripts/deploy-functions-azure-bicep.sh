#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNCTION_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE_FILE="${FUNCTION_ROOT}/infra/azure/main.bicep"
PARAMETERS_FILE="${PARAMETERS_FILE:-${FUNCTION_ROOT}/infra/azure/main.parameters.example.json}"

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Required command not found: ${cmd}" >&2
    exit 1
  fi
}

require_command az

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-ms-foundry-mcp}"
LOCATION="${LOCATION:-canadaeast}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-functions-mcp-selfhosted-azure-$(date +%Y%m%d%H%M%S)}"
DEPLOYMENT_MODE="${DEPLOYMENT_MODE:-Incremental}"
WHAT_IF="${WHAT_IF:-false}"

if [[ ! -f "${PARAMETERS_FILE}" ]]; then
  echo "Parameters file not found: ${PARAMETERS_FILE}" >&2
  exit 1
fi

echo "Resource group : ${RESOURCE_GROUP}"
echo "Location       : ${LOCATION}"
echo "Template file  : ${TEMPLATE_FILE}"
echo "Parameters     : ${PARAMETERS_FILE}"
echo "Deployment     : ${DEPLOYMENT_NAME}"
echo "Mode           : ${DEPLOYMENT_MODE}"
echo "What-If        : ${WHAT_IF}"

if [[ "${WHAT_IF}" == "true" ]]; then
  if ! az group show --name "${RESOURCE_GROUP}" --output none >/dev/null 2>&1; then
    echo "What-if requires an existing resource group: ${RESOURCE_GROUP}" >&2
    echo "Create it first or run without WHAT_IF=true for the initial deployment." >&2
    exit 1
  fi

  az deployment group what-if \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${DEPLOYMENT_NAME}" \
    --mode "${DEPLOYMENT_MODE}" \
    --template-file "${TEMPLATE_FILE}" \
    --parameters "@${PARAMETERS_FILE}" \
    --parameters location="${LOCATION}"

  echo
  echo "What-if completed. No resources were changed."
  exit 0
fi

az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none

az deployment group create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${DEPLOYMENT_NAME}" \
  --mode "${DEPLOYMENT_MODE}" \
  --template-file "${TEMPLATE_FILE}" \
  --parameters "@${PARAMETERS_FILE}" \
  --parameters location="${LOCATION}"

FUNCTION_APP_NAME="$(az deployment group show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${DEPLOYMENT_NAME}" \
  --query "properties.outputs.functionAppName.value" \
  --output tsv)"

FUNCTION_APP_URL="$(az deployment group show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${DEPLOYMENT_NAME}" \
  --query "properties.outputs.functionAppUrl.value" \
  --output tsv)"

FUNCTION_ENDPOINT="$(az deployment group show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${DEPLOYMENT_NAME}" \
  --query "properties.outputs.functionEndpoint.value" \
  --output tsv)"

if [[ -n "${FUNCTION_APP_NAME}" ]]; then
  az resource update \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${FUNCTION_APP_NAME}" \
    --resource-type Microsoft.Web/sites \
    --set properties.httpsOnly=true \
    --output none
fi

echo
echo "Azure resource deployment completed."
echo "Function App   : ${FUNCTION_APP_NAME}"
echo "Function URL   : ${FUNCTION_APP_URL}"
echo "MCP Endpoint   : ${FUNCTION_ENDPOINT}"
echo "Next step:"
echo "  1. Deploy Entra app with scripts/deploy-functions-entra-obo.sh"
echo "  2. Apply Entra settings with scripts/apply-function-entra-settings.sh"
echo "  3. Set FUNCTION_APP_URL above and deploy code with scripts/deploy-functions-zip.sh (remote build)"
