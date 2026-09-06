#!/usr/bin/env python3
"""Push the two approved synthetic indexes with Entra auth, never admin keys."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import httpx
from azure.identity import AzureCliCredential

from deploy_foundation import ROOT, STATE, SUB, RG, az, save
from prepare_search_documents import build_documents

NAME = os.environ.get("PROCUREMENT_SEARCH_SERVICE_NAME", "srch-procurement-observe-nkjm")
EXPECTED_SKU = os.environ.get("PROCUREMENT_SEARCH_SKU", "serverless")
EXPECTED_LOCATION = os.environ.get("PROCUREMENT_SEARCH_LOCATION", "westcentralus")
FOUNDRY_ACCOUNT = os.environ.get("FOUNDRY_ACCOUNT_NAME", "observability-verify")
FOUNDRY_PROJECT = os.environ.get("FOUNDRY_PROJECT_NAME", "proj-default")
SCOPE = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Search/searchServices/{NAME}"
INDEXES = ("procurement-catalog-v1", "procurement-code-master-v1")
API = "2025-09-01"


def assign(principal: str, kind: str, role: str, scope: str):
    existing = az("role", "assignment", "list", "--scope", scope)
    if not any(item["principalId"] == principal and item["roleDefinitionId"].endswith(role)
               and item["scope"].lower() == scope.lower() for item in existing):
        az("role", "assignment", "create", "--assignee-object-id", principal,
           "--assignee-principal-type", kind, "--role", role, "--scope", scope)


def permissions():
    # The deployment caller owns schema management and document loading, never runtime query.
    caller = az("ad", "signed-in-user", "show")["id"]
    project = az("resource", "show", "--ids",
        f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.CognitiveServices/accounts/{FOUNDRY_ACCOUNT}/projects/{FOUNDRY_PROJECT}",
        "--api-version", "2025-06-01")
    runtime = project["identity"]["principalId"]
    assign(caller, "User", "7ca78c08-252a-4471-8644-bb5ff32d4ba0", SCOPE)
    for index in INDEXES:
        assign(caller, "User", "8ebe5a00-799e-43f5-93ac-243d3dce84a7", f"{SCOPE}/indexes/{index}")
        assign(runtime, "ServicePrincipal", "1407120a-92aa-4202-b7e9-c0e197c71c8f", f"{SCOPE}/indexes/{index}")
        # Toolbox inspects the index definition before querying. Data Reader
        # alone only permits documents/read; index-scoped Reader adds no writes/keys.
        assign(runtime, "ServicePrincipal", "acdd72a7-3385-48ef-bd42-f606fba81ae7", f"{SCOPE}/indexes/{index}")
    print("Schema management: deployment caller/service scope; ingestion: caller/2 index scopes; query: project MI/Data Reader + Reader at 2 index scopes.")


def add_content_field():
    """Only the explicitly approved Code Master addition; never replace fields."""
    index = "procurement-code-master-v1"
    schema = json.loads((ROOT / "infra/search/indexes" / f"{index}.json").read_text())
    field = next(item for item in schema["fields"] if item["name"] == "content")
    with AzureCliCredential() as credential, httpx.Client(base_url=f"https://{NAME}.search.windows.net", timeout=60) as client:
        client.headers["Authorization"] = "Bearer " + credential.get_token("https://search.azure.com/.default").token
        path = f"/indexes/{index}"
        response = client.get(path, params={"api-version": API})
        if response.status_code != 200:
            raise RuntimeError(f"Search schema read: HTTP {response.status_code}")
        actual = response.json()
        previous_fields = actual["fields"]
        existing = next((item for item in previous_fields if item["name"] == "content"), None)
        if existing:
            if any(existing.get(key) != value for key, value in field.items()):
                raise RuntimeError("Existing content field differs; refusing modification")
            print("Code Master content field already matches; no schema write.")
            return
        etag = actual.get("@odata.etag") or response.headers.get("etag")
        if not etag:
            raise RuntimeError("Schema ETag missing; refusing unconditional update")
        backup = STATE / "code-master-schema-before-content.json"
        if not backup.exists():
            save(backup, actual)
        update = {key: value for key, value in actual.items() if not key.startswith("@odata.")}
        update["fields"] = [*previous_fields, field]
        result = client.put(path, params={"api-version": API}, json=update, headers={"If-Match": etag})
        if result.status_code not in (200, 201, 204):
            raise RuntimeError(f"Search additive schema update: HTTP {result.status_code}; body withheld")
        verified = client.get(path, params={"api-version": API})
        if verified.status_code != 200:
            raise RuntimeError("Schema applied but read-back failed; inspect before retry")
        fields = {item["name"]: item for item in verified.json()["fields"]}
        if any(fields.get(item["name"]) != item for item in previous_fields) or any(fields.get("content", {}).get(key) != value for key, value in field.items()):
            raise RuntimeError("Schema applied but read-back differs; inspect without replacement")
        print(json.dumps({"index": index, "added_field": "content", "existing_fields_preserved": True}))


def _request(client, method, path, **kwargs):
    response = client.request(method, path, params={"api-version": API}, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"Search {method} {path}: HTTP {response.status_code}; body withheld")
    return response


def _ensure_schemas(client):
    observed = []
    for index in INDEXES:
        schema = json.loads((ROOT / "infra/search/indexes" / f"{index}.json").read_text())
        existing = client.get(f"/indexes/{index}", params={"api-version": API})
        if existing.status_code == 404:
            _request(client, "PUT", f"/indexes/{index}", json=schema, headers={"If-None-Match": "*"})
            observed.append({"index": index, "result": "created"})
        elif existing.status_code != 200:
            raise RuntimeError(f"Search schema read: HTTP {existing.status_code}; RBAC propagation may be pending")
        else:
            expected_fields = {field["name"]: field["type"] for field in schema["fields"]}
            actual_fields = {field["name"]: field["type"] for field in existing.json()["fields"]}
            if actual_fields != expected_fields:
                raise RuntimeError(f"Existing {index} schema differs; no replacement allowed")
            observed.append({"index": index, "result": "matched"})
    return observed


def schemas():
    with AzureCliCredential() as credential, httpx.Client(base_url=f"https://{NAME}.search.windows.net", timeout=60) as client:
        client.headers["Authorization"] = "Bearer " + credential.get_token("https://search.azure.com/.default").token
        print(json.dumps({"schemas": _ensure_schemas(client)}))


def push():
    catalog, codes, manifest = build_documents()
    observed = []
    with AzureCliCredential() as credential, httpx.Client(base_url=f"https://{NAME}.search.windows.net", timeout=60) as client:
        client.headers["Authorization"] = "Bearer " + credential.get_token("https://search.azure.com/.default").token
        _ensure_schemas(client)
        # Preflight both schemas before updating either document set.
        for index, documents in zip(INDEXES, (catalog, codes)):
            result = _request(client, "POST", f"/indexes/{index}/docs/index",
                json={"value": [{"@search.action": "upload", **document} for document in documents]}).json()
            if not all(item["status"] for item in result["value"]):
                raise RuntimeError(f"Some {index} uploads failed; body withheld")
            observed.append({"index": index, "accepted_documents": len(result["value"])})
    save(STATE / "search-manifest.json", {**manifest, "upload_results": observed})
    print(json.dumps({"synthetic": True, "upload_results": observed}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["permissions", "schemas", "add-content-field", "push"])
    args = parser.parse_args()
    try:
        if az("account", "show")["id"] != SUB:
            raise RuntimeError("Wrong subscription")
        resource = az("resource", "show", "--ids", SCOPE, "--api-version", "2026-03-01-preview")
        if (resource["sku"]["name"].lower() != EXPECTED_SKU.lower()
                or resource["location"].lower().replace(" ", "") != EXPECTED_LOCATION.lower().replace(" ", "")):
            raise RuntimeError("Search target differs from the explicitly configured SKU/location")
        {"permissions": permissions, "schemas": schemas,
         "add-content-field": add_content_field, "push": push}[args.action]()
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else type(error).__name__, file=sys.stderr)
        sys.exit(1)
