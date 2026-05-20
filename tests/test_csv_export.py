"""Tests para CSV export helpers."""

import csv
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.repository import Repository
from app.utils.csv_export import (
    export_horizons_csv,
    export_outcomes_csv,
    export_paper_trades_csv,
    export_walk_forward_csv,
)
from app.utils.time_utils import utc_now_iso


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"csv_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_export_outcomes_csv_empty(tmp_path) -> None:
    repo = _repo()
    out = tmp_path / "outcomes.csv"
    n = export_outcomes_csv(
        repo, "2026-01-01", "2026-12-31", out, root=tmp_path
    )
    assert n == 0
    assert out.exists()


def test_export_paper_trades_csv(tmp_path) -> None:
    repo = _repo()
    # Sembrar 1 paper trade
    import sqlite3
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("""
            INSERT INTO paper_trades (
                alert_id, token_id, category, chain, token_address, symbol,
                entry_price, latest_price, stop_loss, take_profit_1,
                take_profit_2, status, unrealized_return_pct, opened_at, updated_at
            ) VALUES (1, 1, 'stock', 'stock', 'NVDA', 'NVDA',
                      100, 105, 95, 110, 120, 'open', 5.0, ?, ?)
        """, (utc_now_iso(), utc_now_iso()))
    out = tmp_path / "trades.csv"
    n = export_paper_trades_csv(repo, status=None, path=out, root=tmp_path)
    assert n >= 1
    with out.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["symbol"] == "NVDA"


def test_export_horizons_csv_empty(tmp_path) -> None:
    repo = _repo()
    out = tmp_path / "horizons.csv"
    n = export_horizons_csv(repo, horizon_hours=24, path=out, root=tmp_path)
    assert n == 0


def test_export_walk_forward_csv(tmp_path) -> None:
    repo = _repo()
    repo.insert_walk_forward_result({
        "strategy_name": "breakout", "symbol": "EURUSD", "category": "forex",
        "train_start": "2026-04-01", "train_end": "2026-04-14",
        "test_start": "2026-04-14", "test_end": "2026-04-21",
        "train_sharpe": 1.2, "train_win_rate": 0.6, "train_avg_return": 2.5,
        "test_sharpe": 0.8, "test_win_rate": 0.5, "test_avg_return": 1.5,
        "degradation_pct": 33.0, "train_samples": 25, "test_samples": 10,
    })
    out = tmp_path / "wf.csv"
    n = export_walk_forward_csv(repo, strategy_name="breakout", path=out, root=tmp_path)
    assert n == 1
    with out.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["strategy_name"] == "breakout"
    assert float(rows[0]["degradation_pct"]) == 33.0
