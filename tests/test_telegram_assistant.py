from pathlib import Path
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.models import AlertRecord, EstimateResult, SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"assistant_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_assistant_status_and_pause() -> None:
    settings = _settings()
    repo = _repo()
    assistant = BasicTelegramAssistant(settings, repo)

    status = assistant.handle("/status")
    assert "Alertas automaticas: activas" in status

    paused = assistant.handle("/pausar")
    assert "Alertas pausadas" in paused
    assert repo.alerts_paused() is True

    resumed = assistant.handle("/reanudar")
    assert "Alertas reanudadas" in resumed
    assert repo.alerts_paused() is False


def test_assistant_can_analyze_saved_symbol() -> None:
    settings = _settings()
    repo = _repo()
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        name="NVIDIA",
        source="test",
        price=100,
        liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=12,
        estimated_loss_pct=20,
        confidence=70,
        label="high-conviction-stock",
        reasons=["test"],
        eligible_for_gain_alert=True,
    )
    repo.upsert_token(snapshot, score=80, risk_level="orange", estimate=estimate)
    assistant = BasicTelegramAssistant(settings, repo)

    reply = assistant.handle("/analiza NVDA")

    assert "Analisis basico" in reply
    assert "NVDA" in reply
    assert "Subida estimada: 12.00%" in reply


def test_assistant_cupos_and_descartes() -> None:
    settings = _settings()
    repo = _repo()
    snapshot = TokenSnapshot(
        chain="base",
        token_address="0xaaa",
        category="memecoin",
        symbol="AAA",
        name="AAA Token",
        source="test",
        price=0.01,
        liquidity_usd=50_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=300,
        estimated_loss_pct=50,
        confidence=60,
        label="watch-only",
        reasons=["test"],
        eligible_for_gain_alert=False,
    )
    token_id = repo.upsert_token(snapshot, score=70, risk_level="yellow", estimate=estimate)
    repo.insert_alert(
        AlertRecord(
            token_id=token_id,
            alert_type="WATCHLIST_MOVEMENT",
            snapshot=snapshot,
            app_version=settings.app_version,
            category="memecoin",
            score=70,
            risk_level="yellow",
            reasons=["test"],
            security=SecuritySummary(raw_summary="unknown"),
            estimate=estimate,
            sent_to_telegram=False,
        )
    )
    assistant = BasicTelegramAssistant(settings, repo)

    cupos = assistant.handle("/cupos")
    descartes = assistant.handle("/descartes")

    assert "Memecoins" in cupos
    assert "Bolsa" in cupos
    assert "Mejores candidatos NO enviados" in descartes
    assert "AAA" in descartes
