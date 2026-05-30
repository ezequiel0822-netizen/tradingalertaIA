"""Tests para la señal de aprendizaje honesta (realized R + quarantine)."""

from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.learning.trade_outcomes import (
    build_strategy_performance,
    is_artifact,
    outcome_label,
    r_multiple,
    realized_return_pct,
    risk_at_entry_pct,
)
from app.learning.training_engine import _refresh_strategy_performance
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


def _trade(**kw):
    base = {
        "strategy_name": "breakout",
        "category": "forex",
        "entry_price": 100.0,
        "latest_price": 100.0,
        "original_stop_loss": 95.0,
        "stop_loss": 95.0,
        "take_profit_1": 105.0,
        "take_profit_2": 110.0,
        "direction": "long",
        "partial_closed": 0,
        "status": "stopped_simulated",
        "closed_at": "2026-05-20T00:00:00+00:00",
    }
    base.update(kw)
    return base


# ---- realized return (direction-aware + partial close) ----

def test_realized_return_long() -> None:
    assert realized_return_pct(_trade(latest_price=110.0)) == 10.0


def test_realized_return_short() -> None:
    # short gana cuando el precio baja
    assert realized_return_pct(_trade(direction="short", latest_price=90.0)) == 10.0


def test_realized_return_partial_close_blends_tp1_and_final() -> None:
    # long: TP1=105 (+5%), pierna final latest=95 (-5%), frac 0.5 -> 0
    t = _trade(latest_price=95.0, take_profit_1=105.0, partial_closed=1)
    assert realized_return_pct(t, partial_fraction=0.5) == 0.0


# ---- risk + R-multiple ----

def test_risk_at_entry_long_and_short() -> None:
    assert risk_at_entry_pct(_trade()) == 5.0
    assert risk_at_entry_pct(_trade(direction="short", original_stop_loss=105.0)) == 5.0


def test_r_multiple_uses_original_stop() -> None:
    # +10% realizado / 5% riesgo = +2R; aun si el stop actual se movió a breakeven
    assert r_multiple(_trade(latest_price=110.0, stop_loss=100.0)) == 2.0


def test_outcome_label() -> None:
    assert outcome_label(_trade(latest_price=110.0)) == "win"
    assert outcome_label(_trade(latest_price=90.0)) == "loss"
    assert outcome_label(_trade(latest_price=100.0)) == "scratch"


# ---- quarantine de artifacts ----

def test_is_artifact_frozen_price_is_artifact() -> None:
    assert is_artifact(_trade(latest_price=100.0)) is True   # latest == entry (congelado)


def test_is_artifact_moved_price_not_artifact() -> None:
    assert is_artifact(_trade(latest_price=104.0)) is False


def test_is_artifact_open_trade_not_artifact() -> None:
    assert is_artifact(_trade(status="open", closed_at=None, latest_price=100.0)) is False


def test_build_strategy_performance_excludes_artifacts() -> None:
    trades = [
        _trade(latest_price=100.0),   # artifact (precio congelado)
        _trade(latest_price=100.0),   # artifact
        _trade(latest_price=110.0),   # win real -> +2R
        _trade(latest_price=90.0),    # loss real -> -2R
    ]
    perfs = build_strategy_performance(trades)
    assert len(perfs) == 1
    p = perfs[0]
    assert (p.strategy_name, p.category) == ("breakout", "forex")
    assert p.trades == 2
    assert p.artifacts_excluded == 2
    assert p.wins == 1 and p.losses == 1
    assert abs(p.avg_r - 0.0) < 1e-9  # (+2 + -2)/2


# ---- integración: persistencia vía learning cycle helper ----

def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"tradeout_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_closed(repo, symbol, entry, latest, ostop, strategy, direction="long") -> None:
    snap = TokenSnapshot(
        chain="forex", token_address=symbol, category="forex", symbol=symbol,
        price=entry, liquidity_usd=1_000_000,
    )
    est = EstimateResult(
        estimated_gain_pct=2, estimated_loss_pct=1, confidence=70,
        label="paper", reasons=[], eligible_for_gain_alert=True,
    )
    tid = repo.upsert_token(snap, 80, "orange", est)
    now = utc_now_iso()
    trade = {
        "alert_id": int(uuid4().int % 10_000_000), "token_id": tid, "category": "forex",
        "chain": "forex", "token_address": symbol, "symbol": symbol, "thesis": "t",
        "readiness_grade": "B", "entry_price": entry, "latest_price": latest,
        "stop_loss": ostop, "take_profit_1": entry * 1.01, "take_profit_2": entry * 1.02,
        "invalidation": None, "status": "stopped_simulated", "unrealized_return_pct": 0,
        "opened_at": now, "updated_at": now, "closed_at": now, "mfe_pct": 0, "mae_pct": 0,
        "original_stop_loss": ostop, "trailing_active": 0, "strategy_name": strategy,
        "direction": direction,
    }
    assert repo.create_paper_trade(trade) is True


def test_refresh_strategy_performance_persists_and_excludes_artifacts() -> None:
    repo = _repo()
    settings = _settings()
    _seed_closed(repo, "EURUSD", 100.0, 110.0, 95.0, "breakout")  # real win, +2R
    _seed_closed(repo, "GBPUSD", 100.0, 100.0, 95.0, "breakout")  # artifact (frozen)

    n = _refresh_strategy_performance(repo, settings)
    assert n >= 1

    rows = repo.fetch_strategy_performance()
    row = next(
        r for r in rows
        if r["strategy_name"] == "breakout" and r["category"] == "forex"
    )
    assert row["trades"] == 1            # artifact excluido
    assert row["artifacts_excluded"] == 1
    assert row["wins"] == 1
    assert abs(row["avg_r"] - 2.0) < 1e-6
