#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNCTION_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENTRA_OUTPUT_FILE="${ENTRA_OUTPUT_FILE:-${FUNCTION_ROOT}/infra/entra/obo-app.outputs.json}"

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Required command not found: ${cmd}" >&2
    exit 1
  fi
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Required environment variable is not set: ${name}" >&2
    exit 1
  fi
}

require_command az
require_command jq
require_env RESOURCE_GROUP
require_env FUNCTION_APP_NAME

if [[ ! -f "${ENTRA_OUTPUT_FILE}" ]]; then
  echo "Entra output file not found: ${ENTRA_OUTPUT_FILE}" >&2
  exit 1
fi

ENTRA_TENANT_ID="$(jq -r '.tenantId' "${ENTRA_OUTPUT_FILE}")"
ENTRA_CLIENT_ID="$(jq -r '.appId' "${ENTRA_OUTPUT_FILE}")"
ENTRA_CLIENT_SECRET="$(jq -r '.clientSecret' "${ENTRA_OUTPUT_FILE}")"
ENTRA_APPLICATION_ID_URI="$(jq -r '.identifierUri' "${ENTRA_OUTPUT_FILE}")"

EXPECTED_TOKEN_AUDIENCES="${EXPECTED_TOKEN_AUDIENCES:-${ENTRA_APPLICATION_ID_URI},${ENTRA_CLIENT_ID}}"
EXPECTED_TENANT_ID="${EXPECTED_TENANT_ID:-${ENTRA_TENANT_ID}}"
GRAPH_SCOPES="${GRAPH_SCOPES:-https://graph.microsoft.com/User.Read}"
GRAPH_BASE_URL="${GRAPH_BASE_URL:-https://graph.microsoft.com/v1.0}"
OBO_MAX_RETRIES="${OBO_MAX_RETRIES:-2}"
OBO_RETRY_BACKOFF_SECONDS="${OBO_RETRY_BACKOFF_SECONDS:-0.5}"
GRAPH_TIMEOUT_SECONDS="${GRAPH_TIMEOUT_SECONDS:-15}"
GRAPH_MAX_RETRIES="${GRAPH_MAX_RETRIES:-2}"
GRAPH_RETRY_BACKOFF_SECONDS="${GRAPH_RETRY_BACKOFF_SECONDS:-0.5}"

az functionapp config appsettings set \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${FUNCTION_APP_NAME}" \
  --settings \
    ENTRA_TENANT_ID="${ENTRA_TENANT_ID}" \
    ENTRA_CLIENT_ID="${ENTRA_CLIENT_ID}" \
    ENTRA_CLIENT_SECRET="${ENTRA_CLIENT_SECRET}" \
    EXPECTED_TOKEN_AUDIENCES="${EXPECTED_TOKEN_AUDIENCES}" \
    EXPECTED_TENANT_ID="${EXPECTED_TENANT_ID}" \
    GRAPH_SCOPES="${GRAPH_SCOPES}" \
    GRAPH_BASE_URL="${GRAPH_BASE_URL}" \
    OBO_MAX_RETRIES="${OBO_MAX_RETRIES}" \
    OBO_RETRY_BACKOFF_SECONDS="${OBO_RETRY_BACKOFF_SECONDS}" \
    GRAPH_TIMEOUT_SECONDS="${GRAPH_TIMEOUT_SECONDS}" \
    GRAPH_MAX_RETRIES="${GRAPH_MAX_RETRIES}" \
    GRAPH_RETRY_BACKOFF_SECONDS="${GRAPH_RETRY_BACKOFF_SECONDS}" \
  --output none

echo "Applied Entra OBO settings to Function App."
echo "Function App : ${FUNCTION_APP_NAME}"
echo "ResourceGroup: ${RESOURCE_GROUP}"
