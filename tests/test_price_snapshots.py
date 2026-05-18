import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.utils.time_utils import utc_now


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"snapshots_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_token(repo: Repository) -> tuple[int, TokenSnapshot]:
    snapshot = TokenSnapshot(
        chain="base",
        token_address="0xabc",
        category="memecoin",
        symbol="TEST",
        name="Test Token",
        price=1.0,
        liquidity_usd=50_000,
        volume_1h=20_000,
        source="test",
    )
    estimate = EstimateResult(
        estimated_gain_pct=120,
        estimated_loss_pct=20,
        confidence=70,
        label="high",
        reasons=[],
        eligible_for_gain_alert=True,
    )
    token_id = repo.upsert_token(snapshot, 80, "yellow", estimate)
    return token_id, snapshot


def _set_captured_at(db_path: Path, snapshot_id: int, iso_value: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE price_snapshots SET captured_at = ? WHERE id = ?",
            (iso_value, snapshot_id),
        )


def test_insert_price_snapshot_creates_row() -> None:
    repo = _repo()
    token_id, snapshot = _seed_token(repo)

    inserted_id = repo.insert_price_snapshot(snapshot, token_id)
    assert inserted_id > 0

    start = (utc_now() - timedelta(hours=1)).isoformat()
    end = (utc_now() + timedelta(minutes=1)).isoformat()
    rows = repo.fetch_snapshots_in_window("base", "0xabc", start, end)
    assert len(rows) == 1
    assert rows[0]["price"] == 1.0
    assert rows[0]["chain"] == "base"


def test_purge_old_snapshots_respects_retention() -> None:
    repo = _repo()
    token_id, snapshot = _seed_token(repo)

    old_id = repo.insert_price_snapshot(snapshot, token_id)
    fresh_id = repo.insert_price_snapshot(snapshot, token_id)
    _set_captured_at(
        repo.db_path, old_id, (utc_now() - timedelta(days=10)).isoformat()
    )
    _set_captured_at(
        repo.db_path, fresh_id, (utc_now() - timedelta(hours=1)).isoformat()
    )

    deleted = repo.purge_old_snapshots(retention_days=5)
    assert deleted == 1

    with sqlite3.connect(repo.db_path) as connection:
        remaining_ids = [
            row[0]
            for row in connection.execute(
                "SELECT id FROM price_snapshots ORDER BY id"
            ).fetchall()
        ]
    assert remaining_ids == [fresh_id]


def test_fetch_snapshots_in_window_order() -> None:
    repo = _repo()
    token_id, snapshot = _seed_token(repo)

    ids = [repo.insert_price_snapshot(snapshot, token_id) for _ in range(3)]
    base = utc_now() - timedelta(hours=2)
    for index, snapshot_id in enumerate(ids):
        _set_captured_at(
            repo.db_path,
            snapshot_id,
            (base + timedelta(minutes=index * 10)).isoformat(),
        )

    start = (base - timedelta(minutes=1)).isoformat()
    end = (base + timedelta(hours=1)).isoformat()
    rows = repo.fetch_snapshots_in_window("base", "0xabc", start, end)
    captured = [row["captured_at"] for row in rows]
    assert captured == sorted(captured)
