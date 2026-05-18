from app.analyzers.trading_readiness import build_trade_readiness
from app.analyzers.technical_patterns import atr_pct_from_candles
from app.database.models import EstimateResult, TokenSnapshot
from tests.test_score import _settings


def _stock_snapshot(price: float = 100.0) -> TokenSnapshot:
    return TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        name="NVIDIA",
        price=price,
        liquidity_usd=1_000_000,
    )


def _high_conviction_estimate() -> EstimateResult:
    return EstimateResult(
        estimated_gain_pct=10,
        estimated_loss_pct=5,
        confidence=80,
        label="high",
        reasons=["IA Pro"],
        eligible_for_gain_alert=True,
    )


def _candles_with_atr(closes: list[float], range_pct: float) -> list[dict[str, float]]:
    candles = []
    for close in closes:
        half_range = close * range_pct / 100 / 2
        candles.append(
            {
                "close": close,
                "high": close + half_range,
                "low": close - half_range,
                "volume": 1000,
            }
        )
    return candles


def test_atr_based_stop_uses_atr_when_available() -> None:
    settings = _settings()
    closes = [100 + i * 0.1 for i in range(30)]
    candles = _candles_with_atr(closes, range_pct=3.0)
    atr_pct = atr_pct_from_candles(candles)
    assert atr_pct is not None and atr_pct > 0

    readiness = build_trade_readiness(
        _stock_snapshot(price=closes[-1]),
        _high_conviction_estimate(),
        85,
        "orange",
        settings,
        candles=candles,
    )

    # With ATR ~3% and stop multiplier 2.0, SL pct ~6% (clamped 3-12 stock).
    assert readiness.stop_loss is not None
    expected_stop_pct = (closes[-1] - readiness.stop_loss) / closes[-1] * 100
    assert 3 <= expected_stop_pct <= 12


def test_atr_disabled_falls_back_to_percent_estimate() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_atr_based_sltp": False})
    closes = [100.0] * 30
    candles = _candles_with_atr(closes, range_pct=10.0)

    readiness = build_trade_readiness(
        _stock_snapshot(price=100),
        _high_conviction_estimate(),
        85,
        "orange",
        settings,
        candles=candles,
    )

    # estimated_loss_pct=5, clamp [3,12] for stock = 5%. So stop = 100 * 0.95 = 95.0.
    assert readiness.stop_loss is not None
    assert abs(readiness.stop_loss - 95.0) < 0.01


def test_atr_clamped_to_stock_safety_range() -> None:
    settings = _settings()
    closes = [100.0 + i * 0.1 for i in range(30)]
    candles = _candles_with_atr(closes, range_pct=20.0)  # crazy volatility

    readiness = build_trade_readiness(
        _stock_snapshot(price=closes[-1]),
        _high_conviction_estimate(),
        85,
        "orange",
        settings,
        candles=candles,
    )

    # Even with huge ATR, stop should clamp at 12% max for stock.
    expected_stop_pct = (closes[-1] - readiness.stop_loss) / closes[-1] * 100
    assert expected_stop_pct <= 12.0001


def test_atr_falls_back_when_no_candles() -> None:
    settings = _settings()

    readiness = build_trade_readiness(
        _stock_snapshot(price=100),
        _high_conviction_estimate(),
        85,
        "orange",
        settings,
        candles=None,
    )

    # No candles → fallback to estimate-based formula (5% clamped).
    assert readiness.stop_loss is not None
    assert abs(readiness.stop_loss - 95.0) < 0.01
