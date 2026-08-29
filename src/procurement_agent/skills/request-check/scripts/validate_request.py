#!/usr/bin/env python3
"""Deterministic structural and provenance checks for a procurement draft."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from typing import Any


def validate_request(draft: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    required_paths = (
        ("item", "product_code"),
        ("item", "unit_price"),
        ("amount", "subtotal"),
        ("amount", "tax"),
        ("amount", "total"),
        ("delivery", "estimated_on"),
        ("applicant", "employee_id"),
        ("applicant", "department_code"),
        ("account", "account_code"),
    )
    for parent, child in required_paths:
        if parent not in draft or child not in draft[parent]:
            violations.append(f"missing:{parent}.{child}")

    amount = draft.get("amount", {})
    arithmetic_ok = False
    if all(key in amount for key in ("taxable_amount", "tax", "total")):
        arithmetic_ok = Decimal(str(amount["taxable_amount"])) + Decimal(str(amount["tax"])) == Decimal(
            str(amount["total"])
        )
        if not arithmetic_ok:
            violations.append("amount.total does not equal taxable_amount plus tax")

    calculated_by_ok = amount.get("calculated_by") == "request-check/scripts/calculate_request.py"
    if not calculated_by_ok:
        violations.append("amount is not sourced from request-check calculation script")

    evidence = list(draft.get("evidence_refs", []))
    evidence_ok = bool(evidence)
    if not evidence_ok:
        violations.append("evidence_refs is empty")

    return {
        "valid": not violations,
        "violations": violations,
        "checks": {
            "required_fields": not any(item.startswith("missing:") for item in violations),
            "arithmetic": arithmetic_ok,
            "calculation_provenance": calculated_by_ok,
            "evidence_present": evidence_ok,
        },
        "evidence_refs": evidence,
    }


def main() -> int:
    payload = json.load(sys.stdin)
    json.dump(validate_request(payload), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
