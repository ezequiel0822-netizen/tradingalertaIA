"""Tests para resolve_bot_mode con todas las fuentes de prioridad."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.database.db import init_db
from app.database.repository import Repository
from app.utils.bot_mode import (
    DEFAULT_MODE,
    VALID_MODES,
    is_valid_mode,
    normalize_mode,
    resolve_bot_mode,
)
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"botmode_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_default_when_everything_empty() -> None:
    repo = _repo()
    settings = SimpleNamespace(bot_mode="")
    assert resolve_bot_mode(settings, repo) == DEFAULT_MODE


def test_setting_wins_over_default() -> None:
    repo = _repo()
    settings = SimpleNamespace(bot_mode="alerts_only")
    assert resolve_bot_mode(settings, repo) == "alerts_only"


def test_persisted_overrides_setting() -> None:
    repo = _repo()
    repo.set_state("bot_mode_active", "alerts_only")
    settings = SimpleNamespace(bot_mode="trader")
    assert resolve_bot_mode(settings, repo) == "alerts_only"


def test_cli_override_wins_over_persisted() -> None:
    repo = _repo()
    repo.set_state("bot_mode_active", "alerts_only")
    settings = SimpleNamespace(bot_mode="trader")
    assert resolve_bot_mode(settings, repo, cli_override="hybrid") == "hybrid"


def test_invalid_cli_falls_through() -> None:
    repo = _repo()
    repo.set_state("bot_mode_active", "alerts_only")
    settings = SimpleNamespace(bot_mode="trader")
    # CLI invalido -> usa bot_state
    assert resolve_bot_mode(settings, repo, cli_override="nonsense") == "alerts_only"


def test_invalid_persisted_falls_through_to_setting() -> None:
    repo = _repo()
    repo.set_state("bot_mode_active", "garbage")
    settings = SimpleNamespace(bot_mode="hybrid")
    assert resolve_bot_mode(settings, repo) == "hybrid"


def test_is_valid_mode() -> None:
    assert is_valid_mode("trader") is True
    assert is_valid_mode("alerts_only") is True
    assert is_valid_mode("hybrid") is True
    assert is_valid_mode("") is False
    assert is_valid_mode(None) is False
    assert is_valid_mode("invalid") is False


def test_normalize_mode() -> None:
    assert normalize_mode("TRADER") == "trader"
    assert normalize_mode("  alerts_only  ") == "alerts_only"
    assert normalize_mode("bad") is None
    assert normalize_mode(None) is None


def test_valid_modes_set() -> None:
    assert "trader" in VALID_MODES
    assert "alerts_only" in VALID_MODES
    assert "hybrid" in VALID_MODES
    assert len(VALID_MODES) == 3
