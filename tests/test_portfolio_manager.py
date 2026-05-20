from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.portfolio.portfolio_manager import PortfolioManager
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"portfolio_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_open_trade(
    repo: Repository,
    symbol: str,
    category: str,
    entry: float,
    stop: float,
    size_notional: float,
    unrealized_return_pct: float = 0.0,
    direction: str = "long",
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
        "unrealized_return_pct": unrealized_return_pct,
        "opened_at": now, "updated_at": now, "closed_at": None,
        "mfe_pct": 0, "mae_pct": 0, "original_stop_loss": stop, "trailing_active": 0,
        "strategy_name": "breakout", "direction": direction,
        "size_notional": size_notional, "size_units": size_notional / entry,
        "risk_pct": 1.0, "partial_closed": 0,
    }
    assert repo.create_paper_trade(trade) is True


def test_get_open_positions_returns_only_open() -> None:
    settings = _settings()
    repo = _repo()
    _seed_open_trade(repo, "NVDA", "stock", 100.0, 95.0, 2000.0)
    pm = PortfolioManager(settings, repo)
    positions = pm.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "NVDA"


def test_count_open_by_category_buckets() -> None:
    settings = _settings()
    repo = _repo()
    _seed_open_trade(repo, "NVDA", "stock", 100.0, 95.0, 2000.0)
    _seed_open_trade(repo, "TSLA", "stock", 200.0, 190.0, 4000.0)
    _seed_open_trade(repo, "EURUSD=X", "forex", 1.10, 1.09, 5000.0)
    pm = PortfolioManager(settings, repo)
    counts = pm.count_open_by_category()
    assert counts.get("stock") == 2
    assert counts.get("forex") == 1


def test_total_exposure_by_category_sums_notional() -> None:
    settings = _settings()
    repo = _repo()
    _seed_open_trade(repo, "NVDA", "stock", 100.0, 95.0, 2000.0)
    _seed_open_trade(repo, "TSLA", "stock", 200.0, 190.0, 4000.0)
    pm = PortfolioManager(settings, repo)
    exp = pm.total_exposure_by_category()
    assert abs(exp["stock"] - 6000.0) < 0.001


def test_total_risk_pct_uses_balance() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 10000.0})
    repo = _repo()
    # entry=100, stop=95, size_notional=2000 → per_unit=5, risk_amount = 5/100 * 2000 = 100
    # con balance 10000 → risk_pct = 1.0
    _seed_open_trade(repo, "NVDA", "stock", 100.0, 95.0, 2000.0)
    pm = PortfolioManager(settings, repo)
    risk = pm.total_risk_pct()
    assert abs(risk - 1.0) < 0.01


def test_account_balance_falls_back_to_starting() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 25000.0})
    repo = _repo()
    pm = PortfolioManager(settings, repo)
    assert pm.account_balance() == 25000.0
