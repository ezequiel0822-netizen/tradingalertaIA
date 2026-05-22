"""Phase 5.5 v2.5.4 — auto-confirm demo orders.

Tests del wiring entre `_try_prepare_demo_order` y `_auto_execute_demo_request`
en `app/scheduler/jobs.py`. Real-money trading sigue bloqueado por construcción:
estas pruebas usan cuentas demo simuladas (`_fake_mt5`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.brokers.mt5_demo_trader import DemoSendResult
from app.config.settings import load_settings
from app.database.db import init_db
from app.database.repository import Repository
from app.scheduler.jobs import TradingAlertJob
from tests.test_mt5_demo_trader import _demo_settings, _fake_mt5


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"auto_confirm_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _paper_trade_row(alert_id: int = 101) -> dict:
    return {
        "alert_id": alert_id,
        "token_id": 201,
        "category": "forex",
        "chain": "forex",
        "token_address": "EURUSD=X",
        "symbol": "EURUSD=X",
        "thesis": "auto-confirm test",
        "readiness_grade": "A",
        "entry_price": 1.10002,
        "latest_price": 1.10002,
        "stop_loss": 1.09902,
        "take_profit_1": 1.10202,
        "take_profit_2": 1.10402,
        "invalidation": "test",
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


class _StubJob:
    """Stub mínimo: solo provee atributos que usan los métodos bajo prueba.

    Bindea los métodos sin construir un `TradingAlertJob` completo (que arrastra
    collectors, ClaudeProcessor, etc.).
    """

    def __init__(self, settings, repository, notifier, mt5_reader=None) -> None:
        self.settings = settings
        self.repository = repository
        self.notifier = notifier
        self.mt5_reader = mt5_reader

    _try_prepare_demo_order = TradingAlertJob._try_prepare_demo_order
    _auto_execute_demo_request = TradingAlertJob._auto_execute_demo_request


def test_enable_auto_confirm_demo_default_false(monkeypatch) -> None:
    """Sin la variable de entorno, el flag default es False (opt-in safety)."""
    monkeypatch.delenv("ENABLE_AUTO_CONFIRM_DEMO", raising=False)
    settings = load_settings()
    assert settings.enable_auto_confirm_demo is False


def test_manual_path_notifies_when_auto_disabled(monkeypatch) -> None:
    """Con flag=False, después de crear request se manda mensaje pidiendo /confirm_demo_trade."""
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    repo = _repo()
    repo.create_paper_trade(_paper_trade_row())
    paper_trade = repo.fetch_paper_trade_by_alert_id(101)
    assert paper_trade is not None

    notifier = MagicMock()
    settings = _demo_settings(enable_auto_confirm_demo=False)
    job = _StubJob(settings, repo, notifier)

    job._try_prepare_demo_order(paper_trade)

    assert notifier.send_message.called
    sent = notifier.send_message.call_args[0][0]
    assert "Orden demo MT5 lista para confirmar" in sent
    assert "/confirm_demo_trade" in sent

    # NO debe haber demo_orders (no se ejecutó nada todavía)
    orders = repo.fetch_demo_orders()
    assert orders == []

    # SÍ debe existir el demo_trade_request en status pending
    request = repo.fetch_demo_trade_request(1)
    assert request is not None
    assert request["status"] == "pending"


def test_auto_execute_sends_order_when_enabled(monkeypatch) -> None:
    """Con flag=True, se envía order_send inmediato y se registra demo_orders."""
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    repo = _repo()
    repo.create_paper_trade(_paper_trade_row())
    paper_trade = repo.fetch_paper_trade_by_alert_id(101)
    assert paper_trade is not None

    notifier = MagicMock()
    settings = _demo_settings(enable_auto_confirm_demo=True)
    job = _StubJob(settings, repo, notifier)

    job._try_prepare_demo_order(paper_trade)

    assert notifier.send_message.called
    sent = notifier.send_message.call_args[0][0]
    assert "Auto-orden demo enviada" in sent
    assert "Retcode: 10009" in sent

    # demo_orders persistido
    orders = repo.fetch_demo_orders()
    assert len(orders) == 1
    assert orders[0]["status"] == "sent"

    # demo_trade_request actualizado a status='sent'
    request = repo.fetch_demo_trade_request(1)
    assert request is not None
    assert request["status"] == "sent"
    assert request["sent_at"] is not None


def test_auto_execute_records_failure_when_send_fails() -> None:
    """Si `send_prepared_request` devuelve ok=False, notifica FALLIDA y persiste status='failed'."""
    repo = _repo()
    repo.create_paper_trade(_paper_trade_row())

    # Seed un demo_trade_request pendiente directamente
    request_id = repo.create_demo_trade_request(
        {
            "paper_trade_id": 1,
            "symbol": "EURUSD",
            "direction": "long",
            "volume": 0.01,
            "entry_price": 1.10002,
            "stop_loss": 1.09902,
            "take_profit": 1.10202,
            "risk_pct": 0.1,
            "strategy_name": "breakout",
            "status": "pending",
            "reason": "test",
            "request_summary": "test summary",
            "created_at": "2026-05-20T00:00:00+00:00",
            "expires_at": "2026-05-20T01:00:00+00:00",
        }
    )

    notifier = MagicMock()
    settings = _demo_settings(enable_auto_confirm_demo=True)
    job = _StubJob(settings, repo, notifier)

    # Trader stub que falla
    stub_trader = SimpleNamespace(
        send_prepared_request=lambda req, n: DemoSendResult(
            ok=False,
            status="failed",
            reason="symbol EURUSD not allowed",
            retcode=None,
            order_ticket=None,
            deal_ticket=None,
            price=None,
            result_summary="rejected by broker",
        )
    )

    job._auto_execute_demo_request(stub_trader, request_id, open_positions=0)

    assert notifier.send_message.called
    sent = notifier.send_message.call_args[0][0]
    assert "Auto-orden demo FALLIDA" in sent
    assert "symbol EURUSD not allowed" in sent

    # demo_trade_request quedó en status='failed' (no 'sent')
    request = repo.fetch_demo_trade_request(request_id)
    assert request is not None
    assert request["status"] == "failed"

    # Sí hay registro en demo_orders con status='failed' para auditoría
    orders = repo.fetch_demo_orders()
    assert len(orders) == 1
    assert orders[0]["status"] == "failed"
