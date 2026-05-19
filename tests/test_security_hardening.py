"""Tests de Fase 2.6 security hardening.

Cubre: Settings.__repr__ masking, safe_path traversal block, safe_optional_file,
halt clamp, position_sizer cap, score negative input, LogRedactor, safe_json.
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock

import requests

from app.analyzers.token_score import score_token
from app.database.models import SecuritySummary, TokenSnapshot
from app.risk.position_sizer import calculate_position_size
from app.utils.log_redactor import LogRedactor
from app.utils.safe_http import safe_json
from app.utils.safe_path import safe_optional_file, safe_resolve_within
from tests.test_score import _settings


# ---------- Settings.__repr__ masking ----------


def test_settings_repr_masks_telegram_token() -> None:
    base = _settings()
    settings = type(base)(
        **{**base.__dict__, "telegram_bot_token": "1234567890:AAEsuperSecretToken1234567890abcde"}
    )
    text = repr(settings)
    assert "AAEsuperSecretToken" not in text
    assert "telegram_bot_token=<redacted>" in text


def test_settings_repr_masks_mt5_password() -> None:
    base = _settings()
    settings = type(base)(
        **{**base.__dict__, "mt5_password": "myRealMT5Password123!"}
    )
    text = repr(settings)
    assert "myRealMT5Password" not in text
    assert "mt5_password=<redacted>" in text


def test_settings_repr_masks_paths_to_basename() -> None:
    base = _settings()
    text = repr(base)
    # sqlite_path debe aparecer como nombre, no como path completo
    assert "C:/Users" not in text
    assert "C:\\Users" not in text


# ---------- safe_path ----------


def test_safe_resolve_within_allows_inside_path(tmp_path) -> None:
    inside = tmp_path / "subdir" / "file.md"
    result = safe_resolve_within(inside, tmp_path)
    assert result is not None


def test_safe_resolve_within_blocks_traversal(tmp_path) -> None:
    # construir un candidate que escape via ..
    candidate = tmp_path / ".." / "evil.md"
    result = safe_resolve_within(candidate, tmp_path)
    assert result is None


def test_safe_optional_file_rejects_relative() -> None:
    result = safe_optional_file("relative/path/terminal.exe")
    assert result is None


def test_safe_optional_file_rejects_nonexistent() -> None:
    result = safe_optional_file("C:/this/path/does/not/exist/terminal.exe")
    assert result is None


def test_safe_optional_file_none_returns_none() -> None:
    assert safe_optional_file(None) is None
    assert safe_optional_file("") is None


# ---------- /halt clamp ----------


def test_halt_command_clamps_negative_hours() -> None:
    from pathlib import Path as _Path
    from uuid import uuid4
    from app.assistant.command_handler import BasicTelegramAssistant
    from app.database.db import init_db
    from app.database.repository import Repository

    db_dir = _Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"sechalt_{uuid4().hex}.db"
    init_db(db_path)
    repo = Repository(db_path)
    assistant = BasicTelegramAssistant(_settings(), repo)
    msg = assistant.handle("/halt -100")
    assert "1h" in msg  # clamped to min


def test_halt_command_clamps_above_max() -> None:
    from pathlib import Path as _Path
    from uuid import uuid4
    from app.assistant.command_handler import BasicTelegramAssistant
    from app.database.db import init_db
    from app.database.repository import Repository

    db_dir = _Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"sechaltmax_{uuid4().hex}.db"
    init_db(db_path)
    repo = Repository(db_path)
    assistant = BasicTelegramAssistant(_settings(), repo)
    msg = assistant.handle("/halt 9999")
    assert "168h" in msg


# ---------- position_sizer cap ----------


def test_position_sizer_rejects_risk_pct_above_cap() -> None:
    result = calculate_position_size(
        entry=100.0, stop=95.0, account_balance=10000.0, risk_pct=50.0
    )
    assert result.invalid_reason is not None
    assert "safety cap" in result.invalid_reason


def test_position_sizer_accepts_risk_pct_within_cap() -> None:
    result = calculate_position_size(
        entry=100.0, stop=95.0, account_balance=10000.0, risk_pct=2.0
    )
    assert result.invalid_reason is None


# ---------- score_token sanitize ----------


def test_score_token_handles_negative_liquidity() -> None:
    snap = TokenSnapshot(
        chain="base", token_address="0xabc", symbol="TEST",
        liquidity_usd=-1000.0,  # data corrupta
        volume_5m=10000, volume_1h=30000,
    )
    security = SecuritySummary(raw_summary="unknown")
    result = score_token(snap, security, _settings())
    # No crashea, retorna score valido
    assert 0 <= result.score <= 100


# ---------- LogRedactor ----------


def test_log_redactor_masks_telegram_token_pattern(caplog) -> None:
    redactor = LogRedactor()
    logger = logging.getLogger("test_redactor_pattern")
    logger.addFilter(redactor)
    with caplog.at_level(logging.INFO, logger="test_redactor_pattern"):
        logger.info("Token: 1234567890:AAEabcdefghijklmnopqrstuvwxyzABCDEFGHIJ")
    full = " ".join(r.getMessage() for r in caplog.records)
    assert "AAEabcdefghij" not in full
    assert "<redacted-token>" in full


def test_log_redactor_replaces_known_secret_values(caplog) -> None:
    redactor = LogRedactor(secret_values=["mySecretPassw0rdValue"])
    logger = logging.getLogger("test_redactor_known")
    logger.addFilter(redactor)
    with caplog.at_level(logging.INFO, logger="test_redactor_known"):
        logger.info("Connecting with mySecretPassw0rdValue to server")
    full = " ".join(r.getMessage() for r in caplog.records)
    assert "mySecretPassw0rdValue" not in full
    assert "<redacted>" in full


def test_log_redactor_passes_clean_messages_through(caplog) -> None:
    redactor = LogRedactor(secret_values=["someSecret"])
    logger = logging.getLogger("test_redactor_clean")
    logger.addFilter(redactor)
    with caplog.at_level(logging.INFO, logger="test_redactor_clean"):
        logger.info("All good here, normal message")
    full = " ".join(r.getMessage() for r in caplog.records)
    assert full == "All good here, normal message"


# ---------- safe_json ----------


def test_safe_json_returns_default_on_invalid() -> None:
    response = MagicMock()
    response.json.side_effect = ValueError("bad json")
    result = safe_json(response, default={"fallback": True})
    assert result == {"fallback": True}


def test_safe_json_returns_parsed_on_valid() -> None:
    response = MagicMock()
    response.json.return_value = {"data": "ok"}
    result = safe_json(response)
    assert result == {"data": "ok"}
