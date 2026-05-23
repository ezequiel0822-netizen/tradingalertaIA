import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_mt5_demo_trader import _demo_settings, _fake_mt5


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"demo_telegram_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_paper_trade(repo: Repository) -> None:
    assert repo.create_paper_trade(
        {
            "alert_id": 101,
            "token_id": 201,
            "category": "forex",
            "chain": "forex",
            "token_address": "EURUSD=X",
            "symbol": "EURUSD=X",
            "thesis": "breakout: london range",
            "readiness_grade": "A",
            "entry_price": 1.10002,
            "latest_price": 1.10002,
            "stop_loss": 1.09902,
            "take_profit_1": 1.10202,
            "take_profit_2": 1.10402,
            "invalidation": "range failed",
            "status": "open",
            "unrealized_return_pct": 0,
            "opened_at": "2026-05-20T00:00:00+00:00",
            "updated_at": "2026-05-20T00:00:00+00:00",
            "closed_at": None,
            "strategy_name": "breakout",
            "direction": "long",
            "time_horizon_hours": 8,
            "size_notional": 1000,
            "size_units": 1000,
            "risk_pct": 0.1,
        }
    )


def test_demo_candidates_lists_forex_paper_trade(monkeypatch) -> None:
    repo = _repo()
    _seed_paper_trade(repo)
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/demo_candidates")
    assert "Candidatos demo MT5" in msg
    assert "ID 1" in msg
    assert "EURUSD" in msg


def test_demo_candidates_hides_stale_take_profit(monkeypatch) -> None:
    repo = _repo()
    _seed_paper_trade(repo)
    monkeypatch.setitem(
        sys.modules,
        "MetaTrader5",
        _fake_mt5(tick=SimpleNamespace(bid=1.10300, ask=1.10302, last=1.10301, time=1)),
    )
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    msg = assistant.handle("/demo_candidates")
    assert "No hay candidatos demo vigentes ahora" in msg
    assert "setup vencido" in msg


def test_demo_halt_blocks_prepare() -> None:
    repo = _repo()
    _seed_paper_trade(repo)
    assistant = BasicTelegramAssistant(_demo_settings(), repo)
    assert "Demo trading detenido" in assistant.handle("/demo_halt")
    msg = assistant.handle("/demo_prepare 1")
    assert "detenido" in msg


def test_prepare_and_confirm_demo_trade(monkeypatch) -> None:
    repo = _repo()
    _seed_paper_trade(repo)
    monkeypatch.setitem(__import__("sys").modules, "MetaTrader5", _fake_mt5())
    assistant = BasicTelegramAssistant(_demo_settings(), repo)

    prepared = assistant.handle("/demo_prepare 1")
    assert "Orden demo preparada #1" in prepared
    assert "/confirm_demo_trade 1" in prepared

    sent = assistant.handle("/confirm_demo_trade 1")
    assert "Orden demo enviada #1" in sent
    assert "Retcode: 10009" in sent

    orders = repo.fetch_demo_orders()
    assert len(orders) == 1
    assert orders[0]["status"] == "sent"


def test_demo_close_all_command_closes_mt5_positions(monkeypatch) -> None:
    repo = _repo()
    fake = _fake_mt5(
        positions=[
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
            )
        ]
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    assistant = BasicTelegramAssistant(_demo_settings(), repo)

    msg = assistant.handle("/demo_close_all")

    assert "Cierre demo MT5: 1/1 posiciones cerradas" in msg
    sent = fake.order_send.call_args.args[0]
    assert sent["position"] == 1001
    assert sent["type"] == fake.ORDER_TYPE_SELL
