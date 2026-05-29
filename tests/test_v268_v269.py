"""v2.6.8 + v2.6.9 — MT5 notional accuracy + per-symbol cooldown tests.

v2.6.8 fixes:
- MT5DemoTrader.compute_actual_notional_usd para USD-base y USD-quote symbols.
- MT5DemoTrader.actual_units para size_units consistente.
- Bug origen: paper_trade.size_notional usaba balance teórico 1M, inflando
  realized_pnl_today 100-1000× y disparando kill switches falsos.

v2.6.9 fixes:
- Repository.has_recent_paper_trade_for_symbol query.
- RiskManager.check_can_open_trade respeta strategy_symbol_cooldown_minutes.
- Bug origen: bot abrió 159 USDCHF en 20 min (28-may) sin dedup por símbolo.
"""

from __future__ import annotations

import sys
import types
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.brokers.mt5_demo_trader import MT5DemoTrader
from app.database.db import init_db
from app.database.repository import Repository
from app.portfolio.portfolio_manager import PortfolioManager
from app.risk.risk_manager import RiskManager
from app.utils.time_utils import utc_now, utc_now_iso
from tests.test_score import _settings


# ---------------- Helpers ----------------


def _demo_settings(**overrides):
    base = _settings()
    values = {
        **base.__dict__,
        "enable_mt5_reader": True,
        "enable_mt5_demo_trading": True,
        "demo_order_require_confirmation": True,
        "demo_max_open_trades": 5,
        "demo_risk_per_trade_pct": 1.5,
        "demo_max_lot": 0.1,
        "demo_allowed_symbols": ["eurusd", "usdjpy", "xauusd"],
        "enable_real_trading": False,
        "mt5_login": 123456,
        "mt5_password": "demo-password",
        "mt5_server": "ICMarkets-Demo",
        **overrides,
    }
    return type(base)(**values)


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"v268_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_paper_trade(repo: Repository, *, symbol: str, opened_at: str | None = None) -> int:
    base = {
        "alert_id": 0, "token_id": 0, "category": "forex", "chain": "forex",
        "token_address": symbol, "symbol": symbol,
        "thesis": "test", "readiness_grade": "A",
        "entry_price": 1.1000, "latest_price": 1.1000,
        "stop_loss": 1.0990, "take_profit_1": 1.1020, "take_profit_2": 1.1040,
        "invalidation": "x", "status": "open", "unrealized_return_pct": 0,
        "opened_at": opened_at or utc_now_iso(),
        "updated_at": utc_now_iso(), "closed_at": None,
        "strategy_name": "test", "direction": "long",
        "time_horizon_hours": 48, "size_notional": 100000, "size_units": 100000,
        "risk_pct": 1.0, "partial_closed": 0,
    }
    repo.create_paper_trade(base)
    trades = repo.fetch_paper_trades(limit=20) or []
    return int(trades[0]["id"])


def _fake_mt5_for_symbol(*, symbol_name: str, contract_size: float, currency_base: str = ""):
    """Minimal MT5 module mock returning a specific symbol_info."""
    fake = types.ModuleType("MetaTrader5")
    fake.ACCOUNT_TRADE_MODE_DEMO = 0
    fake.TRADE_ACTION_DEAL = 1
    fake.TRADE_ACTION_SLTP = 6
    fake.ORDER_TYPE_BUY = 0
    fake.ORDER_TYPE_SELL = 1
    fake.ORDER_TIME_GTC = 0
    fake.ORDER_FILLING_FOK = 0
    fake.ORDER_FILLING_IOC = 1
    fake.ORDER_FILLING_RETURN = 2
    fake.TRADE_RETCODE_DONE = 10009
    fake.TRADE_RETCODE_PLACED = 10008
    fake.TRADE_RETCODE_INVALID_FILL = 10030
    fake.initialize = MagicMock(return_value=True)
    fake.shutdown = MagicMock()
    fake.account_info = MagicMock(
        return_value=SimpleNamespace(
            balance=88700.0, equity=88700.0, currency="USD",
            server="ICMarkets-Demo", login=123456, name="Demo",
            company="ICMarkets Demo", trade_mode=0,
            trade_allowed=True, trade_expert=True,
        )
    )
    fake.symbol_info = MagicMock(
        return_value=SimpleNamespace(
            name=symbol_name, visible=True, point=0.00001, digits=5,
            trade_contract_size=contract_size,
            currency_base=currency_base,
            currency_profit="USD",
            volume_min=0.01, volume_step=0.01, volume_max=100.0,
            trade_tick_value=1.0, trade_tick_size=0.00001,
            filling_mode=1,
        )
    )
    fake.symbol_select = MagicMock(return_value=True)
    fake.symbol_info_tick = MagicMock(
        return_value=SimpleNamespace(bid=1.10000, ask=1.10002, last=1.10001, time=1)
    )
    fake.positions_get = MagicMock(return_value=[])
    fake.order_send = MagicMock(
        return_value=SimpleNamespace(
            retcode=10009, order=999, deal=1999, price=1.10000, comment="ok"
        )
    )
    return fake


# ---------------- v2.6.8: compute_actual_notional_usd ----------------


def test_notional_usd_quote_eurusd(monkeypatch) -> None:
    """EURUSD: USD es QUOTE. notional = volume × contract × price."""
    monkeypatch.setitem(
        sys.modules, "MetaTrader5",
        _fake_mt5_for_symbol(symbol_name="EURUSD", contract_size=100_000, currency_base="EUR"),
    )
    trader = MT5DemoTrader(_demo_settings())
    # 0.1 lot × 100,000 × 1.16 = 11,600 USD
    notional = trader.compute_actual_notional_usd("EURUSD", volume=0.1, entry_price=1.16)
    assert notional == 11600.0


def test_notional_usd_base_usdjpy(monkeypatch) -> None:
    """USDJPY: USD es BASE. notional = volume × contract (sin price)."""
    monkeypatch.setitem(
        sys.modules, "MetaTrader5",
        _fake_mt5_for_symbol(symbol_name="USDJPY", contract_size=100_000, currency_base="USD"),
    )
    trader = MT5DemoTrader(_demo_settings())
    # 0.1 lot × 100,000 = 10,000 USD (price 159 no entra)
    notional = trader.compute_actual_notional_usd("USDJPY", volume=0.1, entry_price=159.0)
    assert notional == 10000.0


def test_notional_xauusd_small_contract(monkeypatch) -> None:
    """XAUUSD: USD es QUOTE pero contract_size = 100 (oz). notional = 0.1 × 100 × 4400 = $44,000."""
    monkeypatch.setitem(
        sys.modules, "MetaTrader5",
        _fake_mt5_for_symbol(symbol_name="XAUUSD", contract_size=100, currency_base="XAU"),
    )
    trader = MT5DemoTrader(_demo_settings())
    notional = trader.compute_actual_notional_usd("XAUUSD", volume=0.1, entry_price=4400.0)
    assert notional == 44000.0


def test_notional_none_when_invalid_inputs(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules, "MetaTrader5",
        _fake_mt5_for_symbol(symbol_name="EURUSD", contract_size=100_000, currency_base="EUR"),
    )
    trader = MT5DemoTrader(_demo_settings())
    assert trader.compute_actual_notional_usd("EURUSD", volume=0, entry_price=1.16) is None
    assert trader.compute_actual_notional_usd("EURUSD", volume=0.1, entry_price=0) is None
    assert trader.compute_actual_notional_usd("EURUSD", volume=-0.1, entry_price=1.16) is None


def test_actual_units_returns_volume_x_contract(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules, "MetaTrader5",
        _fake_mt5_for_symbol(symbol_name="EURUSD", contract_size=100_000, currency_base="EUR"),
    )
    trader = MT5DemoTrader(_demo_settings())
    units = trader.actual_units("EURUSD", volume=0.1)
    assert units == 10000.0


# ---------------- v2.6.9: has_recent_paper_trade_for_symbol ----------------


def test_has_recent_returns_false_when_no_trade() -> None:
    repo = _repo()
    cutoff = (utc_now() - timedelta(minutes=15)).isoformat()
    assert repo.has_recent_paper_trade_for_symbol("EURUSD", cutoff) is False


def test_has_recent_returns_true_when_trade_in_window() -> None:
    repo = _repo()
    # Trade abierto ahora — debería matchear cutoff de 15 min atrás
    _seed_paper_trade(repo, symbol="USDCHF")
    cutoff = (utc_now() - timedelta(minutes=15)).isoformat()
    assert repo.has_recent_paper_trade_for_symbol("USDCHF", cutoff) is True


def test_has_recent_returns_false_when_trade_too_old() -> None:
    repo = _repo()
    # Trade abierto hace 30 min — fuera de la ventana de 15 min
    old_iso = (utc_now() - timedelta(minutes=30)).isoformat()
    _seed_paper_trade(repo, symbol="EURUSD", opened_at=old_iso)
    cutoff = (utc_now() - timedelta(minutes=15)).isoformat()
    assert repo.has_recent_paper_trade_for_symbol("EURUSD", cutoff) is False


def test_has_recent_empty_symbol_returns_false() -> None:
    repo = _repo()
    cutoff = (utc_now() - timedelta(minutes=15)).isoformat()
    assert repo.has_recent_paper_trade_for_symbol("", cutoff) is False


# ---------------- v2.6.9: risk_manager cooldown integration ----------------


def test_risk_manager_blocks_when_symbol_cooldown_active() -> None:
    repo = _repo()
    settings = _demo_settings(strategy_symbol_cooldown_minutes=15)
    portfolio = PortfolioManager(settings, repo)
    rm = RiskManager(settings, repo, portfolio)

    # Sembramos un trade USDCHF abierto recién
    _seed_paper_trade(repo, symbol="USDCHF")

    ok, reason = rm.check_can_open_trade(
        category="forex", proposed_risk_pct=0.5, symbol="USDCHF"
    )
    assert ok is False
    assert "symbol_cooldown_active" in reason
    assert "USDCHF" in reason


def test_risk_manager_allows_when_cooldown_disabled() -> None:
    """Si strategy_symbol_cooldown_minutes=0, no aplica el check (backward compat)."""
    repo = _repo()
    settings = _demo_settings(strategy_symbol_cooldown_minutes=0)
    portfolio = PortfolioManager(settings, repo)
    rm = RiskManager(settings, repo, portfolio)

    _seed_paper_trade(repo, symbol="USDCHF")
    ok, reason = rm.check_can_open_trade(
        category="forex", proposed_risk_pct=0.5, symbol="USDCHF"
    )
    assert ok is True
    assert reason == "ok"


def test_risk_manager_allows_when_no_symbol_provided() -> None:
    """check_can_open_trade(symbol=None) salta el cooldown check (backward compat)."""
    repo = _repo()
    settings = _demo_settings(strategy_symbol_cooldown_minutes=15)
    portfolio = PortfolioManager(settings, repo)
    rm = RiskManager(settings, repo, portfolio)

    _seed_paper_trade(repo, symbol="USDCHF")
    ok, reason = rm.check_can_open_trade(
        category="forex", proposed_risk_pct=0.5  # no symbol
    )
    assert ok is True


def test_risk_manager_allows_different_symbol_during_cooldown() -> None:
    """USDCHF en cooldown no bloquea EURUSD."""
    repo = _repo()
    settings = _demo_settings(strategy_symbol_cooldown_minutes=15)
    portfolio = PortfolioManager(settings, repo)
    rm = RiskManager(settings, repo, portfolio)

    _seed_paper_trade(repo, symbol="USDCHF")
    ok, reason = rm.check_can_open_trade(
        category="forex", proposed_risk_pct=0.5, symbol="EURUSD"
    )
    assert ok is True


def test_risk_manager_allows_after_cooldown_expires() -> None:
    """Trade USDCHF hace 30 min con cooldown 15 min → ok."""
    repo = _repo()
    settings = _demo_settings(strategy_symbol_cooldown_minutes=15)
    portfolio = PortfolioManager(settings, repo)
    rm = RiskManager(settings, repo, portfolio)

    old = (utc_now() - timedelta(minutes=30)).isoformat()
    _seed_paper_trade(repo, symbol="USDCHF", opened_at=old)
    ok, reason = rm.check_can_open_trade(
        category="forex", proposed_risk_pct=0.5, symbol="USDCHF"
    )
    assert ok is True
