#!/usr/bin/env python3
"""Configure the approved OBO integration; keep credentials in memory.

Functions infrastructure is deployed from infra/identity-functions.bicep first.
Only the specified procurement RG is written. Existing tenant app registrations
are reused by adding the necessary redirect/scope; existing entries are kept.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
from azure.ai.projects import AIProjectClient, models
from azure.identity import AzureCliCredential

from deploy_foundation import ROOT, STATE, SUB, RG, WEB, az, save
from deploy_foundry import ENDPOINT, PROJECT

FUNCTION = "func-procurement-obo-nkjm"
CONNECTION = "procurement-whoami"
TOOLBOX = "procurement-identity-toolbox"
TENANT = "d21866e6-786d-4625-8dc0-1e11e973489a"
MANIFEST = STATE / "identity-deployment.json"
ARM = "https://management.azure.com"
WEB_ID = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Web/sites/{WEB}"
FUNCTION_ID = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Web/sites/{FUNCTION}"


def api(credential, method, url, body=None):
    scope = "https://graph.microsoft.com/.default" if url.startswith("https://graph.microsoft.com/") else "https://management.azure.com/.default"
    response = httpx.request(method, url, json=body, timeout=90,
                            headers={"Authorization": "Bearer " + credential.get_token(scope).token,
                                     "Accept": "application/json"})
    if response.is_error:
        raise RuntimeError(f"{method} {url.split('?')[0]}: HTTP {response.status_code}; body withheld")
    return response.json() if response.content else {}


def arm(credential, method, resource, body=None):
    version = "2026-05-01" if "CognitiveServices" in resource else ("2024-04-01" if "Microsoft.Web" in resource else "2024-05-01")
    return api(credential, method, f"{ARM}{resource}?api-version={version}", body)


def application(credential, client_id):
    return api(credential, "GET", f"https://graph.microsoft.com/v1.0/applications(appId='{client_id}')")


def configure_functions(credential, manifest):
    old = az("functionapp", "config", "appsettings", "list", "--resource-group", "rg-ms-foundry-mcp",
             "--name", "func-mcp-server-anonym-229963", "--subscription", SUB)
    allowed = {"ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET", "EXPECTED_TOKEN_AUDIENCES",
               "EXPECTED_TENANT_ID", "GRAPH_SCOPES"}
    settings = arm(credential, "POST", FUNCTION_ID + "/config/appsettings/list")["properties"]
    settings.update({entry["name"]: entry["value"] for entry in old if entry["name"] in allowed})
    if not settings.get("ENTRA_CLIENT_SECRET"):
        raise RuntimeError("Existing App B credential missing")
    settings.update(OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="false")
    arm(credential, "PUT", FUNCTION_ID + "/config/appsettings", {"properties": settings})
    function = arm(credential, "GET", FUNCTION_ID)
    target = "https://" + function["properties"]["defaultHostName"] + "/mcp"
    client = json.loads((ROOT / "src/functions-mcp-selfhosted/infra/entra/foundry-oauth-client-app.outputs.json").read_text())
    connection_id = PROJECT + "/connections/" + CONNECTION
    if not manifest.get("connection"):
        props = {
            "authType": "OAuth2", "category": "RemoteTool", "target": target,
            "credentials": {"tenantId": TENANT, "clientId": client["appId"], "clientSecret": client["clientSecret"]},
            "authorizationUrl": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize",
            "tokenUrl": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
            "scopes": [client["scope"]], "metadata": {"type": "custom_MCP"},
        }
        connection = arm(credential, "PUT", connection_id, {"properties": props})
        manifest.update(connection=connection_id, function=FUNCTION, functionEndpoint=target)
        save(MANIFEST, manifest)
    connection = arm(credential, "GET", connection_id)
    redirect = connection["properties"].get("redirectUrl")
    if not redirect:
        raise RuntimeError("Foundry did not return an OAuth redirect URL")
    app = application(credential, client["appId"])
    redirects = app["web"].get("redirectUris", [])
    if redirect not in redirects:
        api(credential, "PATCH", f"https://graph.microsoft.com/v1.0/applications/{app['id']}",
            {"web": {**app["web"], "redirectUris": redirects + [redirect]}})
    with AIProjectClient(endpoint=ENDPOINT, credential=credential, allow_preview=True) as project:
        if not manifest.get("toolboxVersion"):
            version = project.toolboxes.create_version(name=TOOLBOX, tools=[models.MCPToolboxTool(
                server_label="whoami_func", server_url=target, project_connection_id=connection_id,
                allowed_tools=["whoami"], require_approval="never")])
            manifest.update(toolboxVersion=str(version.version),
                            toolboxEndpoint=f"{ENDPOINT}/toolboxes/{TOOLBOX}/versions/{version.version}/mcp?api-version=v1")
            save(MANIFEST, manifest)
    print(json.dumps({key: manifest[key] for key in ("function", "functionEndpoint", "toolboxVersion", "toolboxEndpoint")}), flush=True)


def configure_web(credential, manifest):
    settings = arm(credential, "POST", WEB_ID + "/config/appsettings/list")["properties"]
    auth = arm(credential, "GET", WEB_ID + "/config/authsettingsV2")["properties"]
    aad = auth["identityProviders"]["azureActiveDirectory"]
    client_id = aad["registration"]["clientId"]
    app = application(credential, client_id)
    # Add only the Foundry delegated scope to the existing EasyAuth app.
    required = app.get("requiredResourceAccess", [])
    foundry_id, scope_id = "18a66f5f-dbdf-4c17-9dd7-1634712a9cbe", "1a7925b5-f871-417a-9b8b-303f9f29fa10"
    entry = next((e for e in required if e["resourceAppId"] == foundry_id), None)
    if entry is None:
        entry = {"resourceAppId": foundry_id, "resourceAccess": []}
        required.append(entry)
    if not any(e["id"] == scope_id for e in entry["resourceAccess"]):
        entry["resourceAccess"].append({"id": scope_id, "type": "Scope"})
        api(credential, "PATCH", f"https://graph.microsoft.com/v1.0/applications/{app['id']}", {"requiredResourceAccess": required})
    for name, value in (("oauth-web-settings-backup.json", settings), ("oauth-web-auth-backup.json", auth)):
        if not (STATE / name).exists():
            save(STATE / name, value)
    settings.update(FOUNDRY_USER_AUTH_MODE="refresh_token", FOUNDRY_OBO_CLIENT_ID=client_id,
                    FOUNDRY_OBO_TENANT_ID=TENANT, FOUNDRY_TOKEN_SCOPES="https://ai.azure.com/.default",
                    IDENTITY_LOOKUP_ENABLED="true", WEB_APP_URL=f"https://{WEB}.azurewebsites.net")
    arm(credential, "PUT", WEB_ID + "/config/appsettings", {"properties": settings})
    aad.setdefault("login", {})["loginParameters"] = ["scope=openid profile email offline_access https://ai.azure.com/.default"]
    auth.setdefault("login", {}).setdefault("tokenStore", {})["enabled"] = True
    arm(credential, "PUT", WEB_ID + "/config/authsettingsV2", {"properties": auth})
    web = arm(credential, "GET", WEB_ID)
    policy = (ROOT / "infra/apim-foundry-policy.xml").read_text().replace("__TENANT__", TENANT).replace(
        "__WEB_PRINCIPAL__", web["identity"]["principalId"]).replace("__WEB_CLIENT__", client_id)
    policy_id = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.ApiManagement/service/apim-procurement-stream-nkjm/apis/foundry-proj-default/policies/policy"
    previous = arm(credential, "GET", policy_id)
    save(STATE / "oauth-apim-policy-backup.json", previous)
    arm(credential, "PUT", policy_id, {"properties": {"format": "rawxml", "value": policy}})
    manifest["webConfigured"] = True
    save(MANIFEST, manifest)
    print("Web delegated authentication and existing APIM route configured; credentials withheld.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["functions", "web"])
    args = parser.parse_args()
    if RG != "rg-ms-foundry-observability-verify" or SUB != "d96eb8c2-2deb-4ed5-8cf2-f9fb178cb3ee":
        raise SystemExit("Unexpected deployment scope")
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    with AzureCliCredential() as credential:
        (configure_functions if args.action == "functions" else configure_web)(credential, manifest)
