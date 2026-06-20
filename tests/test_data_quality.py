"""Tests para data_quality monitor."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.intelligence.data_quality import (
    collector_failure_check,
    gap_check,
    run_full_check,
    staleness_check,
)
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"dq_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_token(repo: Repository, symbol: str, last_seen_minutes_ago: int) -> None:
    """Seedea un token con last_seen_at apropiado para el test."""
    snap = TokenSnapshot(
        chain="stock", token_address=symbol, category="stock",
        symbol=symbol, name=symbol, price=100.0,
    )
    estimate = EstimateResult(
        estimated_gain_pct=5, estimated_loss_pct=2, confidence=70,
        label="test", reasons=[], eligible_for_gain_alert=True,
    )
    repo.upsert_token(snap, 75, "orange", estimate)
    # Forzar last_seen_at en el pasado
    target = datetime.now(timezone.utc) - timedelta(minutes=last_seen_minutes_ago)
    import sqlite3
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE tokens SET last_seen_at = ? WHERE token_address = ?",
            (target.isoformat(), symbol),
        )


def test_staleness_flags_old_tokens() -> None:
    repo = _repo()
    _seed_token(repo, "NVDA", last_seen_minutes_ago=30)  # stale (>15min)
    _seed_token(repo, "AAPL", last_seen_minutes_ago=5)   # fresh
    stale = staleness_check(repo, max_minutes=15)
    symbols_stale = {s["symbol"] for s in stale}
    assert "NVDA" in symbols_stale
    assert "AAPL" not in symbols_stale


def test_staleness_returns_empty_when_no_tokens() -> None:
    repo = _repo()
    assert staleness_check(repo) == []


def test_collector_failure_check_returns_dict() -> None:
    repo = _repo()
    result = collector_failure_check(repo)
    assert "failures_24h" in result


def test_run_full_check_persists_log() -> None:
    repo = _repo()
    settings = _settings()
    _seed_token(repo, "NVDA", last_seen_minutes_ago=30)
    summary = run_full_check(repo, settings)
    assert "stale_symbols" in summary
    log_rows = repo.fetch_data_quality_log(limit=5)
    assert len(log_rows) >= 1


def test_gap_check_detects_gap_and_passes_real_chain() -> None:
    """v3.9.3: gap_check recibe el chain REAL (antes usaba '*' que nunca matchea
    porque fetch_snapshots_in_window filtra chain exacto) y detecta el gap."""
    now = datetime.now(timezone.utc)
    captured: dict = {"chain": None}

    class _Repo:
        def fetch_snapshots_in_window(self, chain, token_address, start_iso, end_iso):
            captured["chain"] = chain
            t0 = now - timedelta(hours=2)
            return [
                {"captured_at": t0.isoformat()},
                {"captured_at": (t0 + timedelta(minutes=15)).isoformat()},
                {"captured_at": (t0 + timedelta(minutes=105)).isoformat()},  # gap 90min
            ]

    gaps = gap_check(_Repo(), "EURUSD", chain="forex")
    assert captured["chain"] == "forex"  # pasa el chain real, no "*"
    assert len(gaps) == 1
    assert gaps[0]["gap_minutes"] == 90
