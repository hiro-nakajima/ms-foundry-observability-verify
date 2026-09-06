#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNCTION_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ZIP_PATH="${SCRIPT_DIR}/functions-mcp-selfhosted.zip"
STAGE_DIR="${SCRIPT_DIR}/.deploy-stage-functions"

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
require_command zip
require_env RESOURCE_GROUP
require_env FUNCTION_APP_NAME
require_env FUNCTION_APP_URL

FUNCTION_APP_URL="${FUNCTION_APP_URL%/}"
if [[ ! "${FUNCTION_APP_URL}" =~ ^https://[^/?#]+$ ]]; then
  echo "FUNCTION_APP_URL must be an HTTPS origin without a path, query, or fragment: ${FUNCTION_APP_URL}" >&2
  exit 1
fi
MCP_ENDPOINT="${FUNCTION_APP_URL}/mcp"

echo "Resource group : ${RESOURCE_GROUP}"
echo "Function App   : ${FUNCTION_APP_NAME}"
echo "Function URL   : ${FUNCTION_APP_URL}"
echo "MCP Endpoint   : ${MCP_ENDPOINT}"
echo "Zip path       : ${ZIP_PATH}"

BUILD_REMOTE="${BUILD_REMOTE:-true}"
if [[ "${BUILD_REMOTE}" != "true" && "${BUILD_REMOTE}" != "false" ]]; then
  echo "BUILD_REMOTE must be true or false." >&2
  exit 1
fi

rm -f "${ZIP_PATH}"
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"

cp "${FUNCTION_ROOT}/mcp_server.py" "${STAGE_DIR}/"
cp "${FUNCTION_ROOT}/host.json" "${STAGE_DIR}/"
cp "${FUNCTION_ROOT}/requirements.txt" "${STAGE_DIR}/"
cp -R "${FUNCTION_ROOT}/mcp_handler" "${STAGE_DIR}/"

if [[ -n "${VENDORED_PACKAGES_DIR:-}" ]]; then
  BUILD_REMOTE="false"
  echo "Vendored packages: ${VENDORED_PACKAGES_DIR}"
  mkdir -p "${STAGE_DIR}/.python_packages/lib/site-packages"
  cp -R "${VENDORED_PACKAGES_DIR}/." "${STAGE_DIR}/.python_packages/lib/site-packages/"
fi

echo "Remote build   : ${BUILD_REMOTE}"

find "${STAGE_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${STAGE_DIR}" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete

pushd "${STAGE_DIR}" >/dev/null
zip -rq "${ZIP_PATH}" . -x "*.zip"
popd >/dev/null

az functionapp deployment source config-zip \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${FUNCTION_APP_NAME}" \
  --src "${ZIP_PATH}" \
  --build-remote "${BUILD_REMOTE}" \
  --output none

rm -rf "${STAGE_DIR}"

echo "Zip deployment completed."
echo "MCP Endpoint : ${MCP_ENDPOINT}"
