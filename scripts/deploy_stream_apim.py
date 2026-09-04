#!/usr/bin/env python3
"""Create the approved SSE-capable gateway, without switching or deleting the old one."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import subprocess
import xml.etree.ElementTree as ET

from deploy_foundation import az, save, STATE, SUB, RG, WEB

OLD = "apim-procurement-observe-nkjm"
NEW = "apim-procurement-stream-nkjm"
BASE = f"/subscriptions/{SUB}/resourceGroups/{RG}"
RESOURCE = f"{BASE}/providers/Microsoft.ApiManagement/service/{NEW}"
PARAMS = STATE / "stream-apim.parameters.json"


def verify():
    gateway = az("apim", "show", "--subscription", SUB, "-g", RG, "-n", NEW)
    if gateway["provisioningState"] != "Succeeded" or gateway["sku"] != {"name": "Developer", "capacity": 1}:
        raise RuntimeError("New Developer gateway is not ready")
    api_url = f"https://management.azure.com{RESOURCE}/apis/foundry-proj-default"
    api = az("rest", "--method", "get", "--url", api_url + "?api-version=2024-05-01")
    operations = az("rest", "--method", "get", "--url", api_url + "/operations?api-version=2024-05-01")
    expected = {"create-conversation", "get-conversation", "update-conversation", "parent-response"}
    if {op["name"] for op in operations["value"]} != expected or api["properties"]["subscriptionRequired"]:
        raise RuntimeError("API operation/authentication contract mismatch")
    # ARM can return policy as BOM-prefixed XML rather than JSON.
    result = subprocess.run(["az", "rest", "--method", "get", "--url",
        api_url + "/policies/policy?api-version=2024-05-01", "--only-show-errors", "-o", "json"],
        capture_output=True, text=True, check=True)
    body = result.stdout.lstrip("\ufeff \r\n")
    xml = body if body.startswith("<") else json.loads(body)["properties"]["value"]
    root = ET.fromstring(xml)
    forward, auth = root.find("backend/forward-request"), root.find("inbound/validate-azure-ad-token")
    source = json.loads((STATE / "stream-apim-source.json").read_text())
    if (forward is None or forward.get("buffer-response") != "false" or auth is None
        or auth.findtext("audiences/audience") != "https://ai.azure.com"
        or auth.findtext("required-claims/claim[@name='oid']/value") != source["web_principal_id"]
        or auth.get("tenant-id") != az("account", "show")["tenantId"]):
        raise RuntimeError("SSE or MI policy mismatch")
    diagnostics = az("rest", "--method", "get", "--url", api_url + "/diagnostics/applicationinsights?api-version=2024-05-01")["properties"]
    if diagnostics.get("httpCorrelationProtocol") != "W3C" or diagnostics.get("logClientIp"):
        raise RuntimeError("Diagnostic context mismatch")
    if any(diagnostics[side][direction]["body"]["bytes"] != 0 or diagnostics[side][direction].get("headers")
           for side in ("frontend", "backend") for direction in ("request", "response")):
        raise RuntimeError("Sensitive header/body logging is enabled")
    summary = {"gateway": NEW, "state": "verified", "operations": sorted(expected),
               "mi_restricted": True, "response_buffering": False, "body_logging_bytes": 0, "correlation": "W3C"}
    save(STATE / "stream-apim-config-verification.json", summary)
    print(json.dumps(summary))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "apply", "status", "verify"])
    args = parser.parse_args()
    if az("account", "show")["id"] != SUB:
        raise RuntimeError("Wrong subscription; no changes made.")
    if args.action == "verify":
        verify()
        return
    marker = STATE / "stream-apim-deployment.json"
    if args.action == "status":
        deployment = json.loads(marker.read_text())
        result = az("deployment", "group", "show", "--subscription", SUB,
                    "-g", RG, "-n", deployment["name"])
        print(json.dumps({"name": deployment["name"], "state": result["properties"]["provisioningState"]}))
        return
    old = az("apim", "show", "--subscription", SUB, "-g", RG, "-n", OLD)
    web = az("webapp", "show", "--subscription", SUB, "-g", RG, "-n", WEB)
    settings = az("webapp", "config", "appsettings", "list", "--subscription", SUB, "-g", RG, "-n", WEB)
    settings = {item["name"]: item["value"] for item in settings}
    provider = az("provider", "show", "--namespace", "Microsoft.ApiManagement", "--subscription", SUB)
    if provider["registrationState"] != "Registered" or old["sku"]["name"] != "Consumption":
        raise RuntimeError("Unexpected provider or source tier; inspect before changes.")
    found = az("resource", "list", "--subscription", SUB, "-g", RG)
    if any(item["id"].lower() == RESOURCE.lower() for item in found):
        raise RuntimeError("Target already exists; inspect status instead of recreating.")
    availability = az("rest", "--method", "post", "--url",
        f"https://management.azure.com/subscriptions/{SUB}/providers/Microsoft.ApiManagement/checkNameAvailability?api-version=2024-05-01",
        "--body", json.dumps({"name": NEW}))
    if not availability.get("nameAvailable"):
        raise RuntimeError("New gateway name unavailable; no changes made.")
    insights = az("rest", "--method", "get", "--url",
        f"https://management.azure.com{BASE}/providers/Microsoft.Insights/components/{WEB}-insights?api-version=2020-02-02")
    values = {"name": NEW, "location": "eastus", "skuName": "Developer",
        "publisherEmail": old["publisherEmail"],
        "projectEndpoint": "https://observability-verify.services.ai.azure.com/api/projects/proj-default",
        "webAppPrincipalId": web["identity"]["principalId"],
        "instrumentationKey": insights["properties"]["InstrumentationKey"]}
    save(PARAMS, {"parameters": {k: {"value": v} for k, v in values.items()}})
    save(STATE / "stream-apim-source.json", {"old_id": old["id"], "old_sku": old["sku"],
        "old_endpoint": settings["PROJECT_ENDPOINT"], "new_id": RESOURCE,
        "web_principal_id": web["identity"]["principalId"]})
    common = ("--subscription", SUB, "-g", RG, "--template-file", "infra/apim.bicep",
              "--parameters", f"@{PARAMS}", "--mode", "Incremental")
    result = az("deployment", "group", "what-if", *common, "--no-pretty-print")
    save(STATE / "stream-apim-what-if.json", result)
    changes = result.get("changes", [])
    print(json.dumps({"new_apim": NEW, "sku": "Developer", "location": "eastus",
                      "what_if": result.get("status"), "changes": dict(Counter(c["changeType"] for c in changes))}), flush=True)
    if result.get("status") != "Succeeded" or not any(c["changeType"] == "Create" for c in changes):
        raise RuntimeError("No successful create plan; not deploying.")
    for change in changes:
        target = change["resourceId"].lower()
        if change["changeType"] == "Ignore":
            continue
        if change["changeType"] != "Create" or not (target == RESOURCE.lower() or target.startswith(RESOURCE.lower() + "/")):
            raise RuntimeError("What-if contains changes outside the new gateway; not deploying.")
    if args.action == "apply":
        name = "procurement-stream-apim-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        save(marker, {"name": name, "resource_id": RESOURCE})
        az("deployment", "group", "create", *common, "-n", name, "--no-wait")
        print(json.dumps({"deployment": name, "state": "submitted; old route unchanged"}))


if __name__ == "__main__":
    main()
