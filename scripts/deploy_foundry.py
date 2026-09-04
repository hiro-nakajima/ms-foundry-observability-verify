#!/usr/bin/env python3
"""Versioned Toolbox/Prompt deployment and source-ZIP Hosted deployment.

Only the approved project is writable. No Foundry resource, ACR, model or Storage
creation, no existing definition replacement and no delete operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys

import httpx
import yaml
from azure.ai.projects import AIProjectClient
from azure.ai.projects import models
from azure.identity import AzureCliCredential
from azure.core.exceptions import HttpResponseError

from procurement_agent.models import CatalogSearchResult, CodeDeterminationResult
from deploy_foundation import ROOT, STATE, SUB, RG, WEB, az, save
from deploy_search import assign
from package_hosted import package

PROJECT = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.CognitiveServices/accounts/observability-verify/projects/proj-default"
ENDPOINT = "https://observability-verify.services.ai.azure.com/api/projects/proj-default"
MANIFEST = STATE / "foundry-deployment.json"


def connection(credential, name, properties):
    resource = f"{PROJECT}/connections/{name}"
    url = f"https://management.azure.com{resource}?api-version=2026-05-01"
    with httpx.Client(timeout=60, headers={"Authorization": "Bearer " + credential.get_token("https://management.azure.com/.default").token}) as client:
        existing = client.get(url)
        if existing.status_code == 200:
            actual = existing.json()["properties"]
            if any(actual.get(key) != properties[key] for key in ("target", "category", "authType")):
                raise RuntimeError(f"Connection {name} exists with different configuration; refusing replacement")
        elif existing.status_code == 404:
            response = client.put(url, json={"properties": properties})
            if response.status_code >= 400:
                raise RuntimeError(f"Connection {name}: HTTP {response.status_code}; body withheld")
        else:
            raise RuntimeError(f"Connection {name} read: HTTP {existing.status_code}")
    return resource


def connections(credential):
    search = connection(credential, "procurement-search-connection", {
        "category": "CognitiveSearch", "target": "https://srch-procurement-observe-nkjm.search.windows.net",
        "authType": "ProjectManagedIdentity", "audience": "https://search.azure.com", "metadata": {"ApiType": "Azure"},
    })
    insights = az("resource", "show", "--ids", f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Insights/components/{WEB}-insights",
                  "--api-version", "2020-02-02")
    connection(credential, "procurement-app-insights", {
        "category": "AppInsights", "target": insights["id"], "authType": "ApiKey", "isSharedToAll": True,
        "credentials": {"key": insights["properties"]["ConnectionString"]},
        "metadata": {"ApiType": "Azure", "ResourceId": insights["id"]},
    })
    print("Search project-MI and Application Insights connections configured; credentials withheld.", flush=True)
    return search


def children(project, credential, manifest, *, new_version=False, agent_name=None):
    if new_version and any(name not in manifest for name in ("catalog-search-agent", "code-determination-agent")):
        raise RuntimeError("Recorded Prompt versions are required for --new-version")
    search_id = connections(credential)
    for filename, result_type in (("catalog-search", CatalogSearchResult), ("code-determination", CodeDeterminationResult)):
        source = ROOT / "infra/foundry/agents"
        spec = yaml.safe_load((source / f"{filename}-agent.yaml").read_text())
        name, toolbox = spec["deployment_name"], spec["toolboxes"][0]
        if agent_name and name != agent_name:
            continue
        if toolbox not in manifest:
            if any(item.name == toolbox for item in project.toolboxes.list()):
                raise RuntimeError(f"Existing toolbox {toolbox} without manifest; inspect before creating another version")
            definition = yaml.safe_load((ROOT / f"infra/foundry/toolboxes/{toolbox}.yaml").read_text())
            tool = definition["tools"][0]
            tool["azure_ai_search"]["indexes"][0]["project_connection_id"] = search_id
            version = project.toolboxes.create_version(name=toolbox, description=definition["description"],
                                                       tools=[models.AzureAISearchToolboxTool(tool)])
            manifest[toolbox] = {"version": version.version, "kind": "toolbox"}
            save(MANIFEST, manifest)
            print(f"Created {toolbox} version {version.version}", flush=True)
        toolbox_url = f"{ENDPOINT}/toolboxes/{toolbox}/versions/{manifest[toolbox]['version']}/mcp?api-version=v1"
        connection_id = connection(credential, toolbox + "-mcp", {
            "category": "RemoteTool", "target": toolbox_url, "authType": "AgenticIdentityToken",
            "audience": "https://ai.azure.com", "metadata": {"ApiType": "Azure"},
        })
        if name not in manifest or new_version:
            previous = manifest.get(name)
            if previous:
                project.agents.get_version(agent_name=name, agent_version=previous["version"])
            elif any(item.name == name for item in project.agents.list()):
                raise RuntimeError(f"Existing agent {name} without manifest; inspect before creating another version")
            definition = models.PromptAgentDefinition(model="gpt-5-mini",
                instructions=(source / spec["instructions_file"]).read_text(),
                tools=[models.MCPTool(server_label=toolbox, server_url=toolbox_url,
                    project_connection_id=connection_id, require_approval="never")],
                text=models.PromptAgentDefinitionTextOptions(format=models.TextResponseFormatJsonSchema(
                    name=result_type.__name__, schema=result_type.model_json_schema(), strict=False)))
            version = project.agents.create_version(agent_name=name, definition=definition)
            manifest[name] = {"version": version.version, "kind": "prompt",
                "instructions_sha256": hashlib.sha256(definition.instructions.encode()).hexdigest()}
            if previous:
                manifest.setdefault("prompt_version_history", []).append({"agent": name, **previous})
            save(MANIFEST, manifest)
            print(f"Created {name} version {version.version}", flush=True)
        version = project.agents.get_version(agent_name=name, agent_version=manifest[name]["version"])
        identity = version.instance_identity
        if identity is None:
            raise RuntimeError(f"Agent {name} identity not yet available")
        principal = identity.principal_id
        assign(principal, "ServicePrincipal", "53ca6127-db72-4b80-b1b0-d745d6d5456d", PROJECT)
        manifest[name]["principal_id"] = principal
        save(MANIFEST, manifest)


def hosted(project, manifest, *, new_version=False):
    name = "procurement-parent-agent"
    for child in ("catalog-search-agent", "code-determination-agent"):
        if child not in manifest:
            raise RuntimeError("Both deployed Prompt child versions are required first")
    exists = any(item.name == name for item in project.agents.list())
    if exists and not (new_version and name in manifest):
        raise RuntimeError("Hosted agent exists; inspect it and explicitly select --new-version")
    if new_version and (not exists or name not in manifest):
        raise RuntimeError("A recorded existing version is required for --new-version")
    previous = manifest.get(name)
    if previous:
        project.agents.get_version(agent_name=name, agent_version=previous["version"])
    from datetime import datetime, timezone
    target = ROOT / ".artifacts" / ("hosted-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + ".zip")
    artifact = package(target)
    definition = models.HostedAgentDefinition(cpu="0.5", memory="1Gi",
        code_configuration=models.CodeConfiguration(runtime="python_3_13", entry_point=["python", "main.py"], dependency_resolution="remote_build"),
        protocol_versions=[models.ProtocolVersionRecord(protocol="responses", version="2.0.0")],
        environment_variables={"PROCUREMENT_PARENT_MODEL_DEPLOYMENT": "gpt-5-mini",
            "PROCUREMENT_CATALOG_AGENT_NAME": "catalog-search-agent", "PROCUREMENT_CATALOG_AGENT_VERSION": str(manifest["catalog-search-agent"]["version"]),
            "PROCUREMENT_CODE_AGENT_NAME": "code-determination-agent", "PROCUREMENT_CODE_AGENT_VERSION": str(manifest["code-determination-agent"]["version"]),
            "OTEL_PROPAGATORS": "tracecontext,baggage", "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false"})
    with target.open("rb") as code:
        version = project.agents.create_version_from_code(agent_name=name, definition=definition,
            code=code, code_zip_sha256=artifact["sha256"], description="Synthetic procurement observability PoC; source ZIP")
    manifest[name] = {"version": version.version, "kind": "hosted", **artifact}
    if previous:
        manifest.setdefault("hosted_version_history", []).append(previous)
    save(MANIFEST, manifest)
    print(json.dumps({"agent": name, "version": version.version, "status": str(version.status), "zip_sha256": artifact["sha256"]}), flush=True)
    web_identity = az("webapp", "show", "--subscription", SUB, "--resource-group", RG, "--name", WEB)["identity"]["principalId"]
    assign(web_identity, "ServicePrincipal", "eed3b665-ab3a-47b6-8f48-c9382fb1dad6", f"{PROJECT}/agents/{name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["children", "hosted"])
    parser.add_argument("--new-version", action="store_true", help="Create immutable Agent version(s); preserve previous ZIP/version")
    parser.add_argument("--agent-name", choices=['catalog-search-agent', 'code-determination-agent'],
                        help="Limit a Prompt update to the changed agent")
    args = parser.parse_args()
    try:
        if az("account", "show")["id"] != SUB:
            raise RuntimeError("Wrong subscription")
        manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
        with AzureCliCredential() as credential, AIProjectClient(endpoint=ENDPOINT, credential=credential, allow_preview=True) as project:
            children(project, credential, manifest, new_version=args.new_version, agent_name=args.agent_name) if args.action == "children" else hosted(project, manifest, new_version=args.new_version)
    except Exception as error:
        if isinstance(error, HttpResponseError):
            print(f"Foundry HTTP {error.status_code}; code={getattr(error.error, 'code', None)}; body withheld", file=sys.stderr)
            if error.status_code == 400 and args.action == "children":
                # This request contains only checked-in synthetic definitions, no credentials/user input.
                print(str(getattr(error.error, "message", ""))[:1000], file=sys.stderr)
        else:
            print(str(error) if isinstance(error, RuntimeError) else type(error).__name__, file=sys.stderr)
        sys.exit(1)
