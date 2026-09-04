#!/usr/bin/env python3
"""Build deterministic Azure AI Search documents from versioned synthetic data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_documents() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    catalog = read_json(DATA / "catalog.json")
    accounts = read_json(DATA / "account_codes.json")
    departments = read_json(DATA / "departments.json")
    versions = {item["data_version"] for item in (catalog, accounts, departments)}
    if len(versions) != 1:
        raise ValueError(f"source data_version mismatch: {sorted(versions)}")
    source_version = versions.pop()
    catalog_documents = []
    for item in catalog["records"]:
        catalog_documents.append({
            "document_id": f"catalog-{item['product_code']}",
            "chunk_id": f"catalog-{item['product_code']}-0",
            "source_version": source_version,
            "product_code": item["product_code"],
            "product_name": item["name"],
            "aliases": item.get("keywords", []),
            "category": item["category"],
            "unit_price": float(item["unit_price"]),
            "currency": item["currency"],
            "content": f"{item['name']}。商品コード {item['product_code']}。分類 {item['category']}。価格 {item['unit_price']} {item['currency']}。",
            "specifications_json": json.dumps(item.get("specifications", {}), ensure_ascii=False, sort_keys=True),
            "active": True,
        })
    code_documents = []
    for item in accounts["records"]:
        for category in item["categories"]:
            document_id = f"account-{item['account_code']}-{category}"
            code_documents.append({
                "document_id": document_id,
                "source_version": source_version,
                "record_type": "account_code",
                "lookup_key": category,
                "aliases": item.get("purposes", []),
                "account_code": item["account_code"],
                "department_code": None,
                "display_name": item["label"],
                "active": True,
            })
    for item in departments["records"]:
        code_documents.append({
            "document_id": f"department-{item['department_code']}",
            "source_version": source_version,
            "record_type": "department",
            "lookup_key": item["department_name"],
            "aliases": item.get("aliases", []),
            "account_code": None,
            "department_code": item["department_code"],
            "display_name": item["department_name"],
            "active": True,
        })
    # Managed Toolbox returns searchable text, not every retrievable field.
    # Carry the adopted values and evidence IDs in that text, from the same JSON.
    for document in catalog_documents + code_documents:
        document["content"] = json.dumps(
            {key: value for key, value in document.items() if key not in {"content", "aliases", "active"}},
            ensure_ascii=False, sort_keys=True,
        )
    manifest = {
        "schema_version": "1.0", "document_projection_version": "2", "source_version": source_version, "synthetic": True,
        "catalog_index": "procurement-catalog-v1", "catalog_document_count": len(catalog_documents),
        "catalog_sha256": canonical_hash(catalog_documents),
        "code_index": "procurement-code-master-v1", "code_document_count": len(code_documents),
        "code_sha256": canonical_hash(code_documents),
    }
    return catalog_documents, code_documents, manifest


def write_outputs(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog, codes, manifest = build_documents()
    for name, value in (
        ("catalog-documents.json", catalog),
        ("code-master-documents.json", codes),
        ("catalog-upload-batch.json", {"value": [{"@search.action": "upload", **item} for item in catalog]}),
        ("code-upload-batch.json", {"value": [{"@search.action": "upload", **item} for item in codes]}),
        ("manifest.json", manifest),
    ):
        (output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".artifacts" / "search")
    args = parser.parse_args()
    write_outputs(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
