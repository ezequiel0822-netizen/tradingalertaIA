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


# v2.6.5 — realized_pnl_today USD-based calculation (Bug A fix).


def _seed_closed_trade(
    repo: Repository,
    symbol: str,
    category: str,
    entry: float,
    size_notional: float | None,
    unrealized_return_pct: float,
    direction: str = "long",
    executed_to_mt5: bool = True,
) -> int:
    """Helper: crea un paper_trade ya cerrado HOY (UTC) con notional opcional.

    v2.7.1: por default seed un demo_order con status='sent' (simulando
    ejecucion exitosa a MT5). Para testear paper-only path (gold huerfano,
    memecoin), pasar executed_to_mt5=False.

    Devuelve el paper_trade_id creado.
    """
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
        "stop_loss": entry * 0.95, "take_profit_1": entry * 1.05, "take_profit_2": entry * 1.10,
        "invalidation": None, "status": "closed_test",
        "unrealized_return_pct": unrealized_return_pct,
        "opened_at": now, "updated_at": now, "closed_at": now,
        "mfe_pct": 0, "mae_pct": 0, "original_stop_loss": entry * 0.95, "trailing_active": 0,
        "strategy_name": "breakout", "direction": direction,
        "size_notional": size_notional, "size_units": (size_notional / entry) if size_notional else 0,
        "risk_pct": 1.0, "partial_closed": 0,
    }
    assert repo.create_paper_trade(trade) is True

    # Recover paper_trade_id (latest by opened_at desc)
    trades = repo.fetch_paper_trades(limit=200) or []
    trade_id = int(trades[0]["id"])

    if executed_to_mt5:
        repo.create_demo_order({
            "demo_request_id": 0,
            "paper_trade_id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "volume": 0.1,
            "price": entry,
            "stop_loss": entry * 0.95,
            "take_profit": entry * 1.05,
            "retcode": 10009,
            "order_ticket": int(uuid4().int % 10_000_000),
            "deal_ticket": int(uuid4().int % 10_000_000),
            "status": "sent",
            "strategy_name": "breakout",
            "result_summary": "test",
            "sent_at": now,
        })

    return trade_id


def test_realized_pnl_today_zero_without_closed_trades() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 100000.0})
    repo = _repo()
    pm = PortfolioManager(settings, repo)
    assert pm.realized_pnl_today() == 0.0


def test_realized_pnl_today_ignores_trades_without_notional() -> None:
    """v2.6.5: memecoin paper trades sin size_notional NO afectan el cálculo.

    Esto es lo que disparaba el bug: USWC memecoin -82% sin notional sumaba
    -82% al cálculo. Ahora se ignora porque no afecta balance MT5 real.
    """
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 100000.0})
    repo = _repo()
    _seed_closed_trade(repo, "USWC", "memecoin", 0.0001, None, -82.75)
    _seed_closed_trade(repo, "GOONC", "memecoin", 0.0001, None, 12.66)
    pm = PortfolioManager(settings, repo)
    result = pm.realized_pnl_today()
    # Ambos memecoins skippeados porque notional=None → resultado 0%
    assert result == 0.0


def test_realized_pnl_today_computes_usd_based() -> None:
    """Trade con notional $10k y -1% = $100 loss. Balance $100k → -0.1%."""
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 100000.0})
    repo = _repo()
    _seed_closed_trade(repo, "EURUSD", "forex", 1.10, 10000.0, -1.0)
    pm = PortfolioManager(settings, repo)
    result = pm.realized_pnl_today()
    # $10000 * -1% = -$100. Como % de $100k = -0.1%
    assert abs(result - (-0.1)) < 0.0001


def test_realized_pnl_today_handles_bug_scenario() -> None:
    """Bug A scenario real: USWC -82% memecoin (sin notional) + GOONC +12% (sin notional)
    + 3 forex trades con 0%. Antes daba -70%. Ahora debe dar 0%.
    """
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 100000.0})
    repo = _repo()
    _seed_closed_trade(repo, "USWC", "memecoin", 0.0001, None, -82.75)
    _seed_closed_trade(repo, "GOONC", "memecoin", 0.0001, None, 12.66)
    _seed_closed_trade(repo, "GBPUSD", "forex", 1.34, 314017.0, 0.0)
    _seed_closed_trade(repo, "USDCHF", "forex", 0.78, 3125000.0, 0.0)
    _seed_closed_trade(repo, "EURUSD", "forex", 1.16, 100000.0, -0.0015)
    pm = PortfolioManager(settings, repo)
    result = pm.realized_pnl_today()
    # Memecoins skippeados (sin notional). Forex con notional pero 0% return.
    # Total USD ≈ 100000 * -0.000015 = -$1.50 / $100k = -0.0015%
    assert abs(result) < 0.01, f"Expected near 0%, got {result}%"


def test_realized_pnl_today_aggregates_multiple_trades() -> None:
    """Múltiples trades con notional → suma USD correcta dividido por balance."""
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 100000.0})
    repo = _repo()
    # Trade 1: $50k notional, -2% = -$1000
    _seed_closed_trade(repo, "T1", "stock", 100.0, 50000.0, -2.0)
    # Trade 2: $20k notional, +5% = +$1000
    _seed_closed_trade(repo, "T2", "stock", 100.0, 20000.0, 5.0)
    # Net: $0 USD on $100k balance = 0%
    pm = PortfolioManager(settings, repo)
    result = pm.realized_pnl_today()
    assert abs(result) < 0.001, f"Expected 0%, got {result}%"


# --- v2.7.1: paper-only filter (kill switch falso de gold) ---


def test_realized_pnl_today_excludes_paper_only_trades() -> None:
    """v2.7.1: Paper trade con notional pero SIN demo_order exitoso NO cuenta.

    Bug del 01-jun: gold paper_trade con symbol=GC=F nunca matcheaba
    DEMO_ALLOWED_SYMBOLS (XAUUSD/GOLD post-yahoo_to_mt5, no GC=F) → no
    ejecutaba a MT5 → size_notional quedaba teorico ($184k) → kill switch
    falso disparaba con -3.20% drawdown cuando el daño real era $0.
    """
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 100000.0})
    repo = _repo()
    # Gold paper-only con notional inflado pero NO ejecuto a MT5
    _seed_closed_trade(
        repo, "GC=F", "gold", 4400.0, 184000.0, -1.1,
        executed_to_mt5=False,  # ← no se ejecuto a MT5
    )
    pm = PortfolioManager(settings, repo)
    result = pm.realized_pnl_today()
    # Sin demo_order → excluido → 0% (correcto: no afecto MT5 real)
    assert result == 0.0, f"Expected 0% (paper-only), got {result}%"


def test_realized_pnl_today_includes_executed_trades() -> None:
    """Mismo trade pero CON demo_order exitoso debe contar normalmente."""
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 100000.0})
    repo = _repo()
    _seed_closed_trade(
        repo, "EURUSD", "forex", 1.16, 10000.0, -1.0,
        executed_to_mt5=True,
    )
    pm = PortfolioManager(settings, repo)
    result = pm.realized_pnl_today()
    # $10k × -1% = -$100. -$100 / $100k = -0.1%
    assert abs(result - (-0.1)) < 0.0001


def test_realized_pnl_today_mixed_executed_and_paper_only() -> None:
    """Mix realista: gold paper-only (huerfano) + forex ejecutado.

    Solo el forex debe contar. Antes de v2.7.1 el gold inflaba el calculo.
    """
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 100000.0})
    repo = _repo()
    # Gold paper-only -1% sobre $184k teorico (paper_pnl=-$2,028, REAL=$0)
    _seed_closed_trade(
        repo, "GC=F", "gold", 4400.0, 184000.0, -1.1, executed_to_mt5=False,
    )
    # Forex ejecutado +0.5% sobre $10k real (real_pnl=+$50)
    _seed_closed_trade(
        repo, "EURUSD", "forex", 1.16, 10000.0, 0.5, executed_to_mt5=True,
    )
    pm = PortfolioManager(settings, repo)
    result = pm.realized_pnl_today()
    # Solo el forex cuenta: +$50 / $100k = +0.05%
    assert abs(result - 0.05) < 0.0001, f"Expected +0.05% (solo forex), got {result}%"


def test_has_successful_demo_order_returns_false_when_no_order() -> None:
    """Repository helper: paper_trade sin demo_order → False."""
    repo = _repo()
    trade_id = _seed_closed_trade(
        repo, "GC=F", "gold", 4400.0, 184000.0, -1.0, executed_to_mt5=False,
    )
    assert repo.has_successful_demo_order(trade_id) is False


def test_has_successful_demo_order_returns_true_when_order_sent() -> None:
    repo = _repo()
    trade_id = _seed_closed_trade(
        repo, "EURUSD", "forex", 1.16, 10000.0, 0.0, executed_to_mt5=True,
    )
    assert repo.has_successful_demo_order(trade_id) is True


# v2.6.5 — account_balance refresh + persist (Bug C fix).


class _FakeReader:
    """Mock mt5_reader que permite controlar is_connected + get_account_info + reconnect."""

    def __init__(self, equity_sequence: list[float | None], connected: bool = True) -> None:
        self._equity_sequence = list(equity_sequence)
        self._connected = connected
        self.disconnect_calls = 0
        self.connect_calls = 0

    def is_connected(self) -> bool:
        return self._connected

    def get_account_info(self) -> dict | None:
        if not self._equity_sequence:
            return None
        equity = self._equity_sequence.pop(0)
        if equity is None:
            return None
        return {"equity": equity, "balance": equity}

    def disconnect(self) -> None:
        self.disconnect_calls += 1

    def connect(self) -> bool:
        self.connect_calls += 1
        self._connected = True
        return True


def test_account_balance_uses_mt5_equity_when_available() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 1000000.0})
    repo = _repo()
    reader = _FakeReader(equity_sequence=[100468.18])
    pm = PortfolioManager(settings, repo, mt5_reader=reader)
    assert pm.account_balance() == 100468.18


def test_account_balance_persists_equity_to_bot_state() -> None:
    """v2.6.5: cuando MT5 devuelve equity, se persiste en bot_state.account_balance.

    Eso garantiza que en próximo arranque (cuando MT5 quizás no responda
    inmediatamente) el bot tenga el valor real reciente, no el starting de 1M.
    """
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 1000000.0})
    repo = _repo()
    reader = _FakeReader(equity_sequence=[100468.18])
    pm = PortfolioManager(settings, repo, mt5_reader=reader)
    pm.account_balance()
    # Verificar que se guardó en bot_state
    stored = repo.get_state("account_balance")
    assert stored == "100468.18"


def test_account_balance_retries_reconnect_when_get_info_returns_none() -> None:
    """v2.6.5: si get_account_info devuelve None la primera vez, reconnect y reintentar.

    Patrón observado en producción: bot conectado horas, MT5 stale, devuelve
    None silencioso. Bug original caía al starting_balance del .env. Ahora
    retry reconnect rescata el valor real.
    """
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 1000000.0})
    repo = _repo()
    # Primera llamada None (stale), segunda 100k (post-reconnect)
    reader = _FakeReader(equity_sequence=[None, 100468.18])
    pm = PortfolioManager(settings, repo, mt5_reader=reader)
    result = pm.account_balance()
    assert result == 100468.18
    assert reader.disconnect_calls == 1
    assert reader.connect_calls == 1


def test_account_balance_falls_back_to_stored_when_mt5_silent() -> None:
    """Si tanto get_info como reconnect fallan, usa el último valor persistido."""
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 1000000.0})
    repo = _repo()
    repo.set_state("account_balance", "99500.00")
    reader = _FakeReader(equity_sequence=[None, None])
    pm = PortfolioManager(settings, repo, mt5_reader=reader)
    result = pm.account_balance()
    # Reconnect intentó pero también None → fallback a stored
    assert result == 99500.00


def test_account_balance_falls_back_to_starting_if_nothing() -> None:
    """Sin MT5 + sin stored → starting_balance del .env."""
    base = _settings()
    settings = type(base)(**{**base.__dict__, "account_starting_balance": 25000.0})
    repo = _repo()
    pm = PortfolioManager(settings, repo)  # sin mt5_reader
    assert pm.account_balance() == 25000.0
