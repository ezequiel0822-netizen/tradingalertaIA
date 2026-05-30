"""v2.7.0 — cost model: el realized-R debe descontar spread+comisión (round-trip)
para no promover a LIVE estrategias positivas en bruto pero negativas netas.
"""
from app.learning.trade_outcomes import (
    build_strategy_performance,
    r_multiple,
    realized_return_pct,
)


def _trade(entry, latest, ostop, direction="long", category="forex", strategy="breakout"):
    return {
        "entry_price": entry,
        "latest_price": latest,
        "original_stop_loss": ostop,
        "direction": direction,
        "status": "stopped_simulated",
        "closed_at": "2026-05-29T00:00:00+00:00",
        "strategy_name": strategy,
        "category": category,
        "partial_closed": 0,
        "take_profit_1": None,
    }


def test_cost_subtracts_from_winner() -> None:
    t = _trade(100.0, 101.0, 98.0)  # bruto +1.0%
    assert realized_return_pct(t, cost_pct=0.0) == 1.0
    assert abs(realized_return_pct(t, cost_pct=0.02) - 0.98) < 1e-9


def test_cost_subtracts_from_loser_too() -> None:
    t = _trade(100.0, 99.0, 98.0)  # bruto -1.0% (el costo empeora aún más)
    assert abs(realized_return_pct(t, cost_pct=0.02) - (-1.02)) < 1e-9


def test_cost_subtracts_on_short() -> None:
    t = _trade(100.0, 99.0, 102.0, direction="short")  # short, precio baja → bruto +1.0%
    assert abs(realized_return_pct(t, cost_pct=0.05) - 0.95) < 1e-9


def test_cost_default_zero_is_backward_compatible() -> None:
    t = _trade(100.0, 101.0, 98.0)
    assert realized_return_pct(t) == 1.0
    assert r_multiple(t) == 0.5  # 1.0% / 2.0% risk


def test_r_multiple_net_lower_than_gross() -> None:
    t = _trade(100.0, 101.0, 98.0)
    assert r_multiple(t, cost_pct=0.0) == 0.5
    assert r_multiple(t, cost_pct=0.02) < 0.5


def test_build_strategy_performance_applies_cost() -> None:
    trades = [_trade(100.0, 101.0, 98.0, category="forex") for _ in range(3)]
    gross = build_strategy_performance(trades)
    net = build_strategy_performance(trades, cost_pct_by_category={"forex": 0.5})
    assert gross[0].avg_r > net[0].avg_r
    # sin mapa de costos → bruto (backward compat)
    assert build_strategy_performance(trades)[0].avg_r == gross[0].avg_r


def test_cost_flips_marginal_strategy_negative() -> None:
    # bruto apenas positivo (+0.1% sobre 1% de riesgo = +0.1R), costo 0.2% → negativo.
    # Este es justo el caso que el gate necesita ver para NO promover a LIVE.
    trades = [_trade(100.0, 100.1, 99.0, category="forex") for _ in range(5)]
    gross = build_strategy_performance(trades)[0]
    net = build_strategy_performance(trades, cost_pct_by_category={"forex": 0.2})[0]
    assert gross.avg_r > 0
    assert net.avg_r < 0
