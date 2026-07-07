"""v2.9.0 — tests del constructor de dataset ML.

Solo usa pandas (ya en requirements); no toca xgboost. Verifica que el dataset
excluye artifacts (misma quarantine que v2.7.0), arma el target win_loss, deriva
features de tiempo/sesion, hace el join temporal de macro (vix/dxy), deriva el
macd_state (real desde el macd persistido o proxy del alert), y captura
rsi_entry/atr_value cuando el trade las guardo al entry (v2.11.0; NaN si no).
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
    rsi: float | None = None,
    atr: float | None = None,
    macd: float | None = None,
    macd_signal: float | None = None,
    vwap_dist: float | None = None,
    vwap_week_dist: float | None = None,
    hurst: float | None = None,
    clv: float | None = None,
    strength: str | None = None,
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
        # v2.11.0 features tecnicas al entry (None = trade viejo / scalping)
        "rsi_entry": rsi, "atr_value": atr,
        "macd_value": macd, "macd_signal_value": macd_signal,
        # v3.12.0 VWAP al entry (None = trade viejo / forex sin volumen)
        "vwap_dist_pct": vwap_dist, "vwap_week_dist_pct": vwap_week_dist,
        # v3.12.0 Hurst + footprint lite al entry
        "hurst_entry": hurst, "clv_entry": clv, "candle_strength": strength,
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


def test_rsi_atr_na_when_not_captured() -> None:
    # Trade viejo / scalping: sin captura -> rsi_entry/atr_value quedan NaN.
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0)
    df = build_ml_dataset(repo.db_path, export_csv=False)
    assert df["rsi_entry"].isna().all()
    assert df["atr_value"].isna().all()


def test_rsi_atr_macd_captured_at_entry() -> None:
    # v2.11.0: si el trade guardo features tecnicas al entry, el dataset las usa
    # como numericas reales y deriva macd_state del macd numerico (no del proxy).
    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])            # alert SIN pista de macd
    _seed_alert(repo, 2, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0, rsi=62.5, atr=1.3, macd=0.8, macd_signal=0.5)
    _seed_trade(repo, 2, 100.0, 95.0, 98.0, symbol="GBPUSD",
                rsi=28.0, atr=0.9, macd=-0.4, macd_signal=-0.1)
    df = build_ml_dataset(repo.db_path, export_csv=False).set_index("alert_id")
    assert abs(float(df.loc[1, "rsi_entry"]) - 62.5) < 1e-6
    assert abs(float(df.loc[1, "atr_value"]) - 1.3) < 1e-6
    assert df.loc[1, "macd_state"] == "bullish"   # macd 0.8 > signal 0.5
    assert df.loc[2, "macd_state"] == "bearish"   # macd -0.4 < signal -0.1


def test_macd_state_real_overrides_alert_proxy() -> None:
    # El macd numerico persistido gana sobre el proxy categorico del alert:
    # alert dice 'macd bajista' pero macd>signal -> bullish.
    repo = _repo()
    _seed_alert(repo, 1, ["macd bajista"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0, macd=1.2, macd_signal=0.3)
    df = build_ml_dataset(repo.db_path, export_csv=False)
    assert df.iloc[0]["macd_state"] == "bullish"


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


def test_vwap_roundtrip_and_nan_for_old_trades() -> None:
    # v3.12.0: vwap_dist_pct / vwap_week_dist_pct viajan del entry al dataset;
    # trades sin captura (viejos / forex sin volumen) quedan NaN, no 0.
    import pandas as pd

    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_alert(repo, 2, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0, vwap_dist=0.42, vwap_week_dist=-1.3)
    _seed_trade(repo, 2, 100.0, 110.0, 95.0)  # sin captura VWAP
    df = build_ml_dataset(repo.db_path, export_csv=False)
    assert "vwap_dist_pct" in df.columns and "vwap_week_dist_pct" in df.columns
    by_alert = df.set_index("alert_id")
    assert by_alert.loc[1, "vwap_dist_pct"] == 0.42
    assert by_alert.loc[1, "vwap_week_dist_pct"] == -1.3
    assert pd.isna(by_alert.loc[2, "vwap_dist_pct"])
    assert pd.isna(by_alert.loc[2, "vwap_week_dist_pct"])


def test_build_live_features_includes_vwap() -> None:
    from app.learning.ml_dataset_builder import build_live_features

    row = build_live_features({"opened_at": utc_now_iso(), "vwap_dist_pct": 0.5,
                               "vwap_week_dist_pct": -0.2})
    assert row["vwap_dist_pct"] == 0.5
    assert row["vwap_week_dist_pct"] == -0.2
    # sin captura -> None (XGBoost maneja NaN; jamas inventar 0)
    row_old = build_live_features({"opened_at": utc_now_iso()})
    assert row_old["vwap_dist_pct"] is None


def test_hurst_and_footprint_roundtrip() -> None:
    # v3.12.0: hurst_entry/clv_entry (numericas) y candle_strength (categorica)
    # viajan del entry al dataset; sin captura -> NaN / "unknown".
    import pandas as pd

    repo = _repo()
    _seed_alert(repo, 1, ["breakout"])
    _seed_alert(repo, 2, ["breakout"])
    _seed_trade(repo, 1, 100.0, 110.0, 95.0,
                hurst=0.58, clv=0.85, strength="strong_bull")
    _seed_trade(repo, 2, 100.0, 110.0, 95.0)  # sin captura
    df = build_ml_dataset(repo.db_path, export_csv=False).set_index("alert_id")
    assert abs(float(df.loc[1, "hurst_entry"]) - 0.58) < 1e-6
    assert abs(float(df.loc[1, "clv_entry"]) - 0.85) < 1e-6
    assert df.loc[1, "candle_strength"] == "strong_bull"
    assert pd.isna(df.loc[2, "hurst_entry"])
    assert pd.isna(df.loc[2, "clv_entry"])
    assert df.loc[2, "candle_strength"] == "unknown"
