import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.models import (
    AlertRecord,
    EstimateResult,
    SecuritySummary,
    TokenSnapshot,
)
from app.database.repository import Repository
from app.utils.time_utils import utc_now
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"telegram_horizons_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _make_alert(repo: Repository, symbol: str) -> int:
    snapshot = TokenSnapshot(
        chain="stock",
        token_address=symbol,
        category="stock",
        symbol=symbol,
        name=symbol,
        source="test",
        price=100.0,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10,
        estimated_loss_pct=3,
        confidence=80,
        label="high",
        reasons=[],
        eligible_for_gain_alert=True,
    )
    token_id = repo.upsert_token(snapshot, 85, "orange", estimate)
    alert_id = repo.insert_alert(
        AlertRecord(
            token_id=token_id,
            alert_type="STOCK_BREAKOUT",
            snapshot=snapshot,
            app_version="test",
            category="stock",
            score=85,
            risk_level="orange",
            reasons=["IA Pro: pro_high_conviction"],
            security=SecuritySummary(raw_summary="unknown"),
            estimate=estimate,
            sent_to_telegram=True,
        )
    )
    return int(alert_id)


def _insert_horizon(
    repo: Repository,
    alert_id: int,
    horizon: int,
    return_pct: float,
    status: str = "final",
    snapshots_used: int = 3,
) -> None:
    with sqlite3.connect(repo.db_path) as connection:
        connection.execute(
            """
            INSERT INTO alert_outcome_horizons (
                alert_id, horizon_hours, entry_price, exit_price,
                return_pct, mfe_pct, mae_pct, snapshots_used,
                outcome_label, status, evaluated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                horizon,
                100.0,
                100.0 * (1 + return_pct / 100),
                return_pct,
                max(return_pct, 0.0) + 1.0,
                min(return_pct, 0.0) - 1.0,
                snapshots_used,
                "win" if return_pct >= 5 else "neutral",
                status,
                utc_now().isoformat(),
            ),
        )


def _backdate_alert(repo: Repository, alert_id: int, hours_ago: float) -> None:
    iso = (utc_now() - timedelta(hours=hours_ago)).isoformat()
    with sqlite3.connect(repo.db_path) as connection:
        connection.execute(
            "UPDATE alerts SET created_at = ? WHERE id = ?", (iso, alert_id)
        )


def test_horizons_command_response_format() -> None:
    repo = _repo()
    alert_id = _make_alert(repo, "NVDA")
    _insert_horizon(repo, alert_id, 1, return_pct=2.3)
    _insert_horizon(repo, alert_id, 6, return_pct=4.8)
    _insert_horizon(repo, alert_id, 24, return_pct=7.0)
    _backdate_alert(repo, alert_id, hours_ago=30)

    assistant = BasicTelegramAssistant(_settings(), repo)
    response = assistant.handle("/horizontes NVDA")

    assert "Horizontes para NVDA" in response
    assert "1h:" in response
    assert "6h:" in response
    assert "24h:" in response
    assert "7d:" in response
    assert "pendiente" in response  # 7d aun no esta evaluado


def test_backtest_command_default_format() -> None:
    repo = _repo()
    # Crear suficientes muestras para que la regla aparezca en ranking
    for index in range(6):
        alert_id = _make_alert(repo, f"NVDA{index}")
        _insert_horizon(repo, alert_id, 24, return_pct=6.0 + index)
        _backdate_alert(repo, alert_id, hours_ago=25)

    base_settings = _settings()
    settings = type(base_settings)(
        **{**base_settings.__dict__, "backtest_min_samples": 3}
    )
    assistant = BasicTelegramAssistant(settings, repo)
    response = assistant.handle("/backtest")

    assert "Top reglas" in response
    assert "horizonte 24h" in response
