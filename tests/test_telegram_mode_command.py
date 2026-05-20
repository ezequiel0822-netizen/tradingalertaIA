"""Tests para comando Telegram /mode."""

from pathlib import Path
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_score import _settings


def _assistant() -> BasicTelegramAssistant:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"tg_mode_{uuid4().hex}.db"
    init_db(db_path)
    repo = Repository(db_path)
    return BasicTelegramAssistant(_settings(), repo)


def test_mode_no_arg_shows_current() -> None:
    a = _assistant()
    msg = a.handle("/mode")
    assert "Modo actual" in msg
    assert "trader" in msg or "alerts_only" in msg or "hybrid" in msg


def test_mode_sets_alerts_only() -> None:
    a = _assistant()
    msg = a.handle("/mode alerts_only")
    assert "Modo cambiado a: alerts_only" in msg
    # Persisted in bot_state
    assert a.repository.get_state("bot_mode_active") == "alerts_only"


def test_mode_sets_trader() -> None:
    a = _assistant()
    a.repository.set_state("bot_mode_active", "alerts_only")
    msg = a.handle("/mode trader")
    assert "trader" in msg
    assert a.repository.get_state("bot_mode_active") == "trader"


def test_mode_rejects_invalid() -> None:
    a = _assistant()
    msg = a.handle("/mode banana")
    assert "invalido" in msg.lower() or "valid" in msg.lower()


def test_mode_alias_with_space() -> None:
    a = _assistant()
    msg = a.handle("mode hybrid")
    assert "hybrid" in msg
