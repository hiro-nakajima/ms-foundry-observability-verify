from __future__ import annotations

import json
from pathlib import Path

from procurement_agent.tools import DATA_FILENAMES, LocalJsonAdapter, default_data_resource


ROOT = Path(__file__).resolve().parents[2]


def test_all_synthetic_documents_are_versioned() -> None:
    versions = set()
    for filename in DATA_FILENAMES:
        document = json.loads((ROOT / "data" / filename).read_text(encoding="utf-8"))
        assert document["synthetic"] is True
        assert document["schema_version"] == "1.0"
        assert document["records"]
        versions.add(document["data_version"])
    assert versions == {"2026-08-28.1"}


def test_local_adapter_validates_all_documents() -> None:
    adapter = LocalJsonAdapter(ROOT / "data")
    assert adapter.data_version == "2026-08-28.1"
    assert len(adapter.catalog) == 3
    assert all(applicant.synthetic for applicant in adapter.applicants)


def test_default_package_resource_loads_synthetic_documents() -> None:
    adapter = LocalJsonAdapter(default_data_resource())
    assert adapter.data_version == "2026-08-28.1"
