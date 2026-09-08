#!/bin/bash
set -e

APP_ROOT="${APP_PATH:-/home/site/wwwroot}"

echo "=== webapp-foundry-oauth startup ==="

if [ -f "${APP_ROOT}/antenv/bin/activate" ]; then
  . "${APP_ROOT}/antenv/bin/activate"
elif [ -f "/home/site/wwwroot/antenv/bin/activate" ]; then
  . "/home/site/wwwroot/antenv/bin/activate"
fi

export PYTHONPATH="${APP_ROOT}/.python_packages/lib/site-packages:${PYTHONPATH:-}"

cd "${APP_ROOT}/backend"

exec python -m uvicorn server:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --workers 1 \
  --log-level info
