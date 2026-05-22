"""v2.6.0 Phase 5.5 Bloque B Commit 4 — learning diferencia swing vs scalping.

Verifica:
- upsert_signal_outcome persiste is_scalping.
- _build_lessons separa buckets swing vs scalping (sufijo _scalping en category).
- /aprendizaje output muestra ambas secciones.
- scalping_engine._record_scalping_outcome inserta outcome al cerrar trade.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.repository import Repository
from app.learning.training_engine import _build_lessons
from app.scheduler.scalping_engine import ScalpingEngine
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings
from tests.test_mt5_demo_trader import _demo_settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"learning_style_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_upsert_signal_outcome_persists_is_scalping_flag() -> None:
    repo = _repo()
    repo.upsert_signal_outcome(
        {
            "alert_id": -5,  # negative para scalping
            "token_id": 0,
            "category": "forex",
            "chain": "forex",
            "token_address": "EURUSD",
            "symbol": "EURUSD",
            "entry_price": 1.1,
            "latest_price": 1.105,
            "observed_return_pct": 0.45,
            "score": 0,
            "confidence": 0,
            "outcome_label": "win",
            "age_minutes": 5,
            "features": '["scalping_breakout"]',
            "evaluated_at": utc_now_iso(),
            "is_scalping": 1,
        }
    )
    outcomes = repo.fetch_signal_outcomes(limit=10)
    assert len(outcomes) == 1
    assert int(outcomes[0].get("is_scalping") or 0) == 1


def test_build_lessons_separates_swing_vs_scalping_categories() -> None:
    """Mismo feature en forex swing vs forex scalping -> dos buckets distintos."""
    # Generamos outcomes con >=2 muestras cada bucket para que _build_lessons los incluya.
    outcomes = []
    for i in range(3):
        outcomes.append(
            {
                "alert_id": i + 1,
                "category": "forex",
                "outcome_label": "win",
                "observed_return_pct": 0.5,
                "score": 80,
                "features": '["breakout_signal"]',
                "is_scalping": 0,
            }
        )
    for i in range(3):
        outcomes.append(
            {
                "alert_id": -(i + 1),
                "category": "forex",
                "outcome_label": "loss",
                "observed_return_pct": -0.3,
                "score": 70,
                "features": '["breakout_signal"]',
                "is_scalping": 1,
            }
        )

    lessons = _build_lessons(outcomes)
    categories = {l["category"] for l in lessons}
    assert "forex" in categories
    assert "forex_scalping" in categories

    # Verifica que las metricas no se mezclen.
    swing_lesson = next(l for l in lessons if l["category"] == "forex")
    scalping_lesson = next(l for l in lessons if l["category"] == "forex_scalping")
    assert swing_lesson["win_rate"] == 1.0  # 3/3 wins
    assert scalping_lesson["win_rate"] == 0.0  # 0/3 wins (all losses)


def test_learning_message_renders_both_sections() -> None:
    """Output /aprendizaje muestra SWING LESSONS y SCALPING LESSONS separadas."""
    repo = _repo()
    # Pre-seed lessons: una swing, una scalping
    repo.upsert_strategy_lesson(
        {
            "feature": "macd_bullish", "category": "forex",
            "sample_count": 5, "win_rate": 0.6, "avg_return_pct": 1.2,
            "avg_score": 75, "confidence": 50, "lesson": "swing forex lesson",
            "updated_at": utc_now_iso(),
        }
    )
    repo.upsert_strategy_lesson(
        {
            "feature": "scalping_breakout", "category": "forex_scalping",
            "sample_count": 10, "win_rate": 0.55, "avg_return_pct": 0.15,
            "avg_score": 0, "confidence": 30, "lesson": "scalping forex lesson",
            "updated_at": utc_now_iso(),
        }
    )

    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/aprendizaje")
    assert "SWING LESSONS" in msg
    assert "SCALPING LESSONS" in msg
    assert "swing forex lesson" in msg
    assert "scalping forex lesson" in msg


def test_scalping_engine_records_outcome_when_closing_trade() -> None:
    """Al close de un paper_trade scalping, se inserta signal_outcome con is_scalping=1."""
    repo = _repo()
    notifier = MagicMock()
    # No mt5_reader necesario para esta prueba (close no necesita mercado).
    engine = ScalpingEngine(
        _settings(), repo, notifier, mt5_reader=None
    )

    # Seed un paper_trade scalping con MFE/MAE simulando una posicion ganadora.
    paper_trade = {
        "alert_id": 0, "token_id": 0, "category": "forex", "chain": "forex",
        "token_address": "EURUSD", "symbol": "EURUSD",
        "thesis": "test scalping", "readiness_grade": "scalping",
        "entry_price": 1.1000,
        "latest_price": 1.1015,  # +15 pips (long winner)
        "stop_loss": 1.0992,
        "take_profit_1": 1.1012,
        "take_profit_2": 1.1012,
        "invalidation": "x", "status": "open",
        "unrealized_return_pct": 0.136,
        "opened_at": utc_now_iso(), "updated_at": utc_now_iso(), "closed_at": None,
        "strategy_name": "scalping_breakout", "direction": "long",
        "time_horizon_hours": 1, "size_notional": 1100, "size_units": 1000, "risk_pct": 1.0,
        "partial_closed": 0, "is_scalping": 1,
    }
    assert repo.create_paper_trade(paper_trade) is True
    trades = repo.fetch_open_positions_full() or []
    assert len(trades) == 1
    trade_id = int(trades[0]["id"])

    # Trigger close
    engine._close_scalping_trade(trade_id, reason="tp_hit")

    # Verifica outcome registrado con is_scalping=1 y alert_id negativo
    outcomes = repo.fetch_signal_outcomes(limit=10)
    assert len(outcomes) == 1
    assert int(outcomes[0]["is_scalping"]) == 1
    assert int(outcomes[0]["alert_id"]) == -trade_id  # negative para no chocar swing
    assert outcomes[0]["category"] == "forex"
    assert outcomes[0]["observed_return_pct"] > 0  # winner
