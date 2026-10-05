from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.learning.lifecycle_manager import manage_open_positions
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"lifecycle_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed(
    repo: Repository, symbol: str, entry: float, stop: float, tp1: float, tp2: float,
    *,
    opened_hours_ago: float = 0.0, direction: str = "long",
    time_horizon_hours: int = 24, size_notional: float = 2000.0,
    partial_closed: int = 0,
) -> int:
    snap = TokenSnapshot(
        chain="stock", token_address=symbol, category="stock", symbol=symbol,
        price=entry, liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10, estimated_loss_pct=5, confidence=70,
        label="paper", reasons=[], eligible_for_gain_alert=True,
    )
    token_id = repo.upsert_token(snap, 80, "orange", estimate)
    opened = datetime.now(timezone.utc) - timedelta(hours=opened_hours_ago)
    trade = {
        "alert_id": int(uuid4().int % 10_000_000),
        "token_id": token_id, "category": "stock", "chain": "stock",
        "token_address": symbol, "symbol": symbol, "thesis": "test",
        "readiness_grade": "B", "entry_price": entry, "latest_price": entry,
        "stop_loss": stop, "take_profit_1": tp1, "take_profit_2": tp2,
        "invalidation": None, "status": "open", "unrealized_return_pct": 0,
        "opened_at": opened.isoformat(), "updated_at": opened.isoformat(),
        "closed_at": None, "mfe_pct": 0, "mae_pct": 0,
        "original_stop_loss": stop, "trailing_active": 0,
        "strategy_name": "breakout", "direction": direction,
        "time_horizon_hours": time_horizon_hours,
        "size_notional": size_notional, "size_units": size_notional / entry,
        "risk_pct": 1.0, "partial_closed": partial_closed,
    }
    assert repo.create_paper_trade(trade) is True
    return int(repo.fetch_paper_trades(limit=1)[0]["id"])


def _set_token_price(repo: Repository, symbol: str, price: float) -> None:
    snap = TokenSnapshot(
        chain="stock", token_address=symbol, category="stock", symbol=symbol,
        price=price, liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10, estimated_loss_pct=5, confidence=70,
        label="paper", reasons=[], eligible_for_gain_alert=True,
    )
    repo.upsert_token(snap, 80, "orange", estimate)


def test_time_exit_closes_trade_past_horizon() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_trailing_stop": False})
    repo = _repo()
    _seed(repo, "NVDA", 100.0, 95.0, 105.0, 110.0, opened_hours_ago=25, time_horizon_hours=24)
    _set_token_price(repo, "NVDA", 101.0)
    summary = manage_open_positions(settings, repo)
    assert summary["time_closed"] == 1
    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["status"] == "closed_by_time"


def test_partial_close_at_tp1_halves_size_and_moves_stop_to_breakeven() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_trailing_stop": False})
    repo = _repo()
    _seed(repo, "NVDA", 100.0, 95.0, 105.0, 115.0, opened_hours_ago=2, time_horizon_hours=24,
          size_notional=2000.0)
    _set_token_price(repo, "NVDA", 106.0)  # hits TP1=105
    manage_open_positions(settings, repo)
    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["partial_closed"] == 1
    assert abs(row["size_notional"] - 1000.0) < 0.01
    assert abs(row["stop_loss"] - 100.0) < 0.01  # breakeven


def test_partial_close_idempotent() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_trailing_stop": False})
    repo = _repo()
    _seed(repo, "NVDA", 100.0, 95.0, 105.0, 115.0, opened_hours_ago=2, time_horizon_hours=24,
          size_notional=2000.0, partial_closed=1)
    _set_token_price(repo, "NVDA", 106.0)
    summary = manage_open_positions(settings, repo)
    assert summary["partial_closed"] == 0  # not double-counted


def test_stop_hit_closes_trade_stopped() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_trailing_stop": False})
    repo = _repo()
    _seed(repo, "NVDA", 100.0, 95.0, 105.0, 110.0, opened_hours_ago=2, time_horizon_hours=24)
    _set_token_price(repo, "NVDA", 94.0)
    summary = manage_open_positions(settings, repo)
    assert summary["stopped"] == 1
    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["status"] == "stopped_simulated"


class _FakeTickReader:
    def __init__(self, bid: float) -> None:
        self._bid = bid
        self.seen_symbol: str | None = None

    def is_connected(self) -> bool:
        return True

    def get_tick(self, symbol: str):
        self.seen_symbol = symbol
        return {"bid": self._bid, "ask": self._bid}


def test_fresh_price_maps_yahoo_forex_symbol_to_mt5() -> None:
    """Regresion v2.7.0: _fresh_price pasaba el símbolo Yahoo crudo ('USDCHF=X')
    a get_tick, que siempre fallaba para forex/gold → caía a precio stale. Ahora
    debe mapear a 'USDCHF' antes de pedir el tick."""
    from app.learning.lifecycle_manager import _fresh_price

    reader = _FakeTickReader(bid=0.9123)
    repo = _repo()
    trade = {"chain": "forex", "token_address": "USDCHF=X", "symbol": "USDCHF=X"}
    price = _fresh_price(trade, repo, reader, "icmarkets")
    assert reader.seen_symbol == "USDCHF"
    assert price == 0.9123


def test_fresh_price_maps_yahoo_gold_symbol_to_mt5() -> None:
    from app.learning.lifecycle_manager import _fresh_price

    reader = _FakeTickReader(bid=4520.5)
    repo = _repo()
    trade = {"chain": "gold", "token_address": "GC=F", "symbol": "GC=F"}
    price = _fresh_price(trade, repo, reader, "icmarkets")
    assert reader.seen_symbol == "XAUUSD"
    assert price == 4520.5


# --------------------------------------------------------------------------- #
# v3.10.1 — trailing en SHORTS + mark-to-market por lado (bid/ask)
# --------------------------------------------------------------------------- #
class _TickReader:
    """Stub de MT5Reader: siempre conectado, tick fijo bid/ask."""

    def __init__(self, bid: float, ask: float) -> None:
        self._bid, self._ask = bid, ask

    def is_connected(self) -> bool:
        return True

    def get_tick(self, symbol: str) -> dict:
        return {"bid": self._bid, "ask": self._ask, "last": None, "time": 0}


def _trailing_settings(base):
    return type(base)(**{
        **base.__dict__,
        "enable_trailing_stop": True,
        "trailing_activation_pct_stock": 5.0,
        "trailing_distance_pct_stock": 2.0,
        "enable_partial_close_at_tp1": False,
    })


def test_short_trailing_moves_stop_down() -> None:
    """v3.10.1: el trailing era long-only — en un short ganador el stop ahora
    BAJA con el precio (latest * (1 + distance))."""
    settings = _trailing_settings(_settings())
    repo = _repo()
    _seed(repo, "NVDA", 100.0, 108.0, 80.0, 70.0, opened_hours_ago=2,
          direction="short")
    _set_token_price(repo, "NVDA", 90.0)  # +10% a favor del short (>= activacion 5%)

    manage_open_positions(settings, repo)

    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["trailing_active"] == 1
    assert abs(row["stop_loss"] - 91.8) < 1e-6  # 90 * 1.02


def test_short_trailing_never_loosens() -> None:
    """El stop de un short trailea hacia abajo y JAMAS vuelve a subir."""
    settings = _trailing_settings(_settings())
    repo = _repo()
    _seed(repo, "NVDA", 100.0, 108.0, 80.0, 70.0, opened_hours_ago=2,
          direction="short")
    _set_token_price(repo, "NVDA", 90.0)
    manage_open_positions(settings, repo)  # stop -> 91.8

    _set_token_price(repo, "NVDA", 91.0)  # rebota: 91*1.02=92.82 seria AFLOJAR
    manage_open_positions(settings, repo)

    row = repo.fetch_paper_trades(limit=1)[0]
    assert abs(row["stop_loss"] - 91.8) < 1e-6  # no se movio


def test_fresh_price_marks_short_at_ask_and_long_at_bid() -> None:
    """v3.10.1: un short se cierra COMPRANDO al ask; un long vendiendo al bid."""
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_trailing_stop": False,
                             "enable_partial_close_at_tp1": False})
    reader = _TickReader(bid=99.0, ask=101.0)

    repo_short = _repo()
    _seed(repo_short, "NVDA", 100.0, 110.0, 80.0, 70.0, opened_hours_ago=2,
          direction="short")
    manage_open_positions(settings, repo_short, mt5_reader=reader)
    row = repo_short.fetch_paper_trades(limit=1)[0]
    assert abs(row["latest_price"] - 101.0) < 1e-6  # ask
    assert abs(row["unrealized_return_pct"] - (-1.0)) < 1e-6

    repo_long = _repo()
    _seed(repo_long, "NVDA", 100.0, 95.0, 120.0, 130.0, opened_hours_ago=2,
          direction="long")
    manage_open_positions(settings, repo_long, mt5_reader=reader)
    row = repo_long.fetch_paper_trades(limit=1)[0]
    assert abs(row["latest_price"] - 99.0) < 1e-6  # bid
    assert abs(row["unrealized_return_pct"] - (-1.0)) < 1e-6


def test_partial_close_never_loosens_a_trailing_stop() -> None:
    """Bug 2026-10-05: con el trailing ya activo (stop sobre la entrada), tocar TP1
    movía el stop de vuelta a breakeven -> lo AFLOJABA. Breakeven solo si ajusta."""
    repo = _repo()
    settings = _settings()                                   # trailing stock: +5 % / 3 %
    _seed(repo, "AMD", 100.0, 95.0, 108.0, 120.0)
    _set_token_price(repo, "AMD", 106.0)                     # activa trailing: stop 102.82
    manage_open_positions(settings, repo)
    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["trailing_active"] == 1 and row["stop_loss"] > 102.0
    _set_token_price(repo, "AMD", 108.5)                     # toca TP1 -> parcial
    manage_open_positions(settings, repo)
    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["partial_closed"] == 1
    assert row["stop_loss"] > 100.0                          # NO vuelve a breakeven
    assert abs(row["stop_loss"] - 108.5 * 0.97) < 1e-6       # el trailing manda


def test_partial_close_never_loosens_short_trailing_stop() -> None:
    repo = _repo()
    settings = _settings()
    _seed(repo, "AMD", 100.0, 105.0, 92.0, 80.0, direction="short")
    _set_token_price(repo, "AMD", 94.0)                      # +6 % short: stop 96.82
    manage_open_positions(settings, repo)
    _set_token_price(repo, "AMD", 91.5)                      # toca TP1 short
    manage_open_positions(settings, repo)
    row = repo.fetch_paper_trades(limit=1)[0]
    assert row["partial_closed"] == 1 and row["stop_loss"] < 100.0
