"""Tests del regime gate vivo (v3.8.0).

Baja a paper un trade que va CONTRA el regimen D1 del simbolo (long en 'down' /
short en 'up'); aligned / 'flat' / sin historia suficiente -> permite. Opt-in OFF,
soft-fail, solo forex/gold. Se usa _StubJob (bindea _regime_gate sin construir el
TradingAlertJob completo); _d1_candles_for_regime se sobrescribe con velas canned.
"""

from dataclasses import replace

from app.scheduler.jobs import TradingAlertJob
from tests.test_score import _settings

_DAY = 86_400


def _candles(closes: list[float]) -> list[dict]:
    return [{"time": i * _DAY, "open": c, "high": c + 0.1, "low": c - 0.1,
             "close": c, "volume": 100} for i, c in enumerate(closes)]


_RISING = _candles([100 + i * 0.5 for i in range(270)])   # regimen UP
_FALLING = _candles([300 - i * 0.5 for i in range(270)])  # regimen DOWN


class _StubJob:
    def __init__(self, settings, candles) -> None:
        self.settings = settings
        self._candles = candles

    _regime_gate = TradingAlertJob._regime_gate

    def _d1_candles_for_regime(self, mt5_symbol):
        return self._candles


def _trade(direction: str, category: str = "forex", symbol: str = "EURUSD=X") -> dict:
    return {"symbol": symbol, "direction": direction, "category": category}


def test_gate_off_allows_everything() -> None:
    job = _StubJob(replace(_settings(), enable_regime_gate=False), _FALLING)
    assert job._regime_gate(_trade("long")) is True  # contra-regimen pero gate OFF


def test_long_against_down_regime_goes_to_paper() -> None:
    job = _StubJob(replace(_settings(), enable_regime_gate=True), _FALLING)
    assert job._regime_gate(_trade("long")) is False   # long vs DOWN -> paper
    assert job._regime_gate(_trade("short")) is True    # short alineado -> permite


def test_short_against_up_regime_goes_to_paper() -> None:
    job = _StubJob(replace(_settings(), enable_regime_gate=True), _RISING)
    assert job._regime_gate(_trade("short")) is False  # short vs UP -> paper
    assert job._regime_gate(_trade("long")) is True     # long alineado -> permite


def test_insufficient_history_allows() -> None:
    job = _StubJob(replace(_settings(), enable_regime_gate=True), _candles([100.0] * 50))
    assert job._regime_gate(_trade("long")) is True  # < SMA200+slope -> soft, permite


def test_non_demo_category_allows() -> None:
    job = _StubJob(replace(_settings(), enable_regime_gate=True), _FALLING)
    # acciones/memecoins no ejecutan a demo de todos modos
    assert job._regime_gate(_trade("long", category="stock", symbol="AAPL")) is True


def test_gold_symbol_maps_and_gates() -> None:
    job = _StubJob(replace(_settings(), enable_regime_gate=True), _FALLING)
    # GC=F -> XAUUSD via yahoo_to_mt5; long contra regimen down -> paper
    assert job._regime_gate(_trade("long", category="gold", symbol="GC=F")) is False


def test_d1_cache_freshness_guard_drops_stale() -> None:
    """M1: el guard descarta el cache D1 viejo (>10 dias) -> [] (gate soft-allow),
    en vez de clasificar el regimen sobre data caduca. Cache fresco se mantiene."""
    import time

    class _Repo:
        def __init__(self, last_time: float) -> None:
            self._last = last_time

        def fetch_mt5_cache_window(self, sym, tf, a, b):
            return [{"time": self._last, "close": 1.0, "high": 1.0, "low": 1.0}]

    class _J:
        _d1_candles_for_regime = TradingAlertJob._d1_candles_for_regime

        def __init__(self, repo) -> None:
            self.repository = repo

    now = time.time()
    fresh = _J(_Repo(now - 2 * 86400))     # 2 dias -> se mantiene
    stale = _J(_Repo(now - 30 * 86400))    # 30 dias -> se descarta
    assert fresh._d1_candles_for_regime("EURUSD") != []
    assert stale._d1_candles_for_regime("EURUSD") == []
