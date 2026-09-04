#!/usr/bin/env python3
"""Deploy the approved PoC foundation; never print secure parameters or Azure bodies.

prepare creates only the dedicated EasyAuth registration/credential and local
secure parameters. plan/apply use Incremental ARM mode and reject modifications
to existing resources. Failed creates are inventoried, never deleted here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local_state" / "deployment"
SUB = "d96eb8c2-2deb-4ed5-8cf2-f9fb178cb3ee"
RG = "rg-ms-foundry-observability-verify"
WEB = "web-procurement-observe-nkjm"
APP = "procurement-observability-web"
PARAMS = STATE / "foundation.parameters.json"


def az(*args: str):
    result = subprocess.run(["az", *args, "--only-show-errors", "-o", "json"],
                            capture_output=True, text=True, cwd=ROOT)
    if result.returncode:
        # Azure error bodies can echo secure request values; retain only codes.
        import re
        codes = re.findall(r"(?:ERROR: \(|\"code\"\s*:\s*\")([A-Za-z][A-Za-z0-9.]+)", result.stderr)
        raise RuntimeError(f"Azure {' '.join(args[:2])} failed: {','.join(dict.fromkeys(codes)) or 'REDACTED_ERROR'}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def save(path: Path, value):
    with open(path, "w", encoding="utf-8", opener=lambda p, flags: os.open(p, flags, 0o600)) as file:
        json.dump(value, file, indent=2)
    path.chmod(0o600)


def prepare():
    marker = STATE / "entra.json"
    apps = az("ad", "app", "list", "--display-name", APP)
    exact = [app for app in apps if app["displayName"] == APP]
    if marker.exists():
        app = json.loads(marker.read_text())
        if not any(item["id"] == app["id"] for item in exact):
            raise RuntimeError("Previously recorded Entra app no longer matches; inspect before retry.")
    else:
        if exact:
            raise RuntimeError("Existing same-name Entra app found without our manifest; refusing to modify.")
        app = az("ad", "app", "create", "--display-name", APP, "--sign-in-audience", "AzureADMyOrg",
                 "--enable-id-token-issuance", "true",
                 "--web-redirect-uris", f"https://{WEB}.azurewebsites.net/.auth/login/aad/callback")
        app = {key: app[key] for key in ("id", "appId")}
        save(marker, app)
        print("Created dedicated single-tenant EasyAuth registration (no delegated API permission).", flush=True)
    principals = az("ad", "sp", "list", "--filter", f"appId eq '{app['appId']}'")
    if not principals:
        az("ad", "sp", "create", "--id", app["appId"])
    # EasyAuth's confidential-client flow requests code + id_token. This flag
    # permits the ID token; implicit access tokens and delegated API grants stay off.
    current = az("ad", "app", "show", "--id", app["appId"])
    if not current["web"]["implicitGrantSettings"]["enableIdTokenIssuance"]:
        az("ad", "app", "update", "--id", app["appId"], "--enable-id-token-issuance", "true")
    if PARAMS.exists():
        print("Existing secure parameters retained; no credential reset.", flush=True)
        return
    expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = STATE / "credential-request.json"
    save(body, {"passwordCredential": {"displayName": "procurement-poc-30d", "endDateTime": expiry}})
    reference = az("rest", "--method", "get", "--url",
        f"https://management.azure.com/subscriptions/{SUB}/resourceGroups/rg-ms-foundry-mcp/providers/Microsoft.ApiManagement/service/apim-mcp-handson?api-version=2024-05-01")
    credential_file = STATE / "credential.json"
    if credential_file.exists():
        password = json.loads(credential_file.read_text())
        expiry = password["endDateTime"]
    else:
        password = az("rest", "--method", "post", "--url",
                      f"https://graph.microsoft.com/v1.0/applications/{app['id']}/addPassword", "--body", f"@{body}")
        save(credential_file, password)
    values = {
        "webAppName": WEB, "appServicePlanName": "asp-procurement-observe",
        "searchServiceName": "srch-procurement-observe-nkjm", "searchLocation": "westcentralus",
        "foundryProjectEndpoint": "https://observability-verify.services.ai.azure.com/api/projects/proj-default",
        "apimName": "apim-procurement-stream-nkjm", "apimLocation": "eastus",
        "apimPublisherEmail": reference["properties"]["publisherEmail"],
        "entraClientId": app["appId"], "entraClientSecret": password["secretText"],
        "sessionSigningKey": secrets.token_urlsafe(48),
    }
    save(PARAMS, {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
                  "contentVersion": "1.0.0.0", "parameters": {key: {"value": value} for key, value in values.items()}})
    save(STATE / "credential-metadata.json", {"expires": expiry, "keyId": password["keyId"]})
    print(f"Secure parameters saved in ignored mode-600 file; EasyAuth credential expires {expiry}.", flush=True)


def plan_or_apply(apply: bool):
    if not PARAMS.exists():
        raise RuntimeError("Run prepare first; example/dummy parameters are never applied.")
    parameters = json.loads(PARAMS.read_text())
    if parameters["parameters"].pop("acrName", None) is not None:
        save(PARAMS, parameters)  # ZIP deployment supersedes the initial ACR plan; never deletes Azure resources.
    offerings = az("rest", "--method", "get", "--url",
                  "https://management.azure.com/providers/Microsoft.Search/offerings?api-version=2026-03-01-preview")
    regions = offerings.get("value", offerings) if isinstance(offerings, dict) else offerings
    if not any(item.get("regionName", "").lower() == "westcentralus"
               and any(sku.get("name") == "serverless" for sku in item.get("skus", [])) for item in regions):
        raise RuntimeError("West Central US serverless offering not confirmed; no SKU fallback.")
    common = ("--subscription", SUB, "--resource-group", RG,
              "--template-file", "infra/webui.bicep", "--parameters", f"@{PARAMS}", "--mode", "Incremental")
    result = az("deployment", "group", "what-if", *common, "--no-pretty-print")
    changes = result.get("changes", [])
    counts = dict(Counter(change["changeType"] for change in changes))
    print(json.dumps({"what_if_status": result.get("status"), "changes": counts}), flush=True)
    save(STATE / "foundation-plan-summary.json", {"status": result.get("status"), "changes": [
        {"id": c["resourceId"], "changeType": c["changeType"]} for c in changes]})
    if result.get("status") != "Succeeded" or any(c["changeType"] not in {"Create", "Ignore", "NoChange"} for c in changes):
        raise RuntimeError("Plan requires inspection: only new creates/no-change/ignore are approved by this script.")
    if apply:
        name = "procurement-foundation-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        save(STATE / "active-deployment.json", {"name": name, "subscription": SUB, "resourceGroup": RG})
        az("deployment", "group", "create", *common, "--name", name, "--no-wait")
        print(json.dumps({"deployment": name, "state": "submitted; verify via ARM"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "plan", "apply"])
    args = parser.parse_args()
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if az("account", "show")["id"] != SUB:
        raise RuntimeError("Wrong active subscription; no changes made.")
    if args.action == "prepare":
        prepare()
    else:
        plan_or_apply(args.action == "apply")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
