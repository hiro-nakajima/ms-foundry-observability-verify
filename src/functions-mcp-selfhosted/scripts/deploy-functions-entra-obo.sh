#!/usr/bin/env bash
set -euo pipefail

# Creates or updates App B: the MCP Server API / Functions OBO app registration.
# Foundry OAuth client app registration is managed by deploy-foundry-oauth-client-app.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNCTION_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${CONFIG_FILE:-${FUNCTION_ROOT}/infra/entra/obo-app-config.example.json}"

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Required command not found: ${cmd}" >&2
    exit 1
  fi
}

require_command az
require_command jq
require_command uuidgen

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Config file not found: ${CONFIG_FILE}" >&2
  exit 1
fi

read_json() {
  local expr="$1"
  jq -r "${expr}" "${CONFIG_FILE}"
}

DISPLAY_NAME="$(read_json '.displayName')"
SIGN_IN_AUDIENCE="$(read_json '.signInAudience // "AzureADMyOrg"')"
IDENTIFIER_URI="$(read_json '.identifierUri // ""')"
SCOPE_NAME="$(read_json '.scope.name')"
ADMIN_CONSENT_DISPLAY_NAME="$(read_json '.scope.adminConsentDisplayName')"
ADMIN_CONSENT_DESCRIPTION="$(read_json '.scope.adminConsentDescription')"
USER_CONSENT_DISPLAY_NAME="$(read_json '.scope.userConsentDisplayName')"
USER_CONSENT_DESCRIPTION="$(read_json '.scope.userConsentDescription')"
CREATE_CLIENT_SECRET="$(read_json '.clientSecret.create // true')"
CLIENT_SECRET_DISPLAY_NAME="$(read_json '.clientSecret.displayName // "codex-obo-secret"')"
CLIENT_SECRET_YEARS_VALID="$(read_json '.clientSecret.yearsValid // 1')"
GRANT_ADMIN_CONSENT="$(read_json '.grantAdminConsent // false')"
OUTPUT_FILE_RAW="$(read_json '.outputFile // "infra/entra/obo-app.outputs.json"')"
OUTPUT_FILE="${OUTPUT_FILE_RAW}"

if [[ "${OUTPUT_FILE}" != /* ]]; then
  OUTPUT_FILE="${FUNCTION_ROOT}/${OUTPUT_FILE}"
fi

mkdir -p "$(dirname "${OUTPUT_FILE}")"

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

if [[ -z "${IDENTIFIER_URI}" || "${IDENTIFIER_URI}" == "null" ]]; then
  IDENTIFIER_URI="api://${APP_ID}"
fi

CURRENT_APP_JSON="$(az rest --method GET --uri "https://graph.microsoft.com/v1.0/applications/${OBJECT_ID}" -o json)"
EXISTING_SCOPE_ID="$(echo "${CURRENT_APP_JSON}" | jq -r --arg scopeName "${SCOPE_NAME}" '.api.oauth2PermissionScopes[]? | select(.value == $scopeName) | .id' | head -n1)"

if [[ -z "${EXISTING_SCOPE_ID}" ]]; then
  SCOPE_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
else
  SCOPE_ID="${EXISTING_SCOPE_ID}"
fi

REDIRECT_URIS_JSON="$(jq -c '.redirectUris // []' "${CONFIG_FILE}")"
PATCH_BODY="$(
  jq -cn \
    --arg identifierUri "${IDENTIFIER_URI}" \
    --arg scopeId "${SCOPE_ID}" \
    --arg scopeName "${SCOPE_NAME}" \
    --arg adminDisplay "${ADMIN_CONSENT_DISPLAY_NAME}" \
    --arg adminDescription "${ADMIN_CONSENT_DESCRIPTION}" \
    --arg userDisplay "${USER_CONSENT_DISPLAY_NAME}" \
    --arg userDescription "${USER_CONSENT_DESCRIPTION}" \
    --argjson redirectUris "${REDIRECT_URIS_JSON}" \
    '{
      identifierUris: [$identifierUri],
      api: {
        requestedAccessTokenVersion: 2,
        oauth2PermissionScopes: [
          {
            id: $scopeId,
            value: $scopeName,
            type: "User",
            isEnabled: true,
            adminConsentDisplayName: $adminDisplay,
            adminConsentDescription: $adminDescription,
            userConsentDisplayName: $userDisplay,
            userConsentDescription: $userDescription
          }
        ]
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
  --body "${PATCH_BODY}" \
  --output none

GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"
mapfile -t GRAPH_PERMISSIONS < <(jq -r '.graphDelegatedPermissions[]? // empty' "${CONFIG_FILE}")

for permission in "${GRAPH_PERMISSIONS[@]}"; do
  permission_id="$(
    az ad sp show \
      --id "${GRAPH_APP_ID}" \
      --query "oauth2PermissionScopes[?value=='${permission}'].id | [0]" \
      -o tsv
  )"

  if [[ -z "${permission_id}" ]]; then
    echo "Could not resolve Graph delegated permission: ${permission}" >&2
    exit 1
  fi

  az ad app permission add \
    --id "${APP_ID}" \
    --api "${GRAPH_APP_ID}" \
    --api-permissions "${permission_id}=Scope" \
    --output none || true
done

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
SCOPE_VALUE="${IDENTIFIER_URI}/${SCOPE_NAME}"

jq -n \
  --arg tenantId "${TENANT_ID}" \
  --arg appId "${APP_ID}" \
  --arg objectId "${OBJECT_ID}" \
  --arg identifierUri "${IDENTIFIER_URI}" \
  --arg scopeValue "${SCOPE_VALUE}" \
  --arg clientSecret "${CLIENT_SECRET_VALUE}" \
  '{
    tenantId: $tenantId,
    appId: $appId,
    objectId: $objectId,
    identifierUri: $identifierUri,
    scope: $scopeValue,
    clientSecret: $clientSecret
  }' > "${OUTPUT_FILE}"

echo "Entra MCP Server API / Functions OBO app deployment completed."
echo "App ID     : ${APP_ID}"
echo "Identifier : ${IDENTIFIER_URI}"
echo "Scope      : ${SCOPE_VALUE}"
echo "Output file: ${OUTPUT_FILE}"
