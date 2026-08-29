# Synthetic calculation rules

Version: `1.0.0`
Confirmed: `2026-08-28`

- Use `Decimal` created from strings. Binary floating point is prohibited.
- `subtotal = quantity * unit_price`.
- `discount = round(subtotal * discount_rate)`.
- `taxable_amount = subtotal - discount`.
- `tax = round(taxable_amount * tax_rate)`.
- `total = taxable_amount + tax`.
- JPY values use a rounding unit of `1` and `ROUND_HALF_UP` in this PoC.
- Negative quantity, price, tax rate, or discount rate is invalid.
- A discount rate greater than `1` is invalid.
