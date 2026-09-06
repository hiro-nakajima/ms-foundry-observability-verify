#!/usr/bin/env bash
set -euo pipefail

MCP_ENDPOINT="${1:-${MCP_ENDPOINT:-}}"

if [[ -z "${MCP_ENDPOINT}" ]]; then
  echo "Usage: MCP_ENDPOINT=https://<function-app-default-hostname>/mcp $0" >&2
  exit 1
fi

curl -sS -X POST "${MCP_ENDPOINT}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"warmup","method":"tools/list","params":{}}' \
  >/dev/null

echo "Warm-up completed: ${MCP_ENDPOINT}"
