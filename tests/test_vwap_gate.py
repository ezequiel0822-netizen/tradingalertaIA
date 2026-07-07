"""Tests del VWAP gate vivo (v3.12.0) + flujo VWAP en el backtest harness.

El gate baja a paper un trade que pelea el VWAP SEMANAL del simbolo (long con
precio claramente BAJO / short claramente SOBRE, umbral vwap_gate_min_dist_pct).
Mismo molde que test_regime_gate: _StubJob bindea _vwap_gate sin construir el
TradingAlertJob completo; _d1_candles_for_regime se sobrescribe con velas canned.
Opt-in OFF, soft-fail, solo forex/gold, downward-only.
"""

from dataclasses import replace
from datetime import datetime, timezone

from app.scheduler.jobs import TradingAlertJob
from tests.test_score import _settings

_DAY = 86_400


def _epoch(year, month, day):
    return datetime(year, month, day, tzinfo=timezone.utc).timestamp()


def _week_candles(closes: list[float], volume: float = 1000.0) -> list[dict]:
    """Velas D1 consecutivas desde el lunes 2026-06-15 (misma semana ISO),
    con hl pegados al close (typical == close) para calcular VWAP a mano."""
    monday = _epoch(2026, 6, 15)
    return [
        {"time": monday + i * _DAY, "open": c, "high": c, "low": c,
         "close": c, "volume": volume}
        for i, c in enumerate(closes)
    ]


class _StubJob:
    def __init__(self, settings, candles) -> None:
        self.settings = settings
        self._candles = candles

    _vwap_gate = TradingAlertJob._vwap_gate

    def _d1_candles_for_regime(self, mt5_symbol):
        return self._candles


def _trade(direction: str, category: str = "forex", symbol: str = "EURUSD=X") -> dict:
    return {"symbol": symbol, "direction": direction, "category": category}


# closes Mon/Tue/Wed: VWAP=(100+100+95)/3=98.33 -> Wed 95 esta -3.39% (bajo)
_PRICE_BELOW = _week_candles([100.0, 100.0, 95.0])
# VWAP=(100+100+105)/3=101.67 -> Wed 105 esta +3.28% (sobre)
_PRICE_ABOVE = _week_candles([100.0, 100.0, 105.0])
# Wed 100.2 vs VWAP 100.07 -> +0.13%, dentro del umbral 0.5 -> no pelea
_PRICE_NEAR = _week_candles([100.0, 100.0, 100.2])


def test_gate_off_allows_everything() -> None:
    job = _StubJob(replace(_settings(), enable_vwap_gate=False), _PRICE_BELOW)
    assert job._vwap_gate(_trade("long")) is True  # pelea el VWAP pero gate OFF


def test_long_below_weekly_vwap_goes_to_paper() -> None:
    job = _StubJob(replace(_settings(), enable_vwap_gate=True), _PRICE_BELOW)
    assert job._vwap_gate(_trade("long")) is False   # long bajo VWAP -> paper
    assert job._vwap_gate(_trade("short")) is True   # short alineado -> permite


def test_short_above_weekly_vwap_goes_to_paper() -> None:
    job = _StubJob(replace(_settings(), enable_vwap_gate=True), _PRICE_ABOVE)
    assert job._vwap_gate(_trade("short")) is False  # short sobre VWAP -> paper
    assert job._vwap_gate(_trade("long")) is True    # long alineado -> permite


def test_within_threshold_allows_both_sides() -> None:
    job = _StubJob(replace(_settings(), enable_vwap_gate=True), _PRICE_NEAR)
    assert job._vwap_gate(_trade("long")) is True
    assert job._vwap_gate(_trade("short")) is True


def test_threshold_is_configurable() -> None:
    # Con umbral 0.05 el +0.13% de _PRICE_NEAR SI pelea para un short.
    settings = replace(
        _settings(), enable_vwap_gate=True, vwap_gate_min_dist_pct=0.05
    )
    job = _StubJob(settings, _PRICE_NEAR)
    assert job._vwap_gate(_trade("short")) is False
    assert job._vwap_gate(_trade("long")) is True


def test_no_volume_soft_allows() -> None:
    # Sin volumen (VWAP=None) el gate NO puede opinar -> permite (soft-fail).
    job = _StubJob(
        replace(_settings(), enable_vwap_gate=True),
        _week_candles([100.0, 100.0, 95.0], volume=0.0),
    )
    assert job._vwap_gate(_trade("long")) is True


def test_single_bar_week_soft_allows() -> None:
    # Lunes (1 sola barra en la semana): VWAP degenerado -> permite.
    job = _StubJob(
        replace(_settings(), enable_vwap_gate=True), _week_candles([95.0])
    )
    assert job._vwap_gate(_trade("long")) is True


def test_empty_cache_soft_allows() -> None:
    job = _StubJob(replace(_settings(), enable_vwap_gate=True), [])
    assert job._vwap_gate(_trade("long")) is True


def test_non_demo_category_allows() -> None:
    job = _StubJob(replace(_settings(), enable_vwap_gate=True), _PRICE_BELOW)
    # acciones no ejecutan a demo de todos modos
    assert job._vwap_gate(_trade("long", category="stock", symbol="AAPL")) is True


def test_exception_soft_allows() -> None:
    class _Boom(_StubJob):
        def _d1_candles_for_regime(self, mt5_symbol):
            raise RuntimeError("cache roto")

    job = _Boom(replace(_settings(), enable_vwap_gate=True), [])
    assert job._vwap_gate(_trade("long")) is True


# --- harness: el contexto del backtest recibe VWAP sin look-ahead ------------


def _d1_series(n: int = 40) -> list[dict]:
    monday = _epoch(2026, 5, 4)  # lunes; n dias consecutivos
    return [
        {"time": monday + i * _DAY, "open": 100 + i * 0.1,
         "high": 100 + i * 0.1 + 0.5, "low": 100 + i * 0.1 - 0.5,
         "close": 100 + i * 0.1, "volume": 500.0}
        for i in range(n)
    ]


def test_backtest_context_carries_vwap_fields() -> None:
    from app.backtest.context_builder import build_context

    candles = _d1_series()
    ctx = build_context(candles, len(candles) - 1, symbol="EURUSD", category="forex")
    assert ctx.pattern.vwap_week_dist_pct is not None
    assert ctx.pattern.vwap_position in {"above", "below", "at"}


def test_backtest_context_vwap_no_lookahead() -> None:
    # Canario: mutar una barra DESPUES de N no puede cambiar el VWAP en N.
    from app.backtest.context_builder import build_context

    candles = _d1_series()
    n = 30
    before = build_context(candles, n, symbol="EURUSD", category="forex")
    candles[n + 1]["close"] = 9_999.0
    candles[n + 1]["volume"] = 9_999_999.0
    after = build_context(candles, n, symbol="EURUSD", category="forex")
    assert before.pattern.vwap == after.pattern.vwap
    assert before.pattern.vwap_week_dist_pct == after.pattern.vwap_week_dist_pct
