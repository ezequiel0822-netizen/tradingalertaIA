"""v2.6.0 Phase 5.5 Bloque B — ScalpingEngine tests.

Tests del ScalpingEngine sin levantar threads (llamando directamente a
_run_one_cycle). Mockea mt5_reader y mt5_demo_trader.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.brokers.mt5_demo_trader import DemoSendResult
from app.database.db import init_db
from app.database.repository import Repository
from app.scheduler.scalping_engine import ScalpingEngine
from app.utils.time_utils import utc_now
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"scalping_eng_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _settings_scalping(**overrides):
    base = _settings()
    return type(base)(
        **{
            **base.__dict__,
            "enable_scalping_engine": True,
            "scalping_allowed_symbols": ["EURUSD"],
            "scalping_max_open_trades": 3,
            "scalping_max_trades_per_day": 30,
            "enable_mt5_demo_trading": False,  # simplifica: paper-only para la mayoria de tests
            **overrides,
        }
    )


def _candles_with_breakout(direction: str) -> list[dict]:
    """Genera 11 velas: 10 en rango, 1 con breakout (LONG o SHORT)."""
    base = [{"high": 1.1010, "low": 1.1000, "close": 1.1005, "time": i} for i in range(10)]
    if direction == "long":
        last = {"high": 1.1020, "low": 1.1015, "close": 1.1018, "time": 10}
    else:
        last = {"high": 1.1005, "low": 1.0985, "close": 1.0990, "time": 10}
    return base + [last]


def _mock_mt5_reader(candles: list[dict], ask: float, bid: float):
    reader = MagicMock()
    reader.is_connected = MagicMock(return_value=True)
    reader.get_rates = MagicMock(return_value=candles)
    reader.get_tick = MagicMock(return_value={"ask": ask, "bid": bid})
    reader.symbol_info = MagicMock(return_value={"point": 0.00001, "digits": 5})
    return reader


def _mock_trader_success():
    """Mock trader que devuelve send_result OK."""
    trader = MagicMock()
    trader.positions = MagicMock(return_value=[])
    trader.send_prepared_request = MagicMock(
        return_value=DemoSendResult(
            ok=True,
            status="sent",
            reason="order_send accepted",
            retcode=10009,
            order_ticket=111,
            deal_ticket=222,
            price=1.1020,
            result_summary="ok",
        )
    )
    return trader


# ---------------- Tests ----------------


def test_engine_thread_lifecycle() -> None:
    """start() arranca thread, stop() lo termina limpio."""
    repo = _repo()
    notifier = MagicMock()
    reader = _mock_mt5_reader(_candles_with_breakout("long"), 1.1020, 1.1019)
    engine = ScalpingEngine(_settings_scalping(), repo, notifier, reader, mt5_demo_trader=_mock_trader_success())

    assert engine.is_running() is False
    engine.start()
    assert engine.is_running() is True
    engine.stop(timeout=5.0)
    assert engine.is_running() is False


def test_engine_skips_when_global_kill_active() -> None:
    """Kill switch global presente → cycle returns sin abrir trades."""
    repo = _repo()
    notifier = MagicMock()
    reader = _mock_mt5_reader(_candles_with_breakout("long"), 1.1020, 1.1019)
    trader = _mock_trader_success()
    engine = ScalpingEngine(_settings_scalping(), repo, notifier, reader, trader)

    future = utc_now() + timedelta(hours=1)
    repo.set_state("kill_switch_active_until", future.isoformat())

    result = engine._run_one_cycle()
    assert result.trades_opened == 0
    assert trader.send_prepared_request.call_count == 0


def test_engine_skips_when_scalping_halted() -> None:
    """bot_state.scalping_halted=true → cycle returns sin trades."""
    repo = _repo()
    notifier = MagicMock()
    reader = _mock_mt5_reader(_candles_with_breakout("long"), 1.1020, 1.1019)
    trader = _mock_trader_success()
    engine = ScalpingEngine(_settings_scalping(), repo, notifier, reader, trader)

    repo.set_state("scalping_halted", "true")

    result = engine._run_one_cycle()
    assert result.trades_opened == 0


def test_engine_opens_paper_trade_on_valid_signal() -> None:
    """Strategy emite LONG → engine crea paper_trade is_scalping=1 (sin MT5 demo)."""
    repo = _repo()
    notifier = MagicMock()
    reader = _mock_mt5_reader(_candles_with_breakout("long"), 1.1020, 1.1019)
    settings = _settings_scalping(enable_mt5_demo_trading=False)
    engine = ScalpingEngine(settings, repo, notifier, reader)

    result = engine._run_one_cycle()
    assert result.signals_evaluated >= 1
    assert result.trades_opened == 1

    # Verifica que paper_trade quedo en DB con is_scalping=1
    open_trades = repo.fetch_open_positions_full() or []
    scalping_trades = [t for t in open_trades if int(t.get("is_scalping") or 0) == 1]
    assert len(scalping_trades) == 1
    assert scalping_trades[0]["symbol"] == "EURUSD"
    assert scalping_trades[0]["direction"] == "long"
    assert scalping_trades[0]["strategy_name"] == "scalping_breakout"


def test_engine_executes_to_mt5_when_demo_enabled() -> None:
    """Con demo trading ON, scalping llama send_prepared_request y crea demo_order."""
    repo = _repo()
    notifier = MagicMock()
    reader = _mock_mt5_reader(_candles_with_breakout("long"), 1.1020, 1.1019)
    trader = _mock_trader_success()
    settings = _settings_scalping(enable_mt5_demo_trading=True)
    engine = ScalpingEngine(settings, repo, notifier, reader, trader)

    result = engine._run_one_cycle()
    assert result.trades_opened == 1
    assert trader.send_prepared_request.call_count == 1

    # Verifica que demo_order quedo en DB con is_scalping=1
    orders = repo.fetch_demo_orders(limit=5)
    assert len(orders) == 1
    assert int(orders[0].get("is_scalping") or 0) == 1
    assert orders[0]["status"] == "sent"


def test_engine_blocks_when_max_open_cap_reached() -> None:
    """Si ya hay scalping_max_open_trades abiertos, no opens nuevos."""
    repo = _repo()
    notifier = MagicMock()
    reader = _mock_mt5_reader(_candles_with_breakout("long"), 1.1020, 1.1019)
    settings = _settings_scalping(scalping_max_open_trades=1, enable_mt5_demo_trading=False)
    engine = ScalpingEngine(settings, repo, notifier, reader)

    # Pre-seed: 1 scalping trade ya abierto
    from app.utils.time_utils import utc_now_iso
    repo.create_paper_trade({
        "alert_id": 0, "token_id": 0, "category": "forex", "chain": "forex",
        "token_address": "OTHER", "symbol": "OTHER",
        "thesis": "preseed", "readiness_grade": "A",
        "entry_price": 1.0, "latest_price": 1.0,
        "stop_loss": 0.99, "take_profit_1": 1.01, "take_profit_2": 1.02,
        "invalidation": "x", "status": "open", "unrealized_return_pct": 0,
        "opened_at": utc_now_iso(), "updated_at": utc_now_iso(), "closed_at": None,
        "strategy_name": "scalping_breakout", "direction": "long",
        "time_horizon_hours": 1, "size_notional": 100, "size_units": 100, "risk_pct": 1.0,
        "partial_closed": 0, "is_scalping": 1,
    })

    result = engine._run_one_cycle()
    assert result.cap_blocks >= 1
    assert result.trades_opened == 0


def test_force_exit_closes_old_paper_trades() -> None:
    """Trade abierto hace > scalping_force_exit_minutes → cerrado en cycle."""
    repo = _repo()
    notifier = MagicMock()
    reader = _mock_mt5_reader(_candles_with_breakout("long"), 1.1020, 1.1019)
    settings = _settings_scalping(scalping_force_exit_minutes=5, enable_mt5_demo_trading=False)
    engine = ScalpingEngine(settings, repo, notifier, reader)

    # Pre-seed: 1 scalping trade abierto hace 10 minutos
    from app.utils.time_utils import utc_now_iso
    old_time = (utc_now() - timedelta(minutes=10)).isoformat()
    repo.create_paper_trade({
        "alert_id": 0, "token_id": 0, "category": "forex", "chain": "forex",
        "token_address": "STALE", "symbol": "STALE",
        "thesis": "old", "readiness_grade": "A",
        "entry_price": 1.0, "latest_price": 1.0,
        "stop_loss": 0.99, "take_profit_1": 1.01, "take_profit_2": 1.02,
        "invalidation": "x", "status": "open", "unrealized_return_pct": 0,
        "opened_at": old_time, "updated_at": old_time, "closed_at": None,
        "strategy_name": "scalping_breakout", "direction": "long",
        "time_horizon_hours": 1, "size_notional": 100, "size_units": 100, "risk_pct": 1.0,
        "partial_closed": 0, "is_scalping": 1,
    })

    result = engine._run_one_cycle()
    assert result.trades_force_exited == 1
