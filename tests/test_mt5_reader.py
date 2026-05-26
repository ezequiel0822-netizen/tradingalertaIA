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


def test_safe_tick_volume_handles_numpy_void_like_objects() -> None:
    """v2.6.4 regression: numpy.void no tiene .get(), solo __getitem__.

    Antes mt5_reader.get_rates crasheaba con
    `AttributeError: 'numpy.void' object has no attribute 'get'`
    contra MT5 real. El helper _safe_tick_volume usa bracket access con
    try/except, manejando ambos casos.
    """
    from app.brokers.mt5_reader import _safe_tick_volume

    # Caso 1: dict normal (lo que usan los tests con mocks)
    assert _safe_tick_volume({"tick_volume": 100}) == 100.0

    # Caso 2: numpy.void-like (solo __getitem__, NO .get)
    class FakeVoid:
        def __init__(self, data: dict) -> None:
            self._data = data

        def __getitem__(self, key: str):
            return self._data[key]
        # Intencionalmente NO definimos .get() para reproducir numpy.void

    assert _safe_tick_volume(FakeVoid({"tick_volume": 250})) == 250.0

    # Caso 3: campo ausente
    assert _safe_tick_volume(FakeVoid({"time": 1})) == 0.0

    # Caso 4: None directo (defensive)
    assert _safe_tick_volume(None) == 0.0

    # Caso 5: valor None en el campo
    assert _safe_tick_volume({"tick_volume": None}) == 0.0


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
    fake.symbol_select = MagicMock(return_value=True)
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


def test_get_rates_calls_symbol_select_before_copy_rates(monkeypatch) -> None:
    """v2.6.5 regression: get_rates DEBE llamar symbol_select(symbol, True)
    antes de copy_rates_from_pos.

    Bug original: si símbolo no estaba en Market Watch del MT5 desktop,
    copy_rates_from_pos devolvía None silenciosamente → "0 velas M1" en
    scalping. User tenía que agregar manualmente cada símbolo a Market Watch.
    Ahora el bot lo hace automáticamente.
    """
    settings = _enable_mt5(_settings())
    fake = types.ModuleType("MetaTrader5")
    fake.initialize = MagicMock(return_value=True)
    fake.shutdown = MagicMock()
    fake.symbol_select = MagicMock(return_value=True)
    fake.copy_rates_from_pos = MagicMock(return_value=[])
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    reader = MT5Reader(settings)
    reader.connect()
    reader.get_rates("USDJPY", 1, 5)

    # Verificar que symbol_select fue llamado con (symbol, True) ANTES de copy_rates
    assert fake.symbol_select.called, "symbol_select debe llamarse antes de copy_rates_from_pos"
    call_args = fake.symbol_select.call_args
    assert call_args.args[0] == "USDJPY", f"Esperaba 'USDJPY', recibió {call_args.args[0]!r}"
    assert call_args.args[1] is True, "Segundo arg debe ser True (selecciona el símbolo)"


def test_get_rates_continues_if_symbol_select_fails(monkeypatch) -> None:
    """v2.6.5: si symbol_select tira excepción, get_rates sigue intentando
    copy_rates_from_pos. Algunos brokers pueden rechazar symbol_select pero
    aceptar copy_rates.
    """
    settings = _enable_mt5(_settings())
    fake = types.ModuleType("MetaTrader5")
    fake.initialize = MagicMock(return_value=True)
    fake.shutdown = MagicMock()
    fake.symbol_select = MagicMock(side_effect=Exception("broker rejected"))
    rates_data = [
        {"time": 1, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "tick_volume": 100},
    ]
    fake.copy_rates_from_pos = MagicMock(return_value=rates_data)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    reader = MT5Reader(settings)
    reader.connect()
    candles = reader.get_rates("EURUSD", 1, 5)
    # No debe crashear, debe seguir y devolver las candles
    assert candles is not None
    assert len(candles) == 1


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
