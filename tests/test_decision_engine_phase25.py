"""Smoke tests for Fase 2.5 Decision Engine integration in jobs.py.

No mockean Telegram ni HTTP a Yahoo. Solo verifican que el wiring entre
PortfolioManager / RiskManager / StrategyRouter / MT5Reader funciona y
que un ciclo de manage_open_positions sobre DB en blanco no rompe.
"""

from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.learning.lifecycle_manager import manage_open_positions
from app.portfolio.portfolio_manager import PortfolioManager
from app.risk.risk_manager import RiskManager
from app.strategies.strategy_router import StrategyRouter
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"decision_phase25_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_manage_open_positions_handles_empty_db() -> None:
    settings = _settings()
    repo = _repo()
    summary = manage_open_positions(settings, repo, mt5_reader=None)
    assert summary["managed"] == 0
    assert summary["time_closed"] == 0


def test_trader_engine_wires_up_without_errors() -> None:
    """Instancia los 4 modulos juntos como lo hace TradingAlertJob.__init__."""
    settings = _settings()
    repo = _repo()
    pm = PortfolioManager(settings, repo, mt5_reader=None)
    rm = RiskManager(settings, repo, pm)
    router = StrategyRouter(settings)
    # smoke: si todo se inicializa, los limites por categoria responden
    assert pm.account_balance() == settings.account_starting_balance
    assert rm.is_kill_switch_active() == (False, None)
    # Phase 3 v2.2.0: ahora son 5 (suma forex_session_breakout)
    assert len(router.strategies) == 5

    # Smoke: con repo vacio, check_can_open_trade pasa
    ok, _ = rm.check_can_open_trade("stock", 1.0)
    assert ok is True
