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
    """v2.6.0: output cambió a 'Modo bot: ...' + linea de scalping."""
    a = _assistant()
    msg = a.handle("/mode")
    assert "Modo bot:" in msg
    assert "trader" in msg or "alerts_only" in msg or "hybrid" in msg
    assert "Scalping:" in msg  # v2.6.0 incluye estado scalping


def test_mode_sets_alerts_only() -> None:
    """v2.6.0: string 'Modo bot cambiado a:' (preserva scalping_active)."""
    a = _assistant()
    msg = a.handle("/mode alerts_only")
    assert "alerts_only" in msg.lower()
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
    """v2.6.0: hybrid es macro que setea ambos flags, output dice HYBRID."""
    a = _assistant()
    msg = a.handle("mode hybrid")
    assert "hybrid" in msg.lower()
    # v2.6.0: hybrid macro setea ambos flags
    assert a.repository.get_state("scalping_active") == "true"
    assert a.repository.get_state("bot_mode_active") == "trader"
