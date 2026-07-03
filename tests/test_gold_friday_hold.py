"""Tests para gold_friday_hold — regla CONGELADA del gate §11 (harness-only).

La regla está pre-registrada en research/HIPOTESIS_2026-07-02.md; estos tests
fijan el contrato congelado (señal jueves UTC, long, stop 2xATR, sin TP, salida
por tiempo) y la SEGURIDAD: existe solo en el registry del harness, jamás en el
router vivo.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.backtest.replay_harness import default_strategy_registry
from app.database.models import TokenSnapshot
from app.strategies.base import StrategyContext
from app.strategies.gold_friday_hold import GoldFridayHoldStrategy
from app.strategies.strategy_router import StrategyRouter
from tests.test_score import _settings


def _gold_ctx(bar_date: datetime, price: float = 2000.0, category: str = "gold"):
    """Contexto estilo harness: velas D1 con clave 'time', la ultima = bar_date."""
    day = bar_date.timestamp()
    candles = [
        {"time": day - (30 - i) * 86400, "open": price, "high": price * 1.01,
         "low": price * 0.99, "close": price, "volume": 1000}
        for i in range(30)
    ]
    candles.append({"time": day, "open": price, "high": price * 1.01,
                    "low": price * 0.99, "close": price, "volume": 1000})
    snap = TokenSnapshot(
        chain="commodity", token_address="XAUUSD", category=category,
        symbol="XAUUSD", price=price, raw={"backtest": True},
    )
    return StrategyContext(
        snapshot=snap, candles=candles,
        pattern=SimpleNamespace(atr_pct=1.2), pro=None, macro={},
    )


def test_signals_long_on_thursday() -> None:
    thursday = datetime(2019, 3, 7, tzinfo=timezone.utc)
    assert thursday.weekday() == 3  # jueves
    sig = GoldFridayHoldStrategy().evaluate(_gold_ctx(thursday), _settings())
    assert sig is not None
    assert sig.direction == "long"
    assert sig.targets == []  # sin TP: la salida es por tiempo
    assert sig.time_horizon_hours == 24  # D1 -> 1 barra
    assert abs(sig.stop - 2000.0 * (1 - 2.0 * 1.2 / 100)) < 1e-6  # 2xATR congelado


def test_no_signal_on_other_weekdays() -> None:
    strat = GoldFridayHoldStrategy()
    settings = _settings()
    # lunes 2019-03-04, martes 05, miercoles 06, viernes 08, sabado 09, domingo 10
    for day in (4, 5, 6, 8, 9, 10):
        date = datetime(2019, 3, day, tzinfo=timezone.utc)
        assert date.weekday() != 3
        assert strat.evaluate(_gold_ctx(date), settings) is None


def test_no_signal_for_non_gold_category() -> None:
    thursday = datetime(2019, 3, 7, tzinfo=timezone.utc)
    ctx = _gold_ctx(thursday, category="forex")
    assert GoldFridayHoldStrategy().evaluate(ctx, _settings()) is None


def test_registered_in_harness_but_never_in_live_router() -> None:
    """SEGURIDAD: la regla congelada existe SOLO en el harness. El router vivo no
    la conoce -> no puede abrir paper trades ni ordenes por mas flags que haya."""
    assert "gold_friday_hold" in default_strategy_registry()
    router = StrategyRouter(_settings())
    assert all(s.name != "gold_friday_hold" for s in router.strategies)
