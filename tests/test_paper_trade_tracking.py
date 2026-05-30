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
    db_path = db_dir / f"paper_track_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_trade(
    repo: Repository,
    entry_price: float,
    stop_loss: float,
    take_profit_2: float,
    category: str = "stock",
) -> int:
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category=category,
        symbol="NVDA",
        name="NVIDIA",
        price=entry_price,
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
        "category": category,
        "chain": "stock",
        "token_address": "NVDA",
        "symbol": "NVDA",
        "thesis": "test",
        "readiness_grade": "B",
        "entry_price": entry_price,
        "latest_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit_1": take_profit_2 * 0.5 + entry_price * 0.5,
        "take_profit_2": take_profit_2,
        "invalidation": None,
        "status": "open",
        "unrealized_return_pct": 0,
        "opened_at": now,
        "updated_at": now,
        "closed_at": None,
        "mfe_pct": 0,
        "mae_pct": 0,
        "original_stop_loss": stop_loss,
        "trailing_active": 0,
    }
    assert repo.create_paper_trade(trade) is True
    row = repo.fetch_paper_trades(status="open", limit=1)[0]
    return int(row["id"])


def _set_latest_price(repo: Repository, price: float) -> None:
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        name="NVIDIA",
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


def _disable_trailing(settings):
    return type(settings)(**{**settings.__dict__, "enable_trailing_stop": False})


def test_paper_trade_tracks_mfe_when_price_rises() -> None:
    repo = _repo()
    settings = _disable_trailing(_settings())
    trade_id = _seed_trade(repo, entry_price=100.0, stop_loss=95.0, take_profit_2=120.0)

    _set_latest_price(repo, 103.0)
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["mfe_pct"] == 3.0
    assert row["mae_pct"] == 0.0

    _set_latest_price(repo, 107.0)
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["mfe_pct"] == 7.0
    assert row["mae_pct"] == 0.0


def test_paper_trade_tracks_mae_when_price_drops() -> None:
    repo = _repo()
    settings = _disable_trailing(_settings())
    trade_id = _seed_trade(repo, entry_price=100.0, stop_loss=85.0, take_profit_2=120.0)

    _set_latest_price(repo, 97.0)
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["mfe_pct"] == 0.0
    assert row["mae_pct"] == -3.0

    _set_latest_price(repo, 93.0)
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["mae_pct"] == -7.0


def test_paper_trade_preserves_mfe_after_rebound() -> None:
    repo = _repo()
    settings = _disable_trailing(_settings())
    _seed_trade(repo, entry_price=100.0, stop_loss=85.0, take_profit_2=200.0)

    _set_latest_price(repo, 110.0)
    _update_paper_trades(repo, settings)
    _set_latest_price(repo, 95.0)
    _update_paper_trades(repo, settings)
    _set_latest_price(repo, 102.0)
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]

    assert row["mfe_pct"] == 10.0
    assert row["mae_pct"] == -5.0
    assert row["status"] == "open"


def _seed_short_trade(
    repo: Repository,
    entry_price: float,
    stop_loss: float,
    take_profit_2: float,
    symbol: str = "USDCHF",
) -> int:
    """Short trade: stop POR ENCIMA del entry, target POR DEBAJO."""
    snapshot = TokenSnapshot(
        chain="forex",
        token_address=symbol,
        category="forex",
        symbol=symbol,
        name=symbol,
        price=entry_price,
        liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=2,
        estimated_loss_pct=1,
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
        "category": "forex",
        "chain": "forex",
        "token_address": symbol,
        "symbol": symbol,
        "thesis": "test short",
        "readiness_grade": "B",
        "entry_price": entry_price,
        "latest_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit_1": entry_price - (entry_price - take_profit_2) / 2,
        "take_profit_2": take_profit_2,
        "invalidation": None,
        "status": "open",
        "unrealized_return_pct": 0,
        "opened_at": now,
        "updated_at": now,
        "closed_at": None,
        "mfe_pct": 0,
        "mae_pct": 0,
        "original_stop_loss": stop_loss,
        "trailing_active": 0,
        "direction": "short",
    }
    assert repo.create_paper_trade(trade) is True
    return int(repo.fetch_paper_trades(status="open", limit=1)[0]["id"])


def _set_forex_price(repo: Repository, price: float, symbol: str = "USDCHF") -> None:
    snapshot = TokenSnapshot(
        chain="forex",
        token_address=symbol,
        category="forex",
        symbol=symbol,
        name=symbol,
        price=price,
        liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=2,
        estimated_loss_pct=1,
        confidence=70,
        label="paper",
        reasons=[],
        eligible_for_gain_alert=True,
    )
    repo.upsert_token(snapshot, 80, "orange", estimate)


def test_short_trade_not_insta_killed_when_price_flat() -> None:
    """Regresion v2.7.0: el bug que envenenó ~85% del historial.

    Un short recién creado tiene latest==entry y stop POR ENCIMA. La lógica
    long-only `latest <= stop` lo marcaba stopped_simulated al instante. Ahora
    debe quedar OPEN porque el precio no tocó el stop (que está arriba).
    """
    repo = _repo()
    settings = _disable_trailing(_settings())
    _seed_short_trade(repo, entry_price=0.9000, stop_loss=0.9050, take_profit_2=0.8900)

    _set_forex_price(repo, 0.9000)  # precio == entry, sin movimiento
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]

    assert row["status"] == "open"
    assert row["mfe_pct"] == 0.0


def test_short_trade_stops_when_price_rises_to_stop() -> None:
    repo = _repo()
    settings = _disable_trailing(_settings())
    _seed_short_trade(repo, entry_price=0.9000, stop_loss=0.9050, take_profit_2=0.8900)

    _set_forex_price(repo, 0.9060)  # sube por encima del stop del short
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]

    assert row["status"] == "stopped_simulated"
    assert row["mae_pct"] < 0  # el short pierde cuando el precio sube


def test_short_trade_targets_when_price_falls() -> None:
    repo = _repo()
    settings = _disable_trailing(_settings())
    _seed_short_trade(repo, entry_price=0.9000, stop_loss=0.9050, take_profit_2=0.8900)

    _set_forex_price(repo, 0.8890)  # cae por debajo del target del short
    _update_paper_trades(repo, settings)
    row = repo.fetch_paper_trades(limit=1)[0]

    assert row["status"] == "target_2_simulated"
    assert row["mfe_pct"] > 0  # el short gana cuando el precio baja
