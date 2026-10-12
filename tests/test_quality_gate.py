"""v3.17.0 — quality gate en sombra (adaptado del paquete "v3.17 calidad").

Cubre: la regla pura (QG1, nunca "discard"), el registro en sombra DESPUÉS de la decisión
del agente, las noticias de acciones (Yahoo ya bajado + Google diferido, as-of) y el
modo que actúa solo fuera del agente. Sin red y sin MT5 real.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.collectors.news_collector import NewsItem
from app.collectors.web_news_enhancer import Headline
from app.database.db import init_db
from app.database.models import AlertRecord, EstimateResult, SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from app.risk import quality_gate as qg
from app.risk.quality_gate import (
    ALLOW,
    PAPER_ONLY,
    QualityCandidate,
    QualityInputs,
    evaluate,
    stop_distance_atr,
)
from app.scheduler.jobs import TradingAlertJob
from app.strategies.base import StrategySignal
from app.utils.time_utils import utc_now
from tests.test_auto_confirm_demo import _paper_trade_row
from tests.test_auto_confirm_demo import _StubJob as _DemoStub
from tests.test_mt5_demo_trader import _demo_settings, _fake_mt5
from tests.test_score import _settings

TH = {"min_confidence": 60, "min_score": 65, "min_confluence": 2}


def _repo() -> Repository:
    d = Path.cwd() / ".test_dbs"
    d.mkdir(exist_ok=True)
    p = d / f"quality_{uuid4().hex}.db"
    init_db(p)
    return Repository(p)


def _rows(repo: Repository) -> list[dict]:
    import sqlite3

    con = sqlite3.connect(repo.db_path)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM quality_gate_shadow ORDER BY id")]
    finally:
        con.close()


# ------------------------------------------------------------- regla pura QG1
def test_all_components_aligned_allows() -> None:
    d = evaluate(QualityInputs("long", confidence=80, alert_score=70, regime="up",
                               calendar_safe=True, stop_atr=1.5), **TH)
    assert d.action == ALLOW and d.confluence == 4
    assert d.score == 50 + 15 + 12 + 8 + 8
    assert d.reasons == ["high_confidence", "regime_aligned", "reasonable_risk", "calendar_safe"]
    assert d.version == "qg1"


def test_one_confluence_is_not_enough() -> None:
    d = evaluate(QualityInputs("long", confidence=80, alert_score=70), **TH)
    assert d.action == PAPER_ONLY and d.confluence == 1
    assert d.reasons[-1] == "insufficient_confluence"


def test_lowest_tier_is_paper_only_never_discard() -> None:
    d = evaluate(QualityInputs("long", confidence=40, alert_score=40, regime="down",
                               calendar_safe=False, stop_atr=5.0), **TH)
    assert d.action == PAPER_ONLY and d.score == 0.0          # 50-20-18-15-25, acotado
    assert "quality_too_low" in d.reasons                      # el "discard" del paquete


def test_no_input_combination_ever_discards() -> None:
    actions = set()
    for regime in ("up", "down", "flat", None):
        for cal in (True, False, None):
            for stop in (None, 0.1, 1.0, 5.0):
                for conf in (None, 30, 90):
                    for cat in (None, True):
                        d = evaluate(QualityInputs(
                            "short", confidence=conf, alert_score=conf, regime=regime,
                            calendar_safe=cal, stop_atr=stop, news_catalyst=cat,
                            news_freshness=90, news_sentiment=-1.0), **TH)
                        actions.add(d.action)
    assert actions == {ALLOW, PAPER_ONLY}


def test_regime_flat_or_unknown_gives_nothing_and_against_subtracts() -> None:
    base = dict(confidence=80, alert_score=70, calendar_safe=True)
    flat = evaluate(QualityInputs("long", regime="flat", **base), **TH)
    none = evaluate(QualityInputs("long", regime=None, **base), **TH)
    against = evaluate(QualityInputs("short", regime="up", **base), **TH)
    assert flat.score == none.score == 50 + 15 + 8
    assert against.score == 50 + 15 + 8 - 18 and "regime_against" in against.reasons


def test_stop_distance_in_atr_bands() -> None:
    s = lambda v: evaluate(QualityInputs("long", stop_atr=v), **TH)  # noqa: E731
    assert "reasonable_risk" in s(0.5).reasons and "reasonable_risk" in s(2.2).reasons
    assert "extreme_risk" in s(0.2).reasons and "extreme_risk" in s(3.6).reasons
    neutral = s(3.0)
    assert "reasonable_risk" not in neutral.reasons and "extreme_risk" not in neutral.reasons


def test_news_catalyst_and_negative_news_against_long() -> None:
    cat = evaluate(QualityInputs("long", news_catalyst=True, news_freshness=60), **TH)
    stale = evaluate(QualityInputs("long", news_catalyst=True, news_freshness=59), **TH)
    neg_long = evaluate(QualityInputs("long", news_sentiment=-0.4), **TH)
    neg_short = evaluate(QualityInputs("short", news_sentiment=-0.9), **TH)
    assert "fresh_catalyst" in cat.reasons and cat.confluence == 1
    assert "fresh_catalyst" not in stale.reasons
    assert "negative_news_vs_long" in neg_long.reasons and neg_long.score == 38
    assert "negative_news_vs_long" not in neg_short.reasons


def test_confidence_unknown_and_garbage_numbers_are_no_data() -> None:
    d = evaluate(QualityInputs("long", confidence=None, alert_score=None), **TH)
    assert "confidence_unknown" in d.reasons and d.score == 50
    g = evaluate(QualityInputs("long", confidence="x", alert_score=float("nan"),
                               stop_atr="abc", news_freshness=True), **TH)
    assert "confidence_unknown" in g.reasons and "extreme_risk" not in g.reasons


def test_soft_fail_returns_allow() -> None:
    class _Broken:
        @property
        def direction(self):
            raise RuntimeError("roto")

    d = evaluate(_Broken(), **TH)  # type: ignore[arg-type]
    assert d.action == ALLOW and d.reasons == ["quality_gate_error"] and d.score is None


def test_stop_distance_atr() -> None:
    assert stop_distance_atr(100.0, 99.0, 0.5) == pytest.approx(2.0)   # 1 % / 0.5 %
    assert stop_distance_atr(100.0, 101.0, 0.5) == pytest.approx(2.0)  # short: abs
    for bad in ((None, 99, 0.5), (100, None, 0.5), (100, 99, None), (100, 99, 0), (0, 99, 1)):
        assert stop_distance_atr(*bad) is None


def _code_names(module) -> set[str]:
    """Nombres que el CÓDIGO usa (no docstrings ni comentarios): variables, atributos e
    imports."""
    import ast

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            names.add(str(node.module))
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


FORBIDDEN = {"order_send", "MT5DemoTrader", "app.brokers.mt5_demo_trader", "MetaTrader5",
             "create_demo_trade_request", "create_paper_trade", "update_paper_trade"}


def test_modules_have_no_order_path() -> None:
    from app.collectors import web_news_enhancer
    from app.risk import block_log

    for mod in (qg, block_log, web_news_enhancer):
        assert not (_code_names(mod) & FORBIDDEN), mod.__name__


# ----------------------------------------------------- registro en sombra (jobs)
class _ShadowJob:
    _try_open_paper_trades = TradingAlertJob._try_open_paper_trades
    _quality_thresholds = TradingAlertJob._quality_thresholds
    _quality_candidate_for = TradingAlertJob._quality_candidate_for
    _quality_inputs = TradingAlertJob._quality_inputs
    _quality_calendar = TradingAlertJob._quality_calendar
    _quality_gate = TradingAlertJob._quality_gate
    _record_quality_shadow = TradingAlertJob._record_quality_shadow
    _yahoo_headlines = TradingAlertJob._yahoo_headlines
    _maybe_fill_quality_news = TradingAlertJob._maybe_fill_quality_news
    _finalize_quality_row = TradingAlertJob._finalize_quality_row

    def __init__(self, settings, repo, regime="up", news_items=None, signal=None) -> None:
        self.settings = settings
        self.repository = repo
        self.mt5_reader = None
        self.notifier = MagicMock()
        self.calls: list = []
        self._regime = regime
        self.news = SimpleNamespace(cached_for_symbol=lambda sym: news_items)
        self._quality_current = None
        self._web_news_source = None
        self._block_seen = ("", set())
        self.strategy_router = SimpleNamespace(route=lambda ctx, s: [signal])
        self.portfolio_manager = SimpleNamespace(get_open_positions=lambda: [],
                                                 account_balance=lambda: 10_000.0)
        self.risk_manager = SimpleNamespace(check_can_open_trade=lambda *a, **k: (True, ""))

    def _ai_agent_context(self, paper_trade, live_fallback=False):
        self.calls.append(("contexto_d1", live_fallback))
        return self._regime, None

    def _try_prepare_demo_order(self, paper_trade) -> None:
        self.calls.append(("decision", paper_trade["id"]))


def _on(**kw):
    return replace(_settings(), enable_quality_gate=True, **kw)


def _open_candidate(job, monkeypatch, category="forex", symbol="EURUSD=X", score=50):
    import app.analyzers.technical_patterns as tp

    pattern = SimpleNamespace(rsi=55.0, atr_pct=0.5, macd=0.1, macd_signal=0.05,
                              vwap_dist_pct=None, vwap_week_dist_pct=None, hurst=0.55,
                              candle_clv=0.7, candle_strength="strong")
    monkeypatch.setattr(tp, "analyze_ohlcv", lambda candles: pattern)
    snap = TokenSnapshot(chain=category, token_address=symbol, category=category,
                         symbol=symbol, price=100.0, liquidity_usd=None,
                         raw={"candles": [{"close": 100.0}]})
    est = EstimateResult(estimated_gain_pct=0, estimated_loss_pct=0, confidence=50,
                         label="x", reasons=[], eligible_for_gain_alert=False)
    token_id = job.repository.upsert_token(snap, score, "low", est)
    record = AlertRecord(token_id=token_id, alert_type="X", snapshot=snap, app_version="t",
                         category=category, score=score, risk_level="low", reasons=["x"],
                         security=SecuritySummary(raw_summary="unknown"), estimate=est)
    job._try_open_paper_trades(snap, record, set())


def _signal(confidence=70) -> StrategySignal:
    # stop 1 % bajo la entrada; con ATR 0.5 % -> 2 ATR ("reasonable_risk")
    return StrategySignal(strategy_name="breakout", direction="long", entry=100.0,
                          stop=99.0, targets=[102.0, 104.0], confidence=confidence,
                          reasoning=["x"], time_horizon_hours=8)


def test_gate_off_keeps_the_open_path_exactly_as_before(monkeypatch) -> None:
    class _Bare:          # sin ningún método nuevo: con el flag apagado no se llaman
        _try_open_paper_trades = TradingAlertJob._try_open_paper_trades

        def __init__(self, repo):
            self.settings = _settings()
            self.repository = repo
            self.mt5_reader = None
            self.notifier = MagicMock()
            self.prepared = []
            self.strategy_router = SimpleNamespace(route=lambda ctx, s: [_signal()])
            self.portfolio_manager = SimpleNamespace(get_open_positions=lambda: [],
                                                     account_balance=lambda: 10_000.0)
            self.risk_manager = SimpleNamespace(check_can_open_trade=lambda *a, **k: (True, ""))

        def _try_prepare_demo_order(self, paper_trade):
            self.prepared.append(paper_trade)

    repo = _repo()
    job = _Bare(repo)
    _open_candidate(job, monkeypatch)
    assert len(job.prepared) == 1 and _rows(repo) == []


def test_shadow_is_written_after_the_agent_decides(monkeypatch) -> None:
    repo = _repo()
    job = _ShadowJob(_on(enable_ai_agent=True), repo, regime="up", signal=_signal(70))
    _open_candidate(job, monkeypatch, score=50)
    pt_id = job.calls[0][1]
    # primero decide el agente (camino de órdenes), DESPUÉS el gate lee el D1
    assert job.calls == [("decision", pt_id), ("contexto_d1", True)]
    (row,) = _rows(repo)
    assert row["paper_trade_id"] == pt_id and row["agent_path"] == 1
    assert row["confidence"] == 70 and row["alert_score"] == 50
    assert row["regime"] == "up" and row["stop_atr"] == pytest.approx(2.0)
    assert row["calendar_safe"] is None and row["news_status"] == "n/a"
    assert row["min_confidence"] == 60 and row["min_score"] == 65 and row["min_confluence"] == 2
    assert row["action"] == ALLOW and row["confluence"] == 3 and row["enforced"] == 0
    assert json.loads(row["reasons_json"])[:3] == [
        "high_confidence", "regime_aligned", "reasonable_risk"]
    assert row["gate_version"] == "qg1" and row["decided_at"]
    assert job._quality_current is None


def test_shadow_never_touches_the_paper_trade(monkeypatch) -> None:
    repo = _repo()
    job = _ShadowJob(_on(), repo, regime="down", signal=_signal(30))   # todo en contra
    _open_candidate(job, monkeypatch, score=10)
    (row,) = _rows(repo)
    assert row["action"] == PAPER_ONLY
    pt = repo.fetch_paper_trade_by_id(row["paper_trade_id"])
    assert pt["status"] == "open"                 # el paper trade sigue: nunca descarta


def test_shadow_is_idempotent_per_paper_trade() -> None:
    repo = _repo()
    job = _ShadowJob(_on(), repo)
    pt = {"id": 5, "category": "gold", "symbol": "GC=F", "direction": "short",
          "entry_price": 100.0, "stop_loss": 101.0, "atr_value": 0.5,
          "opened_at": "2026-10-12T12:00:00+00:00", "strategy_name": "breakout"}
    job._record_quality_shadow(pt)
    job._record_quality_shadow(pt)
    assert len(_rows(repo)) == 1


def test_calendar_input_reads_events_without_the_calendar_gate_flag() -> None:
    repo = _repo()
    now = utc_now()
    repo.upsert_economic_event({
        "event_time": (now + timedelta(minutes=10)).isoformat(), "country": "USD",
        "impact": "high", "title": "CPI", "source": "test",
    })
    job = _ShadowJob(_on(enable_economic_calendar=True, enable_calendar_gate=False), repo)
    assert job._quality_calendar({"symbol": "EURUSD=X"}) is False
    assert job._quality_calendar({"symbol": "USDJPY=X"}) is False      # también USD
    off = _ShadowJob(_on(enable_economic_calendar=False), repo)
    assert off._quality_calendar({"symbol": "EURUSD=X"}) is None


# ------------------------------------------------------------- acciones + noticias
OPENED = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def _stock_trade(pt_id=11, symbol="AAPL", opened=OPENED) -> dict:
    return {"id": pt_id, "category": "stock", "symbol": symbol, "direction": "long",
            "entry_price": 100.0, "stop_loss": 99.0, "atr_value": 0.5,
            "opened_at": opened.isoformat(), "strategy_name": "breakout"}


def _rfc(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def test_stock_without_web_uses_yahoo_cache_as_of_the_opening() -> None:
    repo = _repo()
    yahoo = [NewsItem("Apple earnings beat", "", _rfc(OPENED - timedelta(hours=1))),
             NewsItem("Apple shares fall after the close", "", _rfc(OPENED + timedelta(hours=2)))]
    job = _ShadowJob(_on(), repo, news_items=yahoo)
    job._quality_current = QualityCandidate(11, confidence=80, alert_score=70)
    job._record_quality_shadow(_stock_trade())
    (row,) = _rows(repo)
    assert row["news_status"] == "yahoo" and row["news_sources"] == "yahoo"
    titles = [h["title"] for h in json.loads(row["news_json"])]
    assert titles == ["Apple earnings beat"]             # la del futuro no entra
    assert row["news_catalyst"] == 1 and row["news_freshness"] == 95.0
    assert row["regime"] is None and job.calls == []      # acciones: sin D1 de MT5
    assert "fresh_catalyst" in json.loads(row["reasons_json"]) and row["action"] == ALLOW


def test_stock_without_any_headline_is_none() -> None:
    repo = _repo()
    job = _ShadowJob(_on(), repo, news_items=None)
    job._record_quality_shadow(_stock_trade())
    (row,) = _rows(repo)
    assert row["news_status"] == "none" and row["news_count"] == 0 and row["action"]


class _FakeGoogle:
    def __init__(self, data: dict, paused: bool = False) -> None:
        self.data, self.paused, self.fetched = data, paused, []
        self._cache: set[str] = set()

    def is_cached(self, symbol):
        return symbol in self._cache

    def fetch(self, symbol):
        self.fetched.append(symbol)
        self._cache.add(symbol)
        return self.data.get(symbol)


def test_web_news_is_deferred_then_filled_as_of() -> None:
    repo = _repo()
    yahoo = [NewsItem("Apple unveils phone", "", _rfc(OPENED - timedelta(hours=3)))]
    job = _ShadowJob(_on(enable_web_news_enhancer=True), repo, news_items=yahoo)
    job._quality_current = QualityCandidate(11, confidence=80, alert_score=70)
    job._record_quality_shadow(_stock_trade())
    (row,) = _rows(repo)
    assert row["news_status"] == "pending" and row["action"] is None   # espera a Google

    job._web_news_source = _FakeGoogle({"AAPL": [
        Headline("AAPL merger talks", OPENED - timedelta(hours=1), "google"),
        Headline("AAPL after-hours plunge", OPENED + timedelta(hours=1), "google"),
        Headline("Undated google", None, "google")]})
    job._maybe_fill_quality_news()
    (row,) = _rows(repo)
    titles = [h["title"] for h in json.loads(row["news_json"])]
    assert titles == ["AAPL merger talks", "Apple unveils phone"]
    assert row["news_status"] == "done" and row["news_sources"] == "google,yahoo"
    assert row["action"] == ALLOW and "fresh_catalyst" in json.loads(row["reasons_json"])


def test_web_news_budget_is_two_fetches_per_cycle() -> None:
    repo = _repo()
    job = _ShadowJob(_on(enable_web_news_enhancer=True), repo)
    for i, sym in enumerate(("AAPL", "MSFT", "NVDA"), start=1):   # recién abiertos
        job._record_quality_shadow(_stock_trade(pt_id=i, symbol=sym, opened=utc_now()))
    fake = _FakeGoogle({"AAPL": [], "MSFT": [], "NVDA": []})
    job._web_news_source = fake
    job._maybe_fill_quality_news()
    assert fake.fetched == ["AAPL", "MSFT"]
    assert [r["news_status"] for r in _rows(repo)] == ["done", "done", "pending"]
    job._maybe_fill_quality_news()
    assert fake.fetched == ["AAPL", "MSFT", "NVDA"]
    assert all(r["news_status"] == "done" for r in _rows(repo))


def test_web_news_failure_paused_and_expiry() -> None:
    repo = _repo()
    job = _ShadowJob(_on(enable_web_news_enhancer=True), repo)
    job._record_quality_shadow(_stock_trade(pt_id=1, symbol="AAPL"))
    job._web_news_source = _FakeGoogle({"AAPL": None})          # falla
    job._maybe_fill_quality_news()
    assert _rows(repo)[0]["news_status"] == "google_failed" and _rows(repo)[0]["action"]

    job._record_quality_shadow(_stock_trade(pt_id=2, symbol="MSFT", opened=utc_now()))
    job._record_quality_shadow(
        _stock_trade(pt_id=3, symbol="NVDA", opened=utc_now() - timedelta(hours=7)))
    job._web_news_source = _FakeGoogle({}, paused=True)
    job._maybe_fill_quality_news()
    by_id = {r["paper_trade_id"]: r for r in _rows(repo)}
    assert by_id[2]["news_status"] == "pending"                  # en pausa: espera
    assert by_id[3]["news_status"] == "expired" and by_id[3]["action"]


def test_pending_rows_close_when_web_news_is_turned_off() -> None:
    repo = _repo()
    yahoo = [NewsItem("Apple beats", "", _rfc(OPENED - timedelta(hours=1)))]
    job = _ShadowJob(_on(enable_web_news_enhancer=True), repo, news_items=yahoo)
    job._record_quality_shadow(_stock_trade())
    assert _rows(repo)[0]["news_status"] == "pending"
    job.settings = _on()                     # el user apagó ENABLE_WEB_NEWS_ENHANCER
    job._maybe_fill_quality_news()
    row = _rows(repo)[0]
    assert row["news_status"] == "web_off" and row["news_sources"] == "yahoo" and row["action"]


def test_a_broken_pending_row_does_not_block_the_rest() -> None:
    repo = _repo()
    job = _ShadowJob(_on(enable_web_news_enhancer=True), repo)
    job._record_quality_shadow(_stock_trade(pt_id=1, symbol="AAPL", opened=utc_now()))
    job._record_quality_shadow(_stock_trade(pt_id=2, symbol="MSFT", opened=utc_now()))
    job._web_news_source = _FakeGoogle({"AAPL": [], "MSFT": []})
    real = job._finalize_quality_row

    def flaky(row, google, status, as_of):
        if row["paper_trade_id"] == 1:
            raise RuntimeError("fila rota")
        return real(row, google, status, as_of)

    job._finalize_quality_row = flaky
    job._maybe_fill_quality_news()
    by_id = {r["paper_trade_id"]: r for r in _rows(repo)}
    assert by_id[1]["news_status"] == "error" and by_id[2]["news_status"] == "done"


def test_fill_does_nothing_with_flags_off() -> None:
    repo = _repo()
    job = _ShadowJob(_settings(), repo)          # gate apagado
    job._web_news_source = _FakeGoogle({"AAPL": []})
    job._maybe_fill_quality_news()
    assert job._web_news_source.fetched == []


# ------------------------------------------------- actúa solo fuera del agente
class _EnforceJob(_DemoStub):
    _quality_thresholds = TradingAlertJob._quality_thresholds
    _quality_candidate_for = TradingAlertJob._quality_candidate_for
    _quality_inputs = TradingAlertJob._quality_inputs
    _quality_calendar = TradingAlertJob._quality_calendar
    _quality_gate = TradingAlertJob._quality_gate
    regime = "up"
    _quality_current = None
    _block_seen = ("", set())

    def _ai_agent_context(self, paper_trade, live_fallback=False):
        return self.regime, None


def _enforce_settings(**kw):
    return _demo_settings(enable_quality_gate=True, quality_gate_enforce=True, **kw)


def test_enforce_keeps_paper_only_out_of_mt5(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    repo = _repo()
    repo.create_paper_trade(_paper_trade_row())
    pt = repo.fetch_paper_trade_by_alert_id(101)
    notifier = MagicMock()
    job = _EnforceJob(_enforce_settings(enable_discard_log=True), repo, notifier)
    job.regime = "down"                                    # long contra la tendencia
    job._try_prepare_demo_order(pt)
    assert repo.fetch_demo_trade_request(1) is None and not notifier.send_message.called
    assert job._quality_current.enforced is True
    blocks = repo.fetch_candidate_blocks("2000-01-01")
    assert [(b["stage"], b["reason"]) for b in blocks] == [("mt5", "quality gate")]


def test_enforce_lets_allow_through(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    repo = _repo()
    repo.create_paper_trade(_paper_trade_row())
    pt = repo.fetch_paper_trade_by_alert_id(101)
    notifier = MagicMock()
    job = _EnforceJob(_enforce_settings(), repo, notifier)
    job._quality_current = QualityCandidate(int(pt["id"]), confidence=80, alert_score=80)
    job._try_prepare_demo_order(pt)
    assert repo.fetch_demo_trade_request(1) is not None    # siguió al camino normal
    assert "Orden demo MT5 lista para confirmar" in notifier.send_message.call_args[0][0]


def test_without_enforce_flag_the_gate_never_acts(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    repo = _repo()
    repo.create_paper_trade(_paper_trade_row())
    pt = repo.fetch_paper_trade_by_alert_id(101)
    job = _EnforceJob(_demo_settings(enable_quality_gate=True), repo, MagicMock())
    job.regime = "down"
    job._try_prepare_demo_order(pt)
    assert repo.fetch_demo_trade_request(1) is not None    # solo mide, no actúa


def test_enforce_soft_fails_to_allow() -> None:
    job = _EnforceJob(_enforce_settings(), _repo(), MagicMock())

    def _boom(paper_trade, live_fallback=False):
        raise RuntimeError("MT5 caído")

    job._ai_agent_context = _boom
    assert job._quality_gate({"id": 1, "category": "forex", "direction": "long"}) is True


def test_agent_path_never_reaches_the_gate(monkeypatch) -> None:
    repo = _repo()
    repo.create_paper_trade(_paper_trade_row())
    pt = repo.fetch_paper_trade_by_alert_id(101)
    job = _EnforceJob(_enforce_settings(enable_ai_agent=True), repo, MagicMock())
    seen = []
    job._ai_agent_path = lambda trade: seen.append("agente")
    job._quality_gate = lambda trade: (_ for _ in ()).throw(AssertionError("no debía"))
    job._try_prepare_demo_order(pt)
    assert seen == ["agente"]
