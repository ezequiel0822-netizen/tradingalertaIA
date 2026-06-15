"""Tests del replay_harness (v3.6.0, ESPEC §14).

Determinismo (doble corrida -> output identico), B12 (1 posicion por simbolo/
estrategia a la vez), escribe SOLO en tablas backtest_*, y respeta
STRATEGY_MIN_CONFIDENCE (paridad con el router vivo). Estrategia fake inyectada
para controlar el comportamiento sin depender de los umbrales de una estrategia real.
"""

from pathlib import Path
from uuid import uuid4

from app.backtest.replay_harness import WARMUP_BARS, ReplayHarness, RunConfig
from app.database.db import init_db
from app.database.repository import Repository
from app.strategies.base import StrategySignal
from tests.test_score import _settings

_DAY = 86_400
_D1_MIN = 1440


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"btharness_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_flat_candles(repo: Repository, symbol: str, n: int) -> None:
    """Precio plano: ni SL ni TP se tocan -> todo sale por time exit (deterministico)."""
    candles = [
        {"time": i * _DAY, "open": 1.0, "high": 1.001, "low": 0.999,
         "close": 1.0, "volume": 100}
        for i in range(n)
    ]
    repo.upsert_mt5_cache_candles(symbol, _D1_MIN, candles)


class _FakeAlwaysLong:
    """Emite long en cada barra que la pidan; horizonte 48h -> 2 barras D1."""

    name = "fake_long"
    enabled_setting_key = "enable_strategy_fake"

    def __init__(self, confidence: int) -> None:
        self._conf = confidence

    def evaluate(self, ctx, settings) -> StrategySignal | None:
        price = ctx.snapshot.price
        if price is None:
            return None
        return StrategySignal(
            strategy_name=self.name,
            direction="long",
            entry=price,
            stop=price * 0.98,
            targets=[price * 1.04, price * 1.08],
            confidence=self._conf,
            reasoning=["fake"],
            time_horizon_hours=48,
        )


def _config() -> RunConfig:
    return RunConfig(mode="A", timeframe="D1", symbols=["EURUSD"],
                     strategies=["fake_long"])


def test_harness_runs_and_writes_only_backtest_tables() -> None:
    repo = _repo()
    _seed_flat_candles(repo, "EURUSD", WARMUP_BARS + 60)
    harness = ReplayHarness(_settings(), repo)

    run_id = harness.run(_config(), strategies={"fake_long": _FakeAlwaysLong(70)})

    trades = repo.fetch_backtest_trades(run_id)
    assert len(trades) > 0
    # nada en tablas vivas
    assert repo.fetch_closed_paper_trades(limit=10) == []


def test_b12_one_position_per_symbol_strategy() -> None:
    repo = _repo()
    _seed_flat_candles(repo, "EURUSD", WARMUP_BARS + 60)
    harness = ReplayHarness(_settings(), repo)

    run_id = harness.run(_config(), strategies={"fake_long": _FakeAlwaysLong(70)})

    trades = sorted(repo.fetch_backtest_trades(run_id), key=lambda t: t["entry_utc"])
    assert len(trades) >= 2
    # ningun trade entra antes de que el anterior haya cerrado (sin solape).
    for prev, nxt in zip(trades, trades[1:]):
        assert nxt["entry_utc"] >= prev["exit_utc"]


def test_respects_strategy_min_confidence() -> None:
    settings = _settings()  # strategy_min_confidence = 60
    repo = _repo()
    _seed_flat_candles(repo, "EURUSD", WARMUP_BARS + 60)
    harness = ReplayHarness(settings, repo)

    low = harness.run(_config(), strategies={"fake_long": _FakeAlwaysLong(59)})
    high = harness.run(_config(), strategies={"fake_long": _FakeAlwaysLong(70)})

    assert repo.fetch_backtest_trades(low) == []
    assert len(repo.fetch_backtest_trades(high)) > 0


def test_determinism_double_run_identical() -> None:
    repo = _repo()
    _seed_flat_candles(repo, "EURUSD", WARMUP_BARS + 60)
    harness = ReplayHarness(_settings(), repo)

    run_a = harness.run(_config(), strategies={"fake_long": _FakeAlwaysLong(70)})
    run_b = harness.run(_config(), strategies={"fake_long": _FakeAlwaysLong(70)})

    def _key(t):
        return (t["strategy"], t["direction"], t["signal_bar_utc"], t["entry_utc"],
                t["exit_utc"], t["exit_reason"], t["bars_held"], t["r_gross"], t["r_net"])

    a = [_key(t) for t in repo.fetch_backtest_trades(run_a)]
    b = [_key(t) for t in repo.fetch_backtest_trades(run_b)]
    assert a == b
    assert len(a) > 0


def test_time_exit_with_flat_price_gives_zero_r_gross() -> None:
    repo = _repo()
    _seed_flat_candles(repo, "EURUSD", WARMUP_BARS + 30)
    harness = ReplayHarness(_settings(), repo)
    run_id = harness.run(_config(), strategies={"fake_long": _FakeAlwaysLong(70)})
    trades = repo.fetch_backtest_trades(run_id)
    assert trades
    # Todos salen por time (K=2) salvo el ultimo, que se cierra por agotamiento
    # de data (tambien reason 'time', bars_held < 2): comportamiento documentado.
    assert all(t["exit_reason"] == "time" for t in trades)
    assert all(t["bars_held"] <= 2 for t in trades)
    assert any(t["bars_held"] == 2 for t in trades)  # el caso normal: 48h / D1
    assert all(abs(float(t["r_gross"])) < 1e-9 for t in trades)  # precio plano -> 0R
