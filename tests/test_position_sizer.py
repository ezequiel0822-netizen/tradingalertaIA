from app.risk.position_sizer import calculate_position_size


def test_long_position_sizing_exact_math() -> None:
    # entry=100, stop=95, balance=10000, risk=1%
    # risk_amount = 100, per_unit_risk = 5, size_units = 20, size_notional = 2000
    result = calculate_position_size(
        entry=100.0, stop=95.0, account_balance=10000.0, risk_pct=1.0, direction="long"
    )
    assert result.invalid_reason is None
    assert abs(result.risk_amount - 100.0) < 0.001
    assert abs(result.size_units - 20.0) < 0.001
    assert abs(result.size_notional - 2000.0) < 0.001
    assert abs(result.risk_pct_actual - 1.0) < 0.001


def test_short_position_sizing_exact_math() -> None:
    # short: entry=100, stop=105 (arriba), balance=10000, risk=2%
    # risk_amount = 200, per_unit_risk = 5, size_units = 40, size_notional = 4000
    result = calculate_position_size(
        entry=100.0, stop=105.0, account_balance=10000.0, risk_pct=2.0, direction="short"
    )
    assert result.invalid_reason is None
    assert abs(result.size_units - 40.0) < 0.001
    assert abs(result.size_notional - 4000.0) < 0.001


def test_zero_per_unit_risk_returns_invalid() -> None:
    # long con stop == entry → per_unit_risk = 0
    result = calculate_position_size(
        entry=100.0, stop=100.0, account_balance=10000.0, risk_pct=1.0, direction="long"
    )
    assert result.invalid_reason is not None
    assert result.size_units == 0


def test_balance_zero_returns_invalid() -> None:
    result = calculate_position_size(
        entry=100.0, stop=95.0, account_balance=0.0, risk_pct=1.0
    )
    assert result.invalid_reason is not None
    assert result.size_notional == 0
