"""v2.7.0 — promotion gate: solo estrategias con expectancy realizada positiva
(o aún no probadas) pueden ejecutar a MT5 demo. Las que ya demostraron edge
negativo quedan en SHADOW (paper-only). El gate NO toca real-money ni la creación
de paper_trades — solo el order_send a la cuenta demo.
"""
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.repository import Repository
from app.learning.trade_outcomes import should_execute_live
from app.utils.time_utils import utc_now_iso


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"promo_gate_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _perf(trades: int, avg_r: float) -> dict:
    return {"trades": trades, "avg_r": avg_r}


def test_gate_allows_when_no_perf_data() -> None:
    ok, _ = should_execute_live("breakout", "forex", None, min_samples=30)
    assert ok is True


def test_gate_allows_unproven_small_sample_even_if_negative() -> None:
    # n < min_samples → allow: no condenar una estrategia sin muestra suficiente
    ok, reason = should_execute_live("breakout", "forex", _perf(5, -2.0), min_samples=30)
    assert ok is True
    assert "insuficiente" in reason


def test_gate_blocks_proven_negative_expectancy() -> None:
    # caso real: momentum 53 trades, avgR -0.29 → SHADOW
    ok, reason = should_execute_live("momentum", "forex", _perf(53, -0.29), min_samples=30)
    assert ok is False
    assert "SHADOW" in reason


def test_gate_allows_proven_positive_expectancy() -> None:
    ok, reason = should_execute_live("breakout", "gold", _perf(40, 0.35), min_samples=30)
    assert ok is True
    assert "LIVE" in reason


def test_gate_blocks_exactly_at_threshold() -> None:
    # avg_r == min_expectancy_r → <= → block (no es estrictamente positivo)
    ok, _ = should_execute_live(
        "x", "forex", _perf(50, 0.0), min_samples=30, min_expectancy_r=0.0
    )
    assert ok is False


def test_gate_custom_threshold() -> None:
    ok_low, _ = should_execute_live(
        "x", "forex", _perf(50, 0.1), min_samples=30, min_expectancy_r=0.2
    )
    assert ok_low is False
    ok_high, _ = should_execute_live(
        "x", "forex", _perf(50, 0.3), min_samples=30, min_expectancy_r=0.2
    )
    assert ok_high is True


def test_repository_fetch_strategy_performance_for_and_gate() -> None:
    repo = _repo()
    repo.upsert_strategy_performance(
        {
            "strategy_name": "momentum",
            "category": "forex",
            "trades": 53,
            "wins": 10,
            "losses": 33,
            "scratches": 10,
            "win_rate": 0.19,
            "avg_r": -0.29,
            "avg_return_pct": -0.5,
            "sum_return_pct": -26.5,
            "artifacts_excluded": 0,
            "updated_at": utc_now_iso(),
        }
    )
    row = repo.fetch_strategy_performance_for("momentum", "forex")
    assert row is not None
    assert int(row["trades"]) == 53
    ok, _ = should_execute_live("momentum", "forex", row, min_samples=30)
    assert ok is False
    # estrategia inexistente → None → allow (juntando muestra)
    assert repo.fetch_strategy_performance_for("nope", "forex") is None
    ok2, _ = should_execute_live(
        "nope", "forex", repo.fetch_strategy_performance_for("nope", "forex")
    )
    assert ok2 is True
