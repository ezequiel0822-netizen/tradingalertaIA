from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.portfolio.portfolio_manager import PortfolioManager
from app.risk.risk_manager import RiskManager
from app.utils.time_utils import utc_now, utc_now_iso
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"risk_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_open(
    repo: Repository, symbol: str, category: str,
    entry: float, stop: float, size_notional: float, return_pct: float = 0.0,
) -> None:
    snapshot = TokenSnapshot(
        chain=category, token_address=symbol, category=category, symbol=symbol,
        price=entry, liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10, estimated_loss_pct=5, confidence=70,
        label="paper", reasons=[], eligible_for_gain_alert=True,
    )
    token_id = repo.upsert_token(snapshot, 80, "orange", estimate)
    now = utc_now_iso()
    trade = {
        "alert_id": int(uuid4().int % 10_000_000),
        "token_id": token_id, "category": category, "chain": category,
        "token_address": symbol, "symbol": symbol, "thesis": "test",
        "readiness_grade": "B", "entry_price": entry, "latest_price": entry,
        "stop_loss": stop, "take_profit_1": entry * 1.05, "take_profit_2": entry * 1.10,
        "invalidation": None, "status": "open",
        "unrealized_return_pct": return_pct,
        "opened_at": now, "updated_at": now, "closed_at": None,
        "mfe_pct": 0, "mae_pct": 0, "original_stop_loss": stop, "trailing_active": 0,
        "strategy_name": "breakout", "direction": "long",
        "size_notional": size_notional, "size_units": size_notional / entry,
        "risk_pct": 1.0, "partial_closed": 0,
    }
    assert repo.create_paper_trade(trade) is True


def _mk(settings_overrides: dict | None = None) -> tuple[RiskManager, Repository, PortfolioManager]:
    base = _settings()
    overrides = settings_overrides or {}
    settings = type(base)(**{**base.__dict__, **overrides})
    repo = _repo()
    pm = PortfolioManager(settings, repo)
    rm = RiskManager(settings, repo, pm)
    return rm, repo, pm


def test_kill_switch_inactive_by_default() -> None:
    rm, _, _ = _mk()
    active, _ = rm.is_kill_switch_active()
    assert active is False


def test_blocks_when_kill_switch_active() -> None:
    rm, _, _ = _mk()
    rm.trigger_kill_switch("test", hours=1)
    ok, reason = rm.check_can_open_trade("stock", 1.0)
    assert ok is False
    assert "kill switch" in reason


def test_blocks_when_max_open_total() -> None:
    rm, repo, _ = _mk({"max_open_trades_total": 2})
    _seed_open(repo, "A", "stock", 100, 95, 2000)
    _seed_open(repo, "B", "stock", 100, 95, 2000)
    ok, reason = rm.check_can_open_trade("stock", 1.0)
    assert ok is False
    assert "max_open_trades_total" in reason


def test_blocks_when_max_open_in_category() -> None:
    rm, repo, _ = _mk({"max_open_trades_stock": 1, "max_open_trades_total": 10})
    _seed_open(repo, "A", "stock", 100, 95, 2000)
    ok, reason = rm.check_can_open_trade("stock", 1.0)
    assert ok is False
    assert "max_open_trades_stock" in reason


def test_blocks_when_total_risk_exceeded() -> None:
    rm, repo, _ = _mk({"max_total_risk_pct": 1.0, "account_starting_balance": 10000.0})
    # 2 positions × (5/100 * 2000) = 200 USD risk = 2% of 10000. proposed 0.5 → 2.5 > 1 → block
    _seed_open(repo, "A", "stock", 100, 95, 2000)
    _seed_open(repo, "B", "stock", 100, 95, 2000)
    ok, reason = rm.check_can_open_trade("stock", 0.5)
    assert ok is False
    assert "max_total_risk_pct" in reason


def test_release_kill_switch_clears_state() -> None:
    rm, _, _ = _mk()
    rm.trigger_kill_switch("test", hours=1)
    assert rm.is_kill_switch_active()[0] is True
    rm.release_kill_switch()
    assert rm.is_kill_switch_active()[0] is False


def test_force_close_all_open_marks_trades() -> None:
    rm, repo, _ = _mk()
    _seed_open(repo, "A", "stock", 100, 95, 2000)
    _seed_open(repo, "B", "forex", 1.10, 1.09, 5000)
    n = rm.force_close_all_open("test panic")
    assert n == 2
    open_after = repo.fetch_paper_trades(status="open", limit=10)
    assert len(open_after) == 0
