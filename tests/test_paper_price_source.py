"""v3.14.1 — una sola fuente de precio por paper trade forex/oro (PAPER_PRICE_FROM_MT5).

Reproduce el caso real del 2026-10-06 (research/AGENTE_IA_V2_ADENDA_2026-10-07_oro.md):
la señal de oro salía de Yahoo GC=F (futuro, 4190.0) y el lifecycle marcaba con el spot
de MT5 XAUUSD (~4160) → el paper trade "tocaba" el stop al minuto con −3.5R.
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

from app.ai_agent.agent import MODEL_STATE_KEYS, AiAgent, mixed_gold_decision
from app.ai_agent.features import FEATURE_NAMES_V2, recent_strategy_r
from app.ai_agent.model import LinearThompson
from app.database.db import init_db
from app.database.models import AlertRecord, EstimateResult, SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from app.learning.lifecycle_manager import _fresh_price, manage_open_positions
from app.learning.price_source import (
    MAX_REBASE_PCT,
    PRICE_SOURCE_MT5,
    PRICE_SOURCE_YAHOO,
    is_mixed_price_trade,
    mt5_entry_price,
    rebase_levels,
    resolve_entry_levels,
    without_mixed_gold,
)
from app.learning.training_engine import _update_paper_trades
from app.scheduler.jobs import TradingAlertJob
from app.strategies.base import StrategySignal
from tests.test_ai_agent_v2 import PREREG_TAG, _v2_settings
from tests.test_score import _settings

SPOT_BID, SPOT_ASK = 4159.56, 4159.90      # MT5 XAUUSD 2026-10-06 13:39 UTC (M1)
FUT = 4190.0                                 # Yahoo GC=F en el mismo minuto
FUT_STOP = 4180.5725                         # stop de la señal (paper trade 2085)
FUT_TP1, FUT_TP2 = 4219.64990234, 4249.3


def _repo() -> Repository:
    d = Path.cwd() / ".test_dbs"
    d.mkdir(exist_ok=True)
    p = d / f"price_src_{uuid4().hex}.db"
    init_db(p)
    return Repository(p)


class _Reader:
    """MT5Reader falso: solo lo que usan price_source y el lifecycle."""

    def __init__(self, ticks: dict[str, dict] | None = None, connected: bool = True) -> None:
        self.ticks = ticks or {}
        self.connected = connected
        self.calls: list[str] = []

    def is_connected(self) -> bool:
        return self.connected

    def get_tick(self, symbol: str):
        self.calls.append(symbol)
        return self.ticks.get(symbol)


def _gold_reader(**kw) -> _Reader:
    return _Reader({"XAUUSD": {"bid": SPOT_BID, "ask": SPOT_ASK}}, **kw)


def _on(**kw):
    return replace(_settings(), paper_price_from_mt5=True, **kw)


# ------------------------------------------------------------------- rebase puro
def test_rebase_keeps_distances_and_moves_every_level() -> None:
    lv = rebase_levels(FUT, FUT_STOP, [FUT_TP1, FUT_TP2], SPOT_ASK)
    off = SPOT_ASK - FUT
    assert lv.source == PRICE_SOURCE_MT5 and lv.source_entry == FUT
    assert lv.entry == SPOT_ASK and lv.offset == pytest.approx(off)
    assert lv.stop == pytest.approx(FUT_STOP + off)
    assert lv.targets == pytest.approx((FUT_TP1 + off, FUT_TP2 + off))
    assert lv.entry - lv.stop == pytest.approx(FUT - FUT_STOP)          # misma distancia


def test_rebase_refuses_absurd_offsets_and_bad_inputs() -> None:
    assert rebase_levels(100.0, 99.0, [101.0], 100.0 * (1 + MAX_REBASE_PCT / 100) + 0.01) is None
    assert rebase_levels(100.0, 99.0, [101.0], 102.9) is not None
    assert rebase_levels(0.0, 99.0, [], 100.0) is None
    assert rebase_levels(100.0, 99.0, [], 0.0) is None
    assert rebase_levels(100.0, 99.0, [None], 100.5) is None
    assert rebase_levels(100.0, None, [], 100.5).stop is None


def test_mt5_entry_price_is_ask_for_long_and_bid_for_short() -> None:
    r = _gold_reader()
    assert mt5_entry_price(r, "GC=F", "long") == SPOT_ASK
    assert mt5_entry_price(r, "GC=F", "short") == SPOT_BID
    assert r.calls == ["XAUUSD", "XAUUSD"]                 # mapea Yahoo -> MT5
    assert mt5_entry_price(_gold_reader(connected=False), "GC=F", "long") is None
    assert mt5_entry_price(None, "GC=F", "long") is None
    assert mt5_entry_price(r, "AAPL", "long") is None      # sin mapeo MT5
    assert mt5_entry_price(_Reader({}), "GC=F", "long") is None


def test_resolve_is_noop_with_flag_off_or_other_category() -> None:
    args = ("GC=F", "long", FUT, FUT_STOP, [FUT_TP1])
    assert resolve_entry_levels(_settings(), _gold_reader(), "gold", *args) is None
    assert resolve_entry_levels(_on(), _gold_reader(), "stock", *args) is None
    lv = resolve_entry_levels(_on(), _gold_reader(), "gold", *args)
    assert lv.source == PRICE_SOURCE_MT5 and lv.entry == SPOT_ASK


def test_resolve_falls_back_to_yahoo_when_mt5_is_down_or_absurd() -> None:
    args = ("GC=F", "long", FUT, FUT_STOP, [FUT_TP1])
    down = resolve_entry_levels(_on(), _gold_reader(connected=False), "gold", *args)
    assert down.source == PRICE_SOURCE_YAHOO and down.entry == FUT and down.offset == 0.0
    assert down.stop == FUT_STOP and down.targets == (FUT_TP1,)
    crazy = _Reader({"XAUUSD": {"bid": 2000.0, "ask": 2000.5}})
    assert resolve_entry_levels(_on(), crazy, "gold", *args).source == PRICE_SOURCE_YAHOO


def test_mixed_gold_definition() -> None:
    assert is_mixed_price_trade({"category": "gold"}) is True
    assert is_mixed_price_trade({"category": "gold", "price_source": "mt5"}) is False
    assert is_mixed_price_trade({"category": "gold", "price_source": "yahoo"}) is False
    assert is_mixed_price_trade({"category": "forex"}) is False      # forex casi cuadra
    assert is_mixed_price_trade({"category": "gold", "is_scalping": 1}) is False   # MT5 directo
    assert is_mixed_price_trade(None) is False
    trades = [{"category": "gold"}, {"category": "forex"}]
    assert without_mixed_gold(trades, False) == trades
    assert without_mixed_gold(trades, True) == [{"category": "forex"}]


# ---------------------------------------------------------------- marcado (lifecycle)
def _gold_trade(repo: Repository, *, entry: float, stop: float, tp1: float, tp2: float,
                source: str | None, direction: str = "long", token_price: float = FUT) -> int:
    snap = TokenSnapshot(chain="commodity", token_address="GC=F", category="gold",
                         symbol="GC=F", price=token_price, liquidity_usd=None)
    est = EstimateResult(estimated_gain_pct=0, estimated_loss_pct=0, confidence=50,
                         label="paper", reasons=[], eligible_for_gain_alert=False)
    token_id = repo.upsert_token(snap, 50, "low", est)
    now = datetime.now(timezone.utc).isoformat()
    alert_id = int(uuid4().int % 10_000_000)
    assert repo.create_paper_trade({
        "alert_id": alert_id, "token_id": token_id, "category": "gold", "chain": "commodity",
        "token_address": "GC=F", "symbol": "GC=F", "thesis": "t", "readiness_grade": "B",
        "entry_price": entry, "latest_price": entry, "stop_loss": stop,
        "take_profit_1": tp1, "take_profit_2": tp2, "invalidation": None, "status": "open",
        "unrealized_return_pct": 0, "opened_at": now, "updated_at": now,
        "original_stop_loss": stop, "strategy_name": "forex_session_breakout",
        "direction": direction, "time_horizon_hours": 8, "size_notional": 1000,
        "size_units": 1, "risk_pct": 0.5, "price_source": source,
        "source_entry_price": FUT if source else None,
    })
    return int(repo.fetch_paper_trade_by_alert_id(alert_id)["id"])


def _quiet():
    return replace(_settings(), enable_trailing_stop=False, enable_partial_close_at_tp1=False)


def test_legacy_mixed_gold_is_stopped_at_once_the_bug() -> None:
    repo = _repo()
    tid = _gold_trade(repo, entry=FUT, stop=FUT_STOP, tp1=FUT_TP1, tp2=FUT_TP2, source=None)
    manage_open_positions(_quiet(), repo, _gold_reader())
    t = repo.fetch_paper_trade(tid)
    assert t["status"] == "stopped_simulated" and t["latest_price"] == SPOT_BID   # −3.2R falso
    assert is_mixed_price_trade(t)


def test_rebased_gold_is_marked_only_with_mt5_and_survives() -> None:
    repo = _repo()
    lv = rebase_levels(FUT, FUT_STOP, [FUT_TP1, FUT_TP2], SPOT_ASK)
    tid = _gold_trade(repo, entry=lv.entry, stop=lv.stop, tp1=lv.targets[0], tp2=lv.targets[1],
                      source=PRICE_SOURCE_MT5)
    manage_open_positions(_quiet(), repo, _gold_reader())
    t = repo.fetch_paper_trade(tid)
    assert t["status"] == "open" and t["latest_price"] == SPOT_BID      # solo el spread
    assert t["unrealized_return_pct"] == pytest.approx((SPOT_BID - SPOT_ASK) / SPOT_ASK * 100,
                                                       abs=1e-4)
    # MT5 caído: NO cae al precio de Yahoo (el futuro): se saltea el ciclo
    down = _gold_reader(connected=False)
    assert _fresh_price(t, repo, down) is None
    manage_open_positions(_quiet(), repo, down)
    assert repo.fetch_paper_trade(tid)["latest_price"] == SPOT_BID


def test_yahoo_sourced_trade_never_uses_mt5() -> None:
    repo = _repo()
    tid = _gold_trade(repo, entry=FUT, stop=FUT_STOP, tp1=FUT_TP1, tp2=FUT_TP2,
                      source=PRICE_SOURCE_YAHOO, token_price=4189.5)
    r = _gold_reader()
    assert _fresh_price(repo.fetch_paper_trade(tid), repo, r) == 4189.5
    assert r.calls == []
    manage_open_positions(_quiet(), repo, r)
    assert repo.fetch_paper_trade(tid)["status"] == "open"


def test_yahoo_updater_skips_mt5_sourced_trades() -> None:
    repo = _repo()
    lv = rebase_levels(FUT, FUT_STOP, [FUT_TP1, FUT_TP2], SPOT_ASK)
    tid = _gold_trade(repo, entry=lv.entry, stop=lv.stop, tp1=lv.targets[0], tp2=lv.targets[1],
                      source=PRICE_SOURCE_MT5)
    legacy = _gold_trade(repo, entry=FUT, stop=FUT_STOP, tp1=FUT_TP1, tp2=FUT_TP2, source=None,
                         token_price=4191.0)                 # Yahoo (futuro) dice 4191
    _update_paper_trades(repo, _quiet())
    mt5_row = repo.fetch_paper_trade(tid)
    assert mt5_row["latest_price"] == pytest.approx(lv.entry)          # intacto (no 4191)
    assert mt5_row["status"] == "open"
    assert repo.fetch_paper_trade(legacy)["latest_price"] == 4191.0     # el viejo, como siempre


# ------------------------------------------------------------- apertura (jobs)
SHORT_STOP, SHORT_TP1, SHORT_TP2 = FUT + 9.4275, FUT - 29.65, FUT - 59.3


def _signal(direction: str = "long") -> StrategySignal:
    if direction == "short":
        stop, targets = SHORT_STOP, [SHORT_TP1, SHORT_TP2]
    else:
        stop, targets = FUT_STOP, [FUT_TP1, FUT_TP2]
    return StrategySignal(strategy_name="forex_session_breakout", direction=direction,
                          entry=FUT, stop=stop, targets=targets, confidence=70,
                          reasoning=["rango asiatico roto"], time_horizon_hours=8)


class _OpenJob:
    _try_open_paper_trades = TradingAlertJob._try_open_paper_trades

    def __init__(self, settings, repo, reader, signal) -> None:
        self.settings = settings
        self.repository = repo
        self.mt5_reader = reader
        self.notifier = MagicMock()
        self.prepared: list[dict] = []
        self.strategy_router = SimpleNamespace(route=lambda ctx, s: [signal])
        self.portfolio_manager = SimpleNamespace(get_open_positions=lambda: [],
                                                 account_balance=lambda: 10_000.0)
        self.risk_manager = SimpleNamespace(check_can_open_trade=lambda *a, **k: (True, ""))

    def _try_prepare_demo_order(self, paper_trade: dict) -> None:
        self.prepared.append(paper_trade)


def _open(settings, reader, monkeypatch, direction="long") -> tuple[_OpenJob, dict]:
    import app.analyzers.technical_patterns as tp

    pattern = SimpleNamespace(rsi=55.0, atr_pct=0.4, macd=0.1, macd_signal=0.05,
                              vwap_dist_pct=None, vwap_week_dist_pct=None, hurst=0.55,
                              candle_clv=0.7, candle_strength="strong")
    monkeypatch.setattr(tp, "analyze_ohlcv", lambda candles: pattern)
    repo = _repo()
    snap = TokenSnapshot(chain="commodity", token_address="GC=F", category="gold",
                         symbol="GC=F", price=FUT, liquidity_usd=None,
                         raw={"candles": [{"close": FUT}]})
    est = EstimateResult(estimated_gain_pct=0, estimated_loss_pct=0, confidence=50,
                         label="fx", reasons=[], eligible_for_gain_alert=False)
    token_id = repo.upsert_token(snap, 50, "low", est)
    record = AlertRecord(token_id=token_id, alert_type="GOLD_MOVEMENT", snapshot=snap,
                         app_version="v3.14.1", category="gold", score=50, risk_level="low",
                         reasons=["x"], security=SecuritySummary(raw_summary="unknown"),
                         estimate=est)
    job = _OpenJob(settings, repo, reader, _signal(direction))
    job._try_open_paper_trades(snap, record, set())
    assert len(job.prepared) == 1
    return job, job.prepared[0]


def test_open_with_flag_rebases_to_mt5_and_reports_it(monkeypatch) -> None:
    job, pt = _open(_on(enable_trade_action_reports=True), _gold_reader(), monkeypatch)
    off = SPOT_ASK - FUT
    assert pt["price_source"] == "mt5" and pt["source_entry_price"] == FUT
    assert pt["entry_price"] == SPOT_ASK
    assert pt["stop_loss"] == pytest.approx(FUT_STOP + off)
    assert pt["original_stop_loss"] == pytest.approx(FUT_STOP + off)
    assert pt["take_profit_1"] == pytest.approx(FUT_TP1 + off)
    assert pt["take_profit_2"] == pytest.approx(FUT_TP2 + off)
    msg = job.notifier.send_message.call_args[0][0]
    assert f"Entry {SPOT_ASK:g}" in msg and "precio MT5" in msg and "4190" in msg


def test_open_short_uses_bid_and_keeps_the_stop_above(monkeypatch) -> None:
    _, pt = _open(_on(), _gold_reader(), monkeypatch, direction="short")
    off = SPOT_BID - FUT
    assert pt["entry_price"] == SPOT_BID and pt["price_source"] == "mt5"
    assert pt["stop_loss"] == pytest.approx(SHORT_STOP + off) and pt["stop_loss"] > SPOT_ASK
    assert pt["take_profit_1"] == pytest.approx(SHORT_TP1 + off) and pt["take_profit_1"] < SPOT_BID


def test_open_with_flag_off_is_identical_to_before(monkeypatch) -> None:
    _, pt = _open(_settings(), _gold_reader(), monkeypatch)
    assert pt["entry_price"] == FUT and pt["stop_loss"] == FUT_STOP
    assert pt["price_source"] is None and pt["source_entry_price"] is None


def test_open_with_mt5_down_stays_on_yahoo(monkeypatch) -> None:
    _, pt = _open(_on(), _gold_reader(connected=False), monkeypatch)
    assert pt["price_source"] == "yahoo" and pt["entry_price"] == FUT


# ------------------------------------------------------------------- agente IA
def _decision(repo: Repository, *, gold: bool, source: str | None, reward: float | None,
              tag: str = PREREG_TAG, intended: str = "execute", closed: bool = True) -> int:
    alert_id = int(uuid4().int % 10_000_000)
    entry, stop = (FUT, FUT_STOP) if gold else (1.1, 1.099)
    latest = entry + (entry - stop) * (reward if reward is not None else 0.0)
    now = datetime.now(timezone.utc).isoformat()
    repo.create_paper_trade({
        "alert_id": alert_id, "token_id": 1, "category": "gold" if gold else "forex",
        "chain": "x", "token_address": "GC=F" if gold else "EURUSD=X",
        "symbol": "GC=F" if gold else "EURUSD=X", "thesis": "t", "readiness_grade": "B",
        "entry_price": entry, "latest_price": latest, "stop_loss": stop,
        "take_profit_1": None, "take_profit_2": None, "invalidation": None,
        "status": "stopped_simulated" if closed else "open", "unrealized_return_pct": 0,
        "opened_at": now, "updated_at": now, "closed_at": now if closed else None,
        "original_stop_loss": stop, "strategy_name": "mean_reversion", "direction": "long",
        "price_source": source,
    })
    pt = repo.fetch_paper_trade_by_alert_id(alert_id)
    x = [1.0] + [0.0] * (len(FEATURE_NAMES_V2) - 1)
    return repo.create_ai_agent_decision({
        "paper_trade_id": pt["id"], "created_at": now, "symbol": pt["symbol"],
        "category": pt["category"], "strategy_name": "mean_reversion", "direction": "long",
        "features_json": json.dumps(x), "mean_r": 0.0, "std_r": 0.1, "sampled_r": 0.0,
        "intended": intended, "executed": False, "model_n": 0, "agent_version": 2,
        "policy_tag": tag})


def test_policy_tag_px_suffix_only_with_the_flag() -> None:
    repo = _repo()
    assert AiAgent(_v2_settings(), repo).policy_tag() == PREREG_TAG          # flag OFF: igual
    agent = AiAgent(_v2_settings(paper_price_from_mt5=True), repo)
    assert agent.policy_tag() == PREREG_TAG + "|px0"                          # sin reconstruir
    m = agent.load_model()
    m.meta["excludes_mixed_gold"] = True
    agent.save_model(m)
    assert agent.policy_tag() == PREREG_TAG + "|px1"
    assert AiAgent(_v2_settings(), repo).policy_tag() == PREREG_TAG          # meta no cambia OFF
    assert AiAgent(replace(_v2_settings(), ai_agent_version=1, paper_price_from_mt5=True),
                   repo).policy_tag().startswith("v1|")


def test_model_meta_roundtrip_and_survives_updates() -> None:
    m = LinearThompson(FEATURE_NAMES_V2)
    m.meta["excludes_mixed_gold"] = True
    m2 = LinearThompson.from_json(m.to_json(), FEATURE_NAMES_V2, 0.25, 1.0)
    m2.update([1.0] + [0.0] * 23, -1.0)
    m3 = LinearThompson.from_json(m2.to_json(), FEATURE_NAMES_V2, 0.25, 1.0)
    assert m3.meta == {"excludes_mixed_gold": True} and m3.n == 1
    old = json.loads(m.to_json())
    old.pop("meta")                                            # estado guardado por v3.14.0
    assert LinearThompson.from_json(json.dumps(old), FEATURE_NAMES_V2, 0.25, 1.0).meta == {}


def test_learn_skips_mixed_gold_only_with_the_flag() -> None:
    for flag, expected_n in ((False, 2), (True, 1)):
        repo = _repo()
        _decision(repo, gold=True, source=None, reward=-3.5)                 # oro mezclado
        _decision(repo, gold=False, source=None, reward=-1.0)                # forex viejo: cuenta
        agent = AiAgent(_v2_settings(paper_price_from_mt5=flag), repo)
        assert agent.learn() == expected_n
        rows = repo.fetch_ai_agent_decisions()
        assert all(d["reward_r"] is not None for d in rows)                  # R a la vista igual
        assert agent.load_model().n == expected_n


def test_scoreboard_never_measures_mixed_gold() -> None:
    repo = _repo()
    _decision(repo, gold=True, source=None, reward=-3.5)
    _decision(repo, gold=True, source="mt5", reward=-1.0)
    _decision(repo, gold=False, source=None, reward=0.5)
    agent = AiAgent(_v2_settings(), repo)
    agent.learn()
    sb = agent.scoreboard(version=2)
    assert sb["rewarded"] == 2 and sb["excluded_mixed_gold"] == 1
    assert sb["execute_all_mean_r"] == pytest.approx(-0.25, abs=1e-6)        # (−1 + 0.5) / 2
    rows = repo.fetch_ai_agent_decisions()
    assert sum(mixed_gold_decision(d) for d in rows) == 1


def test_realism_gap_uses_only_single_source_executions_with_the_flag() -> None:
    """Adenda 2: NZDUSD #26 entró en MT5 con el SL/TP del paper sobre otra entrada
    (stop real de 0.4 pips) → R_mt5 +10.95 vs +1.69 en paper → ĝ clavado en +0.25."""
    repo = _repo()
    did = _decision(repo, gold=True, source=None, reward=-3.5)            # oro mezclado
    repo.update_ai_agent_decision(did, {"executed": 1, "reward_r": -3.5, "mt5_r": -1.0})
    fx = _decision(repo, gold=False, source=None, reward=1.69)            # forex previo al fix
    repo.update_ai_agent_decision(fx, {"executed": 1, "reward_r": 1.69, "mt5_r": 10.95})
    assert AiAgent(_v2_settings(), repo).realism_gap() == pytest.approx(0.25)   # OFF: tope
    on = AiAgent(_v2_settings(paper_price_from_mt5=True), repo)
    assert on.realism_gap() == 0.0                                        # sin fuente única
    ok = _decision(repo, gold=False, source="mt5", reward=-1.0)
    repo.update_ai_agent_decision(ok, {"executed": 1, "reward_r": -1.0, "mt5_r": -1.2})
    assert on.realism_gap() == pytest.approx(-0.2 / 6)                    # solo la limpia


def test_status_text_shows_current_tag_and_the_fix() -> None:
    repo = _repo()
    _decision(repo, gold=False, source=None, reward=-1.0)                    # tag original
    agent = AiAgent(_v2_settings(paper_price_from_mt5=True), repo)
    agent.learn()
    text = agent.status_text("v3.14.1")
    assert PREREG_TAG + "|px0" in text
    assert "con otro tag (no cuentan acá): 1" in text
    assert "modelo sin oro mezclado: NO" in text


def test_recent_strategy_r_can_drop_mixed_gold() -> None:
    opened = datetime(2026, 10, 7, 14, tzinfo=timezone.utc)
    rows = []
    for h in range(1, 7):
        rows.append({"strategy_name": "mean_reversion", "category": "gold", "status": "stopped",
                     "closed_at": (opened - timedelta(hours=h)).isoformat(),
                     "entry_price": FUT, "latest_price": SPOT_BID, "direction": "long",
                     "original_stop_loss": FUT_STOP})                          # −3.2R falsos
    assert recent_strategy_r("mean_reversion", opened, rows) < -0.9
    assert recent_strategy_r("mean_reversion", opened, rows, exclude_mixed_gold=True) == 0.0


# --------------------------------------------------------------- warm start
def _warmstart(monkeypatch, db: Path, *extra: str) -> int:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ai_agent_warmstart_t", Path(__file__).resolve().parents[1] / "scripts" / "ai_agent_warmstart.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(db), "--version", "2", "--apply", *extra])
    return mod.main()


def test_warmstart_exclude_mixed_gold_marks_the_model(monkeypatch) -> None:
    repo = _repo()
    _decision(repo, gold=True, source=None, reward=-3.5)
    _decision(repo, gold=True, source="mt5", reward=-1.0)
    _decision(repo, gold=False, source=None, reward=0.5)
    db = repo.db_path
    assert _warmstart(monkeypatch, db) == 0
    plain = LinearThompson.from_json(repo.get_state(MODEL_STATE_KEYS[2]), FEATURE_NAMES_V2, 0.25, 1.0)
    assert plain.n == 3 and not plain.meta
    assert _warmstart(monkeypatch, db, "--exclude-mixed-gold") == 1         # ya aprendió: pide --force
    assert _warmstart(monkeypatch, db, "--exclude-mixed-gold", "--force") == 0
    clean = LinearThompson.from_json(repo.get_state(MODEL_STATE_KEYS[2]), FEATURE_NAMES_V2, 0.25, 1.0)
    assert clean.n == 2 and clean.meta["excludes_mixed_gold"] is True
    assert clean.meta["mixed_gold_excluded"] == 1
