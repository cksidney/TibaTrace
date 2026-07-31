from decimal import Decimal

from apps.core.money import format_decimal, format_money, money


def test_money_quantizes_half_up():
    assert money("10.005") == Decimal("10.01")
    assert money("10.004") == Decimal("10.00")
    assert money(None) == Decimal("0.00")


def test_format_money_always_two_places():
    assert format_money("150") == "150.00"
    assert format_money("150.1") == "150.10"
    assert format_money("150.999") == "151.00"
    assert format_money(None) is None


def test_format_decimal_two_places():
    assert format_decimal("1.0000", places=2) == "1.00"
    assert format_decimal("30", places=2) == "30.00"
