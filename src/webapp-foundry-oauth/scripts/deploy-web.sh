#!/bin/bash
set -e

# The original workflow below is retained as reference, but cannot safely deploy
# the procurement app (it packages the OAuth backend and overwrites webapp.zip).
echo "Use scripts/package-procurement.py and the Bicep-managed App Service settings. See README.md." >&2
exit 2

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STAGE_DIR="${SCRIPT_DIR}/.deploy-stage"
ZIP_PATH="${SCRIPT_DIR}/webapp.zip"

RESOURCE_GROUP="${RESOURCE_GROUP:-}"
WEB_APP="${WEB_APP:-}"
WEB_APP_URL="${WEB_APP_URL:-}"
PROJECT_ENDPOINT="${PROJECT_ENDPOINT:-}"
AGENT_NAME="${AGENT_NAME:-${AGENT_REFERENCE_NAME:-}}"
APIM_SUBSCRIPTION_KEY="${APIM_SUBSCRIPTION_KEY:-}"
CORS_ORIGINS="${CORS_ORIGINS:-}"
PYTHON_RUNTIME="${PYTHON_RUNTIME:-PYTHON|3.14}"

require_env() {
  local name="$1"
  local value="$2"

  if [[ -z "$value" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    exit 1
  fi
}

require_env "RESOURCE_GROUP" "$RESOURCE_GROUP"
require_env "WEB_APP" "$WEB_APP"
require_env "WEB_APP_URL" "$WEB_APP_URL"
require_env "PROJECT_ENDPOINT" "$PROJECT_ENDPOINT"
require_env "AGENT_NAME" "$AGENT_NAME"
require_env "APIM_SUBSCRIPTION_KEY" "$APIM_SUBSCRIPTION_KEY"

WEB_APP_URL="${WEB_APP_URL%/}"
if [[ ! "$WEB_APP_URL" =~ ^https://[^/?#]+$ ]]; then
  echo "WEB_APP_URL must be an HTTPS origin without a path, query, or fragment: ${WEB_APP_URL}" >&2
  exit 1
fi

if [[ -z "$CORS_ORIGINS" ]]; then
  CORS_ORIGINS="$WEB_APP_URL"
fi

echo "Resource group : ${RESOURCE_GROUP}"
echo "Web App       : ${WEB_APP}"
echo "Web App URL   : ${WEB_APP_URL}"
echo "CORS origins  : ${CORS_ORIGINS}"

# Configure app settings for zip deployment with App Service remote build.
az webapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$WEB_APP" \
  --settings \
    PROJECT_ENDPOINT="$PROJECT_ENDPOINT" \
    AGENT_NAME="$AGENT_NAME" \
    APIM_SUBSCRIPTION_KEY="$APIM_SUBSCRIPTION_KEY" \
    CORS_ORIGINS="$CORS_ORIGINS" \
    WEBSITES_PORT="8080" \
    SCM_DO_BUILD_DURING_DEPLOYMENT="true" \
    ENABLE_ORYX_BUILD="true"

echo "App settings configured"

az webapp config set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$WEB_APP" \
  --linux-fx-version "$PYTHON_RUNTIME"

echo "Python runtime configured"

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
cp "${APP_ROOT}/startup.sh" "$STAGE_DIR/"
cp "${APP_ROOT}/backend/requirements.txt" "$STAGE_DIR/"
cp -R "${APP_ROOT}/backend" "$STAGE_DIR/"

rm -rf "${STAGE_DIR}/backend/.venv" \
  "${STAGE_DIR}/backend/__pycache__" \
  "${STAGE_DIR}/backend/.env" \
  "${STAGE_DIR}/.python_packages"
rm -f "${STAGE_DIR}"/backend/.env.*

rm -f "$ZIP_PATH"
(
  cd "$STAGE_DIR"
  zip -rq "$ZIP_PATH" startup.sh requirements.txt backend
)

echo "Zip created"

# Deploy
az webapp deployment source config-zip \
  --resource-group "$RESOURCE_GROUP" \
  --name "$WEB_APP" \
  --src "$ZIP_PATH"

echo "Code deployed"

az webapp config set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$WEB_APP" \
  --startup-file "bash startup.sh"

echo "Startup command configured"

rm -rf "$STAGE_DIR"
