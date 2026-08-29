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

    constraints = draft.get("request_constraints", {})
    requested_specs = {
        str(key).strip().casefold(): str(value).strip().casefold()
        for key, value in constraints.get("specifications", {}).items()
    }
    actual_specs = {
        str(key).strip().casefold(): str(value).strip().casefold()
        for key, value in draft.get("item", {}).get("specifications", {}).items()
    }
    unmet_specs = [
        f"{key}={value}"
        for key, value in requested_specs.items()
        if actual_specs.get(key) != value
    ]
    specifications_ok = not unmet_specs
    if not specifications_ok:
        violations.append(
            "constraint.specifications unmet: " + ", ".join(unmet_specs)
        )

    budget_limit = constraints.get("budget_limit")
    budget_ok = True
    if budget_limit is not None:
        try:
            budget_ok = Decimal(str(amount["total"])) <= Decimal(str(budget_limit))
        except (KeyError, ValueError, ArithmeticError):
            budget_ok = False
        if not budget_ok:
            violations.append(
                "constraint.budget_limit exceeded: "
                f"total={amount.get('total')} limit={budget_limit}"
            )

    delivery = draft.get("delivery", {})
    delivery_ok = delivery.get("meets_request") is True
    if not delivery_ok:
        violations.append(
            "constraint.requested_by unmet: "
            f"estimated_on={delivery.get('estimated_on')} "
            f"requested_by={delivery.get('requested_by')}"
        )

    return {
        "valid": not violations,
        "violations": violations,
        "checks": {
            "required_fields": not any(item.startswith("missing:") for item in violations),
            "arithmetic": arithmetic_ok,
            "calculation_provenance": calculated_by_ok,
            "evidence_present": evidence_ok,
            "specifications": specifications_ok,
            "budget_limit": budget_ok,
            "requested_by": delivery_ok,
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
