import logging
import sys
import types
from unittest.mock import MagicMock

from app.brokers.mt5_reader import MT5Reader
from tests.test_score import _settings


def _enable_mt5(base):
    return type(base)(
        **{
            **base.__dict__,
            "enable_mt5_reader": True,
            "mt5_login": 123456,
            "mt5_password": "supersecret_NOT_REAL",
            "mt5_server": "TestBroker-Demo",
        }
    )


def test_disabled_returns_falsy() -> None:
    settings = _settings()  # enable_mt5_reader=False
    reader = MT5Reader(settings)
    assert reader.connect() is False
    assert reader.is_connected() is False
    assert reader.get_tick("EURUSD") is None
    assert reader.get_rates("EURUSD", 1, 100) is None
    assert reader.get_account_info() is None


def test_import_failure_soft_fails(monkeypatch) -> None:
    settings = _enable_mt5(_settings())
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    reader = MT5Reader(settings)
    # con sys.modules[name]=None Python lanza ImportError al import
    assert reader.connect() is False
    assert reader.is_connected() is False


def test_initialize_failure_does_not_raise(monkeypatch) -> None:
    settings = _enable_mt5(_settings())
    fake = types.ModuleType("MetaTrader5")
    fake.initialize = MagicMock(return_value=False)
    fake.last_error = MagicMock(return_value=(-10001, "some error"))
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    reader = MT5Reader(settings)
    assert reader.connect() is False
    assert reader.is_connected() is False


def test_get_tick_returns_normalized_dict(monkeypatch) -> None:
    settings = _enable_mt5(_settings())
    fake = types.ModuleType("MetaTrader5")
    fake.initialize = MagicMock(return_value=True)
    fake.shutdown = MagicMock()
    tick_obj = types.SimpleNamespace(bid=1.0851, ask=1.0853, last=1.0852, time=1700000000)
    fake.symbol_info_tick = MagicMock(return_value=tick_obj)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    reader = MT5Reader(settings)
    assert reader.connect() is True
    tick = reader.get_tick("EURUSD")
    assert tick is not None
    assert tick["bid"] == 1.0851
    assert tick["ask"] == 1.0853
    assert tick["time"] == 1700000000


def test_get_rates_returns_candles(monkeypatch) -> None:
    settings = _enable_mt5(_settings())
    fake = types.ModuleType("MetaTrader5")
    fake.initialize = MagicMock(return_value=True)
    fake.shutdown = MagicMock()
    rates_data = [
        {"time": 1, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "tick_volume": 100},
        {"time": 2, "open": 1.05, "high": 1.15, "low": 1.0, "close": 1.1, "tick_volume": 150},
    ]
    fake.copy_rates_from_pos = MagicMock(return_value=rates_data)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    reader = MT5Reader(settings)
    reader.connect()
    candles = reader.get_rates("EURUSD", 1, 2)
    assert candles is not None
    assert len(candles) == 2
    assert candles[0]["close"] == 1.05
    assert candles[1]["volume"] == 150


def test_no_password_in_logs(monkeypatch, caplog) -> None:
    secret = "supersecret_NOT_REAL"
    settings = _enable_mt5(_settings())
    fake = types.ModuleType("MetaTrader5")
    fake.initialize = MagicMock(return_value=False)
    fake.last_error = MagicMock(return_value=(-10002, "auth failed"))
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    with caplog.at_level(logging.WARNING):
        reader = MT5Reader(settings)
        reader.connect()

    all_log_text = " ".join(record.getMessage() for record in caplog.records)
    assert secret not in all_log_text
    assert settings.mt5_server not in all_log_text
