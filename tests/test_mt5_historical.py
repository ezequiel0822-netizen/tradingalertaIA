"""Tests para MT5HistoricalFetcher con cache."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from app.brokers.mt5_historical import MT5HistoricalFetcher
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"mt5hist_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _make_fake_reader(candles_to_return: list[dict] | None) -> MagicMock:
    fake = MagicMock()
    fake.is_connected.return_value = candles_to_return is not None
    fake.get_historical_range.return_value = candles_to_return
    return fake


def test_cache_miss_then_fetch_and_persist() -> None:
    repo = _repo()
    settings = _settings()
    candles = [
        {"time": 1700000000, "open": 1.10, "high": 1.11, "low": 1.09, "close": 1.105, "volume": 100},
        {"time": 1700000900, "open": 1.105, "high": 1.115, "low": 1.10, "close": 1.110, "volume": 120},
    ]
    reader = _make_fake_reader(candles)
    fetcher = MT5HistoricalFetcher(settings, repo, reader)
    start = datetime(2023, 11, 14, 22, 0, tzinfo=timezone.utc)
    end = datetime(2023, 11, 15, 0, 0, tzinfo=timezone.utc)

    result = fetcher.fetch_window("EURUSD", 15, start, end)

    assert len(result) >= 2
    # Verifica que se persistio en DB
    cached = repo.fetch_mt5_cache_window("EURUSD", 15, 1700000000, 1700000900)
    assert len(cached) == 2


def test_cache_hit_returns_without_fetch() -> None:
    repo = _repo()
    settings = _settings()

    # Pre-seedear cache
    for time_epoch in range(1700000000, 1700000000 + 96 * 900, 900):  # 96 bars (24h M15)
        repo.upsert_mt5_cache_candle("EURUSD", 15, {
            "time": time_epoch, "open": 1.1, "high": 1.11, "low": 1.09,
            "close": 1.105, "volume": 100,
        })

    # Reader que falla si se llama
    reader = MagicMock()
    reader.is_connected.return_value = True
    reader.get_historical_range = MagicMock(side_effect=AssertionError("no debe llamarse"))

    fetcher = MT5HistoricalFetcher(settings, repo, reader)
    start = datetime.fromtimestamp(1700000000, tz=timezone.utc)
    end = datetime.fromtimestamp(1700000000 + 96 * 900, tz=timezone.utc)

    result = fetcher.fetch_window("EURUSD", 15, start, end)
    assert len(result) == 96
    reader.get_historical_range.assert_not_called()


def test_disconnected_reader_returns_cache_only() -> None:
    repo = _repo()
    settings = _settings()
    reader = _make_fake_reader(None)  # is_connected=False

    fetcher = MT5HistoricalFetcher(settings, repo, reader)
    start = datetime(2023, 11, 14, tzinfo=timezone.utc)
    end = datetime(2023, 11, 15, tzinfo=timezone.utc)
    result = fetcher.fetch_window("EURUSD", 15, start, end)
    assert result == []
