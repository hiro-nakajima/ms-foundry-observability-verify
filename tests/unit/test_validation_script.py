from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "src"
    / "procurement_agent"
    / "skills"
    / "request-check"
    / "scripts"
    / "validate_request.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_request_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _draft() -> dict:
    return {
        "item": {
            "product_code": "LAPTOP-DEV-14",
            "unit_price": "180000",
            "specifications": {"memory": "32GB"},
        },
        "amount": {
            "subtotal": "180000",
            "taxable_amount": "180000",
            "tax": "18000",
            "total": "198000",
            "calculated_by": "request-check/scripts/calculate_request.py",
        },
        "delivery": {"estimated_on": "2026-09-11"},
        "applicant": {"employee_id": "EMP-001", "department_code": "D-ENG"},
        "account": {"account_code": "A-100"},
        "request_constraints": {
            "budget_limit": "200000",
            "specifications": {"memory": "32gb"},
        },
        "evidence_refs": ["catalog:LAPTOP-DEV-14:2026-08-28.1"],
    }


def test_validation_accepts_matching_specification_and_budget() -> None:
    result = _load_module().validate_request(_draft())
    assert result["valid"] is True
    assert result["checks"]["specifications"] is True
    assert result["checks"]["budget_limit"] is True


def test_validation_rejects_unmet_specification_and_budget() -> None:
    draft = _draft()
    draft["request_constraints"] = {
        "budget_limit": "100000",
        "specifications": {"memory": "64GB"},
    }
    result = _load_module().validate_request(draft)
    assert result["valid"] is False
    assert result["checks"]["specifications"] is False
    assert result["checks"]["budget_limit"] is False
    assert any("constraint.specifications" in item for item in result["violations"])
    assert any("constraint.budget_limit" in item for item in result["violations"])
