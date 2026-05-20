"""Tests para extensiones Phase 4 del MT5 reader: symbol_info,
validate_symbol, compute_pip_value, get_historical_range, timeframe constants.
"""

import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.brokers.mt5_reader import MT5Reader, MT5Timeframe
from tests.test_score import _settings


def _enable_mt5(base):
    return type(base)(
        **{
            **base.__dict__,
            "enable_mt5_reader": True,
            "mt5_login": 123456,
            "mt5_password": "x",
            "mt5_server": "ICMarkets-Demo",
        }
    )


def _fake_mt5_with_symbol_info(info_obj) -> types.ModuleType:
    fake = types.ModuleType("MetaTrader5")
    fake.initialize = MagicMock(return_value=True)
    fake.shutdown = MagicMock()
    fake.symbol_info = MagicMock(return_value=info_obj)
    return fake


def test_timeframe_constants() -> None:
    assert MT5Timeframe.M1 == 1
    assert MT5Timeframe.M5 == 5
    assert MT5Timeframe.M15 == 15
    assert MT5Timeframe.H1 == 60
    assert MT5Timeframe.H4 == 240
    assert MT5Timeframe.D1 == 1440


def test_validate_symbol_returns_true_when_found(monkeypatch) -> None:
    settings = _enable_mt5(_settings())
    monkeypatch.setitem(
        sys.modules,
        "MetaTrader5",
        _fake_mt5_with_symbol_info(SimpleNamespace(name="EURUSD")),
    )
    reader = MT5Reader(settings)
    assert reader.connect() is True
    assert reader.validate_symbol("EURUSD") is True


def test_validate_symbol_returns_false_when_not_found(monkeypatch) -> None:
    settings = _enable_mt5(_settings())
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5_with_symbol_info(None))
    reader = MT5Reader(settings)
    reader.connect()
    assert reader.validate_symbol("NOSYMBOL") is False


def test_symbol_info_dict_shape(monkeypatch) -> None:
    settings = _enable_mt5(_settings())
    info = SimpleNamespace(
        name="EURUSD", spread=10, point=0.00001, digits=5,
        trade_contract_size=100000.0, volume_min=0.01, volume_step=0.01,
        trade_tick_value=1.0, trade_tick_size=0.00001, currency_profit="USD",
    )
    monkeypatch.setitem(
        sys.modules, "MetaTrader5", _fake_mt5_with_symbol_info(info)
    )
    reader = MT5Reader(settings)
    reader.connect()
    result = reader.symbol_info("EURUSD")
    assert result is not None
    assert result["name"] == "EURUSD"
    assert result["spread"] == 10
    assert result["digits"] == 5
    assert result["trade_contract_size"] == 100000.0
    assert result["currency_profit"] == "USD"


def test_compute_pip_value_for_eurusd(monkeypatch) -> None:
    """EURUSD 5-digit: 1 pip = 10 points. tick_value=1.0 → 10.0 per lot."""
    settings = _enable_mt5(_settings())
    info = SimpleNamespace(
        name="EURUSD", spread=10, point=0.00001, digits=5,
        trade_contract_size=100000.0, volume_min=0.01, volume_step=0.01,
        trade_tick_value=1.0, trade_tick_size=0.00001, currency_profit="USD",
    )
    monkeypatch.setitem(
        sys.modules, "MetaTrader5", _fake_mt5_with_symbol_info(info)
    )
    reader = MT5Reader(settings)
    reader.connect()
    pip = reader.compute_pip_value("EURUSD", lot_size=1.0)
    assert pip is not None
    # 1.0 * (10 * 0.00001 / 0.00001) = 10.0
    assert abs(pip - 10.0) < 0.01


def test_get_historical_range_parses_candles(monkeypatch) -> None:
    settings = _enable_mt5(_settings())
    fake = types.ModuleType("MetaTrader5")
    fake.initialize = MagicMock(return_value=True)
    fake.shutdown = MagicMock()
    fake.copy_rates_range = MagicMock(
        return_value=[
            {"time": 1, "open": 1.10, "high": 1.11, "low": 1.09, "close": 1.105, "tick_volume": 100},
            {"time": 2, "open": 1.105, "high": 1.115, "low": 1.10, "close": 1.110, "tick_volume": 120},
        ]
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    reader = MT5Reader(settings)
    reader.connect()
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 2, tzinfo=timezone.utc)
    candles = reader.get_historical_range("EURUSD", MT5Timeframe.M15, start, end)
    assert candles is not None
    assert len(candles) == 2
    assert candles[0]["close"] == 1.105
    assert candles[1]["volume"] == 120
