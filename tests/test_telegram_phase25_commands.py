from pathlib import Path
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"phase25cmd_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_open(repo: Repository, symbol: str, category: str = "stock") -> None:
    snap = TokenSnapshot(
        chain=category, token_address=symbol, category=category, symbol=symbol,
        price=100.0, liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10, estimated_loss_pct=5, confidence=70,
        label="paper", reasons=[], eligible_for_gain_alert=True,
    )
    token_id = repo.upsert_token(snap, 80, "orange", estimate)
    now = utc_now_iso()
    trade = {
        "alert_id": int(uuid4().int % 10_000_000),
        "token_id": token_id, "category": category, "chain": category,
        "token_address": symbol, "symbol": symbol, "thesis": "test",
        "readiness_grade": "B", "entry_price": 100.0, "latest_price": 102.0,
        "stop_loss": 95.0, "take_profit_1": 105.0, "take_profit_2": 110.0,
        "invalidation": None, "status": "open",
        "unrealized_return_pct": 2.0, "opened_at": now, "updated_at": now,
        "closed_at": None, "mfe_pct": 3.0, "mae_pct": -0.5,
        "original_stop_loss": 95.0, "trailing_active": 0,
        "strategy_name": "breakout", "direction": "long",
        "time_horizon_hours": 24, "size_notional": 2000.0, "size_units": 20.0,
        "risk_pct": 1.0, "partial_closed": 0,
    }
    assert repo.create_paper_trade(trade) is True


def test_portfolio_command_returns_summary() -> None:
    repo = _repo()
    _seed_open(repo, "NVDA", "stock")
    assistant = BasicTelegramAssistant(_settings(), repo)
    msg = assistant.handle("/portfolio")
    assert "Portfolio" in msg
    assert "Balance" in msg
    assert "stock" in msg


def test_positions_command_lists_open_trades() -> None:
    repo = _repo()
    _seed_open(repo, "NVDA", "stock")
    assistant = BasicTelegramAssistant(_settings(), repo)
    msg = assistant.handle("/posiciones")
    assert "NVDA" in msg
    assert "breakout" in msg
    assert "MFE" in msg


def test_halt_command_triggers_kill_switch() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)
    msg = assistant.handle("/halt 6")
    assert "6h" in msg or "6 h" in msg or "Kill" in msg
    assert repo.get_state("kill_switch_active_until")


def test_resume_trading_releases_kill_switch() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)
    assistant.handle("/halt 1")
    msg = assistant.handle("/resume_trading")
    assert "liberado" in msg.lower()
    # bot_state value will be empty string (since release sets it to "")
    val = repo.get_state("kill_switch_active_until")
    assert not val


def test_strategies_command_lists_enabled() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)
    msg = assistant.handle("/strategies")
    assert "breakout" in msg
    assert "mean_reversion" in msg
    assert "momentum" in msg
    assert "news_catalyst" in msg
