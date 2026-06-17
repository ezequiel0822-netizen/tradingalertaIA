"""Tests del harness sobre ACCIONES (ESPEC_BACKTEST_STOCKS_v1 §9, S2).

El harness corre con category='stock', taggea los trades como stock (cost model
de acciones) y el reporte lleva el banner de SURVIVORSHIP BIAS. Un run de forex
(sin category) NO lleva el banner. Estrategia fake inyectada + precio plano.
"""

from pathlib import Path
from uuid import uuid4

from app.backtest.replay_harness import WARMUP_BARS, ReplayHarness, RunConfig
from app.backtest.report import generate_report
from app.database.db import init_db
from app.database.repository import Repository
from app.strategies.base import StrategySignal
from tests.test_score import _settings

_DAY = 86_400
_D1 = 1440


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"stockharness_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed(repo: Repository, symbol: str, n: int) -> None:
    candles = [
        {"time": i * _DAY, "open": 1.0, "high": 1.001, "low": 0.999,
         "close": 1.0, "volume": 100}
        for i in range(n)
    ]
    repo.upsert_mt5_cache_candles(symbol, _D1, candles)


class _FakeLong:
    name = "fake_long"
    enabled_setting_key = "enable_strategy_fake"

    def evaluate(self, ctx, settings) -> StrategySignal | None:
        price = ctx.snapshot.price
        if price is None:
            return None
        return StrategySignal("fake_long", "long", price, price * 0.98,
                              [price * 1.04, price * 1.08], 70, ["fake"], 48)


def _run_stock(repo: Repository) -> int:
    cfg = RunConfig(mode="A", timeframe="D1", symbols=["AAPL"],
                    strategies=["fake_long"], category="stock")
    return ReplayHarness(_settings(), repo).run(cfg, strategies={"fake_long": _FakeLong()})


def test_harness_tags_trades_as_stock() -> None:
    repo = _repo()
    _seed(repo, "AAPL", WARMUP_BARS + 60)
    run_id = _run_stock(repo)
    trades = repo.fetch_backtest_trades(run_id)
    assert trades
    assert all(t["category"] == "stock" for t in trades)  # cost model de acciones


def test_stock_report_has_survivorship_banner(tmp_path) -> None:
    repo = _repo()
    _seed(repo, "AAPL", WARMUP_BARS + 60)
    run_id = _run_stock(repo)
    md = Path(generate_report(repo, run_id, _settings(),
                              out_base=str(tmp_path))["report_md"]).read_text(encoding="utf-8")
    assert "SESGO DE SUPERVIVENCIA" in md
    assert "DESCARTAR" in md


def test_forex_run_has_no_banner(tmp_path) -> None:
    repo = _repo()
    _seed(repo, "EURUSD", WARMUP_BARS + 60)
    cfg = RunConfig(mode="A", timeframe="D1", symbols=["EURUSD"],
                    strategies=["fake_long"])  # sin category -> forex
    run_id = ReplayHarness(_settings(), repo).run(cfg, strategies={"fake_long": _FakeLong()})
    md = Path(generate_report(repo, run_id, _settings(),
                              out_base=str(tmp_path))["report_md"]).read_text(encoding="utf-8")
    assert "SESGO DE SUPERVIVENCIA" not in md
