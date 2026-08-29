#!/usr/bin/env python3
"""Deterministic Decimal calculation entrypoint for the request-check skill."""

from __future__ import annotations

import json
import sys
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP
from typing import Any


ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_DOWN": ROUND_DOWN,
}


def _decimal(value: str | int | Decimal, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except Exception as exc:  # Decimal raises several input-specific exceptions.
        raise ValueError(f"{field} must be a decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def calculate_request(
    *,
    quantity: int,
    unit_price: str,
    tax_rate: str,
    discount_rate: str = "0",
    rounding_mode: str = "ROUND_HALF_UP",
    rounding_unit: str = "1",
) -> dict[str, Any]:
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    price = _decimal(unit_price, "unit_price")
    tax_rate_decimal = _decimal(tax_rate, "tax_rate")
    discount_rate_decimal = _decimal(discount_rate, "discount_rate")
    unit = _decimal(rounding_unit, "rounding_unit")
    if price < 0 or tax_rate_decimal < 0 or discount_rate_decimal < 0:
        raise ValueError("monetary values and rates must not be negative")
    if discount_rate_decimal > 1:
        raise ValueError("discount_rate must be at most 1")
    if unit <= 0:
        raise ValueError("rounding_unit must be positive")
    try:
        rounding = ROUNDING_MODES[rounding_mode]
    except KeyError as exc:
        raise ValueError(f"unsupported rounding_mode: {rounding_mode}") from exc

    subtotal = (Decimal(quantity) * price).quantize(unit, rounding=rounding)
    discount = (subtotal * discount_rate_decimal).quantize(unit, rounding=rounding)
    taxable_amount = (subtotal - discount).quantize(unit, rounding=rounding)
    tax = (taxable_amount * tax_rate_decimal).quantize(unit, rounding=rounding)
    total = (taxable_amount + tax).quantize(unit, rounding=rounding)

    return {
        "currency": "JPY",
        "quantity": quantity,
        "unit_price": str(price),
        "subtotal": str(subtotal),
        "discount": str(discount),
        "taxable_amount": str(taxable_amount),
        "tax": str(tax),
        "total": str(total),
        "tax_rate": str(tax_rate_decimal),
        "discount_rate": str(discount_rate_decimal),
        "rounding_mode": rounding_mode,
        "calculated_by": "request-check/scripts/calculate_request.py",
    }


def main() -> int:
    payload = json.load(sys.stdin)
    result = calculate_request(**payload)
    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
