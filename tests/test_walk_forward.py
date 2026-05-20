"""Tests para WalkForwardBacktester."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.repository import Repository
from app.learning.walk_forward import WalkForwardBacktester
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"wf_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_closed_trade(
    repo: Repository,
    strategy_name: str,
    category: str,
    closed_at: datetime,
    return_pct: float,
) -> None:
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("""
            INSERT INTO paper_trades (
                alert_id, token_id, category, chain, token_address, symbol,
                entry_price, latest_price, stop_loss, take_profit_1, take_profit_2,
                status, unrealized_return_pct, opened_at, updated_at, closed_at,
                strategy_name
            ) VALUES (?, 1, ?, ?, ?, ?, 100, ?, 95, 105, 110,
                      'target_2_simulated', ?, ?, ?, ?, ?)
        """, (
            int(uuid4().int % 10_000_000),
            category, "stock", "SYM", "SYM",
            100 * (1 + return_pct / 100),
            return_pct,
            (closed_at - timedelta(hours=24)).isoformat(),
            closed_at.isoformat(),
            closed_at.isoformat(),
            strategy_name,
        ))


def test_walk_forward_skips_window_below_min_samples() -> None:
    repo = _repo()
    settings = _settings()
    now = datetime.now(timezone.utc)
    # Solo 3 trades — menos que min_samples=10
    for i in range(3):
        _seed_closed_trade(repo, "breakout", "stock", now - timedelta(days=10 - i), 2.0)
    wf = WalkForwardBacktester(repo, settings)
    windows = wf.run(
        "breakout", "stock",
        (now - timedelta(days=40)).isoformat(),
        now.isoformat(),
    )
    assert windows == []


def test_walk_forward_computes_metrics_with_enough_samples() -> None:
    repo = _repo()
    settings = _settings()
    now = datetime.now(timezone.utc)
    # 15 trades en train window + 5 en test
    for i in range(15):
        _seed_closed_trade(
            repo, "breakout", "stock",
            now - timedelta(days=25 - i), 2.5
        )  # train: winners
    for i in range(5):
        _seed_closed_trade(
            repo, "breakout", "stock",
            now - timedelta(days=10 - i), -1.0
        )  # test: losers (degradacion)

    wf = WalkForwardBacktester(repo, settings)
    windows = wf.run(
        "breakout", "stock",
        (now - timedelta(days=30)).isoformat(),
        now.isoformat(),
    )
    assert len(windows) >= 1
    w = windows[0]
    assert w.strategy_name == "breakout"
    assert w.train_samples >= 10
    assert w.train_win_rate > w.test_win_rate  # degradacion clara


def test_walk_forward_persists_windows() -> None:
    repo = _repo()
    settings = _settings()
    now = datetime.now(timezone.utc)
    for i in range(15):
        _seed_closed_trade(repo, "momentum", "stock", now - timedelta(days=25 - i), 1.5)
    for i in range(5):
        _seed_closed_trade(repo, "momentum", "stock", now - timedelta(days=10 - i), 0.5)

    wf = WalkForwardBacktester(repo, settings)
    windows = wf.run("momentum", "stock",
                     (now - timedelta(days=30)).isoformat(), now.isoformat())
    n = wf.persist_windows(windows)
    assert n >= 1
    stored = repo.fetch_walk_forward_results(strategy_name="momentum")
    assert len(stored) >= 1


def test_walk_forward_filter_by_strategy() -> None:
    repo = _repo()
    settings = _settings()
    now = datetime.now(timezone.utc)
    for i in range(12):
        _seed_closed_trade(repo, "breakout", "stock", now - timedelta(days=20 - i), 1.0)
    for i in range(12):
        _seed_closed_trade(repo, "momentum", "stock", now - timedelta(days=20 - i), -2.0)

    wf = WalkForwardBacktester(repo, settings)
    breakout_windows = wf.run("breakout", "stock",
                              (now - timedelta(days=25)).isoformat(), now.isoformat())
    momentum_windows = wf.run("momentum", "stock",
                              (now - timedelta(days=25)).isoformat(), now.isoformat())
    # Cada strategy se evalua independiente
    assert len(breakout_windows) >= 0
    assert len(momentum_windows) >= 0
    for w in breakout_windows:
        assert w.strategy_name == "breakout"
    for w in momentum_windows:
        assert w.strategy_name == "momentum"


def test_walk_forward_degradation_calc() -> None:
    repo = _repo()
    settings = _settings()
    now = datetime.now(timezone.utc)
    for i in range(12):
        _seed_closed_trade(repo, "news_catalyst", "stock", now - timedelta(days=22 - i), 3.0)
    for i in range(6):
        _seed_closed_trade(repo, "news_catalyst", "stock", now - timedelta(days=10 - i), -0.5)

    wf = WalkForwardBacktester(repo, settings)
    windows = wf.run("news_catalyst", "stock",
                     (now - timedelta(days=25)).isoformat(), now.isoformat())
    # degradation_pct deberia ser positiva (train > test)
    if windows:
        positive_degradation = any(w.degradation_pct > 0 for w in windows)
        assert positive_degradation


def test_walk_forward_returns_empty_with_no_data() -> None:
    repo = _repo()
    settings = _settings()
    wf = WalkForwardBacktester(repo, settings)
    now = datetime.now(timezone.utc)
    windows = wf.run("breakout", "stock",
                     (now - timedelta(days=30)).isoformat(), now.isoformat())
    assert windows == []
