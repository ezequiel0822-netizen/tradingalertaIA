import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.models import (
    AlertRecord,
    EstimateResult,
    SecuritySummary,
    TokenSnapshot,
)
from app.database.repository import Repository
from app.learning.horizon_evaluator import HORIZONS, evaluate_horizons
from app.utils.time_utils import utc_now
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"horizons_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_alert(repo: Repository, entry: float = 100.0, hours_ago: float = 30.0) -> int:
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        name="NVIDIA",
        source="test",
        price=entry,
        liquidity_usd=1_000_000,
        volume_1h=200_000,
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
    backdated = (utc_now() - timedelta(hours=hours_ago)).isoformat()
    with sqlite3.connect(repo.db_path) as connection:
        connection.execute(
            "UPDATE alerts SET created_at = ?, price = ? WHERE id = ?",
            (backdated, entry, alert_id),
        )
    return alert_id


def _seed_snapshots(
    repo: Repository,
    chain: str,
    token_address: str,
    base_offset_hours: float,
    prices: list[float],
    spacing_minutes: int = 10,
) -> None:
    base_time = utc_now() - timedelta(hours=base_offset_hours)
    token_id, _ = _fetch_token_id(repo, chain, token_address)
    for index, price in enumerate(prices):
        captured = (base_time + timedelta(minutes=index * spacing_minutes)).isoformat()
        with sqlite3.connect(repo.db_path) as connection:
            connection.execute(
                """
                INSERT INTO price_snapshots (
                    token_id, chain, token_address, category, price,
                    liquidity_usd, volume_5m, volume_1h, volume_24h,
                    captured_at, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    chain,
                    token_address,
                    "stock",
                    price,
                    1_000_000,
                    50_000,
                    200_000,
                    1_000_000,
                    captured,
                    "test",
                ),
            )


def _fetch_token_id(repo: Repository, chain: str, addr: str) -> tuple[int, dict]:
    token = repo.get_token(chain, addr)
    assert token is not None
    return int(token["id"]), token


def _settings_for_horizons(min_age_minutes: int = 0):
    base = _settings()
    return type(base)(
        **{
            **base.__dict__,
            "learning_min_alert_age_minutes": min_age_minutes,
            "enable_horizon_evaluator": True,
            "horizon_min_snapshots": 2,
        }
    )


def test_horizon_returns_correct_pct() -> None:
    repo = _repo()
    _seed_alert(repo, entry=100.0, hours_ago=30)
    _seed_snapshots(
        repo,
        "stock",
        "NVDA",
        base_offset_hours=29.9,
        prices=[100, 110, 105, 115, 108],
        spacing_minutes=10,
    )

    result = evaluate_horizons(_settings_for_horizons(), repo)

    assert result["horizons_created"] >= 1
    horizons_1h = repo.fetch_alert_outcome_horizons(horizon_hours=1)
    assert horizons_1h
    row = horizons_1h[0]
    assert row["status"] == "final"
    assert row["return_pct"] is not None
    assert abs(row["return_pct"] - 8.0) < 0.5
    assert row["mfe_pct"] >= 14.0
    assert row["mae_pct"] <= 1.0


def test_horizon_mae_when_dump() -> None:
    repo = _repo()
    _seed_alert(repo, entry=100.0, hours_ago=30)
    _seed_snapshots(
        repo,
        "stock",
        "NVDA",
        base_offset_hours=29.9,
        prices=[100, 95, 80, 90, 85],
        spacing_minutes=10,
    )

    evaluate_horizons(_settings_for_horizons(), repo)
    horizons_1h = repo.fetch_alert_outcome_horizons(horizon_hours=1)
    assert horizons_1h
    row = horizons_1h[0]
    assert row["mae_pct"] <= -19.0
    assert row["return_pct"] < 0


def test_horizon_insufficient_data_label() -> None:
    repo = _repo()
    _seed_alert(repo, entry=100.0, hours_ago=30)
    _seed_snapshots(
        repo,
        "stock",
        "NVDA",
        base_offset_hours=29.9,
        prices=[100],
        spacing_minutes=10,
    )

    evaluate_horizons(_settings_for_horizons(), repo)
    horizons_1h = repo.fetch_alert_outcome_horizons(horizon_hours=1)
    assert horizons_1h
    row = horizons_1h[0]
    assert row["status"] == "pending"
    assert row["outcome_label"] == "insufficient_data"


def test_horizon_final_status_when_window_closes() -> None:
    repo = _repo()
    _seed_alert(repo, entry=50.0, hours_ago=25)
    _seed_snapshots(
        repo,
        "stock",
        "NVDA",
        base_offset_hours=24.9,
        prices=[50, 52, 49, 51, 53, 55, 54, 52, 51, 50],
        spacing_minutes=20,
    )

    evaluate_horizons(_settings_for_horizons(), repo)
    horizons_24h = repo.fetch_alert_outcome_horizons(horizon_hours=24)
    assert horizons_24h
    assert horizons_24h[0]["status"] == "final"
    horizons_7d = repo.fetch_alert_outcome_horizons(horizon_hours=168)
    # Aun no han pasado 7 dias; el evaluator no debe crear fila para 7d.
    assert not horizons_7d


def test_horizon_idempotent_upsert() -> None:
    repo = _repo()
    _seed_alert(repo, entry=10.0, hours_ago=30)
    _seed_snapshots(
        repo,
        "stock",
        "NVDA",
        base_offset_hours=29.9,
        prices=[10, 11, 12, 13],
        spacing_minutes=10,
    )

    first = evaluate_horizons(_settings_for_horizons(), repo)
    second = evaluate_horizons(_settings_for_horizons(), repo)

    assert first["horizons_created"] >= 1
    # Segunda corrida no crea filas finales nuevas (las existentes ya estan final).
    assert second["horizons_created"] == 0
    assert second["horizons_updated"] == 0
    horizons_1h = repo.fetch_alert_outcome_horizons(horizon_hours=1)
    assert len(horizons_1h) == 1
