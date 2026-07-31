"""Canonical two-place money helpers.

JSON numbers are binary floats. Till totals, price books and receivables must
never round-trip through one. Callers store and exchange money as Decimal or as
a two-place decimal string ("150.00"), never as float.

Every money() / format_money() path uses ROUND_HALF_UP to a cent so API
payloads, printed receipts and terminal screens agree.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

ZERO = Decimal("0.00")
PENNY = Decimal("0.01")
CENTI = Decimal("0.01")


def money(value: Any) -> Decimal:
    """Coerce to a two-place Decimal, never via float."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        amount = value
    else:
        # str() first: Decimal(float) inherits binary error.
        amount = Decimal(str(value))
    return amount.quantize(PENNY, rounding=ROUND_HALF_UP)


def format_money(value: Any) -> str | None:
    """Serialize money as a fixed two-place string, or None when absent."""
    if value is None or value == "":
        return None
    return format(money(value), "f")


def format_decimal(value: Any, *, places: int = 2) -> str | None:
    """Serialize a decimal to a fixed number of places (default 2).

    Used for terminal-facing quantities and similar non-money figures where the
    product standard is two decimal places. Clinical dose fields should not use
    this helper.
    """
    if value is None or value == "":
        return None
    quant = Decimal("1").scaleb(-places)
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(amount.quantize(quant, rounding=ROUND_HALF_UP), "f")
