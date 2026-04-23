from __future__ import annotations

from decimal import Decimal

from services.payment.service import calculate_final_amount


def test_calculate_final_amount_uses_decimal_math() -> None:
    result = calculate_final_amount(Decimal("99.99"), vip_level=2)

    assert result["discount_amount"] == Decimal("10.00")
    assert result["tax_amount"] == Decimal("7.20")
    assert result["final_amount"] == Decimal("97.19")


def test_bug_float_precision_exposes_unrounded_value(monkeypatch) -> None:
    monkeypatch.setenv("BUG_FLOAT_PRECISION", "true")

    result = calculate_final_amount(Decimal("99.99"), vip_level=2)

    assert result["final_amount"] != Decimal("97.19")
