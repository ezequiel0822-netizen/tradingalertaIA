"""v2.9.0 — Constructor de dataset para la capa ML hibrida (XGBoost).

Arma un dataset limpio donde cada fila es un paper_trade CERRADO no-artifact con
sus features al momento de entrada y su outcome (win=1, loss=0). Reusa la misma
logica de quarantine (is_artifact) y de realized-R (realized_return_pct,
r_multiple) que v2.7.0, asi el target cuadra con /expectancy.

NOTA HONESTA SOBRE FEATURES (verificado contra el schema 2026-06):
  - vix_level, dxy_level   -> SI (macro_snapshots, join temporal por captured_at)
  - session/hour/dow       -> SI (derivadas de opened_at)
  - strategy_name/category -> SI (paper_trades)
  - features del alert      -> SI (feature_extractor sobre el alert vinculado:
                                 ia_pro, bullish/bearish_pattern, volumen, etc.)
  - macd_state             -> PROXY categorico (bullish/bearish/neutral desde el
                                 alert; el MACD numerico no se persiste)
  - rsi_entry, atr_value   -> NO se persisten hoy -> quedan NaN. Para tenerlos de
                                 verdad hay que capturarlos al crear el trade
                                 (cambio futuro, no retroactivo).

Solo depende de pandas (ya en requirements) + modulos internos. No importa xgboost.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.database.db import get_connection
from app.learning.feature_extractor import extract_features
from app.learning.trade_outcomes import is_artifact, r_multiple, realized_return_pct

# Columnas minimas requeridas por el plan (en este orden al frente del CSV).
REQUIRED_COLUMNS = [
    "rsi_entry",
    "macd_state",
    "atr_value",
    "vix_level",
    "dxy_level",
    "session",
    "strategy_name",
    "category",
    "time_of_day_hour",
    "day_of_week",
    "realized_return",
    "r_multiple",
    "win_loss",
]

# Features del alert (one-hot) que el feature_extractor puede emitir y que son
# utiles para el modelo. Prefijo feat_ para no chocar con las columnas base.
_ALERT_FEATURE_KEYS = [
    "ia_pro",
    "bullish_pattern",
    "bearish_pattern",
    "positive_news",
    "negative_news",
    "sec_catalyst",
    "sec_risk",
    "anti_hype",
    "volume_strength",
    "liquidity_strength",
    "low_liquidity",
    "security_unknown",
    "critical_security",
    "boosted_or_trending",
]


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _session_label(hour: int) -> str:
    """4 sesiones alineadas al pedido del plan (london/ny/asian/off), en hora UTC.

    (El comando /edge usa 5 franjas mas finas; aca usamos 4 porque es la
    granularidad que pidio el plan para el modelo.)
    """
    if 0 <= hour < 7:
        return "asian"
    if 7 <= hour < 12:
        return "london"
    if 12 <= hour < 21:
        return "ny"
    return "off"


def _macd_state_from_features(feats: list[str]) -> str:
    """Proxy del estado MACD desde las features categoricas del alert.
    El MACD numerico no se persiste; el feature_extractor marca 'bullish_pattern'
    cuando detecta 'macd alcista' y 'bearish_pattern' para 'macd bajista'."""
    if "bullish_pattern" in feats:
        return "bullish"
    if "bearish_pattern" in feats:
        return "bearish"
    return "neutral"


def _load_macro_df(db_path: Path) -> pd.DataFrame:
    """Todos los macro_snapshots como DataFrame ordenado por tiempo (para asof)."""
    with get_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT captured_at, vix_value, dxy_value FROM macro_snapshots "
            "ORDER BY captured_at"
        ).fetchall()
    data = [dict(r) for r in rows]
    if not data:
        return pd.DataFrame(columns=["captured_dt", "vix_value", "dxy_value"])
    df = pd.DataFrame(data)
    df["captured_dt"] = pd.to_datetime(
        df["captured_at"], utc=True, errors="coerce"
    ).dt.tz_localize(None)
    df = df.dropna(subset=["captured_dt"]).sort_values("captured_dt")
    return df[["captured_dt", "vix_value", "dxy_value"]]


def _load_closed_trades(db_path: Path) -> list[dict[str, Any]]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM paper_trades WHERE status != 'open' AND closed_at IS NOT NULL"
        ).fetchall()
    return [dict(r) for r in rows]


def _load_alert_features(db_path: Path) -> dict[int, list[str]]:
    """alert_id -> features categoricas (extract_features) del alert vinculado."""
    with get_connection(db_path) as connection:
        rows = connection.execute("SELECT * FROM alerts").fetchall()
    out: dict[int, list[str]] = {}
    for r in rows:
        alert = dict(r)
        try:
            out[int(alert["id"])] = extract_features(alert)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def build_ml_dataset(
    db_path: Path | str,
    export_csv: bool = True,
    csv_path: Path | str = "exports/ml_dataset.csv",
    cost_pct_by_category: dict[str, float] | None = None,
    partial_fraction: float = 0.5,
    scratch_eps: float = 0.05,
) -> pd.DataFrame:
    """Construye el dataset ML de paper_trades cerrados no-artifact.

    Cada fila = un trade con features al entry + outcome. Excluye artifacts (misma
    quarantine que v2.7.0). Exporta a CSV y retorna el DataFrame.

    `scratch_eps`: trades con |realized_return| <= eps (scratch) se EXCLUYEN del
    dataset de clasificacion (no son ni win ni loss claros). El target win_loss es
    binario: 1 si r_multiple > 0, 0 si <= 0.
    """
    db_path = Path(db_path)
    costs = cost_pct_by_category or {}
    macro_df = _load_macro_df(db_path)
    alert_features = _load_alert_features(db_path)
    closed = _load_closed_trades(db_path)

    records: list[dict[str, Any]] = []
    for t in closed:
        if is_artifact(t):
            continue
        cat = str(t.get("category") or "unknown")
        cost = float(costs.get(cat, 0.0) or 0.0)
        ret = realized_return_pct(t, partial_fraction, cost)
        rr = r_multiple(t, partial_fraction, cost)
        if ret is None or rr is None:
            continue
        if abs(ret) <= scratch_eps:
            continue  # scratch: ni win ni loss claro
        opened = _parse_dt(t.get("opened_at"))
        if opened is None:
            continue
        feats = alert_features.get(int(t.get("alert_id") or -1), [])
        rec: dict[str, Any] = {
            # outcome
            "realized_return": round(ret, 6),
            "r_multiple": round(rr, 6),
            "win_loss": 1 if rr > 0 else 0,
            # tiempo
            "session": _session_label(opened.hour),
            "time_of_day_hour": opened.hour,
            "day_of_week": opened.weekday(),  # 0=lunes
            # categoricas
            "strategy_name": str(t.get("strategy_name") or "unknown"),
            "category": cat,
            "direction": str(t.get("direction") or "long"),
            # tecnicas: proxy / no persistidas
            "macd_state": _macd_state_from_features(feats),
            "rsi_entry": pd.NA,   # no persistido hoy
            "atr_value": pd.NA,   # no persistido hoy
            # macro (se completan abajo con merge_asof)
            "vix_level": pd.NA,
            "dxy_level": pd.NA,
            # trazabilidad
            "alert_id": int(t.get("alert_id") or -1),
            "symbol": str(t.get("symbol") or ""),
            "opened_dt": opened.replace(tzinfo=None),
        }
        for key in _ALERT_FEATURE_KEYS:
            rec[f"feat_{key}"] = 1 if key in feats else 0
        records.append(rec)

    if not records:
        empty = pd.DataFrame(columns=REQUIRED_COLUMNS)
        if export_csv:
            _export(empty, csv_path)
        return empty

    df = pd.DataFrame(records).sort_values("opened_dt").reset_index(drop=True)

    # join temporal de macro (vix/dxy): el snapshot mas reciente <= opened_dt.
    if not macro_df.empty:
        merged = pd.merge_asof(
            df[["opened_dt"]].copy(),
            macro_df,
            left_on="opened_dt",
            right_on="captured_dt",
            direction="backward",
        )
        df["vix_level"] = merged["vix_value"].to_numpy()
        df["dxy_level"] = merged["dxy_value"].to_numpy()

    # ordenar columnas: requeridas primero, luego feat_* y trazabilidad
    feat_cols = [f"feat_{k}" for k in _ALERT_FEATURE_KEYS]
    trace_cols = ["direction", "alert_id", "symbol", "opened_dt"]
    ordered = REQUIRED_COLUMNS + feat_cols + trace_cols
    df = df[[c for c in ordered if c in df.columns]]

    if export_csv:
        _export(df, csv_path)
    return df


def _export(df: pd.DataFrame, csv_path: Path | str) -> None:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def feature_coverage(df: pd.DataFrame) -> dict[str, float]:
    """Fraccion de filas con valor no-nulo por columna. Util para ver que features
    estan realmente pobladas (ej. rsi_entry/atr_value seran 0.0 hoy)."""
    if df.empty:
        return {}
    n = len(df)
    return {col: round(float(df[col].notna().sum()) / n, 4) for col in df.columns}


def build_live_features(
    paper_trade: dict[str, Any],
    macro_row: dict[str, Any] | None = None,
    alert_features: list[str] | None = None,
) -> dict[str, Any]:
    """Arma el dict de features para MLPredictor.predict() de UN trade vivo, con la
    MISMA logica que build_ml_dataset (DRY). `macro_row`: dict con vix_value/dxy_value
    (ej. fetch_latest_macro_snapshot). `alert_features`: extract_features del alert
    vinculado. rsi_entry/atr_value quedan None (no persistidas hoy)."""
    opened = _parse_dt(paper_trade.get("opened_at")) or datetime.now(timezone.utc)
    feats = alert_features or []
    macro = macro_row or {}
    row: dict[str, Any] = {
        "vix_level": macro.get("vix_value"),
        "dxy_level": macro.get("dxy_value"),
        "time_of_day_hour": opened.hour,
        "day_of_week": opened.weekday(),
        "rsi_entry": None,
        "atr_value": None,
        "session": _session_label(opened.hour),
        "strategy_name": str(paper_trade.get("strategy_name") or "unknown"),
        "category": str(paper_trade.get("category") or "unknown"),
        "macd_state": _macd_state_from_features(feats),
        "direction": str(paper_trade.get("direction") or "long"),
    }
    for key in _ALERT_FEATURE_KEYS:
        row[f"feat_{key}"] = 1 if key in feats else 0
    return row


if __name__ == "__main__":  # pragma: no cover
    import os

    db = os.getenv("SQLITE_PATH", "trading_alert_ai.db")
    data = build_ml_dataset(db)
    print(f"Dataset: {len(data)} filas, {len(data.columns)} columnas")
    print("Coverage:", feature_coverage(data))
