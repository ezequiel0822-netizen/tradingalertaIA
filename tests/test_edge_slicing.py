"""v2.8.0 — Edge detection sliceado por sesión y dirección.

Cubre:
- session_of: clasificación de franja UTC (límites + naive + inválido).
- build_sliced_performance: agrupación por sesión/dirección, exclusión de
  artifacts, costos, y consistencia de re-agregación contra build_strategy_performance.
- should_execute_live_sliced: el gate sliceado es estrictamente más restrictivo y
  SOLO puede mover a SHADOW (nunca promueve un slice +R sobre un agregado SHADOW).
- Repository: upsert/fetch de strategy_performance_sliced.
- training_engine._refresh_sliced_performance: pobla la tabla; OFF respeta el flag.
- Comando /edge: aliases, sin-datos, con-datos, soft-fail.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.learning.trade_outcomes import (
    build_sliced_performance,
    build_strategy_performance,
    session_of,
    should_execute_live_sliced,
)
from app.learning.training_engine import _refresh_sliced_performance
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"edge_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _trade(
    *,
    entry: float,
    latest: float,
    ostop: float,
    direction: str,
    opened_at: str,
    strategy: str = "breakout",
    category: str = "forex",
) -> dict:
    """Un dict-trade cerrado mínimo, con los campos que usan trade_outcomes."""
    return {
        "strategy_name": strategy,
        "category": category,
        "status": "stopped_simulated",
        "closed_at": opened_at,
        "opened_at": opened_at,
        "entry_price": entry,
        "latest_price": latest,
        "original_stop_loss": ostop,
        "stop_loss": ostop,
        "direction": direction,
        "partial_closed": 0,
    }


def _seed_closed(
    repo: Repository,
    symbol: str,
    entry: float,
    latest: float,
    ostop: float,
    direction: str,
    opened_at: str,
    strategy: str = "breakout",
) -> None:
    """Persiste un paper_trade cerrado real en la DB (para _refresh y /edge)."""
    snap = TokenSnapshot(
        chain="forex", token_address=symbol, category="forex", symbol=symbol,
        price=entry, liquidity_usd=1_000_000,
    )
    est = EstimateResult(
        estimated_gain_pct=2, estimated_loss_pct=1, confidence=70,
        label="paper", reasons=[], eligible_for_gain_alert=True,
    )
    tid = repo.upsert_token(snap, 80, "orange", est)
    repo.create_paper_trade({
        "alert_id": int(uuid4().int % 10_000_000), "token_id": tid, "category": "forex",
        "chain": "forex", "token_address": symbol, "symbol": symbol, "thesis": "t",
        "readiness_grade": "B", "entry_price": entry, "latest_price": latest,
        "stop_loss": ostop, "take_profit_1": entry * 1.01, "take_profit_2": entry * 1.02,
        "invalidation": None, "status": "stopped_simulated", "unrealized_return_pct": 0,
        "opened_at": opened_at, "updated_at": opened_at, "closed_at": opened_at,
        "mfe_pct": 0, "mae_pct": 0, "original_stop_loss": ostop, "trailing_active": 0,
        "strategy_name": strategy, "direction": direction,
    })


# --------------------------------------------------------------------------- #
# session_of
# --------------------------------------------------------------------------- #
def test_session_of_boundaries() -> None:
    cases = {
        "2026-06-02T00:00:00+00:00": "Asia",
        "2026-06-02T06:59:00+00:00": "Asia",
        "2026-06-02T07:00:00+00:00": "London",
        "2026-06-02T11:59:00+00:00": "London",
        "2026-06-02T12:00:00+00:00": "LDN-NY",
        "2026-06-02T15:59:00+00:00": "LDN-NY",
        "2026-06-02T16:00:00+00:00": "NY",
        "2026-06-02T20:59:00+00:00": "NY",
        "2026-06-02T21:00:00+00:00": "Off",
        "2026-06-02T23:59:00+00:00": "Off",
    }
    for ts, expected in cases.items():
        assert session_of(ts) == expected, f"{ts} -> {session_of(ts)} != {expected}"


def test_session_of_naive_assumed_utc() -> None:
    # sin tzinfo se asume UTC
    assert session_of("2026-06-02T14:00:00") == "LDN-NY"


def test_session_of_invalid_is_unknown() -> None:
    assert session_of("no-soy-fecha") == "unknown"
    assert session_of(None) == "unknown"
    assert session_of("") == "unknown"


# --------------------------------------------------------------------------- #
# build_sliced_performance
# --------------------------------------------------------------------------- #
def _mixed_trades() -> list[dict]:
    # 2 long en LDN-NY (1 win 1 loss), 1 short en Asia (win), 1 artifact (frozen)
    return [
        _trade(entry=100, latest=110, ostop=95, direction="long",
               opened_at="2026-06-02T14:00:00+00:00"),   # long win +2R, LDN-NY
        _trade(entry=100, latest=95, ostop=95, direction="long",
               opened_at="2026-06-02T13:00:00+00:00"),   # long loss -1R, LDN-NY
        _trade(entry=100, latest=90, ostop=110, direction="short",
               opened_at="2026-06-02T03:00:00+00:00"),   # short win +1R, Asia
        _trade(entry=100, latest=100, ostop=95, direction="long",
               opened_at="2026-06-02T14:00:00+00:00"),   # artifact (frozen)
    ]


def test_build_sliced_groups_by_session_and_direction() -> None:
    perfs = build_sliced_performance(_mixed_trades())
    by = {(p.dimension, p.bucket): p for p in perfs}
    # sesiones
    assert by[("session", "LDN-NY")].trades == 2
    assert by[("session", "Asia")].trades == 1
    # direcciones
    assert by[("direction", "long")].trades == 2
    assert by[("direction", "short")].trades == 1


def test_build_sliced_excludes_artifacts_but_counts_them() -> None:
    perfs = build_sliced_performance(_mixed_trades())
    ldnny = next(p for p in perfs if p.dimension == "session" and p.bucket == "LDN-NY")
    # 2 reales en LDN-NY + 1 artifact en LDN-NY contado aparte
    assert ldnny.trades == 2
    assert ldnny.artifacts_excluded == 1


def test_build_sliced_reaggregation_matches_aggregate() -> None:
    # La suma de trades de los buckets de una dimensión == total real del agregado.
    trades = _mixed_trades()
    agg = build_strategy_performance(trades)
    agg_breakout = next(p for p in agg if p.strategy_name == "breakout")
    sliced = build_sliced_performance(trades)
    dir_total = sum(p.trades for p in sliced if p.dimension == "direction")
    sess_total = sum(p.trades for p in sliced if p.dimension == "session")
    assert dir_total == agg_breakout.trades
    assert sess_total == agg_breakout.trades


def test_build_sliced_applies_cost() -> None:
    trades = [
        _trade(entry=100, latest=110, ostop=95, direction="long",
               opened_at="2026-06-02T14:00:00+00:00"),
    ]
    no_cost = build_sliced_performance(trades)
    with_cost = build_sliced_performance(trades, cost_pct_by_category={"forex": 5.0})
    r_no = next(p for p in no_cost if p.dimension == "direction").avg_r
    r_cost = next(p for p in with_cost if p.dimension == "direction").avg_r
    assert r_cost < r_no  # el costo siempre empeora el R


# --------------------------------------------------------------------------- #
# should_execute_live_sliced
# --------------------------------------------------------------------------- #
def _row(trades: int, avg_r: float, dimension: str = "session", bucket: str = "LDN-NY") -> dict:
    return {"trades": trades, "avg_r": avg_r, "dimension": dimension, "bucket": bucket}


def test_sliced_gate_aggregate_shadow_stays_shadow() -> None:
    # agregado ya prueba edge negativo -> SHADOW, sin importar slices
    ok, reason = should_execute_live_sliced(
        "x", "forex", {"trades": 40, "avg_r": -0.5}, [_row(35, 0.8)], 30, 0.0
    )
    assert ok is False
    assert "SHADOW" in reason


def test_sliced_gate_blocks_when_slice_proves_negative() -> None:
    # agregado LIVE, pero un slice con n>=min prueba perder -> SHADOW
    ok, reason = should_execute_live_sliced(
        "x", "forex", {"trades": 40, "avg_r": 0.2}, [_row(35, -0.5)], 30, 0.0
    )
    assert ok is False
    assert "slice" in reason and "SHADOW" in reason


def test_sliced_gate_respects_aggregate_when_slice_small() -> None:
    # slice perdedor pero n<min -> no condena, respeta el agregado LIVE
    ok, reason = should_execute_live_sliced(
        "x", "forex", {"trades": 40, "avg_r": 0.2}, [_row(5, -0.9)], 30, 0.0
    )
    assert ok is True
    assert "LIVE" in reason


def test_sliced_gate_positive_slice_never_rescues_shadow_aggregate() -> None:
    # regla anti-data-dredging: un slice +R NO promueve un agregado SHADOW
    ok, _ = should_execute_live_sliced(
        "x", "forex", {"trades": 40, "avg_r": -0.5}, [_row(35, 1.5)], 30, 0.0
    )
    assert ok is False


def test_sliced_gate_no_slices_equals_base_gate() -> None:
    ok, reason = should_execute_live_sliced(
        "x", "forex", {"trades": 40, "avg_r": 0.3}, [], 30, 0.0
    )
    assert ok is True
    assert "LIVE" in reason


def test_sliced_gate_all_clean_allows_live() -> None:
    ok, _ = should_execute_live_sliced(
        "x", "forex", {"trades": 40, "avg_r": 0.3},
        [_row(35, 0.4), _row(33, 0.1, "direction", "long")], 30, 0.0
    )
    assert ok is True


# --------------------------------------------------------------------------- #
# Repository: strategy_performance_sliced
# --------------------------------------------------------------------------- #
def _perf_row(strategy: str, cat: str, dim: str, bucket: str, trades: int, avg_r: float) -> dict:
    return {
        "strategy_name": strategy, "category": cat, "dimension": dim, "bucket": bucket,
        "trades": trades, "wins": 0, "losses": 0, "scratches": 0, "win_rate": 0.0,
        "avg_r": avg_r, "avg_return_pct": 0.0, "sum_return_pct": 0.0,
        "artifacts_excluded": 0, "updated_at": utc_now_iso(),
    }


def test_repository_upsert_and_fetch_sliced() -> None:
    repo = _repo()
    repo.upsert_sliced_performance(_perf_row("breakout", "forex", "session", "LDN-NY", 30, -0.4))
    repo.upsert_sliced_performance(_perf_row("breakout", "forex", "direction", "long", 25, -0.5))
    rows = repo.fetch_sliced_performance()
    assert len(rows) == 2
    # upsert sobre la misma PK actualiza, no duplica
    repo.upsert_sliced_performance(_perf_row("breakout", "forex", "session", "LDN-NY", 31, -0.3))
    rows2 = repo.fetch_sliced_performance()
    assert len(rows2) == 2
    ldnny = next(r for r in rows2 if r["dimension"] == "session")
    assert int(ldnny["trades"]) == 31


def test_repository_fetch_sliced_for_filters_by_bucket() -> None:
    repo = _repo()
    repo.upsert_sliced_performance(_perf_row("breakout", "forex", "session", "LDN-NY", 30, -0.4))
    repo.upsert_sliced_performance(_perf_row("breakout", "forex", "session", "Asia", 18, 0.1))
    repo.upsert_sliced_performance(_perf_row("breakout", "forex", "direction", "long", 25, -0.5))
    got = repo.fetch_sliced_performance_for("breakout", "forex", ["LDN-NY", "long"])
    buckets = {r["bucket"] for r in got}
    assert buckets == {"LDN-NY", "long"}
    # buckets vacíos -> []
    assert repo.fetch_sliced_performance_for("breakout", "forex", []) == []


# --------------------------------------------------------------------------- #
# training_engine._refresh_sliced_performance
# --------------------------------------------------------------------------- #
def test_refresh_sliced_populates_table() -> None:
    repo = _repo()
    settings = _settings()
    _seed_closed(repo, "EURUSD", 100, 110, 95, "long", "2026-06-02T14:00:00+00:00")
    _seed_closed(repo, "GBPUSD", 100, 90, 110, "short", "2026-06-02T03:00:00+00:00")
    n = _refresh_sliced_performance(repo, settings)
    assert n > 0
    rows = repo.fetch_sliced_performance()
    dims = {r["dimension"] for r in rows}
    assert dims == {"session", "direction"}


def test_refresh_sliced_off_when_flag_disabled() -> None:
    repo = _repo()
    settings = replace(_settings(), enable_edge_slicing=False)
    _seed_closed(repo, "EURUSD", 100, 110, 95, "long", "2026-06-02T14:00:00+00:00")
    assert _refresh_sliced_performance(repo, settings) == 0
    assert repo.fetch_sliced_performance() == []


# --------------------------------------------------------------------------- #
# Comando /edge
# --------------------------------------------------------------------------- #
def test_edge_command_aliases() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)
    for alias in ["/edge", "edge", "/borde"]:
        resp = assistant.handle(alias)
        assert "Edge por slice" in resp, f"alias {alias!r} no responde"


def test_edge_command_empty_db() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)
    resp = assistant.handle("/edge")
    assert "sin datos" in resp.lower()
    assert "No es recomendacion financiera" in resp


def test_edge_command_shows_slices_and_marks_reliable() -> None:
    repo = _repo()
    settings = replace(_settings(), edge_slice_min_samples=2)
    # 2 long LDN-NY (win + loss) y 1 short Asia -> con min=2 el slice long es [OK]
    _seed_closed(repo, "EURUSD", 100, 110, 95, "long", "2026-06-02T14:00:00+00:00")
    _seed_closed(repo, "AUDUSD", 100, 110, 95, "long", "2026-06-02T13:00:00+00:00")
    _seed_closed(repo, "GBPUSD", 100, 90, 110, "short", "2026-06-02T03:00:00+00:00")
    _refresh_sliced_performance(repo, settings)
    assistant = BasicTelegramAssistant(settings, repo)
    resp = assistant.handle("/edge")
    assert "POR SESION" in resp
    assert "POR DIRECCION" in resp
    assert "[OK]" in resp  # al menos un slice con n>=2


def test_edge_command_soft_fails_on_repository_error() -> None:
    repo = _repo()
    assistant = BasicTelegramAssistant(_settings(), repo)

    def boom(*_a, **_k):
        raise RuntimeError("db gone")

    repo.fetch_sliced_performance = boom  # type: ignore[method-assign]
    resp = assistant.handle("/edge")
    assert "no disponible" in resp.lower()
