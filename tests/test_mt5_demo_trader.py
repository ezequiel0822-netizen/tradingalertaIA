import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.brokers.mt5_demo_trader import MT5DemoTrader
from tests.test_score import _settings


def _demo_settings(**overrides):
    base = _settings()
    values = {
        **base.__dict__,
        "enable_mt5_reader": True,
        "enable_mt5_demo_trading": True,
        "demo_order_require_confirmation": True,
        "demo_max_open_trades": 1,
        "demo_risk_per_trade_pct": 0.25,
        "demo_max_lot": 0.01,
        "demo_allowed_symbols": ["eurusd", "xauusd"],
        "enable_real_trading": False,
        "enable_auto_confirm_demo": False,
        "demo_max_total_risk_pct": 10.0,
        "mt5_login": 123456,
        "mt5_password": "demo-password",
        "mt5_server": "ICMarkets-Demo",
        **overrides,
    }
    return type(base)(**values)


def _paper_trade(**overrides):
    trade = {
        "id": 7,
        "status": "open",
        "category": "forex",
        "symbol": "EURUSD=X",
        "direction": "long",
        "entry_price": 1.10002,
        "stop_loss": 1.09902,
        "take_profit_1": 1.10202,
        "strategy_name": "breakout",
        "thesis": "breakout: london range",
    }
    trade.update(overrides)
    return trade


def _fake_mt5(*, account=None, symbol_info=None, positions=None, tick=None):
    fake = types.ModuleType("MetaTrader5")
    fake.ACCOUNT_TRADE_MODE_DEMO = 0
    fake.TRADE_ACTION_DEAL = 1
    fake.ORDER_TYPE_BUY = 0
    fake.ORDER_TYPE_SELL = 1
    fake.ORDER_TIME_GTC = 0
    fake.ORDER_FILLING_FOK = 0
    fake.ORDER_FILLING_IOC = 1
    fake.ORDER_FILLING_RETURN = 2
    fake.TRADE_RETCODE_DONE = 10009
    fake.TRADE_RETCODE_PLACED = 10008
    fake.TRADE_RETCODE_INVALID_FILL = 10030
    fake.initialize = MagicMock(return_value=True)
    fake.shutdown = MagicMock()
    fake.account_info = MagicMock(
        return_value=account
        or SimpleNamespace(
            balance=10000.0,
            equity=10000.0,
            currency="USD",
            leverage=100,
            server="ICMarkets-Demo",
            login=123456,
            name="Demo Trader",
            company="ICMarkets Demo",
            trade_mode=0,
            trade_allowed=True,
            trade_expert=True,
        )
    )
    fake.symbol_info = MagicMock(
        return_value=symbol_info
        or SimpleNamespace(
            name="EURUSD",
            visible=True,
            spread=10,
            point=0.00001,
            digits=5,
            trade_contract_size=100000.0,
            volume_min=0.01,
            volume_step=0.01,
            volume_max=100.0,
            trade_tick_value=1.0,
            trade_tick_size=0.00001,
            currency_profit="USD",
            filling_mode=1,
        )
    )
    fake.symbol_select = MagicMock(return_value=True)
    fake.symbol_info_tick = MagicMock(
        return_value=tick
        or SimpleNamespace(bid=1.10000, ask=1.10002, last=1.10001, time=1)
    )
    fake.positions_get = MagicMock(return_value=positions or [])
    fake.order_send = MagicMock(
        side_effect=lambda request: SimpleNamespace(
            retcode=10009,
            order=111,
            deal=222,
            price=request["price"],
            comment="Request executed",
        )
    )
    return fake


def test_demo_trader_blocks_when_feature_disabled(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    trader = MT5DemoTrader(_demo_settings(enable_mt5_demo_trading=False))
    result = trader.prepare_from_paper_trade(_paper_trade())
    assert result.ok is False
    assert "ENABLE_MT5_DEMO_TRADING=false" in result.reason


def test_demo_trader_blocks_non_demo_account(monkeypatch) -> None:
    account = SimpleNamespace(
        balance=10000.0,
        equity=10000.0,
        server="ICMarkets-Live",
        name="Real Account",
        company="ICMarkets",
        trade_mode=2,
        trade_allowed=True,
        trade_expert=True,
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5(account=account))
    trader = MT5DemoTrader(_demo_settings())
    result = trader.prepare_from_paper_trade(_paper_trade())
    assert result.ok is False
    assert "not demo" in result.reason


def test_demo_trader_requires_sl_and_tp(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    trader = MT5DemoTrader(_demo_settings())
    no_sl = trader.prepare_from_paper_trade(_paper_trade(stop_loss=None))
    no_tp = trader.prepare_from_paper_trade(_paper_trade(take_profit_1=None))
    assert no_sl.ok is False
    assert "stop loss" in no_sl.reason
    assert no_tp.ok is False
    assert "take profit" in no_tp.reason


def test_demo_trader_normalizes_volume_to_step(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    trader = MT5DemoTrader(_demo_settings(demo_max_lot=0.037))
    result = trader.prepare_from_paper_trade(_paper_trade())
    assert result.ok is True
    assert result.draft is not None
    assert result.draft.volume == 0.03


def test_demo_trader_falls_back_when_tick_value_missing(monkeypatch) -> None:
    symbol_info = SimpleNamespace(
        name="EURUSD",
        visible=True,
        point=0.00001,
        trade_contract_size=100000.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        trade_tick_value=0.0,
        trade_tick_size=0.0,
        filling_mode=1,
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5(symbol_info=symbol_info))
    trader = MT5DemoTrader(_demo_settings())
    result = trader.prepare_from_paper_trade(_paper_trade())
    assert result.ok is True
    assert result.draft is not None
    assert result.draft.risk_pct > 0


def test_demo_trader_blocks_excessive_risk(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    trader = MT5DemoTrader(_demo_settings())
    result = trader.prepare_from_paper_trade(_paper_trade(stop_loss=1.00000))
    assert result.ok is False
    assert "exceeds" in result.reason


def test_demo_trader_sends_order_when_confirmed(monkeypatch) -> None:
    fake = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    trader = MT5DemoTrader(_demo_settings())
    request = {
        "symbol": "EURUSD",
        "direction": "long",
        "volume": 0.01,
        "entry_price": 1.10002,
        "stop_loss": 1.09902,
        "take_profit": 1.10202,
    }
    result = trader.send_prepared_request(request)
    assert result.ok is True
    assert result.retcode == 10009
    assert result.order_ticket == 111
    assert fake.order_send.call_count == 1


def test_demo_trader_maps_symbol_filling_flags_to_order_filling(monkeypatch) -> None:
    symbol_info = SimpleNamespace(
        name="XAUUSD",
        visible=True,
        spread=10,
        point=0.01,
        digits=2,
        trade_contract_size=100.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        trade_tick_value=1.0,
        trade_tick_size=0.01,
        currency_profit="USD",
        filling_mode=2,
    )
    fake = _fake_mt5(
        symbol_info=symbol_info,
        tick=SimpleNamespace(bid=4520.77, ask=4520.95, last=4520.86, time=1),
    )
    fake.ORDER_FILLING_FOK = 0
    fake.ORDER_FILLING_IOC = 1
    fake.ORDER_FILLING_RETURN = 2
    fake.SYMBOL_FILLING_FOK = 1
    fake.SYMBOL_FILLING_IOC = 2
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    trader = MT5DemoTrader(
        _demo_settings(
            demo_risk_per_trade_pct=5.26,
            demo_allowed_symbols=["XAUUSD"],
        )
    )
    request = {
        "symbol": "XAUUSD",
        "direction": "short",
        "volume": 0.01,
        "entry_price": 4520.77,
        "stop_loss": 4538.00,
        "take_profit": 4486.00,
    }

    result = trader.send_prepared_request(request)

    assert result.ok is True
    sent_request = fake.order_send.call_args.args[0]
    assert sent_request["type_filling"] == fake.ORDER_FILLING_IOC


def test_demo_trader_retries_next_filling_mode_when_unsupported(monkeypatch) -> None:
    symbol_info = SimpleNamespace(
        name="EURUSD",
        visible=True,
        spread=10,
        point=0.00001,
        digits=5,
        trade_contract_size=100000.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        trade_tick_value=1.0,
        trade_tick_size=0.00001,
        currency_profit="USD",
        filling_mode=1,
    )
    fake = _fake_mt5(symbol_info=symbol_info)
    fake.ORDER_FILLING_FOK = 0
    fake.TRADE_RETCODE_INVALID_FILL = 10030
    fake.order_send = MagicMock(
        side_effect=[
            SimpleNamespace(
                retcode=10030,
                order=0,
                deal=0,
                price=1.10002,
                comment="Unsupported filling mode",
            ),
            SimpleNamespace(
                retcode=10009,
                order=333,
                deal=444,
                price=1.10002,
                comment="Request executed",
            ),
        ]
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    trader = MT5DemoTrader(_demo_settings(demo_risk_per_trade_pct=5.26))
    request = {
        "symbol": "EURUSD",
        "direction": "long",
        "volume": 0.01,
        "entry_price": 1.10002,
        "stop_loss": 1.09902,
        "take_profit": 1.10202,
    }

    result = trader.send_prepared_request(request)

    assert result.ok is True
    assert result.order_ticket == 333
    sent_fillings = [
        call.args[0]["type_filling"] for call in fake.order_send.call_args_list
    ]
    assert sent_fillings == [fake.ORDER_FILLING_FOK, fake.ORDER_FILLING_IOC]


def test_demo_trader_closes_all_open_positions(monkeypatch) -> None:
    positions = [
        SimpleNamespace(
            ticket=1001,
            symbol="EURUSD",
            volume=0.01,
            type=0,
            price_open=1.1000,
            price_current=1.1010,
            sl=1.0950,
            tp=1.1100,
            profit=1.5,
        ),
        SimpleNamespace(
            ticket=1002,
            symbol="XAUUSD",
            volume=0.02,
            type=1,
            price_open=4520.0,
            price_current=4519.0,
            sl=4540.0,
            tp=4480.0,
            profit=2.0,
        ),
    ]
    fake = _fake_mt5(positions=positions)
    fake.symbol_info_tick = MagicMock(
        side_effect=[
            SimpleNamespace(bid=1.1010, ask=1.1012, last=1.1011, time=1),
            SimpleNamespace(bid=4519.0, ask=4519.2, last=4519.1, time=1),
        ]
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    trader = MT5DemoTrader(_demo_settings(demo_allowed_symbols=["EURUSD", "XAUUSD"]))
    results = trader.close_all_positions()

    assert [result.ok for result in results] == [True, True]
    sent = [call.args[0] for call in fake.order_send.call_args_list]
    assert sent[0]["position"] == 1001
    assert sent[0]["type"] == fake.ORDER_TYPE_SELL
    assert sent[1]["position"] == 1002
    assert sent[1]["type"] == fake.ORDER_TYPE_BUY
