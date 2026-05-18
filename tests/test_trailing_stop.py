from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.learning.training_engine import _update_paper_trades
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"trailing_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_stock_trade(repo: Repository, entry: float, stop: float, tp2: float) -> int:
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        price=entry,
        liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10,
        estimated_loss_pct=5,
        confidence=70,
        label="paper",
        reasons=[],
        eligible_for_gain_alert=True,
    )
    token_id = repo.upsert_token(snapshot, 80, "orange", estimate)
    now = utc_now_iso()
    trade = {
        "alert_id": int(uuid4().int % 10_000_000),
        "token_id": token_id,
        "category": "stock",
        "chain": "stock",
        "token_address": "NVDA",
        "symbol": "NVDA",
        "thesis": "test",
        "readiness_grade": "B",
        "entry_price": entry,
        "latest_price": entry,
        "stop_loss": stop,
        "take_profit_1": entry + (tp2 - entry) / 2,
        "take_profit_2": tp2,
        "invalidation": None,
        "status": "open",
        "unrealized_return_pct": 0,
        "opened_at": now,
        "updated_at": now,
        "closed_at": None,
        "mfe_pct": 0,
        "mae_pct": 0,
        "original_stop_loss": stop,
        "trailing_active": 0,
    }
    assert repo.create_paper_trade(trade) is True
    return int(repo.fetch_paper_trades(limit=1)[0]["id"])


def _set_price(repo: Repository, price: float) -> None:
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        price=price,
        liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10,
        estimated_loss_pct=5,
        confidence=70,
        label="paper",
        reasons=[],
        eligible_for_gain_alert=True,
    )
    repo.upsert_token(snapshot, 80, "orange", estimate)


def test_trailing_not_activated_below_threshold() -> None:
    repo = _repo()
    settings = _settings()  # trailing on, stock activation=5%
    _seed_stock_trade(repo, entry=100.0, stop=95.0, tp2=130.0)

    _set_price(repo, 103.0)  # +3% < 5%
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]

    assert row["trailing_active"] == 0
    assert row["stop_loss"] == 95.0


def test_trailing_activates_and_raises_stop() -> None:
    repo = _repo()
    settings = _settings()  # stock activation=5%, distance=3%
    _seed_stock_trade(repo, entry=100.0, stop=95.0, tp2=130.0)

    _set_price(repo, 110.0)  # +10% >= 5%, should activate
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]

    assert row["trailing_active"] == 1
    # stop should be lifted to 110 * (1 - 3/100) = 106.7
    assert row["stop_loss"] > 95.0
    assert abs(row["stop_loss"] - 106.7) < 0.01
    assert row["original_stop_loss"] == 95.0  # unchanged historical record


def test_trailing_never_lowers_stop() -> None:
    repo = _repo()
    settings = _settings()
    _seed_stock_trade(repo, entry=100.0, stop=95.0, tp2=200.0)

    _set_price(repo, 120.0)  # activate, raise stop to ~116.4
    _update_paper_trades(repo, settings)
    high_stop = repo.fetch_paper_trades(limit=1)[0]["stop_loss"]

    _set_price(repo, 115.0)  # price drops but still above stop
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]

    # stop should not have been lowered
    assert row["stop_loss"] == high_stop


def test_trailing_disabled_via_setting() -> None:
    repo = _repo()
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_trailing_stop": False})
    _seed_stock_trade(repo, entry=100.0, stop=95.0, tp2=130.0)

    _set_price(repo, 120.0)  # would normally activate
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]

    assert row["trailing_active"] == 0
    assert row["stop_loss"] == 95.0
