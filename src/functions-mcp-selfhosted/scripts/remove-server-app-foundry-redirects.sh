#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNCTION_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVER_OUTPUT_FILE="${SERVER_OUTPUT_FILE:-${FUNCTION_ROOT}/infra/entra/obo-app.outputs.json}"
MATCH_PREFIX="${MATCH_PREFIX:-https://global.consent.azure-apim.net/redirect/}"
DRY_RUN="${DRY_RUN:-true}"

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Required command not found: ${cmd}" >&2
    exit 1
  fi
}

require_command az
require_command jq

SERVER_APP_ID="${SERVER_APP_ID:-}"
if [[ -z "${SERVER_APP_ID}" ]]; then
  if [[ ! -f "${SERVER_OUTPUT_FILE}" ]]; then
    echo "SERVER_APP_ID is not set and server output file was not found: ${SERVER_OUTPUT_FILE}" >&2
    exit 1
  fi
  SERVER_APP_ID="$(jq -r '.appId' "${SERVER_OUTPUT_FILE}")"
fi

SERVER_APP_JSON="$(az ad app show --id "${SERVER_APP_ID}" -o json)"
SERVER_OBJECT_ID="$(echo "${SERVER_APP_JSON}" | jq -r '.id')"
CURRENT_APP_JSON="$(az rest --method GET --uri "https://graph.microsoft.com/v1.0/applications/${SERVER_OBJECT_ID}" -o json)"
CURRENT_REDIRECTS="$(echo "${CURRENT_APP_JSON}" | jq -c '.web.redirectUris // []')"
UPDATED_REDIRECTS="$(echo "${CURRENT_REDIRECTS}" | jq -c --arg prefix "${MATCH_PREFIX}" 'map(select(startswith($prefix) | not))')"
REMOVED_REDIRECTS="$(jq -n --argjson before "${CURRENT_REDIRECTS}" --argjson after "${UPDATED_REDIRECTS}" '$before - $after')"

if [[ "${CURRENT_REDIRECTS}" == "${UPDATED_REDIRECTS}" ]]; then
  echo "No matching Foundry redirect URIs were found on server app ${SERVER_APP_ID}."
  exit 0
fi

cat <<MSG
Server App ID : ${SERVER_APP_ID}
Remove URIs   : $(echo "${REMOVED_REDIRECTS}" | jq -r 'join(", ")')
Dry run       : ${DRY_RUN}
MSG

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "Dry run only. Set DRY_RUN=false to apply."
  exit 0
fi

PATCH_BODY="$(jq -n --argjson redirectUris "${UPDATED_REDIRECTS}" '{web: {redirectUris: $redirectUris}}')"
az rest \
  --method PATCH \
  --uri "https://graph.microsoft.com/v1.0/applications/${SERVER_OBJECT_ID}" \
  --headers Content-Type=application/json \
  --body "${PATCH_BODY}" \
  --output none

echo "Removed matching Foundry redirect URIs from server app ${SERVER_APP_ID}."
