"""Tests de trend_following_d1 (v3.6.0, ESPEC §9 / §14).

Entra en el breakout Donchian 55 alineado al regimen, sale por Donchian 20
(close-confirmada), short espejo, y respeta el gate de regimen. Mas integracion
con el harness (la salida Donchian llega via el hook backtest_close_exit).
"""

from pathlib import Path
from uuid import uuid4

import pytest

from app.backtest.replay_harness import WARMUP_BARS, ReplayHarness, RunConfig
from app.database.db import init_db
from app.database.models import TokenSnapshot
from app.database.repository import Repository
from app.strategies.base import StrategyContext
from app.strategies.trend_following_d1 import TrendFollowingD1Strategy
from tests.test_score import _settings

_DAY = 86_400
_D1_MIN = 1440


def _candle(close: float, i: int, rng: float = 0.2) -> dict:
    return {"time": i * _DAY, "open": close, "high": close + rng / 2,
            "low": close - rng / 2, "close": close, "volume": 100}


def _series(closes: list[float]) -> list[dict]:
    return [_candle(c, i) for i, c in enumerate(closes)]


def _ctx(candles: list[dict]) -> StrategyContext:
    snap = TokenSnapshot(chain="forex", token_address="EURUSD", category="forex",
                         symbol="EURUSD", price=candles[-1]["close"])
    return StrategyContext(snapshot=snap, candles=candles, pattern=None,
                           pro=None, macro={})


# -- entrada / gate -------------------------------------------------------


def test_long_entry_on_breakout_with_up_regime() -> None:
    candles = _series([100 + i * 0.5 for i in range(260)])  # sube monotono -> regimen up
    sig = TrendFollowingD1Strategy().evaluate(_ctx(candles), _settings())
    assert sig is not None
    assert sig.direction == "long"
    assert sig.confidence == 70
    assert sig.targets == []                       # sin TP fijo
    assert sig.time_horizon_hours == 2880          # 120 barras D1
    assert sig.entry == pytest.approx(229.5)
    assert sig.stop == pytest.approx(228.3)        # entry - 2*ATR14(=0.6)


def test_short_entry_mirror() -> None:
    candles = _series([300 - i * 0.5 for i in range(260)])  # baja monotono -> regimen down
    sig = TrendFollowingD1Strategy().evaluate(_ctx(candles), _settings())
    assert sig is not None
    assert sig.direction == "short"
    assert sig.entry == pytest.approx(170.5)
    assert sig.stop == pytest.approx(171.7)        # entry + 2*ATR14


def test_regime_gate_blocks_when_regime_unknown() -> None:
    # 100 barras: hay breakout 55 claro, pero no alcanza para SMA200 -> regimen
    # 'unknown' -> el gate bloquea (sin el gate, emitiria long).
    candles = _series([100 + i * 0.5 for i in range(100)])
    assert TrendFollowingD1Strategy().evaluate(_ctx(candles), _settings()) is None


def test_no_signal_with_insufficient_candles() -> None:
    candles = _series([100 + i * 0.5 for i in range(50)])
    assert TrendFollowingD1Strategy().evaluate(_ctx(candles), _settings()) is None


# -- salida Donchian (hook backtest_close_exit) ---------------------------


def test_donchian_exit_long_fires_below_channel() -> None:
    strat = TrendFollowingD1Strategy()
    candles = _series([11.0] * 50)            # plano: low=10.9, high=11.1
    candles[40] = _candle(9.0, 40)            # close 9 < min low del canal previo
    exit_fn = strat.backtest_close_exit(candles, entry_idx=30, direction="long",
                                        settings=_settings())
    assert exit_fn(10, candles[40]) is True   # m = 30+10 = 40
    assert exit_fn(11, candles[41]) is False  # close 11 > min low ~10.9


def test_donchian_exit_short_mirror() -> None:
    strat = TrendFollowingD1Strategy()
    candles = _series([11.0] * 50)
    candles[42] = _candle(13.0, 42)           # close 13 > max high del canal previo
    exit_fn = strat.backtest_close_exit(candles, entry_idx=30, direction="short",
                                        settings=_settings())
    assert exit_fn(12, candles[42]) is True   # m = 42
    assert exit_fn(13, candles[43]) is False


def test_donchian_exit_no_lookahead_at_series_start() -> None:
    strat = TrendFollowingD1Strategy()
    candles = _series([11.0] * 50)
    exit_fn = strat.backtest_close_exit(candles, entry_idx=5, direction="long",
                                        settings=_settings())
    assert exit_fn(0, candles[5]) is False    # m-20 < 0 -> sin canal, no sale


# -- integracion con el harness ------------------------------------------


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"bttrend_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_harness_trend_following_opens_and_exits_via_donchian() -> None:
    # Sube monotono (regimen up + breakouts -> entra long), despues un crash que
    # rompe el canal Donchian 20 por abajo -> salida 'trail' (close-confirmada).
    rising = [100 + i * 0.5 for i in range(290)]
    # Declive GRADUAL: el close cruza el canal Donchian 20 y ejecuta al open
    # siguiente sin gapear el SL duro (un crash empinado daria gap_sl, correcto).
    crash = [rising[-1] - (k + 1) * 1.0 for k in range(40)]
    repo = _repo()
    repo.upsert_mt5_cache_candles("EURUSD", _D1_MIN, _series(rising + crash))
    harness = ReplayHarness(_settings(), repo)

    run_id = harness.run(RunConfig(mode="A", timeframe="D1", symbols=["EURUSD"],
                                   strategies=["trend_following_d1"]))
    trades = repo.fetch_backtest_trades(run_id)

    assert len(trades) >= 1
    reasons = {t["exit_reason"] for t in trades}
    assert "tp" not in reasons                 # trend_following no tiene TP fijo
    assert reasons <= {"sl", "trail", "time", "gap_sl"}
    assert any(t["direction"] == "long" for t in trades)
    assert "trail" in reasons                  # la salida Donchian se disparo
