"""v2.9.0 — tests del constructor de dataset ML.

Solo usa pandas (ya en requirements); no toca xgboost. Verifica que el dataset
excluye artifacts (misma quarantine que v2.7.0), arma el target win_loss, deriva
features de tiempo/sesion, hace el join temporal de macro (vix/dxy), deriva el
proxy macd_state desde el alert, y deja rsi_entry/atr_value como NaN (no persistidas).
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.database.db import get_connection, init_db
from app.database.repository import Repository
from app.learning.ml_dataset_builder import (
    REQUIRED_COLUMNS,
    build_ml_dataset,
    feature_coverage,
)
from app.utils.time_utils import utc_now_iso


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"mlds_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _seed_alert(repo: Repository, alert_id: int, reasons: list[str], category: str = "forex") -> None:
    with get_connection(repo.db_path) as conn:
        conn.execute(
            "INSERT INTO alerts (id, token_id, alert_type, category, chain, "
            "token_address, symbol, risk_level, reasons, score, estimate_confidence, "
            "estimated_gain_pct, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (alert_id, 1, "BREAKOUT", category, "forex", "EURUSD", "EURUSD",
             "medium", json.dumps(reasons), 80, 70, 2.0, utc_now_iso()),
        )


def _seed_macro(repo: Repository, captured_at: str, vix: float, dxy: float) -> None:
    with get_connection(repo.db_path) as conn:
        conn.execute(
            "INSERT INTO macro_snapshots (captured_at, vix_value, dxy_value) "
            "VALUES (?,?,?)",
            (captured_at, vix, dxy),
        )


def _seed_trade(
    repo: Repository,
    alert_id: int,
    entry: float,
    latest: float,
    ostop: float,
    direction: str = "long",
    opened_at: str | None = None,
    strategy: str = "breakout",
    category: str = "forex",
    symbol: str = "EURUSD",
) -> None:
    now = opened_at or utc_now_iso()
    repo.create_paper_trade({
        "alert_id": alert_id, "token_id": 1, "category": category, "chain": "forex",
        "token_address": symbol, "symbol": symbol, "thesis": "t", "readiness_grade": "B",
        "entry_price": entry, "latest_price": latest, "stop_loss": ostop,
        "take_profit_1": entry * 1.01, "take_profit_2": entry * 1.02, "invalidation": None,
        "status": "stopped_simulated", "unrealized_return_pct": 0, "opened_at": now,
        "updated_at": now, "closed_at": now, "mfe_pct": 0, "mae_pct": 0,
        "original_stop_loss": ostop, "trailing_active": 0, "strategy_name": strategy,
        "direction": direction,
    })


# --------------------------------------------------------------------------- #
def test_empty_db_returns_empty_df_with_columns() -> None:
    repo = _repo()
    df = build_ml_dataset(repo.db_path, export_csv=False)
    assert df.empty
    for col in REQUIRED_COLUMNS:
        assert col in df.columns


def test_excludes_artifacts() -> None:
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_alert(repo, 2, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0)   # real win
    _seed_trade(repo, 2, 100.0, 100.0, 95.0)   # artifact (frozen)
    df = build_ml_dataset(repo.db_path, export_csv=False)
    assert len(df) == 1


def test_has_all_required_columns() -> None:
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0)
    df = build_ml_dataset(repo.db_path, export_csv=False)
    for col in REQUIRED_COLUMNS:
        assert col in df.columns, f"falta columna {col}"


def test_win_loss_target() -> None:
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_alert(repo, 2, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0)   # +10% -> win
    _seed_trade(repo, 2, 100.0, 95.0, 98.0, symbol="GBPUSD")  # -5% -> loss
    df = build_ml_dataset(repo.db_path, export_csv=False)
    wins = df[df["win_loss"] == 1]
    losses = df[df["win_loss"] == 0]
    assert len(wins) == 1 and len(losses) == 1
    assert (wins["r_multiple"] > 0).all()
    assert (losses["r_multiple"] <= 0).all()


def test_session_and_time_features() -> None:
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0, opened_at="2026-06-02T14:30:00+00:00")
    df = build_ml_dataset(repo.db_path, export_csv=False)
    row = df.iloc[0]
    assert row["session"] == "ny"          # 14h UTC -> ny (12-21)
    assert row["time_of_day_hour"] == 14
    assert row["day_of_week"] == 1          # 2026-06-02 es martes


def test_macro_join_temporal() -> None:
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_macro(repo, "2026-06-02T13:00:00+00:00", 18.5, 104.2)  # antes del trade
    _seed_macro(repo, "2026-06-02T20:00:00+00:00", 25.0, 99.0)   # despues (no debe usarse)
    _seed_trade(repo, 1, 100.0, 110.0, 95.0, opened_at="2026-06-02T14:00:00+00:00")
    df = build_ml_dataset(repo.db_path, export_csv=False)
    row = df.iloc[0]
    assert abs(float(row["vix_level"]) - 18.5) < 1e-6
    assert abs(float(row["dxy_level"]) - 104.2) < 1e-6


def test_macd_state_proxy_from_alert() -> None:
    repo = _repo()
    _seed_alert(repo, 1, ["macd alcista", "ia pro"])
    _seed_alert(repo, 2, ["macd bajista"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0)
    _seed_trade(repo, 2, 100.0, 95.0, 98.0, symbol="GBPUSD")
    df = build_ml_dataset(repo.db_path, export_csv=False).set_index("alert_id")
    assert df.loc[1, "macd_state"] == "bullish"
    assert df.loc[1, "feat_ia_pro"] == 1
    assert df.loc[2, "macd_state"] == "bearish"


def test_rsi_atr_are_na_today() -> None:
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0)
    df = build_ml_dataset(repo.db_path, export_csv=False)
    assert df["rsi_entry"].isna().all()
    assert df["atr_value"].isna().all()


def test_scratch_trades_excluded() -> None:
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_trade(repo, 1, 100.0, 100.02, 95.0)  # +0.02% -> scratch (<=0.05)
    df = build_ml_dataset(repo.db_path, export_csv=False)
    assert df.empty


def test_csv_export(tmp_path) -> None:
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0)
    out = tmp_path / "ml_dataset.csv"
    df = build_ml_dataset(repo.db_path, export_csv=True, csv_path=out)
    assert out.exists()
    assert len(df) == 1


def test_feature_coverage_reports_na_features() -> None:
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0)
    df = build_ml_dataset(repo.db_path, export_csv=False)
    cov = feature_coverage(df)
    assert cov["session"] == 1.0          # siempre poblada
    assert cov["rsi_entry"] == 0.0        # nunca poblada hoy
