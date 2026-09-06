#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNCTION_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLIENT_OUTPUT_FILE="${CLIENT_OUTPUT_FILE:-${FUNCTION_ROOT}/infra/entra/foundry-oauth-client-app.outputs.json}"
API_VERSION="${API_VERSION:-2025-04-01-preview}"

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
require_env SUBSCRIPTION_ID
require_env RESOURCE_GROUP
require_env FOUNDRY_ACCOUNT_NAME
require_env FOUNDRY_PROJECT_NAME
require_env CONNECTION_NAME

if [[ ! -f "${CLIENT_OUTPUT_FILE}" ]]; then
  echo "Client app output file not found: ${CLIENT_OUTPUT_FILE}" >&2
  exit 1
fi

TENANT_ID="$(jq -r '.tenantId' "${CLIENT_OUTPUT_FILE}")"
CLIENT_ID="$(jq -r '.appId' "${CLIENT_OUTPUT_FILE}")"
CLIENT_SECRET="${CLIENT_SECRET:-$(jq -r '.clientSecret // ""' "${CLIENT_OUTPUT_FILE}")}"
CLIENT_SECRET="$(printf '%s' "${CLIENT_SECRET}" | sed 's/[[:space:]]*$//')"
SCOPE="$(jq -r '.scope' "${CLIENT_OUTPUT_FILE}")"

if [[ -z "${CLIENT_SECRET}" || "${CLIENT_SECRET}" == "null" ]]; then
  echo "Client secret is missing. Set CLIENT_SECRET or use an output file that contains clientSecret." >&2
  exit 1
fi

AUTH_URL="https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/authorize"
TOKEN_URL="https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token"
CONNECTION_URL="https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${FOUNDRY_ACCOUNT_NAME}/projects/${FOUNDRY_PROJECT_NAME}/connections/${CONNECTION_NAME}?api-version=${API_VERSION}"

CURRENT_CONNECTION="$(az rest --method GET --url "${CONNECTION_URL}" -o json)"
TARGET="$(echo "${CURRENT_CONNECTION}" | jq -r '.properties.target')"
REDIRECT_URL="$(echo "${CURRENT_CONNECTION}" | jq -r '.properties.redirectUrl // empty')"
CONNECTOR_NAME="$(echo "${CURRENT_CONNECTION}" | jq -r '.properties.connectorName // empty')"

if [[ -z "${TARGET}" || "${TARGET}" == "null" ]]; then
  echo "Current Foundry connection target is missing for ${CONNECTION_NAME}" >&2
  exit 1
fi

REQUEST_BODY="$(
  echo "${CURRENT_CONNECTION}" | jq \
    --arg tenantId "${TENANT_ID}" \
    --arg clientId "${CLIENT_ID}" \
    --arg clientSecret "${CLIENT_SECRET}" \
    --arg authUrl "${AUTH_URL}" \
    --arg tokenUrl "${TOKEN_URL}" \
    --arg scope "${SCOPE}" \
    --arg target "${TARGET}" \
    --arg redirectUrl "${REDIRECT_URL}" \
    --arg connectorName "${CONNECTOR_NAME}" \
    '{
      properties: (
        .properties
        | .authType = "OAuth2"
        | .category = (.category // "RemoteTool")
        | .target = $target
        | .credentials = {
            tenantId: $tenantId,
            clientId: $clientId,
            clientSecret: $clientSecret,
            authUrl: $authUrl
          }
        | .authorizationUrl = $authUrl
        | .tokenUrl = $tokenUrl
        | .refreshUrl = $tokenUrl
        | .scopes = [$scope]
        | .metadata = (.metadata // {type: "custom_MCP"})
        | .isSharedToAll = (.isSharedToAll // false)
        | .useWorkspaceManagedIdentity = (.useWorkspaceManagedIdentity // false)
        | .peRequirement = (.peRequirement // "NotRequired")
        | .peStatus = (.peStatus // "NotApplicable")
        | .group = (.group // "GenericProtocol")
        | .useCustomConnector = (.useCustomConnector // false)
        | if $redirectUrl != "" then .redirectUrl = $redirectUrl else . end
        | if $connectorName != "" then .connectorName = $connectorName else . end
        | del(.error)
      )
    }'
)"

az rest \
  --method PUT \
  --url "${CONNECTION_URL}" \
  --headers Content-Type=application/json \
  --body "${REQUEST_BODY}" \
  --output none

cat <<MSG
Foundry MCP OAuth connection updated.
Connection : ${CONNECTION_NAME}
Target     : ${TARGET}
Client ID  : ${CLIENT_ID}
Scope      : ${SCOPE}
Redirect   : ${REDIRECT_URL}
MSG
