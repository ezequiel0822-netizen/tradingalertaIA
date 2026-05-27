"""v2.6.6 — scalping_mean_reversion strategy tests.

Verifica:
- LONG signal cuando bid <= BB_lower y RSI <= oversold.
- SHORT signal cuando ask >= BB_upper y RSI >= overbought.
- No signal cuando precio en medio del rango.
- No signal cuando BB toca pero RSI no extremo.
- Cooldown bloquea reentry.
- Insufficient candles → None.
- Mercado plano (std≈0) → None.
- pip_size inválido → None.
- Helpers _bollinger y _rsi correctos.
"""

from __future__ import annotations

from app.strategies.scalping_breakout import ScalpingContext
from app.strategies.scalping_mean_reversion import ScalpingMeanReversionStrategy
from tests.test_score import _settings


def _candles_long_setup() -> list[dict]:
    """20 velas: 19 closes a 1.1000, última close a 1.0980 (sharp dip).

    BB(20,2) sobre estos closes: mean=1.0999, std≈0.000436, lower≈1.099028.
    RSI(14) sobre últimas 15 closes: 13 diffs en cero, 1 diff de -0.0020 → RSI=0.
    """
    base = [
        {"high": 1.1002, "low": 1.0998, "close": 1.1000, "time": i}
        for i in range(19)
    ]
    base.append({"high": 1.0985, "low": 1.0975, "close": 1.0980, "time": 19})
    return base


def _candles_short_setup() -> list[dict]:
    """Mirror del LONG: última close salta a 1.1020 → BB upper tocado, RSI=100."""
    base = [
        {"high": 1.1002, "low": 1.0998, "close": 1.1000, "time": i}
        for i in range(19)
    ]
    base.append({"high": 1.1025, "low": 1.1015, "close": 1.1020, "time": 19})
    return base


def _candles_flat_market() -> list[dict]:
    """20 velas idénticas: std=0, BB collapses → strategy debe rechazar."""
    return [
        {"high": 1.1000, "low": 1.1000, "close": 1.1000, "time": i}
        for i in range(20)
    ]


def _candles_oscillating_no_extreme_rsi() -> list[dict]:
    """Closes oscilan +/-0.0002 alrededor de 1.1000 con dip pequeño al final.

    Da BB con bandwidth real (no plano), pero RSI mid-range (~30-50).
    Sirve para test "bid en BB lower pero RSI no oversold".
    """
    closes = []
    for i in range(18):
        # Alterna 1.1002, 1.0998
        closes.append(1.1002 if i % 2 == 0 else 1.0998)
    closes.extend([1.0985, 1.0985])  # leve dip al final
    return [
        {"high": c + 0.0001, "low": c - 0.0001, "close": c, "time": i}
        for i, c in enumerate(closes)
    ]


# ---------------- Signal detection ----------------


def test_long_signal_at_lower_band_with_oversold_rsi() -> None:
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=_candles_long_setup(),
        current_ask=1.0981,
        current_bid=1.0980,  # <= bb_lower ≈ 1.0990
        pip_size=0.0001,
    )
    signal = ScalpingMeanReversionStrategy().evaluate(ctx, _settings())
    assert signal is not None, "LONG mean-reversion debería disparar"
    assert signal.direction == "long"
    assert signal.strategy_name == "scalping_mean_reversion"
    # Entry = ask, SL = entry - 8 pips, TP = entry + 12 pips
    assert signal.entry == 1.0981
    assert abs(signal.stop_loss - (1.0981 - 0.0008)) < 1e-8
    assert abs(signal.take_profit - (1.0981 + 0.0012)) < 1e-8


def test_short_signal_at_upper_band_with_overbought_rsi() -> None:
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=_candles_short_setup(),
        current_ask=1.1021,  # >= bb_upper ≈ 1.1008
        current_bid=1.1020,
        pip_size=0.0001,
    )
    signal = ScalpingMeanReversionStrategy().evaluate(ctx, _settings())
    assert signal is not None, "SHORT mean-reversion debería disparar"
    assert signal.direction == "short"
    assert signal.entry == 1.102
    # Entry = bid, SL = entry + 8 pips, TP = entry - 12 pips
    assert abs(signal.stop_loss - (1.1020 + 0.0008)) < 1e-8
    assert abs(signal.take_profit - (1.1020 - 0.0012)) < 1e-8


def test_no_signal_when_price_inside_band() -> None:
    """Bid/ask en el medio del rango → ni LONG ni SHORT."""
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=_candles_long_setup(),
        current_ask=1.1000,  # mid-range
        current_bid=1.0999,
        pip_size=0.0001,
    )
    signal = ScalpingMeanReversionStrategy().evaluate(ctx, _settings())
    assert signal is None


def test_no_signal_when_band_touches_but_rsi_not_extreme() -> None:
    """Bid <= BB_lower pero RSI mid-range (no oversold) → None.

    Con el fixture oscilante, RSI termina ~30-40 (no <= 30). El bid touches
    BB lower pero la segunda condición AND falla.
    """
    settings = _settings()
    # Forzar RSI threshold más estricto para garantizar que falle el AND
    settings = type(settings)(**{**settings.__dict__, "scalping_mr_rsi_oversold": 10})
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=_candles_oscillating_no_extreme_rsi(),
        current_ask=1.0985,
        current_bid=1.0985,
        pip_size=0.0001,
    )
    signal = ScalpingMeanReversionStrategy().evaluate(ctx, settings)
    assert signal is None, "RSI no debería estar bajo 10 con este fixture"


def test_cooldown_blocks_reentry() -> None:
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=_candles_long_setup(),
        current_ask=1.0981,
        current_bid=1.0980,
        pip_size=0.0001,
        last_signal_ts=100.0,
    )
    # 30s después del último signal: cooldown activo
    blocked = ScalpingMeanReversionStrategy().evaluate(ctx, _settings(), now_ts=130.0)
    assert blocked is None
    # 200s después: cooldown expirado
    allowed = ScalpingMeanReversionStrategy().evaluate(ctx, _settings(), now_ts=300.0)
    assert allowed is not None
    assert allowed.direction == "long"


def test_returns_none_with_insufficient_candles() -> None:
    """Menos de max(bb_period, rsi_period+1) closes → None."""
    short_candles = _candles_long_setup()[:10]  # solo 10 velas
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=short_candles,
        current_ask=1.0981,
        current_bid=1.0980,
        pip_size=0.0001,
    )
    signal = ScalpingMeanReversionStrategy().evaluate(ctx, _settings())
    assert signal is None


def test_returns_none_in_flat_market() -> None:
    """Std≈0 → bandwidth < 1 pip → strategy rechaza (sin ventaja vs spread)."""
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=_candles_flat_market(),
        current_ask=1.1000,
        current_bid=1.1000,
        pip_size=0.0001,
    )
    signal = ScalpingMeanReversionStrategy().evaluate(ctx, _settings())
    assert signal is None


def test_returns_none_with_invalid_pip_size() -> None:
    ctx = ScalpingContext(
        symbol="EURUSD",
        candles_m1=_candles_long_setup(),
        current_ask=1.0981,
        current_bid=1.0980,
        pip_size=0.0,
    )
    signal = ScalpingMeanReversionStrategy().evaluate(ctx, _settings())
    assert signal is None


# ---------------- Helper math correctness ----------------


def test_bollinger_helper_correctness() -> None:
    """Closes constantes = mean=ese valor, std=0, upper=lower=mean."""
    closes = [1.1000] * 20
    bb = ScalpingMeanReversionStrategy._bollinger(closes, period=20, std_mult=2.0)
    assert bb is not None
    mean, upper, lower = bb
    assert mean == 1.1000
    assert upper == 1.1000
    assert lower == 1.1000


def test_bollinger_returns_none_with_short_window() -> None:
    closes = [1.1, 1.2, 1.3]
    assert ScalpingMeanReversionStrategy._bollinger(closes, period=10, std_mult=2.0) is None


def test_rsi_zero_when_only_losses() -> None:
    closes = [1.10, 1.09, 1.08, 1.07, 1.06, 1.05]  # monotonic down
    rsi = ScalpingMeanReversionStrategy._rsi(closes, period=5)
    assert rsi == 0.0


def test_rsi_hundred_when_only_gains() -> None:
    closes = [1.05, 1.06, 1.07, 1.08, 1.09, 1.10]  # monotonic up
    rsi = ScalpingMeanReversionStrategy._rsi(closes, period=5)
    assert rsi == 100.0


def test_rsi_returns_none_with_insufficient_data() -> None:
    closes = [1.1, 1.2]
    assert ScalpingMeanReversionStrategy._rsi(closes, period=14) is None
