"""v2.6.9 — /gate_preview Telegram command tests.

Verifica:
- Comando responde a /gate_preview, /preview_gate, /learning_gate, "preview gate".
- Sin samples suficientes, mensaje informa "no filtraria nada".
- Con samples insuficientes (< min_samples) marca como PASS(insuf).
- Settings actuales aparecen en la respuesta para transparencia.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"gate_preview_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_gate_preview_command_responds_to_all_aliases():
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)

    for alias in ["/gate_preview", "/preview_gate", "/learning_gate", "preview gate"]:
        response = assistant.handle(alias)
        assert "Learning Gate Preview" in response, f"alias {alias!r} no responde"


def test_gate_preview_shows_current_settings():
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)
    response = assistant.handle("/gate_preview")

    # Debe mostrar los settings actuales para transparencia
    assert "min_samples" in response
    assert "min_wr" in response
    assert "ENABLE_LEARNING_GATE" in response
    assert "FORCE_FOR_MEMECOIN" in response


def test_gate_preview_empty_db_says_no_features():
    """DB sin outcomes → mensaje claro indicando no se filtrara nada."""
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)
    response = assistant.handle("/gate_preview")

    assert "no filtraria nada" in response.lower() or "no hay features" in response.lower()


def test_gate_preview_includes_disclaimer():
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)
    response = assistant.handle("/gate_preview")
    assert "No es recomendacion financiera" in response


def test_gate_preview_handles_repository_error_gracefully(monkeypatch):
    """Si rank_top_strategies tira excepción, el comando NO crashea."""
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)

    # Mock para forzar excepción
    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(
        "app.assistant.command_handler.rank_top_strategies", boom
    )
    response = assistant.handle("/gate_preview")
    assert "Error: RuntimeError" in response
