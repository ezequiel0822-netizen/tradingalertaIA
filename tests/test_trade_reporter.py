from app.alerts.trade_reporter import format_trade_closed, format_trade_opened
from app.database.models import TokenSnapshot
from app.risk.position_sizer import PositionSizing
from app.strategies.base import StrategySignal


def test_format_trade_opened_long_contains_all_fields() -> None:
    snap = TokenSnapshot(
        chain="forex", token_address="EURUSD=X", category="forex",
        symbol="EURUSD=X", price=1.0850,
    )
    sig = StrategySignal(
        strategy_name="breakout", direction="long",
        entry=1.0850, stop=1.0820, targets=[1.0890, 1.0950],
        confidence=78, reasoning=["Volumen 2.5x", "ATR 3.0%"],
        time_horizon_hours=24,
    )
    sizing = PositionSizing(size_notional=5000.0, size_units=4608.3,
                            risk_amount=100.0, risk_pct_actual=1.0)
    msg = format_trade_opened(snap, sig, sizing)
    assert "EURUSD=X" in msg
    assert "breakout" in msg
    assert "1.085" in msg
    assert "Simulado" in msg
    assert "🟢" in msg


def test_format_trade_opened_short_uses_red_emoji() -> None:
    snap = TokenSnapshot(
        chain="forex", token_address="USDJPY=X", category="forex",
        symbol="USDJPY=X", price=150.0,
    )
    sig = StrategySignal(
        strategy_name="mean_reversion", direction="short",
        entry=150.0, stop=151.5, targets=[148.5, 147.0],
        confidence=65, reasoning=["RSI 79"], time_horizon_hours=6,
    )
    sizing = PositionSizing(size_notional=3000.0, size_units=20.0,
                            risk_amount=30.0, risk_pct_actual=0.6)
    msg = format_trade_opened(snap, sig, sizing)
    assert "🔴" in msg
    assert "short" in msg


def test_format_trade_closed_includes_pnl_and_strategy() -> None:
    row = {
        "symbol": "NVDA", "direction": "long",
        "strategy_name": "momentum", "mfe_pct": 4.2, "mae_pct": -1.1,
    }
    msg = format_trade_closed(row, "target_2_simulated", pnl_pct=4.0)
    assert "NVDA" in msg
    assert "momentum" in msg
    assert "+4.00%" in msg
    assert "🟢" in msg
