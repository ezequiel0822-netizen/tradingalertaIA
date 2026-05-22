"""v2.6.0 Phase 5.5 Bloque B — scalping_breakout strategy.

Verifica que detecta breakouts bullish/bearish correctamente, no emite signal
en rango tranquilo, y respeta el cooldown post-signal.
"""

from __future__ import annotations

from app.strategies.scalping_breakout import (
    ScalpingBreakoutStrategy,
    ScalpingContext,
)
from tests.test_score import _settings


def _candles(highs_lows: list[tuple[float, float]]) -> list[dict]:
    """Construye lista de candles con high/low/close en formato dict."""
    return [
        {"high": h, "low": l, "close": (h + l) / 2, "time": idx}
        for idx, (h, l) in enumerate(highs_lows)
    ]


def test_detects_long_breakout_above_range() -> None:
    """Si current_ask > range_high con buffer, emite LONG."""
    # Rango estable 1.1000-1.1010 las primeras 10 velas, vela 11 (actual) con ask alto.
    candles = _candles([(1.1010, 1.1000) for _ in range(10)] + [(1.1020, 1.1015)])
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=candles,
        current_ask=1.1020,  # > 1.1010 * 1.00005 = 1.10105
        current_bid=1.1019,
        pip_size=0.0001,
    )
    signal = ScalpingBreakoutStrategy().evaluate(ctx, _settings())
    assert signal is not None
    assert signal.direction == "long"
    assert signal.entry == 1.102
    # SL = entry - 8 pips = 1.1020 - 0.0008 = 1.1012
    assert abs(signal.stop_loss - 1.1012) < 1e-8
    # TP = entry + 12 pips = 1.1020 + 0.0012 = 1.1032
    assert abs(signal.take_profit - 1.1032) < 1e-8


def test_detects_short_breakout_below_range() -> None:
    """Si current_bid < range_low, emite SHORT."""
    candles = _candles([(1.1010, 1.1000) for _ in range(10)] + [(1.1005, 1.0989)])
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=candles,
        current_ask=1.0991,
        current_bid=1.0989,  # < 1.1000 * 0.99995 = 1.09994
        pip_size=0.0001,
    )
    signal = ScalpingBreakoutStrategy().evaluate(ctx, _settings())
    assert signal is not None
    assert signal.direction == "short"
    assert signal.entry == 1.0989
    # SL = entry + 8 pips = 1.0997
    assert abs(signal.stop_loss - 1.0997) < 1e-8
    # TP = entry - 12 pips = 1.0977
    assert abs(signal.take_profit - 1.0977) < 1e-8


def test_no_signal_inside_range() -> None:
    """Price dentro del rango: no emite signal."""
    candles = _candles([(1.1010, 1.1000) for _ in range(10)] + [(1.1008, 1.1003)])
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=candles,
        current_ask=1.1007,  # dentro de 1.1000-1.1010
        current_bid=1.1005,
        pip_size=0.0001,
    )
    signal = ScalpingBreakoutStrategy().evaluate(ctx, _settings())
    assert signal is None


def test_cooldown_blocks_reentry() -> None:
    """Si last_signal_ts fue hace <60s, no emite signal aunque hay breakout."""
    candles = _candles([(1.1010, 1.1000) for _ in range(10)] + [(1.1020, 1.1015)])
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=candles,
        current_ask=1.1020,
        current_bid=1.1019,
        pip_size=0.0001,
        last_signal_ts=100.0,  # signal hace 30s
    )
    signal = ScalpingBreakoutStrategy().evaluate(ctx, _settings(), now_ts=130.0)
    assert signal is None

    # Mas alla del cooldown: si emite.
    signal2 = ScalpingBreakoutStrategy().evaluate(ctx, _settings(), now_ts=200.0)
    assert signal2 is not None
    assert signal2.direction == "long"


def test_returns_none_if_insufficient_candles() -> None:
    """Menos de lookback+1 velas → no evaluable."""
    candles = _candles([(1.1010, 1.1000) for _ in range(5)])
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=candles,
        current_ask=1.1020,
        current_bid=1.1019,
        pip_size=0.0001,
    )
    signal = ScalpingBreakoutStrategy().evaluate(ctx, _settings())
    assert signal is None


def test_returns_none_with_invalid_pip_size() -> None:
    """pip_size=0 (datos malos del symbol_info) no debe crashear."""
    candles = _candles([(1.1010, 1.1000) for _ in range(10)] + [(1.1020, 1.1015)])
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=candles,
        current_ask=1.1020,
        current_bid=1.1019,
        pip_size=0.0,
    )
    signal = ScalpingBreakoutStrategy().evaluate(ctx, _settings())
    assert signal is None
