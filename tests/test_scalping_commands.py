"""v2.6.0 Phase 5.5 Bloque B — comandos scalping Telegram.

Tests de los handlers nuevos:
- /scalping_on, /scalping_off (persistencia en bot_state)
- /scalping_halt, /scalping_resume
- /scalping_status, /scalping_stats
- /mode macro (swing_only, scalping_only, hybrid)
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_mt5_demo_trader import _demo_settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"scalping_cmd_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_scalping_on_off_persists_state() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)

    msg_on = assistant.handle("/scalping_on")
    assert "ON" in msg_on
    assert repo.get_state("scalping_active") == "true"

    msg_off = assistant.handle("/scalping_off")
    assert "OFF" in msg_off
    assert repo.get_state("scalping_active") == "false"


def test_scalping_halt_resume_persists_state() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)

    msg_halt = assistant.handle("/scalping_halt")
    assert "HALTED" in msg_halt
    assert repo.get_state("scalping_halted") == "true"

    msg_resume = assistant.handle("/scalping_resume")
    assert "resumed" in msg_resume.lower()
    assert repo.get_state("scalping_halted") == "false"


def test_scalping_status_shows_caps_and_state() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/scalping_status")
    assert "Scalping engine:" in msg
    assert "Trades abiertos:" in msg
    assert "Trades hoy:" in msg
    assert "Simbolos:" in msg


def test_scalping_stats_empty_state() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/scalping_stats")
    assert "Sin outcomes scalping todavia" in msg


def test_mode_macro_swing_only() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/mode swing_only")
    assert "SWING_ONLY" in msg
    assert repo.get_state("bot_mode_active") == "trader"
    assert repo.get_state("scalping_active") == "false"


def test_mode_macro_scalping_only() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/mode scalping_only")
    assert "SCALPING_ONLY" in msg
    assert repo.get_state("bot_mode_active") == "alerts_only"
    assert repo.get_state("scalping_active") == "true"


def test_mode_macro_hybrid() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/mode hybrid")
    assert "HYBRID" in msg
    assert repo.get_state("bot_mode_active") == "trader"
    assert repo.get_state("scalping_active") == "true"


def test_mode_no_arg_shows_current_state() -> None:
    repo = _repo()
    repo.set_state("scalping_active", "true")
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/mode")
    assert "Modo bot:" in msg
    assert "Scalping: ON" in msg


def test_mode_basic_trader_keeps_scalping_state() -> None:
    """Cambiar a /mode trader NO debe tocar scalping_active."""
    repo = _repo()
    repo.set_state("scalping_active", "true")
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/mode trader")
    assert "trader" in msg.lower()
    # scalping no toca:
    assert repo.get_state("scalping_active") == "true"


def test_health_includes_scalping_section() -> None:
    """v2.5.5 /health ahora debe incluir seccion Scalping engine."""
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/health")
    assert "Scalping engine:" in msg
    assert "trades hoy:" in msg
    assert "abiertos:" in msg
    assert "simbolos:" in msg
