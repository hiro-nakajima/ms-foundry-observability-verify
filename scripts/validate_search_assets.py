#!/usr/bin/env python3
"""Static validation for synthetic data, Search indexes, and Foundry Toolboxes."""

from __future__ import annotations

import json
import yaml
from prepare_search_documents import ROOT, build_documents


def validate() -> dict[str, object]:
    catalog_docs, code_docs, manifest = build_documents()
    if len(catalog_docs) != 10:
        raise ValueError("procurement-catalog-v1 must contain exactly 10 products")
    for documents in (catalog_docs, code_docs):
        ids = [item["document_id"] for item in documents]
        if len(ids) != len(set(ids)):
            raise ValueError("document_id values must be unique")
    expected = {
        "procurement-catalog-v1": ("catalog_search", "catalog-search-toolbox.yaml"),
        "procurement-code-master-v1": ("code_master_search", "code-master-toolbox.yaml"),
    }
    for index_name, (tool_name, toolbox_file) in expected.items():
        schema = json.loads((ROOT / "infra/search/indexes" / f"{index_name}.json").read_text(encoding="utf-8"))
        if schema["name"] != index_name:
            raise ValueError(f"index name mismatch for {index_name}")
        keys = [field["name"] for field in schema["fields"] if field.get("key")]
        if keys != ["document_id"]:
            raise ValueError(f"{index_name} must have document_id as its only key")
        toolbox = yaml.safe_load((ROOT / "infra/foundry/toolboxes" / toolbox_file).read_text(encoding="utf-8"))
        tools = toolbox.get("tools", [])
        if len(tools) != 1 or tools[0]["type"] != "azure_ai_search" or tools[0]["name"] != tool_name:
            raise ValueError(f"invalid tool inventory in {toolbox_file}")
        indexes = tools[0]["azure_ai_search"]["indexes"]
        if [entry["index_name"] for entry in indexes] != [index_name]:
            raise ValueError(f"{toolbox_file} must reference only {index_name}")
    return manifest


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, sort_keys=True))
