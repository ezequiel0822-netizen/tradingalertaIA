"""v2.5.5 — comando /health en Telegram.

Verifica que el panel de salud devuelve las secciones esperadas, refleja el
estado de auto-confirm, y no crashea con DB vacía.
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
    db_path = db_dir / f"health_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_health_message_contains_all_sections() -> None:
    """Output debe incluir las secciones core: MT5, trades, riesgo, kill-switch, auto-orders."""
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/health")
    assert "Trading Alert AI" in msg
    assert "MT5:" in msg
    assert "demo trading:" in msg
    assert "auto-confirm:" in msg
    assert "real trading:" in msg
    assert "Paper trades open:" in msg
    assert "Riesgo agregado:" in msg
    assert "cap default:" in msg
    assert "cap demo:" in msg
    assert "Kill switch:" in msg
    assert "Demo trading halt:" in msg
    assert "Auto-orders demo" in msg


def test_health_message_reflects_auto_confirm_flag() -> None:
    """El flag enable_auto_confirm_demo debe reflejarse como ON u OFF."""
    repo = _repo()
    assistant_off = BasicTelegramAssistant(
        _demo_settings(enable_auto_confirm_demo=False), repo
    )
    msg_off = assistant_off.handle("/health")
    assert "auto-confirm: OFF" in msg_off

    assistant_on = BasicTelegramAssistant(
        _demo_settings(enable_auto_confirm_demo=True), repo
    )
    msg_on = assistant_on.handle("/health")
    assert "auto-confirm: ON" in msg_on


def test_health_message_works_with_empty_db() -> None:
    """DB sin trades ni orders debe responder sin crashear y reportar zeros."""
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/health")
    assert "Paper trades open: 0" in msg
    assert "Ultima auto-order: ninguna registrada todavia" in msg


def test_health_command_aliases() -> None:
    """Tanto /health como /salud disparan el mismo handler."""
    repo = _repo()
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg_health = assistant.handle("/health")
    msg_salud = assistant.handle("/salud")
    # No comparar exact match porque incluye timestamps, pero deberían tener mismas secciones.
    assert "MT5:" in msg_health and "MT5:" in msg_salud
    assert "Paper trades open:" in msg_health and "Paper trades open:" in msg_salud
