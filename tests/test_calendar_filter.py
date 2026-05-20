"""Tests para is_safe_window."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.repository import Repository
from app.intelligence.calendar_filter import currencies_for_symbol, is_safe_window


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"calfilter_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_currencies_for_symbol() -> None:
    assert currencies_for_symbol("EURUSD=X") == {"USD", "EUR"}
    assert currencies_for_symbol("XAUUSD=X") == {"USD"}
    assert currencies_for_symbol("UNKNOWN") == {"USD"}


def test_safe_when_no_events() -> None:
    repo = _repo()
    now = datetime.now(timezone.utc)
    ok, _ = is_safe_window("EURUSD=X", now, repo, buffer_min=30)
    assert ok is True


def test_blocked_when_high_impact_event_in_window() -> None:
    repo = _repo()
    now = datetime.now(timezone.utc)
    # Insertar evento USD en +15min (dentro del buffer 30)
    event_time = (now + timedelta(minutes=15)).isoformat()
    repo.upsert_economic_event({
        "event_time": event_time,
        "country": "USD",
        "impact": "high",
        "title": "NFP",
    })
    ok, reason = is_safe_window("EURUSD=X", now, repo, buffer_min=30)
    assert ok is False
    assert "NFP" in reason
