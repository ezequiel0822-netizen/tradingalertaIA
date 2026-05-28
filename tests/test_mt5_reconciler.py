"""v2.6.7 — MT5Reconciler + close_position_by_ticket + update_position_sl tests.

Verifica:
- close_position_by_ticket reusa _close_position interno cuando ticket existe.
- close_position_by_ticket falla limpio si ticket no está en MT5.
- update_position_sl arma TRADE_ACTION_SLTP correcto y maneja success/fail.
- MT5Reconciler:
  * Cierra MT5 huérfana cuando paper_trade.status != 'open'.
  * Sincroniza SL cuando paper_trade.SL difiere de MT5.sl (TIGHTENING only).
  * No-op cuando todo en sync.
  * Soft-fail si trader.positions() falla.
  * Ignora posiciones MT5 sin demo_order matching (manual trades).
  * NUNCA relaja el SL (loosening) — solo tighten.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.brokers.mt5_demo_trader import MT5DemoTrader, DemoCloseResult, DemoSendResult
from app.database.db import init_db
from app.database.repository import Repository
from app.portfolio.mt5_reconciler import MT5Reconciler, ReconcileSummary
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


# ---------------- Helpers ----------------


def _demo_settings(**overrides):
    base = _settings()
    values = {
        **base.__dict__,
        "enable_mt5_reader": True,
        "enable_mt5_demo_trading": True,
        "demo_order_require_confirmation": True,
        "demo_max_open_trades": 5,
        "demo_risk_per_trade_pct": 1.5,
        "demo_max_lot": 0.1,
        "demo_allowed_symbols": ["eurusd", "xauusd"],
        "enable_real_trading": False,
        "mt5_login": 123456,
        "mt5_password": "demo-password",
        "mt5_server": "ICMarkets-Demo",
        **overrides,
    }
    return type(base)(**values)


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"reconciler_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_paper_trade(
    repo: Repository, *, status: str = "open", stop_loss: float = 1.0990, **extras
) -> int:
    base = {
        "alert_id": 0,
        "token_id": 0,
        "category": "forex",
        "chain": "forex",
        "token_address": "EURUSD",
        "symbol": "EURUSD",
        "thesis": "test",
        "readiness_grade": "A",
        "entry_price": 1.1000,
        "latest_price": 1.1000,
        "stop_loss": stop_loss,
        "take_profit_1": 1.1020,
        "take_profit_2": 1.1040,
        "invalidation": "x",
        "status": status,
        "unrealized_return_pct": 0,
        "opened_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "closed_at": None,
        "strategy_name": "breakout",
        "direction": "long",
        "time_horizon_hours": 48,
        "size_notional": 100000,
        "size_units": 100000,
        "risk_pct": 1.0,
        "partial_closed": 0,
    }
    base.update(extras)
    repo.create_paper_trade(base)
    trades = repo.fetch_paper_trades(limit=10) or []
    return int(trades[0]["id"])


def _seed_demo_order(
    repo: Repository, *, paper_trade_id: int, order_ticket: int, symbol: str = "EURUSD"
) -> None:
    repo.create_demo_order({
        "demo_request_id": 0,
        "paper_trade_id": paper_trade_id,
        "symbol": symbol,
        "direction": "long",
        "volume": 0.1,
        "price": 1.1000,
        "stop_loss": 1.0990,
        "take_profit": 1.1020,
        "retcode": 10009,
        "order_ticket": order_ticket,
        "deal_ticket": order_ticket + 1000,
        "status": "sent",
        "strategy_name": "breakout",
        "result_summary": "ok",
        "sent_at": utc_now_iso(),
    })


def _fake_mt5(*, positions=None, order_send_result=None):
    fake = types.ModuleType("MetaTrader5")
    fake.ACCOUNT_TRADE_MODE_DEMO = 0
    fake.TRADE_ACTION_DEAL = 1
    fake.TRADE_ACTION_SLTP = 6
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
        return_value=SimpleNamespace(
            balance=88700.0, equity=88700.0, currency="USD",
            server="ICMarkets-Demo", login=123456, name="Demo",
            company="ICMarkets Demo", trade_mode=0,
            trade_allowed=True, trade_expert=True,
        )
    )
    fake.symbol_info = MagicMock(
        return_value=SimpleNamespace(
            name="EURUSD", visible=True, point=0.00001, digits=5,
            trade_contract_size=100000.0,
            volume_min=0.01, volume_step=0.01, volume_max=100.0,
            trade_tick_value=1.0, trade_tick_size=0.00001,
            currency_profit="USD", filling_mode=1,
        )
    )
    fake.symbol_select = MagicMock(return_value=True)
    fake.symbol_info_tick = MagicMock(
        return_value=SimpleNamespace(bid=1.10000, ask=1.10002, last=1.10001, time=1)
    )
    fake.positions_get = MagicMock(return_value=positions or [])
    if order_send_result is None:
        order_send_result = lambda req: SimpleNamespace(
            retcode=10009, order=999, deal=1999,
            price=req.get("price", 0), comment="executed",
        )
    fake.order_send = MagicMock(side_effect=order_send_result)
    return fake


# ---------------- close_position_by_ticket ----------------


def test_close_position_by_ticket_success(monkeypatch) -> None:
    pos = SimpleNamespace(
        ticket=12345, symbol="EURUSD", volume=0.1, type=0,
        price_open=1.1000, price_current=1.1010, sl=1.0990, tp=1.1020, profit=10.0,
    )
    fake = _fake_mt5(positions=[pos])
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    trader = MT5DemoTrader(_demo_settings())

    result = trader.close_position_by_ticket(12345)
    assert result.ok is True
    assert result.ticket == 12345
    assert result.symbol == "EURUSD"


def test_close_position_by_ticket_not_found(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5(positions=[]))
    trader = MT5DemoTrader(_demo_settings())

    result = trader.close_position_by_ticket(99999)
    assert result.ok is False
    assert "not found" in result.reason


def test_close_position_by_ticket_blocked_when_demo_off(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    trader = MT5DemoTrader(_demo_settings(enable_mt5_demo_trading=False))

    result = trader.close_position_by_ticket(12345)
    assert result.ok is False
    assert "ENABLE_MT5_DEMO_TRADING" in result.reason


# ---------------- update_position_sl ----------------


def test_update_position_sl_success(monkeypatch) -> None:
    pos = SimpleNamespace(
        ticket=55555, symbol="EURUSD", volume=0.1, type=0,
        price_open=1.1000, price_current=1.1010, sl=1.0990, tp=1.1020, profit=10.0,
    )
    captured_requests = []

    def capture(req):
        captured_requests.append(dict(req))
        return SimpleNamespace(retcode=10009, order=999, deal=1999, price=0, comment="ok")

    fake = _fake_mt5(positions=[pos], order_send_result=capture)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    trader = MT5DemoTrader(_demo_settings())

    result = trader.update_position_sl(55555, new_sl=1.0995)
    assert result.ok is True

    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req["action"] == 6  # TRADE_ACTION_SLTP
    assert req["position"] == 55555
    assert req["sl"] == 1.0995
    assert req["tp"] == 1.1020  # preservado


def test_update_position_sl_not_found(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5(positions=[]))
    trader = MT5DemoTrader(_demo_settings())

    result = trader.update_position_sl(404, new_sl=1.0995)
    assert result.ok is False
    assert "not found" in result.reason


# ---------------- MT5Reconciler ----------------


def _mock_trader_with_positions(positions: list[dict]):
    trader = MagicMock()
    trader.positions = MagicMock(return_value=positions)
    trader.close_position_by_ticket = MagicMock(
        return_value=DemoCloseResult(
            ok=True, ticket=0, symbol="EURUSD", volume=0.1,
            reason="closed", retcode=10009, price=1.1010,
        )
    )
    trader.update_position_sl = MagicMock(
        return_value=DemoSendResult(
            ok=True, status="sent", reason="SL updated", retcode=10009,
        )
    )
    return trader


def test_reconciler_noop_when_demo_disabled() -> None:
    repo = _repo()
    trader = _mock_trader_with_positions([])
    rec = MT5Reconciler(_demo_settings(enable_mt5_demo_trading=False), repo, trader)
    summary = rec.reconcile()
    assert summary.positions_checked == 0
    assert summary.orphans_closed == 0
    trader.positions.assert_not_called()


def test_reconciler_noop_when_no_mt5_positions() -> None:
    repo = _repo()
    trader = _mock_trader_with_positions([])
    rec = MT5Reconciler(_demo_settings(), repo, trader)
    summary = rec.reconcile()
    assert summary.positions_checked == 0
    assert summary.orphans_closed == 0


def test_reconciler_closes_orphan_when_paper_trade_closed() -> None:
    repo = _repo()
    pt_id = _seed_paper_trade(repo, status="closed_by_time")
    _seed_demo_order(repo, paper_trade_id=pt_id, order_ticket=77777)

    positions = [{
        "ticket": 77777, "symbol": "EURUSD", "volume": 0.1, "type": 0,
        "price_open": 1.1000, "price_current": 1.0980,
        "sl": 1.0990, "tp": 1.1020, "profit": -200.0,
    }]
    trader = _mock_trader_with_positions(positions)
    rec = MT5Reconciler(_demo_settings(), repo, trader)

    summary = rec.reconcile()
    assert summary.positions_checked == 1
    assert summary.orphans_closed == 1
    trader.close_position_by_ticket.assert_called_once_with(77777)


def test_reconciler_syncs_sl_when_paper_trade_tightens() -> None:
    repo = _repo()
    pt_id = _seed_paper_trade(repo, status="open", stop_loss=1.0998)
    _seed_demo_order(repo, paper_trade_id=pt_id, order_ticket=88888)

    positions = [{
        "ticket": 88888, "symbol": "EURUSD", "volume": 0.1, "type": 0,
        "price_open": 1.1000, "price_current": 1.1005,
        "sl": 1.0990, "tp": 1.1020, "profit": 50.0,
    }]
    trader = _mock_trader_with_positions(positions)
    rec = MT5Reconciler(_demo_settings(), repo, trader)

    summary = rec.reconcile()
    assert summary.sls_synced == 1
    trader.update_position_sl.assert_called_once()
    call = trader.update_position_sl.call_args
    assert call.args[0] == 88888
    assert call.args[1] == 1.0998
    trader.close_position_by_ticket.assert_not_called()


def test_reconciler_does_not_loosen_sl_on_long() -> None:
    repo = _repo()
    pt_id = _seed_paper_trade(repo, status="open", stop_loss=1.0980)
    _seed_demo_order(repo, paper_trade_id=pt_id, order_ticket=11111)

    positions = [{
        "ticket": 11111, "symbol": "EURUSD", "volume": 0.1, "type": 0,
        "price_open": 1.1000, "price_current": 1.1005,
        "sl": 1.0995, "tp": 1.1020, "profit": 50.0,
    }]
    trader = _mock_trader_with_positions(positions)
    rec = MT5Reconciler(_demo_settings(), repo, trader)

    summary = rec.reconcile()
    assert summary.sls_synced == 0
    trader.update_position_sl.assert_not_called()


def test_reconciler_does_not_loosen_sl_on_short() -> None:
    repo = _repo()
    pt_id = _seed_paper_trade(
        repo, status="open", stop_loss=1.1020, direction="short",
    )
    _seed_demo_order(repo, paper_trade_id=pt_id, order_ticket=22222)

    positions = [{
        "ticket": 22222, "symbol": "EURUSD", "volume": 0.1, "type": 1,
        "price_open": 1.1000, "price_current": 1.0995,
        "sl": 1.1010, "tp": 1.0980, "profit": 50.0,
    }]
    trader = _mock_trader_with_positions(positions)
    rec = MT5Reconciler(_demo_settings(), repo, trader)

    summary = rec.reconcile()
    assert summary.sls_synced == 0
    trader.update_position_sl.assert_not_called()


def test_reconciler_ignores_unmatched_positions() -> None:
    repo = _repo()

    positions = [{
        "ticket": 33333, "symbol": "EURUSD", "volume": 0.1, "type": 0,
        "price_open": 1.1000, "price_current": 1.1005,
        "sl": 1.0990, "tp": 1.1020, "profit": 50.0,
    }]
    trader = _mock_trader_with_positions(positions)
    rec = MT5Reconciler(_demo_settings(), repo, trader)

    summary = rec.reconcile()
    assert summary.unmatched == 1
    assert summary.orphans_closed == 0
    assert summary.sls_synced == 0
    trader.close_position_by_ticket.assert_not_called()
    trader.update_position_sl.assert_not_called()


def test_reconciler_soft_fails_on_positions_error() -> None:
    repo = _repo()
    trader = MagicMock()
    trader.positions = MagicMock(side_effect=RuntimeError("MT5 disconnected"))
    rec = MT5Reconciler(_demo_settings(), repo, trader)

    summary = rec.reconcile()
    assert summary.errors == 1
    assert summary.orphans_closed == 0


def test_reconciler_no_op_when_sl_in_sync() -> None:
    repo = _repo()
    pt_id = _seed_paper_trade(repo, status="open", stop_loss=1.0990)
    _seed_demo_order(repo, paper_trade_id=pt_id, order_ticket=44444)

    positions = [{
        "ticket": 44444, "symbol": "EURUSD", "volume": 0.1, "type": 0,
        "price_open": 1.1000, "price_current": 1.1005,
        "sl": 1.0990, "tp": 1.1020, "profit": 50.0,
    }]
    trader = _mock_trader_with_positions(positions)
    rec = MT5Reconciler(_demo_settings(), repo, trader)

    summary = rec.reconcile()
    assert summary.sls_synced == 0
    trader.update_position_sl.assert_not_called()
    trader.close_position_by_ticket.assert_not_called()


def test_reconciler_summary_dataclass_defaults() -> None:
    s = ReconcileSummary()
    assert s.positions_checked == 0
    assert s.orphans_closed == 0
    assert s.orphans_close_failed == 0
    assert s.sls_synced == 0
    assert s.sls_sync_failed == 0
    assert s.unmatched == 0
    assert s.errors == 0
