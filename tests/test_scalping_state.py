"""v2.6.0 Phase 5.5 Bloque B — resolve_scalping_state.

Verifica que la prioridad CLI > bot_state > setting > default se respeta y
que el kill-switch is_scalping_halted lee correctamente del bot_state.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.repository import Repository
from app.utils.scalping_state import (
    is_scalping_halted,
    resolve_scalping_state,
)
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"scalping_state_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _with_setting(value: bool):
    base = _settings()
    return type(base)(**{**base.__dict__, "enable_scalping_engine": value})


def test_default_state_is_false_without_overrides() -> None:
    """Sin setting, sin bot_state, sin CLI → False."""
    repo = _repo()
    assert resolve_scalping_state(_with_setting(False), repo) is False


def test_setting_true_resolves_true() -> None:
    """Con setting True y nada en bot_state → True."""
    repo = _repo()
    assert resolve_scalping_state(_with_setting(True), repo) is True


def test_bot_state_overrides_setting() -> None:
    """bot_state.scalping_active=true override del setting=false."""
    repo = _repo()
    repo.set_state("scalping_active", "true")
    assert resolve_scalping_state(_with_setting(False), repo) is True

    repo.set_state("scalping_active", "false")
    assert resolve_scalping_state(_with_setting(True), repo) is False


def test_cli_override_wins_over_all() -> None:
    """CLI flag override absoluto, ignora bot_state y setting."""
    repo = _repo()
    repo.set_state("scalping_active", "false")
    assert (
        resolve_scalping_state(_with_setting(False), repo, cli_override="on")
        is True
    )
    repo.set_state("scalping_active", "true")
    assert (
        resolve_scalping_state(_with_setting(True), repo, cli_override="off")
        is False
    )


def test_cli_override_ignores_invalid_values() -> None:
    """CLI flag con valor invalido (ej. 'maybe') cae al siguiente nivel."""
    repo = _repo()
    repo.set_state("scalping_active", "true")
    # 'maybe' no es interpretable → ignora CLI, usa bot_state=true.
    assert (
        resolve_scalping_state(_with_setting(False), repo, cli_override="maybe")
        is True
    )


def test_is_scalping_halted_defaults_false() -> None:
    """Sin scalping_halted en bot_state → no esta halt."""
    repo = _repo()
    assert is_scalping_halted(repo) is False


def test_is_scalping_halted_reads_state() -> None:
    """scalping_halted=true → halt activo."""
    repo = _repo()
    repo.set_state("scalping_halted", "true")
    assert is_scalping_halted(repo) is True
    repo.set_state("scalping_halted", "false")
    assert is_scalping_halted(repo) is False
