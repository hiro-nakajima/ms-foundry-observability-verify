#!/usr/bin/env python3
"""Static deployment contract validation. It never authenticates or changes Azure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate() -> dict[str, object]:
    azure = yaml.safe_load((ROOT / "azure.yaml").read_text(encoding="utf-8"))
    if azure["metadata"]["architecture"] != "procurement_application_v2":
        raise ValueError("azure.yaml architecture mismatch")
    agent_dir = ROOT / "infra/foundry/agents"
    toolboxes = {
        "catalog_search_agent": ["catalog-search-toolbox"],
        "code_determination_agent": ["code-master-toolbox"],
    }
    instruction_hashes = {}
    for definition_path in agent_dir.glob("*-agent.yaml"):
        definition = yaml.safe_load(definition_path.read_text(encoding="utf-8"))
        if definition["toolboxes"] != toolboxes[definition["name"]]:
            raise ValueError(f"toolbox ownership mismatch: {definition_path.name}")
        instruction_path = agent_dir / definition["instructions_file"]
        instruction_hashes[definition["name"]] = {
            "version": definition["version"],
            "sha256": digest(instruction_path),
        }
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src/hosted-agent/procurement_agent").glob("*.py"))
    if not source_text:
        raise ValueError("Hosted source directory is empty or missing")
    forbidden = ("class CatalogSearchAgent", "class CodeDeterminationAgent", "SerializedProcurementContextProvider", "class AgentSession")
    matches = [token for token in forbidden if token in source_text]
    if matches:
        raise ValueError(f"forbidden child/session implementation remains: {matches}")
    return {
        "architecture_id": "procurement_application_v2",
        "instruction_hashes": instruction_hashes,
        "azure_apply_performed": False,
        "rbac_identities": ["runtime", "index_manager", "document_ingestor"],
    }


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, sort_keys=True))
