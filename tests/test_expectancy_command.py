"""v2.7.0 — /expectancy Telegram command tests.

Verifica que el comando muestra la expectancy REALIZADA en R por estrategia,
desde paper_trades cerrados, excluyendo artifacts del feedback-loop.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.learning.training_engine import _refresh_strategy_performance
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"expectancy_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_closed(repo, symbol, entry, latest, ostop, strategy) -> None:
    snap = TokenSnapshot(
        chain="forex", token_address=symbol, category="forex", symbol=symbol,
        price=entry, liquidity_usd=1_000_000,
    )
    est = EstimateResult(
        estimated_gain_pct=2, estimated_loss_pct=1, confidence=70,
        label="paper", reasons=[], eligible_for_gain_alert=True,
    )
    tid = repo.upsert_token(snap, 80, "orange", est)
    now = utc_now_iso()
    repo.create_paper_trade({
        "alert_id": int(uuid4().int % 10_000_000), "token_id": tid, "category": "forex",
        "chain": "forex", "token_address": symbol, "symbol": symbol, "thesis": "t",
        "readiness_grade": "B", "entry_price": entry, "latest_price": latest,
        "stop_loss": ostop, "take_profit_1": entry * 1.01, "take_profit_2": entry * 1.02,
        "invalidation": None, "status": "stopped_simulated", "unrealized_return_pct": 0,
        "opened_at": now, "updated_at": now, "closed_at": now, "mfe_pct": 0, "mae_pct": 0,
        "original_stop_loss": ostop, "trailing_active": 0, "strategy_name": strategy,
        "direction": "long",
    })


def test_expectancy_responds_to_aliases() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)
    for alias in ["/expectancy", "expectancy", "/expectativa", "expectativa"]:
        resp = assistant.handle(alias)
        assert "Expectancy realizada por estrategia" in resp, f"alias {alias!r} no responde"


def test_expectancy_empty_db_says_no_data_and_disclaimer() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)
    resp = assistant.handle("/expectancy")
    assert "sin datos" in resp.lower()
    assert "No es recomendacion financiera" in resp


def test_expectancy_shows_strategy_r_and_excludes_artifacts() -> None:
    repo = _repo()
    settings = _settings()
    _seed_closed(repo, "EURUSD", 100.0, 110.0, 95.0, "breakout")  # win real +2R
    _seed_closed(repo, "GBPUSD", 100.0, 100.0, 95.0, "breakout")  # artifact (frozen)
    _refresh_strategy_performance(repo, settings)

    assistant = BasicTelegramAssistant(settings, repo)
    resp = assistant.handle("/expectancy")
    assert "breakout/forex" in resp
    assert "avgR=+2.00" in resp
    assert "artifacts excl." in resp
