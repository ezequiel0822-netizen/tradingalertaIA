"""Tests para mt5_symbol_map."""

from app.brokers.mt5_symbol_map import (
    mt5_to_yahoo,
    supported_brokers,
    yahoo_to_mt5,
)


def test_yahoo_to_mt5_forex_icmarkets() -> None:
    assert yahoo_to_mt5("EURUSD=X") == "EURUSD"
    assert yahoo_to_mt5("GBPUSD=X") == "GBPUSD"
    assert yahoo_to_mt5("USDJPY=X") == "USDJPY"


def test_yahoo_to_mt5_gold() -> None:
    assert yahoo_to_mt5("GC=F") == "XAUUSD"
    assert yahoo_to_mt5("XAUUSD=X") == "XAUUSD"


def test_yahoo_to_mt5_unknown_returns_none() -> None:
    assert yahoo_to_mt5("UNKNOWN") is None
    assert yahoo_to_mt5("") is None
    assert yahoo_to_mt5("NVDA") is None  # stock CFD no mapeado


def test_mt5_to_yahoo_reverse() -> None:
    assert mt5_to_yahoo("EURUSD") == "EURUSD=X"
    assert mt5_to_yahoo("XAUUSD") in {"GC=F", "XAUUSD=X"}
    assert mt5_to_yahoo("UNKNOWN") is None


def test_supported_brokers_list() -> None:
    brokers = supported_brokers()
    assert "icmarkets" in brokers
    assert len(brokers) >= 2
