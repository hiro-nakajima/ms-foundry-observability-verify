#!/usr/bin/env python3
"""Static validation for synthetic data, Search indexes, and Foundry Toolboxes."""

from __future__ import annotations

import json
import yaml
from prepare_search_documents import ROOT, build_documents


def validate() -> dict[str, object]:
    catalog_docs, code_docs, manifest = build_documents()
    if len(catalog_docs) != 11:
        raise ValueError("procurement-catalog-v1 must contain exactly 11 products")
    for documents in (catalog_docs, code_docs):
        ids = [item["document_id"] for item in documents]
        if len(ids) != len(set(ids)):
            raise ValueError("document_id values must be unique")
    expected = {
        "procurement-catalog-v1": {
            "tool": "catalog_search",
            "toolbox": "catalog-search-toolbox.yaml",
            "container": "procurement-catalog",
            "documents": catalog_docs,
        },
        "procurement-code-master-v1": {
            "tool": "code_master_search",
            "toolbox": "code-master-toolbox.yaml",
            "container": "procurement-code-master",
            "documents": code_docs,
        },
    }
    search_root = ROOT / "infra/search"
    static_manifest = json.loads((search_root / "documents/manifest.json").read_text(encoding="utf-8"))
    if static_manifest != manifest:
        raise ValueError("static Search document manifest differs from Repository projection")
    for index_name, values in expected.items():
        tool_name = values["tool"]
        toolbox_file = values["toolbox"]
        container = values["container"]
        documents = values["documents"]
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
        static_documents = json.loads(
            (search_root / "documents" / container / "documents.json").read_text(encoding="utf-8")
        )
        if static_documents != documents:
            raise ValueError(f"static documents differ from Repository projection for {index_name}")
        data_source_name = f"{container}-blob-source"
        data_source = json.loads(
            (search_root / "datasources" / f"{data_source_name}.json").read_text(encoding="utf-8")
        )
        if (
            data_source.get("name") != data_source_name
            or data_source.get("type") != "azureblob"
            or data_source.get("container") != {"name": container}
            or not data_source.get("credentials", {}).get("connectionString", "").startswith("ResourceId=")
        ):
            raise ValueError(f"invalid static Data source definition for {index_name}")
        indexer_name = f"{container}-blob-indexer"
        indexer = json.loads(
            (search_root / "indexers" / f"{indexer_name}.json").read_text(encoding="utf-8")
        )
        if (
            indexer.get("name") != indexer_name
            or indexer.get("dataSourceName") != data_source_name
            or indexer.get("targetIndexName") != index_name
            or indexer.get("parameters", {}).get("configuration", {}).get("parsingMode") != "jsonArray"
        ):
            raise ValueError(f"invalid static Indexer definition for {index_name}")
    return manifest


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, sort_keys=True))
