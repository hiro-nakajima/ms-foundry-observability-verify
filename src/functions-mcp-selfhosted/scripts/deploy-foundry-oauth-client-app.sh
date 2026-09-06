#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNCTION_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${CONFIG_FILE:-${FUNCTION_ROOT}/infra/entra/foundry-oauth-client-app-config.example.json}"

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Required command not found: ${cmd}" >&2
    exit 1
  fi
}

resolve_path() {
  local path="$1"
  if [[ "${path}" == /* ]]; then
    echo "${path}"
  else
    echo "${FUNCTION_ROOT}/${path}"
  fi
}

read_json() {
  local expr="$1"
  jq -r "${expr}" "${CONFIG_FILE}"
}

require_command az
require_command jq

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Config file not found: ${CONFIG_FILE}" >&2
  exit 1
fi

DISPLAY_NAME="$(read_json '.displayName')"
SIGN_IN_AUDIENCE="$(read_json '.signInAudience // "AzureADMyOrg"')"
SERVER_OUTPUT_FILE_RAW="$(read_json '.serverOutputFile // "infra/entra/obo-app.outputs.json"')"
SERVER_OUTPUT_FILE="$(resolve_path "${SERVER_OUTPUT_FILE_RAW}")"
SERVER_APP_ID="${SERVER_APP_ID:-$(read_json '.serverAppId // ""')}"
SERVER_SCOPE_NAME="${SERVER_SCOPE_NAME:-$(read_json '.serverScopeName // "access_as_user"')}"
PRE_AUTHORIZE_CLIENT="$(read_json '.preAuthorizeClient // true')"
CREATE_CLIENT_SECRET="$(read_json '.clientSecret.create // true')"
CLIENT_SECRET_DISPLAY_NAME="$(read_json '.clientSecret.displayName // "codex-foundry-oauth-client-secret"')"
CLIENT_SECRET_YEARS_VALID="$(read_json '.clientSecret.yearsValid // 1')"
GRANT_ADMIN_CONSENT="$(read_json '.grantAdminConsent // false')"
OUTPUT_FILE_RAW="$(read_json '.outputFile // "infra/entra/foundry-oauth-client-app.outputs.json"')"
OUTPUT_FILE="$(resolve_path "${OUTPUT_FILE_RAW}")"
REDIRECT_URIS_JSON="$(jq -c '.redirectUris // []' "${CONFIG_FILE}")"

if [[ -n "${REDIRECT_URIS:-}" ]]; then
  REDIRECT_URIS_JSON="$(jq -cn --arg raw "${REDIRECT_URIS}" '$raw | split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0))')"
fi

if [[ -z "${SERVER_APP_ID}" || "${SERVER_APP_ID}" == "null" ]]; then
  if [[ ! -f "${SERVER_OUTPUT_FILE}" ]]; then
    echo "Server app ID is not set and server output file was not found: ${SERVER_OUTPUT_FILE}" >&2
    exit 1
  fi
  SERVER_APP_ID="$(jq -r '.appId' "${SERVER_OUTPUT_FILE}")"
fi

if [[ -z "${DISPLAY_NAME}" || "${DISPLAY_NAME}" == "null" ]]; then
  echo "displayName is required in ${CONFIG_FILE}" >&2
  exit 1
fi

if [[ -z "${SERVER_APP_ID}" || "${SERVER_APP_ID}" == "null" ]]; then
  echo "serverAppId is required. Set .serverAppId, SERVER_APP_ID, or serverOutputFile." >&2
  exit 1
fi

mkdir -p "$(dirname "${OUTPUT_FILE}")"

SERVER_APP_JSON="$(az ad app show --id "${SERVER_APP_ID}" -o json)"
SERVER_OBJECT_ID="$(echo "${SERVER_APP_JSON}" | jq -r '.id')"
SERVER_IDENTIFIER_URI="$(echo "${SERVER_APP_JSON}" | jq -r --arg serverAppId "${SERVER_APP_ID}" '.identifierUris[0] // ("api://" + $serverAppId)')"
SERVER_SCOPE_ID="$(echo "${SERVER_APP_JSON}" | jq -r --arg scopeName "${SERVER_SCOPE_NAME}" '.api.oauth2PermissionScopes[]? | select(.value == $scopeName) | .id' | head -n1)"

if [[ -z "${SERVER_SCOPE_ID}" || "${SERVER_SCOPE_ID}" == "null" ]]; then
  echo "Could not resolve server delegated scope '${SERVER_SCOPE_NAME}' from app ${SERVER_APP_ID}" >&2
  exit 1
fi

APP_JSON="$(az ad app list --display-name "${DISPLAY_NAME}" --query "[0]" -o json)"
APP_ID="$(echo "${APP_JSON}" | jq -r '.appId // empty')"
OBJECT_ID="$(echo "${APP_JSON}" | jq -r '.id // empty')"

if [[ -z "${APP_ID}" || "${APP_ID}" == "null" ]]; then
  APP_JSON="$(az ad app create \
    --display-name "${DISPLAY_NAME}" \
    --sign-in-audience "${SIGN_IN_AUDIENCE}" \
    -o json)"
  APP_ID="$(echo "${APP_JSON}" | jq -r '.appId')"
  OBJECT_ID="$(echo "${APP_JSON}" | jq -r '.id')"
fi

CLIENT_PATCH_BODY="$(
  jq -cn \
    --argjson redirectUris "${REDIRECT_URIS_JSON}" \
    '{
      identifierUris: [],
      api: {
        requestedAccessTokenVersion: 2,
        oauth2PermissionScopes: []
      },
      web: {
        redirectUris: $redirectUris
      }
    }'
)"

az rest \
  --method PATCH \
  --uri "https://graph.microsoft.com/v1.0/applications/${OBJECT_ID}" \
  --headers Content-Type=application/json \
  --body "${CLIENT_PATCH_BODY}" \
  --output none

az ad app permission add \
  --id "${APP_ID}" \
  --api "${SERVER_APP_ID}" \
  --api-permissions "${SERVER_SCOPE_ID}=Scope" \
  --output none || true

if [[ "${PRE_AUTHORIZE_CLIENT}" == "true" ]]; then
  CURRENT_SERVER_APP_JSON="$(az rest --method GET --uri "https://graph.microsoft.com/v1.0/applications/${SERVER_OBJECT_ID}" -o json)"
  SERVER_PATCH_BODY="$(
    echo "${CURRENT_SERVER_APP_JSON}" | jq \
      --arg clientAppId "${APP_ID}" \
      --arg scopeId "${SERVER_SCOPE_ID}" \
      '{
        api: {
          requestedAccessTokenVersion: (.api.requestedAccessTokenVersion // 2),
          oauth2PermissionScopes: (.api.oauth2PermissionScopes // []),
          preAuthorizedApplications: (((.api.preAuthorizedApplications // []) | map(select(.appId != $clientAppId))) + [{appId: $clientAppId, delegatedPermissionIds: [$scopeId]}])
        }
      }'
  )"
  az rest \
    --method PATCH \
    --uri "https://graph.microsoft.com/v1.0/applications/${SERVER_OBJECT_ID}" \
    --headers Content-Type=application/json \
    --body "${SERVER_PATCH_BODY}" \
    --output none
fi

if [[ "${GRANT_ADMIN_CONSENT}" == "true" ]]; then
  az ad app permission admin-consent --id "${APP_ID}" --output none
fi

CLIENT_SECRET_VALUE=""
if [[ "${CREATE_CLIENT_SECRET}" == "true" ]]; then
  CLIENT_SECRET_VALUE="$(
    az ad app credential reset \
      --id "${APP_ID}" \
      --append \
      --display-name "${CLIENT_SECRET_DISPLAY_NAME}" \
      --years "${CLIENT_SECRET_YEARS_VALID}" \
      --query password \
      -o tsv
  )"
fi

TENANT_ID="$(az account show --query tenantId -o tsv)"
SCOPE_VALUE="${SERVER_IDENTIFIER_URI}/${SERVER_SCOPE_NAME}"

jq -n \
  --arg tenantId "${TENANT_ID}" \
  --arg appId "${APP_ID}" \
  --arg objectId "${OBJECT_ID}" \
  --arg displayName "${DISPLAY_NAME}" \
  --arg serverAppId "${SERVER_APP_ID}" \
  --arg serverObjectId "${SERVER_OBJECT_ID}" \
  --arg serverIdentifierUri "${SERVER_IDENTIFIER_URI}" \
  --arg serverScopeName "${SERVER_SCOPE_NAME}" \
  --arg serverScopeId "${SERVER_SCOPE_ID}" \
  --arg scope "${SCOPE_VALUE}" \
  --arg clientSecret "${CLIENT_SECRET_VALUE}" \
  --argjson redirectUris "${REDIRECT_URIS_JSON}" \
  '{
    tenantId: $tenantId,
    appId: $appId,
    objectId: $objectId,
    displayName: $displayName,
    serverAppId: $serverAppId,
    serverObjectId: $serverObjectId,
    serverIdentifierUri: $serverIdentifierUri,
    serverScopeName: $serverScopeName,
    serverScopeId: $serverScopeId,
    scope: $scope,
    redirectUris: $redirectUris,
    clientSecret: $clientSecret
  }' > "${OUTPUT_FILE}"

cat <<MSG
Foundry OAuth client app deployment completed.
Client App ID : ${APP_ID}
Server App ID : ${SERVER_APP_ID}
Scope         : ${SCOPE_VALUE}
Redirect URIs : $(echo "${REDIRECT_URIS_JSON}" | jq -r 'join(", ")')
Output file   : ${OUTPUT_FILE}
MSG
