"""Tests para comandos Telegram Phase 4."""

from pathlib import Path
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_score import _settings


def _assistant() -> BasicTelegramAssistant:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"tg_p4_{uuid4().hex}.db"
    init_db(db_path)
    repo = Repository(db_path)
    return BasicTelegramAssistant(_settings(), repo)


def test_mt5_status_returns_not_connected_when_disabled() -> None:
    a = _assistant()
    msg = a.handle("/mt5_status")
    assert "MT5 reader: NO conectado" in msg


def test_data_quality_runs_without_crash() -> None:
    a = _assistant()
    msg = a.handle("/data_quality")
    assert "Data quality" in msg
    assert "Symbols stale" in msg


def test_walk_forward_returns_help_when_no_args() -> None:
    a = _assistant()
    msg = a.handle("/walk_forward")
    assert "Uso:" in msg


def test_walk_forward_handles_no_data() -> None:
    a = _assistant()
    msg = a.handle("/walk_forward breakout 30 stock")
    assert "breakout" in msg
    # Sin data deberia decir "sin ventanas"
    assert "sin ventanas" in msg.lower() or "ventanas" in msg.lower()


def test_export_csv_default_outcomes(tmp_path, monkeypatch) -> None:
    # Cambiar cwd a tmp para que el export caiga ahi
    monkeypatch.chdir(tmp_path)
    a = _assistant()
    msg = a.handle("/export_csv outcomes")
    assert "Export OK" in msg
    assert "outcomes" in msg


def test_export_csv_invalid_kind() -> None:
    a = _assistant()
    msg = a.handle("/export_csv badthing")
    assert "Uso:" in msg
