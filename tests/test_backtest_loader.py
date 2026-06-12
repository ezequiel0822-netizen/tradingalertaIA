"""Tests del historical_loader del backtest harness (v3.6.0, ESPEC §14).

Casos clave: cache round-trip, reporte de profundidad real por simbolo,
simbolo sin data => soft-fail con aviso claro, mapeo minutos -> constante
TIMEFRAME_* del package MetaTrader5, y probe descendente de profundidad.
"""

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from app.backtest.historical_loader import (
    BacktestHistoricalLoader,
    LoadSummary,
    SymbolDepth,
    depth_report,
    timeframe_minutes_from_label,
)
from app.brokers.mt5_reader import MT5Timeframe
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_score import _settings


_DAY = 86_400


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"btloader_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _candles(n: int, start_epoch: int = 1_600_000_000) -> list[dict]:
    return [
        {"time": start_epoch + i * _DAY, "open": 1.1, "high": 1.2,
         "low": 1.0, "close": 1.15, "volume": 100}
        for i in range(n)
    ]


def _connected_reader(candles: list[dict] | None) -> MagicMock:
    reader = MagicMock()
    reader.is_connected.return_value = True
    reader.get_rates.return_value = candles
    return reader


def test_load_symbol_fetches_persists_and_measures() -> None:
    repo = _repo()
    reader = _connected_reader(_candles(3))
    loader = BacktestHistoricalLoader(_settings(), repo, reader)

    depth = loader.load_symbol("eurusd", MT5Timeframe.D1)

    assert depth.symbol == "EURUSD"  # normalizado
    assert depth.timeframe_label == "D1"
    assert depth.bars == 3
    assert depth.fetched_from_mt5 is True
    assert depth.first_utc is not None and depth.last_utc is not None
    # Round-trip: quedo en el cache SQLite compartido con mt5_historical
    cached = repo.fetch_mt5_cache_window(
        "EURUSD", MT5Timeframe.D1, 1_600_000_000, 1_600_000_000 + 2 * _DAY
    )
    assert len(cached) == 3


def test_load_symbol_idempotent_no_duplicates() -> None:
    repo = _repo()
    reader = _connected_reader(_candles(5))
    loader = BacktestHistoricalLoader(_settings(), repo, reader)

    first = loader.load_symbol("EURUSD", MT5Timeframe.D1)
    second = loader.load_symbol("EURUSD", MT5Timeframe.D1)

    assert first.bars == 5
    assert second.bars == 5  # upsert: re-cargar no duplica barras


def test_symbol_without_data_soft_fails_with_clear_note() -> None:
    repo = _repo()
    reader = _connected_reader(None)  # MT5 conectado pero sin data
    loader = BacktestHistoricalLoader(_settings(), repo, reader)

    depth = loader.load_symbol("XAUUSD", MT5Timeframe.D1)

    assert depth.bars == 0
    assert depth.fetched_from_mt5 is False
    assert "sin data" in depth.note.lower()


def test_disconnected_reader_serves_cache_only() -> None:
    repo = _repo()
    repo.upsert_mt5_cache_candles("EURUSD", MT5Timeframe.D1, _candles(4))
    reader = MagicMock()
    reader.is_connected.return_value = False
    loader = BacktestHistoricalLoader(_settings(), repo, reader)

    depth = loader.load_symbol("EURUSD", MT5Timeframe.D1)

    assert depth.bars == 4
    assert depth.fetched_from_mt5 is False
    assert "no conectado" in depth.note.lower()
    reader.get_rates.assert_not_called()


def test_probe_descends_until_data_appears() -> None:
    """MT5 puede devolver None si el count pedido excede Max bars: el probe
    baja hasta encontrar un count que el terminal banque."""
    repo = _repo()
    reader = MagicMock()
    reader.is_connected.return_value = True

    def rates_for(symbol: str, timeframe: int, count: int):
        return _candles(10) if count <= 10_000 else None

    reader.get_rates.side_effect = rates_for
    loader = BacktestHistoricalLoader(_settings(), repo, reader)

    depth = loader.load_symbol("EURUSD", MT5Timeframe.D1)

    assert depth.bars == 10
    tried_counts = [c.args[2] for c in reader.get_rates.call_args_list]
    assert tried_counts[0] > 10_000  # empezo por el mas profundo
    assert tried_counts[-1] <= 10_000  # y bajo hasta lograr data


def test_d1_and_h1_map_to_mt5_api_constants() -> None:
    """1440/60 minutos NO son constantes validas del package MetaTrader5
    (D1=16408, H1=16385): sin el mapeo, copy_rates devuelve None silencioso."""
    repo = _repo()
    reader = _connected_reader(_candles(2))
    loader = BacktestHistoricalLoader(_settings(), repo, reader)

    loader.load_symbol("EURUSD", MT5Timeframe.D1)
    assert reader.get_rates.call_args.args[1] == 16408

    loader.load_symbol("EURUSD", MT5Timeframe.H1)
    assert reader.get_rates.call_args.args[1] == 16385


def test_load_all_covers_settings_symbols_d1_and_h1() -> None:
    repo = _repo()
    reader = _connected_reader(_candles(2))
    settings = _settings()
    loader = BacktestHistoricalLoader(settings, repo, reader)

    summary = loader.load_all()

    assert summary.mt5_connected is True
    expected = {(s, label) for s in settings.backtest_symbols for label in ("D1", "H1")}
    got = {(d.symbol, d.timeframe_label) for d in summary.depths}
    assert got == expected


def test_timeframe_label_parsing() -> None:
    assert timeframe_minutes_from_label("D1") == MT5Timeframe.D1
    assert timeframe_minutes_from_label("h1") == MT5Timeframe.H1
    assert timeframe_minutes_from_label("desconocido") is None


def test_depth_report_marks_missing_and_truncation() -> None:
    summary = LoadSummary(
        mt5_connected=True,
        depths=[
            SymbolDepth(
                symbol="EURUSD", timeframe_label="D1",
                timeframe_minutes=MT5Timeframe.D1, bars=5200,
                first_utc="2006-06-12 00:00 UTC", last_utc="2026-06-11 00:00 UTC",
            ),
            SymbolDepth(
                symbol="NZDUSD", timeframe_label="D1",
                timeframe_minutes=MT5Timeframe.D1, bars=0,
            ),
            SymbolDepth(
                symbol="XAUUSD", timeframe_label="D1",
                timeframe_minutes=MT5Timeframe.D1, bars=800,
                first_utc="2024-01-02 00:00 UTC", last_utc="2026-06-11 00:00 UTC",
                truncation_suspect=True,
            ),
        ],
    )
    report = depth_report(summary)
    assert "EURUSD" in report and "5200" in report
    assert "SIN DATA" in report  # simbolo sin data, aviso claro
    assert "truncamiento" in report  # sospecha de Max bars corto
    assert "Max. barras" in report  # y la instruccion de como arreglarlo


def test_loader_marks_short_d1_history_as_truncation_suspect() -> None:
    repo = _repo()
    reader = _connected_reader(_candles(100))  # 100 barras D1 = sospechoso
    loader = BacktestHistoricalLoader(_settings(), repo, reader)

    depth = loader.load_symbol("EURUSD", MT5Timeframe.D1)

    assert depth.truncation_suspect is True
