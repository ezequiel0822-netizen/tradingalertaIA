"""v3.17.0 — Web News Enhancer (solo acciones, as-of, nunca frena). Sin red: sesión falsa."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.collectors import web_news_enhancer as wn
from app.collectors.web_news_enhancer import (
    GoogleNewsSource,
    Headline,
    features_from_headlines,
    is_stock_symbol,
    merge_as_of,
    parse_pub_date,
    parse_rss,
    simple_sentiment,
)

OPEN = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def _h(title, hours_before=None, source="google"):
    pub = None if hours_before is None else OPEN - timedelta(hours=hours_before)
    return Headline(title, pub, source)


def _rss(items: list[tuple[str, str | None]]) -> bytes:
    parts = []
    for title, pub in items:
        pub_xml = f"<pubDate>{pub}</pubDate>" if pub else ""
        parts.append(f"<item><title>{title}</title>{pub_xml}</item>")
    return f"<rss><channel>{''.join(parts)}</channel></rss>".encode()


class _Resp:
    def __init__(self, status=200, content=b""):
        self.status_code = status
        self.content = content


class _Session:
    """Sesión falsa: cuenta las llamadas y devuelve lo programado (o lanza)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[str] = []
        self.headers: dict = {}

    def get(self, url, timeout=None):
        self.calls.append(url)
        r = self.responses.pop(0) if self.responses else _Resp(200, _rss([]))
        if isinstance(r, Exception):
            raise r
        return r


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ------------------------------------------------------------- funciones puras
def test_sentiment_basic_and_ambiguous_words_are_neutral() -> None:
    assert simple_sentiment("Apple beats estimates, shares surge") == 1.0
    assert simple_sentiment("Tesla misses, stock falls on weak demand") == -1.0
    assert simple_sentiment("Apple unveils a new phone") == 0.0
    assert simple_sentiment("") == 0.0
    # la revisión: "cut" (baja de tasas), "lower"/"higher" y "baja" ya no cuentan
    assert simple_sentiment("Fed cut rates, yields lower") == 0.0
    assert simple_sentiment("Stocks higher as Fed cuts") == 0.0
    assert simple_sentiment("La baja de tasas") == 0.0


def test_parse_pub_date_rfc2822_to_utc_and_garbage() -> None:
    dt = parse_pub_date("Mon, 12 Oct 2026 14:03:00 GMT")
    assert dt == datetime(2026, 10, 12, 14, 3, tzinfo=timezone.utc)
    assert parse_pub_date("Mon, 12 Oct 2026 10:00:00 -0400") == datetime(
        2026, 10, 12, 14, 0, tzinfo=timezone.utc)
    assert parse_pub_date("no es una fecha") is None
    assert parse_pub_date(None) is None


def test_parse_rss_titles_and_dates() -> None:
    items = parse_rss(_rss([("AAPL beats", "Mon, 12 Oct 2026 14:00:00 GMT"), ("Sin fecha", None),
                            ("", "Mon, 12 Oct 2026 14:00:00 GMT")]), "google")
    assert [h.title for h in items] == ["AAPL beats", "Sin fecha"]
    assert items[0].published is not None and items[1].published is None
    with pytest.raises(Exception):
        parse_rss(b"<rss><channel>", "google")


def test_merge_as_of_drops_future_and_undated_google_but_keeps_undated_yahoo() -> None:
    google = [_h("Old news", 5), _h("Future news", -1), _h("Undated google"),
              _h("dup  title", 2)]
    yahoo = [_h("Undated yahoo", source="yahoo"), _h("DUP title", 1, "yahoo")]
    out = merge_as_of([yahoo, google], OPEN)
    titles = [h.title for h in out]
    assert "Future news" not in titles and "Undated google" not in titles
    assert "Undated yahoo" in titles
    assert sum(1 for t in titles if t.lower().split() == ["dup", "title"]) == 1
    assert titles[0] == "DUP title"                       # más nuevo primero
    many = [_h(f"t{i}", i + 1) for i in range(20)]
    assert len(merge_as_of([many], OPEN)) == wn.MAX_HEADLINES


def test_features_are_measured_against_the_opening() -> None:
    assert features_from_headlines([], OPEN).freshness_score == 0.0
    f = features_from_headlines([_h("Earnings beat", 2)], OPEN)
    assert f.freshness_score == 95.0 and f.age_hours == 2.0 and f.has_catalyst is True
    assert features_from_headlines([_h("x", 5)], OPEN).freshness_score == 80.0
    assert features_from_headlines([_h("x", 12)], OPEN).freshness_score == 60.0
    assert features_from_headlines([_h("x", 30)], OPEN, 18.0).freshness_score == 25.0
    undated = features_from_headlines([_h("x", source="yahoo")], OPEN)
    assert undated.freshness_score == 40.0 and undated.age_hours is None
    neg = features_from_headlines([_h("Shares fall on lawsuit", 1)], OPEN)
    assert neg.sentiment == -1.0 and neg.has_catalyst is True          # |sent| >= 0.25
    plain = features_from_headlines([_h("Company holds meeting", 1)], OPEN)
    assert plain.has_catalyst is False and plain.sources == ["google"]


def test_stock_symbols_only() -> None:
    assert is_stock_symbol("AAPL") and is_stock_symbol("brk.b") and is_stock_symbol("BF-B")
    for s in ("EURUSD=X", "GC=F", "^VIX", "", None, "EUR/USD"):
        assert not is_stock_symbol(s)


# ------------------------------------------------------------- fuente Google
def test_google_fetch_parses_and_caches_without_new_requests() -> None:
    sess = _Session([_Resp(200, _rss([("AAPL beats", "Mon, 12 Oct 2026 14:00:00 GMT")]))])
    clock = _Clock()
    src = GoogleNewsSource(session=sess, clock=clock)
    first = src.fetch("aapl")
    assert [h.title for h in first] == ["AAPL beats"] and first[0].source == "google"
    assert "AAPL+stock+OR+AAPL+shares+when%3A1d" in sess.calls[0]
    assert src.is_cached("AAPL")
    assert src.fetch("AAPL") == first and len(sess.calls) == 1        # caché: sin red
    clock.t += wn.GOOGLE_CACHE_SECONDS + 1
    assert not src.is_cached("AAPL")
    src.fetch("AAPL")
    assert len(sess.calls) == 2


def test_google_never_queries_forex_or_gold() -> None:
    sess = _Session([])
    src = GoogleNewsSource(session=sess, clock=_Clock())
    assert src.fetch("EURUSD=X") is None and src.fetch("GC=F") is None
    assert sess.calls == []


def test_google_failures_pause_after_three_in_a_row() -> None:
    sess = _Session([_Resp(500), TimeoutError("lento"), _Resp(200, b"no es xml <")])
    clock = _Clock()
    src = GoogleNewsSource(session=sess, clock=clock)
    assert src.fetch("AAPL") is None and src.fetch("MSFT") is None and src.fetch("NVDA") is None
    assert src.paused and len(sess.calls) == 3
    assert src.fetch("AMZN") is None and len(sess.calls) == 3          # en pausa: sin red
    clock.t += wn.GOOGLE_PAUSE_SECONDS + 1
    assert not src.paused
    assert src.fetch("AMZN") == [] and len(sess.calls) == 4            # vuelve (RSS vacío)


def test_google_rejects_huge_responses() -> None:
    sess = _Session([_Resp(200, b"x" * (wn.GOOGLE_MAX_BYTES + 1))])
    assert GoogleNewsSource(session=sess, clock=_Clock()).fetch("AAPL") is None


def test_module_never_touches_mt5() -> None:
    import ast

    tree = ast.parse(Path(wn.__file__).read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {str(n.module) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any("mt5" in m.lower() or "MetaTrader5" in m for m in imported)
    assert "requests" in imported                       # solo HTTP de lectura (RSS)
