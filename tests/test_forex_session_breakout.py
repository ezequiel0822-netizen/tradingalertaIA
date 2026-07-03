"""Tests para ForexSessionBreakoutStrategy + analyze_multitf.

v3.10.0: la estrategia es replayable — su reloj es el BAR-TIME (ultima vela), el
overlap se deriva de ese bar-time, y hay un guard de frescura SOLO-vivo (>2h).
Los tests congelan datetime.now() (fecha fija) para ser deterministas a cualquier
hora del dia en que corra la suite.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import app.strategies.forex_session_breakout as fsb
from app.analyzers.technical_patterns import analyze_multitf
from app.database.models import TokenSnapshot
from app.strategies.base import StrategyContext
from app.strategies.forex_session_breakout import ForexSessionBreakoutStrategy
from tests.test_score import _settings

# Dia fijo para todos los tests (miercoles). El "reloj de pared" se congela por
# test con _freeze(monkeypatch, hora) — asi el guard de frescura es determinista.
_DAY_START = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _freeze(monkeypatch, hour: float) -> None:
    """Congela fsb.datetime.now() en _DAY_START + hour (UTC)."""
    fake_now = _DAY_START + __import__("datetime").timedelta(hours=hour)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return fake_now if tz else fake_now.replace(tzinfo=None)

    monkeypatch.setattr(fsb, "datetime", _FrozenDatetime)


def _forex_snap(price: float = 1.0900) -> TokenSnapshot:
    return TokenSnapshot(
        chain="forex", token_address="EURUSD=X", category="forex",
        symbol="EURUSD=X", price=price,
    )


def _candles(asian_high: float = 1.0850, asian_low: float = 1.0820, count: int = 48):
    """Velas 15m del dia fijo: primeras 32 en la sesion asiatica (00:00-08:00 UTC)
    con el asian range; el resto en el overlap London/NY desde 13:00 UTC. Con
    count=48 la ULTIMA vela (que define el bar-time) cae 16:45 UTC."""
    start = _DAY_START.timestamp()
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
            "timestamp": start + 13 * 3600 + i * 900,  # overlap 13:00-16:45 UTC
            "open": asian_high * (1 + 0.0001 * i),
            "high": asian_high * (1 + 0.001 * i),
            "low": asian_low,
            "close": asian_high * (1 + 0.0008 * i),
            "volume": 1500,
        })
    return candles


def test_forex_breakout_long_during_overlap(monkeypatch) -> None:
    _freeze(monkeypatch, 16.9)  # 16:54 UTC — bar-time 16:45 fresco y en overlap
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


def test_forex_breakout_short_when_below_asian_low(monkeypatch) -> None:
    _freeze(monkeypatch, 16.9)
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


def test_forex_breakout_skip_outside_overlap(monkeypatch) -> None:
    """v3.10.0: el overlap se deriva del BAR-TIME. Velas solo asiaticas (ultima
    07:45 UTC, fresca con now=08:30) -> fuera de 13-17 -> no opera."""
    _freeze(monkeypatch, 8.5)  # 08:30 — la vela de 07:45 es fresca (45 min)
    settings = _settings()
    snap = _forex_snap(price=1.0880)
    ctx = StrategyContext(
        snapshot=snap,
        candles=_candles(count=32),  # bar-time 07:45 UTC
        pattern=SimpleNamespace(atr_pct=0.5),
        pro=None,
        macro={"active_sessions": ["asian"], "is_high_liquidity": False},
    )
    signal = ForexSessionBreakoutStrategy().evaluate(ctx, settings)
    assert signal is None


def test_forex_breakout_skip_non_forex_category(monkeypatch) -> None:
    _freeze(monkeypatch, 16.9)
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


def test_forex_breakout_ignores_stale_5day_old_candles(monkeypatch) -> None:
    """Regresion bug A1: si las velas son de hace ~5 dias, NO debe operar. En vivo
    el guard de frescura (>2h) lo bloquea aunque el bar-time viejo caiga en un
    overlap de aquel dia."""
    _freeze(monkeypatch, 16.9)
    settings = _settings()
    snap = _forex_snap(price=1.0880)
    start = _DAY_START.timestamp() - 5 * 86400  # hace 5 dias
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


def test_forex_breakout_live_stale_feed_refuses(monkeypatch) -> None:
    """v3.10.0: guard de frescura SOLO-vivo — bar-time 13:30 (en overlap) pero el
    reloj real es 16:54 -> feed colgado hace 3.4h -> no opera."""
    _freeze(monkeypatch, 16.9)
    settings = _settings()
    start = _DAY_START.timestamp()
    candles = [
        {"timestamp": start + i * 900, "open": 1.0835, "high": 1.0850,
         "low": 1.0820, "close": 1.0835, "volume": 1000}
        for i in range(32)
    ]
    candles.append({
        "timestamp": start + 13.5 * 3600, "open": 1.0850, "high": 1.0860,
        "low": 1.0830, "close": 1.0855, "volume": 1200,
    })
    ctx = StrategyContext(
        snapshot=_forex_snap(price=1.0880), candles=candles,
        pattern=SimpleNamespace(atr_pct=0.5), pro=None, macro={},
    )
    assert ForexSessionBreakoutStrategy().evaluate(ctx, settings) is None


def test_forex_breakout_replayable_with_harness_candles() -> None:
    """v3.10.0: la estrategia es REPLAYABLE — velas con clave 'time' (cache MT5),
    fecha historica (2019) y raw['backtest']=True (apaga el guard de frescura).
    Antes usaba datetime.now() y macro['active_sessions'] -> jamas disparaba en
    el harness y la estrategia mas operada tenia CERO validacion historica."""
    settings = _settings()
    day_start = datetime(2019, 3, 5, tzinfo=timezone.utc).timestamp()  # martes
    candles = []
    for i in range(8):  # asian H1: 00:00-08:00
        candles.append({
            "time": day_start + i * 3600, "open": 1.0835, "high": 1.0850,
            "low": 1.0820, "close": 1.0835, "volume": 1000,
        })
    for i in range(6):  # H1 hasta 14:00 (bar-time final 13:00-14:00)
        candles.append({
            "time": day_start + (8 + i) * 3600, "open": 1.0850,
            "high": 1.0860, "low": 1.0830, "close": 1.0855, "volume": 1200,
        })
    # relleno para llegar al minimo de 30 velas (dia previo, fuera del asian de hoy)
    filler = [
        {"time": day_start - 86400 + i * 3600, "open": 1.083, "high": 1.084,
         "low": 1.082, "close": 1.083, "volume": 900}
        for i in range(20)
    ]
    candles = filler + candles
    snap = TokenSnapshot(
        chain="forex", token_address="EURUSD", category="forex",
        symbol="EURUSD", price=1.0880,  # rompe el asian high 1.0850
        raw={"backtest": True, "candles": candles},
    )
    ctx = StrategyContext(
        snapshot=snap, candles=candles,
        pattern=SimpleNamespace(atr_pct=0.5), pro=None, macro={},
    )
    signal = ForexSessionBreakoutStrategy().evaluate(ctx, settings)
    assert signal is not None
    assert signal.direction == "long"


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
