"""Tests del CRUD backtest_* (v3.6.0, ESPEC §5 / §14).

Cubre: round-trip de las 3 tablas, indices, y el invariante de aislacion:
cero foreign keys hacia tablas vivas.
"""

import sqlite3
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.repository import Repository


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"backtest_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _run_row(**overrides) -> dict:
    row = {
        "created_at_utc": "2026-06-12T00:00:00+00:00",
        "git_commit": "abc1234",
        "mode": "A",
        "timeframe": "D1",
        "symbols": "EURUSD,GBPUSD",
        "strategies": "breakout,mean_reversion",
        "data_ranges_json": '{"EURUSD": ["2010-01-01", "2026-06-11"]}',
        "config_json": '{"breakout": {"lookback": 20}}',
        "cost_multiplier": 1.25,
        "n_configs_tested": 1,
        "notes": None,
    }
    row.update(overrides)
    return row


def _trade_row(**overrides) -> dict:
    row = {
        "config_id": "breakout/default",
        "strategy": "breakout",
        "symbol": "EURUSD",
        "category": "forex",
        "direction": "long",
        "signal_bar_utc": "2020-03-01T00:00:00+00:00",
        "entry_utc": "2020-03-02T00:00:00+00:00",
        "entry_price": 1.1000,
        "sl_initial": 1.0900,
        "tp_initial": 1.1200,
        "exit_utc": "2020-03-09T00:00:00+00:00",
        "exit_price": 1.1200,
        "exit_reason": "tp",
        "bars_held": 5,
        "r_gross": 2.0,
        "cost_r": 0.05,
        "r_net": 1.95,
        "mfe_r": 2.2,
        "mae_r": -0.3,
        "session": "london",
        "regime_trend": "up",
        "regime_vol": "mid",
        "year": 2020,
    }
    row.update(overrides)
    return row


def test_insert_and_fetch_backtest_run_round_trip() -> None:
    repo = _repo()
    run_id = repo.insert_backtest_run(_run_row())
    assert run_id > 0
    fetched = repo.fetch_backtest_run(run_id)
    assert fetched is not None
    assert fetched["mode"] == "A"
    assert fetched["timeframe"] == "D1"
    assert fetched["symbols"] == "EURUSD,GBPUSD"
    assert fetched["config_json"] == '{"breakout": {"lookback": 20}}'
    assert fetched["cost_multiplier"] == 1.25
    assert fetched["n_configs_tested"] == 1


def test_fetch_backtest_runs_orders_desc_and_limits() -> None:
    repo = _repo()
    first = repo.insert_backtest_run(_run_row())
    second = repo.insert_backtest_run(_run_row(mode="B"))
    runs = repo.fetch_backtest_runs(limit=1)
    assert len(runs) == 1
    assert runs[0]["id"] == second
    assert repo.fetch_backtest_runs(limit=10)[1]["id"] == first


def test_update_backtest_run_notes() -> None:
    repo = _repo()
    run_id = repo.insert_backtest_run(_run_row())
    repo.update_backtest_run_notes(run_id, "re-run Modo B: grid documentado")
    assert (
        repo.fetch_backtest_run(run_id)["notes"]
        == "re-run Modo B: grid documentado"
    )


def test_insert_backtest_trades_bulk_and_fetch() -> None:
    repo = _repo()
    run_id = repo.insert_backtest_run(_run_row())
    n = repo.insert_backtest_trades(
        run_id,
        [
            _trade_row(),
            _trade_row(direction="short", entry_utc="2020-04-02T00:00:00+00:00"),
        ],
    )
    assert n == 2
    trades = repo.fetch_backtest_trades(run_id)
    assert len(trades) == 2
    # Orden por entry_utc ascendente
    assert trades[0]["entry_utc"] < trades[1]["entry_utc"]
    assert trades[0]["r_net"] == 1.95
    assert trades[1]["direction"] == "short"


def test_fetch_backtest_trades_filters_by_strategy_and_symbol() -> None:
    repo = _repo()
    run_id = repo.insert_backtest_run(_run_row())
    repo.insert_backtest_trades(
        run_id,
        [
            _trade_row(strategy="breakout", symbol="EURUSD"),
            _trade_row(strategy="mean_reversion", symbol="EURUSD"),
            _trade_row(strategy="breakout", symbol="GBPUSD"),
        ],
    )
    assert len(repo.fetch_backtest_trades(run_id, strategy="breakout")) == 2
    assert len(repo.fetch_backtest_trades(run_id, symbol="EURUSD")) == 2
    assert (
        len(
            repo.fetch_backtest_trades(
                run_id, strategy="breakout", symbol="GBPUSD"
            )
        )
        == 1
    )


def test_insert_backtest_trades_empty_returns_zero() -> None:
    repo = _repo()
    run_id = repo.insert_backtest_run(_run_row())
    assert repo.insert_backtest_trades(run_id, []) == 0
    assert repo.fetch_backtest_trades(run_id) == []


def test_insert_and_fetch_backtest_walkforward() -> None:
    repo = _repo()
    run_id = repo.insert_backtest_run(_run_row(mode="B"))
    row_id = repo.insert_backtest_walkforward(
        {
            "run_id": run_id,
            "config_id": "trend_following_d1/entry55_atr2.0",
            "train_from": "2018-01-01",
            "train_to": "2019-12-31",
            "test_from": "2020-01-01",
            "test_to": "2020-06-30",
            "strategy": "trend_following_d1",
            "n": 42,
            "avg_r_net": 0.12,
            "median_r_net": -0.2,
            "win_rate": 0.38,
            "max_dd_r": 11.5,
            "profit_factor": 1.21,
        }
    )
    assert row_id > 0
    rows = repo.fetch_backtest_walkforward(run_id)
    assert len(rows) == 1
    assert rows[0]["strategy"] == "trend_following_d1"
    assert rows[0]["n"] == 42
    assert rows[0]["avg_r_net"] == 0.12


def test_backtest_tables_have_no_fks_to_live_tables() -> None:
    """Invariante de aislacion (ESPEC §5): las FKs de backtest_* solo pueden
    apuntar a backtest_runs, jamas a una tabla viva."""
    repo = _repo()
    with sqlite3.connect(repo.db_path) as connection:
        for table in ("backtest_runs", "backtest_trades", "backtest_walkforward"):
            fks = connection.execute(
                f"PRAGMA foreign_key_list({table})"
            ).fetchall()
            referenced = {fk[2] for fk in fks}  # columna 2 = tabla referenciada
            assert referenced <= {"backtest_runs"}, (
                f"{table} referencia tablas vivas: {referenced}"
            )


def test_backtest_trades_indices_exist() -> None:
    repo = _repo()
    with sqlite3.connect(repo.db_path) as connection:
        names = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(backtest_trades)"
            ).fetchall()
        }
    assert "idx_backtest_trades_run" in names
    assert "idx_backtest_trades_strategy_symbol" in names


def test_fetch_mt5_cache_depth_empty_and_seeded() -> None:
    repo = _repo()
    empty = repo.fetch_mt5_cache_depth("EURUSD", 1440)
    assert empty["bars"] == 0
    assert empty["first_epoch"] is None
    assert empty["last_epoch"] is None

    day = 86_400
    candles = [
        {"time": 1_600_000_000 + i * day, "open": 1.1, "high": 1.2,
         "low": 1.0, "close": 1.15, "volume": 100}
        for i in range(3)
    ]
    assert repo.upsert_mt5_cache_candles("EURUSD", 1440, candles) == 3
    depth = repo.fetch_mt5_cache_depth("EURUSD", 1440)
    assert depth["bars"] == 3
    assert depth["first_epoch"] == 1_600_000_000
    assert depth["last_epoch"] == 1_600_000_000 + 2 * day


def test_upsert_mt5_cache_candles_idempotent() -> None:
    repo = _repo()
    candles = [
        {"time": 1_600_000_000, "open": 1.1, "high": 1.2, "low": 1.0,
         "close": 1.15, "volume": 100},
    ]
    repo.upsert_mt5_cache_candles("EURUSD", 1440, candles)
    # Mismo bar con close nuevo: actualiza, no duplica
    candles[0]["close"] = 1.18
    repo.upsert_mt5_cache_candles("EURUSD", 1440, candles)
    depth = repo.fetch_mt5_cache_depth("EURUSD", 1440)
    assert depth["bars"] == 1
    window = repo.fetch_mt5_cache_window(
        "EURUSD", 1440, 1_600_000_000, 1_600_000_000
    )
    assert window[0]["close"] == 1.18
