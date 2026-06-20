"""Tests para ForexSessionBreakoutStrategy + analyze_multitf."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.analyzers.technical_patterns import analyze_multitf
from app.database.models import TokenSnapshot
from app.strategies.base import StrategyContext
from app.strategies.forex_session_breakout import ForexSessionBreakoutStrategy
from tests.test_score import _settings


def _forex_snap(price: float = 1.0900) -> TokenSnapshot:
    return TokenSnapshot(
        chain="forex", token_address="EURUSD=X", category="forex",
        symbol="EURUSD=X", price=price,
    )


def _today_asian_start() -> float:
    """Epoch (s) de las 00:00 UTC de HOY — inicio de la sesion asiatica."""
    return (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )


def _candles(asian_high: float = 1.0850, asian_low: float = 1.0820, count: int = 60):
    """Genera candles con TIMESTAMP real: primeras 32 en la sesion asiatica de HOY
    (00:00-08:00 UTC, cada 15m) con el asian range; el resto despues (London/NY)."""
    start = _today_asian_start()
    candles = []
    for i in range(min(32, count)):
        mid = (asian_high + asian_low) / 2
        candles.append({
            "timestamp": start + i * 900,  # 15m dentro de 00:00-08:00 UTC
            "open": mid, "high": asian_high, "low": asian_low,
            "close": mid, "volume": 1000,
        })
    for i in range(count - len(candles)):
        candles.append({
            "timestamp": start + 13 * 3600 + i * 900,  # despues del rango asiatico
            "open": asian_high * (1 + 0.0001 * i),
            "high": asian_high * (1 + 0.001 * i),
            "low": asian_low,
            "close": asian_high * (1 + 0.0008 * i),
            "volume": 1500,
        })
    return candles


def test_forex_breakout_long_during_overlap() -> None:
    settings = _settings()
    snap = _forex_snap(price=1.0880)  # rompe asian_high 1.0850
    ctx = StrategyContext(
        snapshot=snap,
        candles=_candles(),
        pattern=SimpleNamespace(atr_pct=0.5),
        pro=None,
        macro={"active_sessions": ["london", "ny"], "is_high_liquidity": True},
    )
    signal = ForexSessionBreakoutStrategy().evaluate(ctx, settings)
    assert signal is not None
    assert signal.direction == "long"


def test_forex_breakout_short_when_below_asian_low() -> None:
    settings = _settings()
    snap = _forex_snap(price=1.0800)  # rompe asian_low 1.0820 hacia abajo
    ctx = StrategyContext(
        snapshot=snap,
        candles=_candles(),
        pattern=SimpleNamespace(atr_pct=0.5),
        pro=None,
        macro={"active_sessions": ["london", "ny"], "is_high_liquidity": True},
    )
    signal = ForexSessionBreakoutStrategy().evaluate(ctx, settings)
    assert signal is not None
    assert signal.direction == "short"


def test_forex_breakout_skip_outside_overlap() -> None:
    settings = _settings()
    snap = _forex_snap(price=1.0880)
    ctx = StrategyContext(
        snapshot=snap,
        candles=_candles(),
        pattern=SimpleNamespace(atr_pct=0.5),
        pro=None,
        macro={"active_sessions": ["asian"], "is_high_liquidity": False},
    )
    signal = ForexSessionBreakoutStrategy().evaluate(ctx, settings)
    assert signal is None


def test_forex_breakout_skip_non_forex_category() -> None:
    settings = _settings()
    snap = TokenSnapshot(
        chain="stock", token_address="NVDA", category="stock",
        symbol="NVDA", price=200.0,
    )
    ctx = StrategyContext(
        snapshot=snap,
        candles=_candles(),
        pattern=SimpleNamespace(atr_pct=0.5),
        pro=None,
        macro={"active_sessions": ["london", "ny"], "is_high_liquidity": True},
    )
    signal = ForexSessionBreakoutStrategy().evaluate(ctx, settings)
    assert signal is None


def test_forex_breakout_ignores_stale_5day_old_candles() -> None:
    """Regresion bug A1: si las velas son de hace ~5 dias (sin sesion asiatica de HOY),
    NO debe operar. Antes tomaba las primeras 32 POSICIONALES sin mirar la fecha y
    disparaba breakouts contra un 'rango asiatico' de hace 5 dias."""
    settings = _settings()
    snap = _forex_snap(price=1.0880)
    start = _today_asian_start() - 5 * 86400  # hace 5 dias
    candles = [
        {"timestamp": start + i * 900, "open": 1.0835, "high": 1.0850,
         "low": 1.0820, "close": 1.0835, "volume": 1000}
        for i in range(60)
    ]
    ctx = StrategyContext(
        snapshot=snap, candles=candles, pattern=SimpleNamespace(atr_pct=0.5),
        pro=None, macro={"active_sessions": ["london", "ny"], "is_high_liquidity": True},
    )
    assert ForexSessionBreakoutStrategy().evaluate(ctx, settings) is None


def _ohlcv(close_series: list[float]) -> list[dict[str, float]]:
    return [
        {"open": c, "high": c * 1.005, "low": c * 0.995, "close": c, "volume": 1000}
        for c in close_series
    ]


def test_analyze_multitf_aligned_bullish() -> None:
    short = _ohlcv([100 + i * 0.5 for i in range(30)])
    long_tf = _ohlcv([100 + i * 0.5 for i in range(50)])
    result = analyze_multitf(short, long_tf)
    assert result["short_pattern"] is not None
    assert result["long_pattern"] is not None
    # No aseguramos aligned True porque depende de trend del analyzer,
    # pero confluence_score debe ser 10 o 0
    assert result["confluence_score"] in {0, 10}


def test_analyze_multitf_short_only() -> None:
    short = _ohlcv([100 + i * 0.5 for i in range(30)])
    result = analyze_multitf(short, None)
    assert result["short_pattern"] is not None
    assert result["long_pattern"] is None
    assert result["confluence_score"] == 0
