"""v3.17.0 — contador de frenados (/frenados) y conteos del quality gate (/filtro).

Solo registro: ninguno cambia decisiones. /filtro nunca muestra resultados de trades
(regla de no mirar de research/CALIDAD_SOMBRA_2026-10-12.md).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.models import AlertRecord, EstimateResult, SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from app.risk.block_log import reason_code
from app.scheduler import jobs as jobs_mod
from app.scheduler.jobs import TradingAlertJob, _note_block
from app.strategies.base import StrategySignal
from app.utils.time_utils import utc_now
from tests.test_score import _settings


def _repo() -> Repository:
    d = Path.cwd() / ".test_dbs"
    d.mkdir(exist_ok=True)
    p = d / f"blocks_{uuid4().hex}.db"
    init_db(p)
    return Repository(p)


def _on(**kw):
    return replace(_settings(), enable_discard_log=True, **kw)


# ------------------------------------------------------------- normalización
def test_reason_code_groups_by_type() -> None:
    assert reason_code("max_open_trades_total reached (5/5)") == "max_open_trades_total reached"
    assert reason_code("symbol_cooldown_active (AAPL, last trade <15min ago)") == (
        "symbol_cooldown_active")
    assert reason_code("kill switch active: daily drawdown -3.1% (hasta x)") == "kill switch active"
    assert reason_code("demo_max_total_risk_pct exceeded (1.20+0.50>2.0)") == (
        "demo_max_total_risk_pct exceeded")
    assert reason_code("máx. 3 posiciones del agente abiertas") == (
        "máx. n posiciones del agente abiertas")
    assert reason_code("risk_pct 12.5 > 10") == "risk_pct n > n"
    assert reason_code(None) == "sin motivo" and reason_code("   ") == "sin motivo"


# ------------------------------------------------------------- contador
class _J:
    def __init__(self, settings, repo):
        self.settings, self.repository = settings, repo


def test_off_by_default_writes_nothing() -> None:
    repo = _repo()
    _note_block(_J(_settings(), repo), "riesgo", "x", "forex", "EURUSD|b|long")
    assert repo.fetch_candidate_blocks("2000-01-01") == []


def test_counts_events_and_distinct_setups_per_day(monkeypatch) -> None:
    repo = _repo()
    job = _J(_on(), repo)
    for _ in range(3):                                   # el mismo setup, 3 ciclos
        _note_block(job, "riesgo", "max_open_trades_total reached (5/5)", "forex", "EURUSD|b|long")
    _note_block(job, "riesgo", "max_open_trades_total reached (5/5)", "forex", "GBPUSD|b|short")
    (row,) = repo.fetch_candidate_blocks("2000-01-01")
    assert (row["stage"], row["reason"], row["category"]) == (
        "riesgo", "max_open_trades_total reached", "forex")
    assert row["events"] == 4 and row["unique_setups"] == 2

    later = utc_now() + timedelta(days=1)               # cambia el día: setups de nuevo
    monkeypatch.setattr(jobs_mod, "utc_now", lambda: later)
    _note_block(job, "riesgo", "max_open_trades_total reached (5/5)", "forex", "EURUSD|b|long")
    rows = repo.fetch_candidate_blocks("2000-01-01")
    assert [(r["day"] == later.date().isoformat(), r["unique_setups"]) for r in rows][0] == (True, 1)


def test_counter_soft_fails() -> None:
    broken = SimpleNamespace(bump_candidate_block=MagicMock(side_effect=RuntimeError("db")))
    _note_block(_J(_on(), broken), "riesgo", "x", "forex", "s")       # no lanza


class _OpenJob:
    _try_open_paper_trades = TradingAlertJob._try_open_paper_trades

    def __init__(self, settings, repo, signal, risk=(True, ""), open_positions=None):
        self.settings = settings
        self.repository = repo
        self.mt5_reader = None
        self.notifier = MagicMock()
        self.prepared = []
        self.strategy_router = SimpleNamespace(route=lambda ctx, s: [signal])
        self.portfolio_manager = SimpleNamespace(
            get_open_positions=lambda: list(open_positions or []),
            account_balance=lambda: 10_000.0)
        self.risk_manager = SimpleNamespace(check_can_open_trade=lambda *a, **k: risk)

    def _try_prepare_demo_order(self, paper_trade):
        self.prepared.append(paper_trade)


def _run(job, monkeypatch, symbol="EURUSD=X"):
    import app.analyzers.technical_patterns as tp

    pattern = SimpleNamespace(rsi=55.0, atr_pct=0.5, macd=0.1, macd_signal=0.05,
                              vwap_dist_pct=None, vwap_week_dist_pct=None, hurst=0.55,
                              candle_clv=0.7, candle_strength="strong")
    monkeypatch.setattr(tp, "analyze_ohlcv", lambda candles: pattern)
    snap = TokenSnapshot(chain="forex", token_address=symbol, category="forex", symbol=symbol,
                         price=1.1, liquidity_usd=None, raw={"candles": [{"close": 1.1}]})
    est = EstimateResult(estimated_gain_pct=0, estimated_loss_pct=0, confidence=50,
                         label="x", reasons=[], eligible_for_gain_alert=False)
    token_id = job.repository.upsert_token(snap, 50, "low", est)
    record = AlertRecord(token_id=token_id, alert_type="X", snapshot=snap, app_version="t",
                         category="forex", score=50, risk_level="low", reasons=["x"],
                         security=SecuritySummary(raw_summary="unknown"), estimate=est)
    job._try_open_paper_trades(snap, record, set())


def _sig(stop=1.09) -> StrategySignal:
    return StrategySignal(strategy_name="breakout", direction="long", entry=1.1, stop=stop,
                          targets=[1.12, 1.14], confidence=70, reasoning=["x"],
                          time_horizon_hours=8)


def test_open_path_counts_risk_sizing_and_already_open(monkeypatch) -> None:
    repo = _repo()
    blocked = _OpenJob(_on(), repo, _sig(), risk=(False, "max_open_trades_total reached (5/5)"))
    _run(blocked, monkeypatch)
    bad_stop = _OpenJob(_on(), repo, _sig(stop=1.2))          # stop del lado equivocado
    _run(bad_stop, monkeypatch)
    already = _OpenJob(_on(), repo, _sig(),
                       open_positions=[{"chain": "forex", "token_address": "EURUSD=X"}])
    _run(already, monkeypatch)
    got = {(r["stage"], r["reason"]) for r in repo.fetch_candidate_blocks("2000-01-01")}
    assert got == {("riesgo", "max_open_trades_total reached"),
                   ("sizing", "invalid stop relative to entry"),
                   ("abierto", "ya hay un paper trade abierto del simbolo")}
    assert blocked.prepared == bad_stop.prepared == already.prepared == []


def test_open_path_with_counter_off_writes_nothing(monkeypatch) -> None:
    repo = _repo()
    _run(_OpenJob(_settings(), repo, _sig(), risk=(False, "kill switch active: x")), monkeypatch)
    assert repo.fetch_candidate_blocks("2000-01-01") == []


# ------------------------------------------------------------- comandos
def test_frenados_shows_counts_and_agent_limits() -> None:
    repo = _repo()
    job = _J(_on(), repo)
    _note_block(job, "riesgo", "max_open_trades_total reached (5/5)", "forex", "EURUSD|b|long")
    _note_block(job, "mt5", "calendar gate", "gold", "GC=F|b|short")
    repo.create_ai_agent_decision({
        "paper_trade_id": 1, "created_at": utc_now().isoformat(), "features_json": "[]",
        "intended": "execute", "block_reason": "evento económico de alto impacto cerca"})
    msg = BasicTelegramAssistant(_on(), repo).handle("/frenados")
    assert "ENCENDIDO" in msg and "max_open_trades_total reached" in msg
    assert "calendar gate" in msg and "evento económico de alto impacto cerca 1" in msg
    off = BasicTelegramAssistant(_settings(), _repo()).handle("/frenos")
    assert "APAGADO (ENABLE_DISCARD_LOG=false)" in off and "sin frenos registrados" in off


def test_descartes_still_shows_unsent_alerts() -> None:
    msg = BasicTelegramAssistant(_settings(), _repo()).handle("/descartes")
    assert "descartes" in msg.lower() and "frenados" not in msg.lower()


def test_filtro_shows_only_counts() -> None:
    repo = _repo()
    base = {"created_at": utc_now().isoformat(), "gate_version": "qg1", "news_status": "n/a",
            "enforced": 0, "category": "forex", "action": "allow"}
    repo.insert_quality_shadow({**base, "paper_trade_id": 1})
    repo.insert_quality_shadow({**base, "paper_trade_id": 2, "action": "paper_only"})
    repo.insert_quality_shadow({**base, "paper_trade_id": 3, "category": "stock",
                                "action": None, "news_status": "pending"})
    s = replace(_settings(), enable_quality_gate=True, enable_ai_agent=True)
    msg = BasicTelegramAssistant(s, repo).handle("/filtro")
    assert "Anotando: SI" in msg and "reglas qg1" in msg
    assert "forex: allow 1 / paper_only 1" in msg and "stock: esperando 1" in msg
    assert "Noticias (acciones): pending 1" in msg
    assert "con el agente encendido no cambia ninguna orden" in msg
    assert "No muestra resultados" in msg
    for word in ("expectancy", "win rate", "R neto", "acierto"):
        assert word not in msg
    empty = BasicTelegramAssistant(_settings(), _repo()).handle("/filtro")
    assert "Anotando: NO (ENABLE_QUALITY_GATE=false)" in empty and "anotados: 0" in empty


def test_quality_stats_never_reads_trade_results() -> None:
    import inspect

    src = inspect.getsource(Repository.quality_shadow_stats)
    for needle in ("paper_trades", "reward_r", "unrealized_return_pct", "mt5_r"):
        assert needle not in src


def test_shadow_insert_fills_not_null_flags() -> None:
    repo = _repo()
    ok = repo.insert_quality_shadow({"paper_trade_id": 9, "created_at": "2026-10-12T00:00:00",
                                     "gate_version": "qg1", "news_status": "n/a"})
    st = repo.quality_shadow_stats()
    assert ok is True and st["rows"] == 1 and st["enforced"] == 0
    assert json.loads(json.dumps(st["by_action"])) == [
        {"category": None, "action": "esperando", "n": 1}]
