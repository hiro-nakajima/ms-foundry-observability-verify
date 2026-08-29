---
name: request-check
description: Validate a synthetic procurement request and deterministically calculate subtotal, discount, taxable amount, tax, and total. Use before presenting any application draft.
license: MIT
compatibility: Python 3.13 or 3.14; scripts are allowlisted and operate on synthetic JSON only.
metadata:
  author: foundry-procurement-poc
  version: "1.0.0"
allowed-tools: run_skill_script
---

# Request Check

Use this skill after product code, unit price, quantity, applicant, department,
account code, and delivery estimate have been obtained from structured tools.

1. Run `scripts/calculate_request.py` with the structured input schema below.
2. Copy every amount from the script output without modification.
3. Assemble the application draft while preserving all evidence references.
4. Run `scripts/validate_request.py` on the assembled draft.
5. Present the draft only when validation is `valid: true`.

## Calculation input

```json
{
  "quantity": 3,
  "unit_price": "180000",
  "tax_rate": "0.10",
  "discount_rate": "0",
  "rounding_mode": "ROUND_HALF_UP",
  "rounding_unit": "1"
}
```

## Prohibitions

- Do not infer a product code, price, account code, or delivery date.
- Do not replace script output with mental arithmetic or model-generated values.
- Do not execute scripts outside this skill's `scripts/` directory.
- Do not include hidden reasoning or chain-of-thought in output or trace data.
