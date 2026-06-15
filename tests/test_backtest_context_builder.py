"""Tests del context_builder (v3.6.0, ESPEC §4 / §14).

El caso estrella es el CANARIO anti-look-ahead: un spike artificial en N+5 NO
puede cambiar el contexto en N. Ademas: ventanas terminan en N, campos sin
historia -> None (B11), completeness report, y paridad de campos con el
StrategyContext vivo.
"""

from dataclasses import fields

from app.backtest.context_builder import (
    build_context,
    context_completeness,
    context_field_names,
)
from app.strategies.base import StrategyContext

_DAY = 86_400


def _series(n: int) -> list[dict]:
    """Serie deterministica con tendencia + algo de textura, suficiente para
    que analyze_ohlcv produzca un pattern real (no 'insufficient')."""
    out = []
    for i in range(n):
        close = 100 + i * 0.1 + (i % 7) * 0.05
        out.append(
            {
                "time": i * _DAY,
                "open": close - 0.02,
                "high": close + 0.08,
                "low": close - 0.08,
                "close": close,
                "volume": 1000 + (i % 5) * 10,
            }
        )
    return out


# -- canario anti-look-ahead (el corazon de §14) -------------------------


def test_future_spike_does_not_change_context_at_n() -> None:
    base = _series(300)
    n = 200

    ctx_clean = build_context(base, n, symbol="EURUSD", category="forex")

    poisoned = [dict(c) for c in base]
    for key in ("open", "high", "low", "close"):
        poisoned[n + 5][key] = poisoned[n + 5][key] * 1000  # spike brutal en N+5
    ctx_poisoned = build_context(poisoned, n, symbol="EURUSD", category="forex")

    # El pattern es un dataclass: la igualdad es campo a campo.
    assert ctx_clean.pattern == ctx_poisoned.pattern
    assert ctx_clean.candles == ctx_poisoned.candles
    assert ctx_clean.snapshot.price == ctx_poisoned.snapshot.price


def test_window_ends_exactly_at_n() -> None:
    base = _series(300)
    n = 200
    ctx = build_context(base, n, symbol="EURUSD", category="forex")
    assert ctx.candles[-1]["time"] == base[n]["time"]
    assert all(c["time"] <= base[n]["time"] for c in ctx.candles)


def test_lookback_caps_window_length() -> None:
    base = _series(300)
    ctx = build_context(base, 290, symbol="EURUSD", category="forex", lookback=50)
    assert len(ctx.candles) == 50
    assert ctx.candles[-1]["time"] == base[290]["time"]


# -- B11: campos sin historia -> None/empty ------------------------------


def test_unhistorical_fields_are_none(  ) -> None:
    base = _series(300)
    ctx = build_context(base, 200, symbol="EURUSD", category="forex")
    assert ctx.pro is None
    assert ctx.news_label == "no_recent_news"
    assert ctx.news_score == 0
    assert ctx.macro == {}


# -- completeness report --------------------------------------------------


def test_completeness_marks_missing_informational_fields() -> None:
    base = _series(300)
    ctx = build_context(base, 200, symbol="EURUSD", category="forex")
    report = context_completeness(ctx)
    # price + candles + pattern poblados; pro/news/macro sin historia en v1.
    assert report.populated == 3
    assert report.total == 6
    assert report.pct == 50.0
    assert set(report.missing) == {"pro", "news", "macro"}


def test_completeness_flags_insufficient_pattern() -> None:
    base = _series(10)  # < 20 velas -> pattern 'insufficient_chart_data'
    ctx = build_context(base, 9, symbol="EURUSD", category="forex")
    report = context_completeness(ctx)
    assert "pattern" in report.missing


# -- paridad con el contexto vivo ----------------------------------------


def test_field_parity_with_live_context() -> None:
    expected = {"snapshot", "candles", "pattern", "pro", "news_label",
                "news_score", "macro"}
    assert context_field_names() == expected
    assert {f.name for f in fields(StrategyContext)} == expected


def test_build_returns_strategy_context_instance() -> None:
    base = _series(300)
    ctx = build_context(base, 200, symbol="XAUUSD", category="gold")
    assert isinstance(ctx, StrategyContext)
    assert ctx.snapshot.symbol == "XAUUSD"
    assert ctx.snapshot.category == "gold"
    assert ctx.snapshot.price == base[200]["close"]


# -- guardas de rango -----------------------------------------------------


def test_out_of_range_index_raises() -> None:
    base = _series(50)
    for bad in (-1, 50, 999):
        try:
            build_context(base, bad, symbol="EURUSD", category="forex")
            raise AssertionError(f"n={bad} deberia haber fallado")
        except IndexError:
            pass


def test_empty_candles_raises() -> None:
    try:
        build_context([], 0, symbol="EURUSD", category="forex")
        raise AssertionError("candles vacio deberia fallar")
    except ValueError:
        pass
