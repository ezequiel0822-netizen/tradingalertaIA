"""COT-features ML experiment — el experimento REAL de la Fase D (research-only).

Pregunta honesta: ¿agregar features derivadas del COT (posicionamiento institucional
CFTC) al dataset del ML le da SEÑAL FORWARD que los features actuales no tienen?

Contexto (memoria del proyecto):
  - El ML sobre los features ACTUALES ya se probó = callejón sin salida: TimeSeriesSplit
    AUC ~0.475 OOS (peor que azar), aunque el k-fold con shuffle daba ~0.69 (peeking
    in-sample) y un split 80/20 simple ~0.627. La brecha es la firma de CERO señal
    forward + overfitting.
  - El COT ya tiene 5 años de historia (backfill: tabla cot_snapshots, 9 mercados FX+oro).
  - Protocolo: mirar SIEMPRE el TimeSeriesSplit OOS, NUNCA el k-fold. Solo si sube de
    ~0.55 OOS hay algo.

Este script NO toca el bot vivo, NO prende ningún flag, NO escribe en la DB viva:
  1. Hace un SNAPSHOT read-only de la DB viva (sqlite backup API) a un temp -> cero
     contención con el bot (historial de 'database is locked').
  2. Reproduce el baseline (split 80/20, k-fold shuffle, TimeSeriesSplit) sobre los
     features actuales (set completo y subset feature-complete rsi/atr).
  3. Deriva features de COT con rigor anti-lookahead (índice COT/Williams + percentil +
     net/OI + cambio, normalizados sobre la historia, con LAG DE RELEASE: el reporte del
     martes se publica el viernes -> usarlo antes sería lookahead).
  4. Re-corre el MISMO TimeSeriesSplit con las features de COT añadidas y compara.

Uso (desde la raíz del repo o el worktree, con el venv del proyecto):
    python scripts/cot_ml_experiment.py
    python scripts/cot_ml_experiment.py --db "C:/ruta/a/trading_alert_ai.db"
    python scripts/cot_ml_experiment.py --cot-lag-days 3 --cot-window 156
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

# Bootstrap: raíz del repo en sys.path para 'import app...'.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# La consola de Windows usa cp1252 y no encodea Δ/—/etc. Forzamos UTF-8 en stdout.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # pragma: no cover
    pass

try:
    import xgboost as xgb
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import KFold, TimeSeriesSplit
except ImportError as exc:  # pragma: no cover
    print(f"FALTAN libs ML ({exc}). Instalá: pip install xgboost scikit-learn")
    raise SystemExit(1)

from app.learning.ml_dataset_builder import build_ml_dataset  # noqa: E402
from app.learning.ml_predictor import _prepare_features  # noqa: E402


# ----------------------------------------------------------------------------- #
# Resolución del path de la DB viva (sin leer/mostrar secrets del .env)
# ----------------------------------------------------------------------------- #
def resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    # Cargar el .env del repo principal SOLO para SQLITE_PATH (un path no es secreto).
    try:
        from dotenv import load_dotenv

        for env in (
            Path(r"C:\Users\LENOVO\tradingalertaIA\.env"),
            Path(__file__).resolve().parents[1] / ".env",
        ):
            if env.exists():
                load_dotenv(env)
                break
    except ImportError:
        pass
    from app.config.settings import load_settings

    return Path(load_settings().sqlite_path)


def snapshot_db(live_path: Path) -> Path:
    """Copia consistente read-only de la DB viva (backup API). Devuelve el path temp."""
    if not live_path.exists():
        raise FileNotFoundError(f"No existe la DB viva: {live_path}")
    tmp = Path(tempfile.gettempdir()) / "cot_ml_snapshot.db"
    src = sqlite3.connect(f"file:{live_path.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return tmp


# ----------------------------------------------------------------------------- #
# Evaluación: 3 vistas del AUC (la honesta es TimeSeriesSplit)
# ----------------------------------------------------------------------------- #
def _xgb() -> "xgb.XGBClassifier":
    return xgb.XGBClassifier(
        max_depth=5,
        learning_rate=0.1,
        n_estimators=100,
        subsample=0.8,
        eval_metric="auc",
        random_state=42,
    )


def eval_aucs(x: pd.DataFrame, y: pd.Series, n_splits: int = 5) -> dict[str, float | int]:
    """Devuelve {split80, kfold_shuffle, timeseries, n, pos_rate}. NaN si no se puede."""
    out: dict[str, float | int] = {
        "n": int(len(x)),
        "pos_rate": float(y.mean()) if len(y) else float("nan"),
        "split80": float("nan"),
        "kfold_shuffle": float("nan"),
        "timeseries": float("nan"),
    }
    if len(x) < 40 or y.nunique() < 2:
        return out

    # (1) split 80/20 temporal simple (como MLPredictor._fit)
    cut = max(1, int(len(x) * 0.8))
    xtr, xte, ytr, yte = x.iloc[:cut], x.iloc[cut:], y.iloc[:cut], y.iloc[cut:]
    if len(xte) >= 5 and yte.nunique() == 2:
        m = _xgb().fit(xtr, ytr)
        out["split80"] = float(roc_auc_score(yte, m.predict_proba(xte)[:, 1]))

    # (2) k-fold con SHUFFLE = peeking in-sample (el espejismo 0.69)
    aucs: list[float] = []
    for tr, te in KFold(n_splits=n_splits, shuffle=True, random_state=42).split(x):
        ytr2, yte2 = y.iloc[tr], y.iloc[te]
        if ytr2.nunique() < 2 or yte2.nunique() < 2:
            continue
        m = _xgb().fit(x.iloc[tr], ytr2)
        aucs.append(roc_auc_score(yte2, m.predict_proba(x.iloc[te])[:, 1]))
    if aucs:
        out["kfold_shuffle"] = float(np.mean(aucs))

    # (3) TimeSeriesSplit = el honesto (train pasado / test futuro, sin look-ahead)
    aucs = []
    for tr, te in TimeSeriesSplit(n_splits=n_splits).split(x):
        ytr2, yte2 = y.iloc[tr], y.iloc[te]
        if ytr2.nunique() < 2 or yte2.nunique() < 2:
            continue
        m = _xgb().fit(x.iloc[tr], ytr2)
        aucs.append(roc_auc_score(yte2, m.predict_proba(x.iloc[te])[:, 1]))
    if aucs:
        out["timeseries"] = float(np.mean(aucs))
    return out


# ----------------------------------------------------------------------------- #
# Features de COT (anti-lookahead)
# ----------------------------------------------------------------------------- #
# símbolo del bot -> (market_code COT, signo para orientar al par)
#   +1: long del par = long de esa divisa (XXXUSD)
#   -1: long del par = short de esa divisa (USDXXX)
_CCY = {"EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"}


def symbol_to_cot(symbol: str) -> tuple[str | None, int]:
    s = (symbol or "").upper().replace("/", "").replace("_", "")
    if s.startswith("XAU") or s == "GOLD":
        return "GOLD", 1
    if len(s) >= 6:
        base, quote = s[:3], s[3:6]
        if quote == "USD" and base in _CCY:
            return base, 1
        if base == "USD" and quote in _CCY:
            return quote, -1
    return None, 0


def build_cot_features(
    cot: pd.DataFrame, window: int, min_periods: int, lag_days: int
) -> pd.DataFrame:
    """Por mercado y report_date: índice COT (Williams), percentil, net/OI y cambio,
    todo con ventana TRAILING (sin mirar el futuro) + una fecha 'disponible_desde' que
    aplica el lag de release de la CFTC (martes -> publicado el viernes)."""
    cot = cot.copy()
    cot["report_dt"] = pd.to_datetime(cot["report_date"], errors="coerce")
    cot = cot.dropna(subset=["report_dt", "net_noncomm"]).sort_values(
        ["market_code", "report_dt"]
    )
    cols = ["cot_curr_idx", "cot_pctile", "cot_net_oi", "cot_idx_chg"]

    # Loop explícito por mercado (a prueba de la semántica cambiante de groupby.apply).
    parts: list[pd.DataFrame] = []
    for _, g in cot.groupby("market_code", sort=False):
        g = g.copy()
        net = g["net_noncomm"].astype(float)
        roll = net.rolling(window=window, min_periods=min_periods)
        lo, hi = roll.min(), roll.max()
        rng = (hi - lo).replace(0, np.nan)
        g["cot_curr_idx"] = ((net - lo) / rng).clip(0, 1)  # índice COT/Williams [0,1]
        # percentil del net dentro de la ventana trailing (incluye el actual)
        g["cot_pctile"] = roll.apply(
            lambda w: (w <= w[-1]).mean() if len(w) else np.nan, raw=True
        )
        oi = g["open_interest"].astype(float).replace(0, np.nan)
        g["cot_net_oi"] = (net / oi).clip(-1, 1)
        g["cot_idx_chg"] = g["cot_curr_idx"].diff(4)  # cambio del índice a 4 semanas
        g["available_from"] = g["report_dt"] + pd.Timedelta(days=lag_days)
        parts.append(g)

    out = pd.concat(parts, ignore_index=True)
    return out[["market_code", "available_from", *cols]].dropna(subset=["available_from"])


def attach_cot(df: pd.DataFrame, cot_feat: pd.DataFrame) -> pd.DataFrame:
    """As-of join: a cada trade le pega el último reporte COT DISPONIBLE (available_from
    <= opened_dt) de su mercado. Agrega columnas feat_cot_* (las toma _prepare_features)."""
    df = df.copy()
    mapped = df["symbol"].map(symbol_to_cot)
    df["cot_market"] = mapped.map(lambda t: t[0])
    df["cot_sign"] = mapped.map(lambda t: t[1])
    df["opened_dt"] = pd.to_datetime(df["opened_dt"])

    left = df.reset_index().sort_values("opened_dt")
    right = cot_feat.sort_values("available_from")
    merged = pd.merge_asof(
        left,
        right,
        left_on="opened_dt",
        right_on="available_from",
        left_by="cot_market",
        right_by="market_code",
        direction="backward",
    ).set_index("index")
    merged = merged.reindex(df.index)  # re-alinear al orden original (merge_asof reordena)

    curr = merged["cot_curr_idx"]
    df["feat_cot_curr_idx"] = curr
    # orientado al par: para USDXXX (sign -1) invierte el índice de la divisa
    df["feat_cot_pair_idx"] = curr.where(df["cot_sign"] >= 0, 1.0 - curr)
    df["feat_cot_net_oi"] = merged["cot_net_oi"] * df["cot_sign"]
    df["feat_cot_idx_chg"] = merged["cot_idx_chg"]
    return df


# ----------------------------------------------------------------------------- #
def fmt(v: float | int) -> str:
    if isinstance(v, int):
        return str(v)
    return "  n/a" if v != v else f"{v:.3f}"  # NaN-safe


def print_row(label: str, r: dict) -> None:
    print(
        f"  {label:<34} n={r['n']:<5} pos={fmt(r['pos_rate'])}  "
        f"split80={fmt(r['split80'])}  kfold(shuffle)={fmt(r['kfold_shuffle'])}  "
        f"TimeSeriesSplit={fmt(r['timeseries'])}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Experimento ML con features de COT (research)")
    ap.add_argument("--db", default=None, help="path a la DB (default: SQLITE_PATH del .env)")
    ap.add_argument("--cot-window", type=int, default=156, help="ventana trailing (semanas) del índice COT")
    ap.add_argument("--cot-min-periods", type=int, default=26, help="mínimo de semanas para normalizar")
    ap.add_argument("--cot-lag-days", type=int, default=3, help="lag de release CFTC (martes->viernes)")
    ap.add_argument("--splits", type=int, default=5, help="folds del TimeSeriesSplit/k-fold")
    args = ap.parse_args()

    live = resolve_db_path(args.db)
    print(f"DB viva: {live.name}  (snapshot read-only, sin tocar el bot)")
    snap = snapshot_db(live)

    # --- dataset base (features actuales) ---
    df = build_ml_dataset(snap, export_csv=False)
    print(f"\nDataset: {len(df)} filas (trades cerrados no-artifact con outcome).")
    if df.empty:
        print("Sin filas -> nada para evaluar.")
        return 0

    rng = (pd.to_datetime(df["opened_dt"]).min(), pd.to_datetime(df["opened_dt"]).max())
    print(f"Rango temporal de los trades: {rng[0].date()} -> {rng[1].date()}")

    fc_mask = df["rsi_entry"].notna() & df["atr_value"].notna()
    df_fc = df[fc_mask].reset_index(drop=True)

    y_all = pd.to_numeric(df["win_loss"], errors="coerce").fillna(0).astype(int)
    y_fc = pd.to_numeric(df_fc["win_loss"], errors="coerce").fillna(0).astype(int)

    print("\n=== BASELINE (features actuales) — el honesto es TimeSeriesSplit ===")
    print_row("set completo", eval_aucs(_prepare_features(df), y_all, args.splits))
    print_row("subset feature-complete (rsi/atr)", eval_aucs(_prepare_features(df_fc), y_fc, args.splits))

    # --- features de COT ---
    with sqlite3.connect(f"file:{snap.as_posix()}?mode=ro", uri=True) as con:
        cot = pd.read_sql_query("SELECT * FROM cot_snapshots", con)
    print(f"\ncot_snapshots: {len(cot)} filas, {cot['market_code'].nunique()} mercados, "
          f"{cot['report_date'].min()} -> {cot['report_date'].max()}")

    cot_feat = build_cot_features(cot, args.cot_window, args.cot_min_periods, args.cot_lag_days)
    df_fc_cot = attach_cot(df_fc, cot_feat)
    cot_cols = ["feat_cot_curr_idx", "feat_cot_pair_idx", "feat_cot_net_oi", "feat_cot_idx_chg"]
    cov = df_fc_cot[cot_cols].notna().mean()
    matched = df_fc_cot["feat_cot_pair_idx"].notna().sum()
    print(f"Trades con COT disponible (FX/oro, as-of+lag): {matched}/{len(df_fc_cot)} "
          f"({100*matched/max(1,len(df_fc_cot)):.0f}%)")
    print("Cobertura por feature COT: " + ", ".join(f"{c.replace('feat_cot_','')}={cov[c]:.2f}" for c in cot_cols))

    print("\n=== CON FEATURES DE COT (mismo subset feature-complete, mismo TimeSeriesSplit) ===")
    x_base = _prepare_features(df_fc)
    x_cot = _prepare_features(df_fc_cot)  # incluye las feat_cot_* (prefijo feat_)
    base_ts = eval_aucs(x_base, y_fc, args.splits)
    cot_ts = eval_aucs(x_cot, y_fc, args.splits)
    print_row("baseline (sin COT)", base_ts)
    print_row("+ COT features", cot_ts)

    # solo sobre las filas que SÍ tienen COT (FX/oro) — el test más justo para el COT
    cot_only = df_fc_cot[df_fc_cot["feat_cot_pair_idx"].notna()].reset_index(drop=True)
    if len(cot_only) >= 40:
        y_co = pd.to_numeric(cot_only["win_loss"], errors="coerce").fillna(0).astype(int)
        print_row("solo trades con COT (sin feats)",
                  eval_aucs(_prepare_features(cot_only.drop(columns=cot_cols)), y_co, args.splits))
        print_row("solo trades con COT (+ COT)",
                  eval_aucs(_prepare_features(cot_only), y_co, args.splits))

    d = cot_ts["timeseries"] - base_ts["timeseries"]
    print("\n=== VEREDICTO ===")
    print(f"  TimeSeriesSplit OOS:  baseline={fmt(base_ts['timeseries'])}  +COT={fmt(cot_ts['timeseries'])}  "
          f"(Δ={d:+.3f})" if d == d else "  TimeSeriesSplit no evaluable (muestra/clase)")
    if cot_ts["timeseries"] == cot_ts["timeseries"]:
        if cot_ts["timeseries"] >= 0.55 and d >= 0.03:
            print("  -> SEÑAL: el COT sube el OOS por encima de ~0.55. Vale formalizar (con tests).")
        else:
            print("  -> SIN SEÑAL nueva: el COT no levanta el OOS sobre los features actuales.")
            print("     Coherente con la anti-lista (MAPA §5). Documentar y NO prender ENABLE_ML_PREDICTOR.")
    print("\n(Recordá: mirar SIEMPRE TimeSeriesSplit, NUNCA el k-fold/shuffle — ese es el espejismo in-sample.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
