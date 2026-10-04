"""Estudio H-MS1 — microestructura L1 en BTCUSDT perp: ¿predecible Y operable?

Implementa EXACTAMENTE el pre-registro research/HIPOTESIS_2026-10-03_microestructura.md
(commiteado antes de bajar datos). Nada de esto es ajustable después de ver
resultados: features, barreras, modelos, hiperparámetros, umbral y criterio
están fijados allá.

Entrada: parquets de 1 s de scripts/microstructure_backfill.py.
Salida: reporte markdown + JSON con todos los números (no toca el bot ni la DB).

Uso:
  python scripts/microstructure_study.py \
      --data C:/Users/LENOVO/tradingalertaIA/trading_data/binance_micro/BTCUSDT_1s \
      --out  C:/Users/LENOVO/tradingalertaIA/exports/microstructure_study
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

# ---- parámetros CONGELADOS por el pre-registro ---------------------------------
WINDOW_START = date(2023, 8, 1)
DEV_END = date(2023, 10, 10)          # inclusive
HOLDOUT_START = date(2023, 10, 11)
WINDOW_END = date(2023, 10, 31)       # inclusive
HORIZONS = {30: 4.0, 60: 6.0, 300: 14.0}   # H (s) -> barrera ± bps
NORM_WINDOW = 300
OFI_CVD_WINDOWS = (1, 5, 15, 30)
NTR_WINDOWS = (5, 30)
RET_WINDOWS = (1, 5, 15, 30, 60, 300)
TRAIN_STRIDE = 5
MIN_TRAIN_WEEKS = 3
THRESHOLD_QUANTILE = 0.90
FEE_SCENARIOS = {"bruto": 0.0, "maker_2bps": 2.0, "taker_4bps": 4.0, "taker_5bps": 5.0}
PRIMARY_FEE = "taker_4bps"
T_CRIT = 2.64          # Bonferroni k=6, alfa 0.05 bilateral
MIN_TRADES = 200
EXISTENCE_AUC = 0.52


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


# ---- carga ---------------------------------------------------------------------
def load(data_dir: Path) -> tuple[pd.DataFrame, list[str]]:
    frames, missing = [], []
    d = WINDOW_START
    while d <= WINDOW_END:
        f = data_dir / f"{d.isoformat()}.parquet"
        if f.exists():
            frames.append(pd.read_parquet(f))
        else:
            missing.append(d.isoformat())
        d += timedelta(days=1)
    df = pd.concat(frames, ignore_index=True).sort_values("sec")
    grid = pd.RangeIndex(epoch(WINDOW_START), epoch(WINDOW_END) + 86_400)
    df = df.set_index("sec").reindex(grid)   # días faltantes -> NaN (no se rellenan)
    df.index.name = "sec"
    return df, missing


# ---- features (solo data <= t) -------------------------------------------------
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    bid, ask, bq, aq = df["bid"], df["ask"], df["bq"], df["aq"]
    mid = (bid + ask) / 2.0
    f = pd.DataFrame(index=df.index)
    depth = bq + aq
    f["obi"] = (bq - aq) / depth
    micro = (ask * bq + bid * aq) / depth
    f["micro_dev_bps"] = (micro - mid) / mid * 1e4
    f["spread_bps"] = (ask - bid) / mid * 1e4
    depth_norm = depth.rolling(NORM_WINDOW, min_periods=NORM_WINDOW).mean()
    vol = df["buy_vol"] + df["sell_vol"]
    vol_norm = vol.rolling(NORM_WINDOW, min_periods=NORM_WINDOW).sum().replace(0.0, np.nan)
    signed = df["buy_vol"] - df["sell_vol"]
    for w in OFI_CVD_WINDOWS:
        f[f"ofi_{w}"] = df["ofi"].rolling(w, min_periods=w).sum() / depth_norm
        f[f"cvd_{w}"] = signed.rolling(w, min_periods=w).sum() / vol_norm
    for w in NTR_WINDOWS:
        f[f"ntr_{w}"] = np.log1p(df["n_tr"].rolling(w, min_periods=w).sum())
    logmid = np.log(mid)
    for w in RET_WINDOWS:
        f[f"ret_{w}"] = (logmid - logmid.shift(w)) * 1e4
    r1sq = (logmid.diff() * 1e4) ** 2
    f["rv_60"] = np.sqrt(r1sq.rolling(60, min_periods=60).sum())
    f["rv_300"] = np.sqrt(r1sq.rolling(300, min_periods=300).sum())
    return f.astype("float32")


# ---- labels triple-barrier + PnL ejecutable -------------------------------------
def triple_barrier(logmid: np.ndarray, H: int, b_bps: float):
    n = len(logmid)
    up, dn = np.log1p(b_bps / 1e4), np.log1p(-b_bps / 1e4)
    label = np.zeros(n, np.int8)
    tau = np.full(n, H, np.int32)
    resolved = np.zeros(n, bool)
    for k in range(1, H + 1):
        r = np.full(n, np.nan)
        r[: n - k] = logmid[k:] - logmid[: n - k]
        hu = ~resolved & (r >= up)
        hd = ~resolved & (r <= dn)
        label[hu], label[hd] = 1, -1
        tau[hu | hd] = k
        resolved |= hu | hd
    nan_cum = np.concatenate([[0], np.cumsum(np.isnan(logmid))])
    idx = np.arange(n)
    ok_end = idx + H < n
    valid = np.zeros(n, bool)
    valid[ok_end] = (nan_cum[idx[ok_end] + H + 1] - nan_cum[idx[ok_end]]) == 0
    return label, tau, valid


def executable_pnl(bid: np.ndarray, ask: np.ndarray, tau: np.ndarray, valid: np.ndarray):
    """PnL bruto (bps) de entrar en t (o t+1 con latencia) al quote ejecutable y
    salir en t+tau al quote opuesto. Long: compra ask, vende bid. Short: espejo."""
    n = len(bid)
    idx = np.arange(n)
    out = {}
    for lat in (0, 1):
        e = np.minimum(idx + lat, n - 1)
        x = np.minimum(idx + np.maximum(tau, lat), n - 1)
        long_p = (bid[x] / ask[e] - 1.0) * 1e4
        short_p = (bid[e] - ask[x]) / bid[e] * 1e4
        long_p[~valid] = np.nan
        short_p[~valid] = np.nan
        out[lat] = (long_p.astype("float32"), short_p.astype("float32"))
    return out


# ---- modelos (hiperparámetros fijos) --------------------------------------------
def make_model(name: str):
    if name == "logreg":
        return LogisticRegression(C=1.0, max_iter=300)
    return HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.05, max_leaf_nodes=31,
        min_samples_leaf=200, early_stopping=False, random_state=0,
    )


def fit_predict(name: str, Xtr, ytr, Xte):
    model = make_model(name)
    if name == "logreg":
        sc = StandardScaler().fit(Xtr)
        model.fit(sc.transform(Xtr), ytr)
        proba = model.predict_proba(sc.transform(Xte))
    else:
        model.fit(Xtr, ytr)
        proba = model.predict_proba(Xte)
    cls = list(model.classes_)
    p_up = proba[:, cls.index(1)] if 1 in cls else np.zeros(len(Xte))
    p_dn = proba[:, cls.index(-1)] if -1 in cls else np.zeros(len(Xte))
    return p_up - p_dn, proba, cls


# ---- trading sin solapamiento ---------------------------------------------------
def simulate(s: np.ndarray, theta: float, mask: np.ndarray, tau: np.ndarray,
             pnl_long: np.ndarray, pnl_short: np.ndarray, lat: int):
    cand = np.flatnonzero(mask & (np.abs(s) > theta))
    busy_until = -1
    ts, pnls = [], []
    for t in cand:
        if t <= busy_until:
            continue
        p = pnl_long[t] if s[t] > 0 else pnl_short[t]
        if np.isnan(p):
            continue
        ts.append(t)
        pnls.append(float(p))
        busy_until = t + max(int(tau[t]), lat)
    return np.array(ts, dtype=np.int64), np.array(pnls, dtype=np.float64)


def trade_stats(ts: np.ndarray, gross: np.ndarray, fee: float, t_mid: int) -> dict:
    net = gross - 2.0 * fee
    n = len(net)
    if n < 2:
        return {"n": n, "mean": None, "t": None, "h1": None, "h2": None, "win": None}
    mean, sd = float(net.mean()), float(net.std(ddof=1))
    tstat = mean / (sd / np.sqrt(n)) if sd > 0 else None
    h1 = net[ts < t_mid]
    h2 = net[ts >= t_mid]
    return {
        "n": n, "mean": mean, "t": tstat,
        "h1": float(h1.mean()) if len(h1) else None,
        "h2": float(h2.mean()) if len(h2) else None,
        "win": float((net > 0).mean()),
    }


# ---- main -----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    log("cargando 1s...")
    df, missing = load(Path(args.data))
    log(f"filas={len(df):,} días_faltantes={missing}")
    feats = build_features(df)
    X_all = feats.to_numpy()
    feat_ok = np.isfinite(X_all).all(axis=1)
    bid = df["bid"].to_numpy()
    ask = df["ask"].to_numpy()
    logmid = np.log((bid + ask) / 2.0)
    sec = df.index.to_numpy()

    # bloques: dev semanal (último absorbe el día extra), holdout
    dev_start, hold_start = epoch(WINDOW_START), epoch(HOLDOUT_START)
    dev_end_excl = epoch(DEV_END) + 86_400
    hold_end_excl = epoch(WINDOW_END) + 86_400
    block_edges = list(range(dev_start, dev_end_excl, 7 * 86_400))
    if dev_end_excl - block_edges[-1] < 7 * 86_400:
        block_edges = block_edges[:-1]
    block_edges.append(dev_end_excl)
    blocks = list(zip(block_edges[:-1], block_edges[1:]))
    t_mid_hold = hold_start + (hold_end_excl - hold_start) // 2
    log(f"bloques dev={len(blocks)} | folds walk-forward={len(blocks) - MIN_TRAIN_WEEKS}")

    results: dict = {"missing_days": missing, "horizons": {}}
    for H, b in HORIZONS.items():
        log(f"=== H={H}s barrera ±{b}bps: labels...")
        label, tau, lab_ok = triple_barrier(logmid, H, b)
        pnl = executable_pnl(bid, ask, tau, lab_ok)
        valid = feat_ok & lab_ok
        dist_hold = {int(c): float(((label == c) & valid & (sec >= hold_start)).sum())
                     for c in (-1, 0, 1)}
        hres: dict = {"barrier_bps": b, "label_dist_holdout": dist_hold, "models": {}}

        for mname in ("logreg", "hgb"):
            log(f"  [{mname}] walk-forward...")
            s_oos = np.full(len(sec), np.nan)
            folds = []
            for i in range(MIN_TRAIN_WEEKS, len(blocks)):
                te0, te1 = blocks[i]
                tr_mask = valid & (sec >= dev_start) & (sec < te0 - (H + NORM_WINDOW)) \
                    & ((sec - dev_start) % TRAIN_STRIDE == 0)
                te_mask = valid & (sec >= te0) & (sec < te1)
                s_te, _, _ = fit_predict(mname, X_all[tr_mask], label[tr_mask], X_all[te_mask])
                s_oos[te_mask] = s_te
                yb = label[te_mask]
                nz = yb != 0
                auc = roc_auc_score(yb[nz] == 1, s_te[nz]) if nz.sum() > 100 else None
                folds.append({"test_start": datetime.fromtimestamp(te0, timezone.utc).date().isoformat(),
                              "n_train": int(tr_mask.sum()), "n_test": int(te_mask.sum()),
                              "auc_up_vs_dn": auc})
                log(f"    fold {folds[-1]['test_start']} auc={auc}")
            theta = float(np.nanquantile(np.abs(s_oos), THRESHOLD_QUANTILE))

            log(f"  [{mname}] modelo final + holdout (theta={theta:.4f})...")
            tr_mask = valid & (sec >= dev_start) & (sec < hold_start - (H + NORM_WINDOW)) \
                & ((sec - dev_start) % TRAIN_STRIDE == 0)
            ho_mask = valid & (sec >= hold_start) & (sec < hold_end_excl)
            s_ho, proba_ho, cls = fit_predict(mname, X_all[tr_mask], label[tr_mask], X_all[ho_mask])
            s_full = np.full(len(sec), np.nan)
            s_full[ho_mask] = s_ho
            y_ho = label[ho_mask]
            nz = y_ho != 0
            auc_ho = float(roc_auc_score(y_ho[nz] == 1, s_ho[nz]))
            prior = np.array([(label[tr_mask] == c).mean() for c in cls])
            ll_model = float(log_loss(y_ho, proba_ho, labels=cls))
            ll_prior = float(log_loss(y_ho, np.tile(prior, (len(y_ho), 1)), labels=cls))

            econ = {}
            for lat in (0, 1):
                ts, gross = simulate(s_full, theta, ho_mask, tau, pnl[lat][0], pnl[lat][1], lat)
                econ[f"lat{lat}"] = {k: trade_stats(ts, gross, fee, t_mid_hold)
                                     for k, fee in FEE_SCENARIOS.items()}
            prim = econ["lat0"][PRIMARY_FEE]
            passes = bool(prim["mean"] is not None and prim["mean"] > 0
                          and prim["t"] is not None and prim["t"] >= T_CRIT
                          and prim["n"] >= MIN_TRADES
                          and (prim["h1"] or 0) > 0 and (prim["h2"] or 0) > 0)
            lat1 = econ["lat1"][PRIMARY_FEE]
            passes_lat1 = bool(passes and lat1["mean"] is not None and lat1["mean"] > 0)
            hres["models"][mname] = {
                "folds": folds, "theta": theta, "auc_holdout": auc_ho,
                "logloss_model": ll_model, "logloss_prior": ll_prior,
                "econ": econ, "passes_primary": passes, "passes_with_latency_1s": passes_lat1,
            }
            log(f"  [{mname}] AUC_ho={auc_ho:.4f} | primario n={prim['n']} "
                f"mean={prim['mean']} t={prim['t']} -> {'PASA' if passes else 'NO PASA'}")
        results["horizons"][str(H)] = hres

    any_pass = any(m["passes_primary"] for h in results["horizons"].values()
                   for m in h["models"].values())
    any_pass_lat = any(m["passes_with_latency_1s"] for h in results["horizons"].values()
                       for m in h["models"].values())
    exist_auc = results["horizons"]["30"]["models"]["hgb"]["auc_holdout"]
    results["verdict"] = {
        "existence_pass": bool(exist_auc >= EXISTENCE_AUC),
        "economic_pass": any_pass,
        "economic_pass_with_latency": any_pass_lat,
        "runtime_min": round((time.time() - t_start) / 60, 1),
    }
    (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render(results), encoding="utf-8")
    log(f"LISTO. veredicto={results['verdict']}")
    return 0


def _fmt(v, nd=2):
    return "—" if v is None else f"{v:+.{nd}f}"


def render(r: dict) -> str:
    v = r["verdict"]
    L = ["# H-MS1 — Microestructura L1 BTCUSDT perp: resultado", "",
         "Pre-registro: `research/HIPOTESIS_2026-10-03_microestructura.md`.", "",
         f"- Días faltantes: {r['missing_days'] or 'ninguno'}",
         f"- **Existencia** (AUC +1 vs −1, H=30s, HGB, holdout ≥ {EXISTENCE_AUC}): "
         f"**{'PASA' if v['existence_pass'] else 'NO PASA'}**",
         f"- **Economía** (taker 4 bps/lado, latencia 0, t≥{T_CRIT}, n≥{MIN_TRADES}, ambas mitades +): "
         f"**{'PASA' if v['economic_pass'] else 'NO PASA'}**",
         f"- Con latencia 1 s: **{'PASA' if v['economic_pass_with_latency'] else 'NO PASA'}**",
         f"- Runtime: {v['runtime_min']} min", ""]
    L += ["## Holdout (2023-10-11 → 10-31) — señal", "",
          "| H | modelo | AUC ↑vs↓ | logloss modelo | logloss prior | umbral θ |",
          "|---|---|---|---|---|---|"]
    for H, h in r["horizons"].items():
        for m, d in h["models"].items():
            L.append(f"| {H}s | {m} | {d['auc_holdout']:.4f} | {d['logloss_model']:.4f} | "
                     f"{d['logloss_prior']:.4f} | {d['theta']:.4f} |")
    L += ["", "## Holdout — economía (PnL por trade, bps, sin solapamiento)", "",
          "| H | modelo | lat | n | bruto | maker 2 | **taker 4** | t (taker 4) | mitad 1 | mitad 2 | taker 5 | win% (taker 4) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for H, h in r["horizons"].items():
        for m, d in h["models"].items():
            for lat in ("lat0", "lat1"):
                e = d["econ"][lat]
                p = e[PRIMARY_FEE]
                win = "—" if p["win"] is None else f"{p['win']:.0%}"
                L.append(
                    f"| {H}s | {m} | {lat[-1]}s | {p['n']} | {_fmt(e['bruto']['mean'])} | "
                    f"{_fmt(e['maker_2bps']['mean'])} | **{_fmt(p['mean'])}** | {_fmt(p['t'])} | "
                    f"{_fmt(p['h1'])} | {_fmt(p['h2'])} | {_fmt(e['taker_5bps']['mean'])} | {win} |")
    L += ["", "## Distribución de labels en holdout (segundos)", "",
          "| H | barrera | ↓ | timeout | ↑ |", "|---|---|---|---|---|"]
    for H, h in r["horizons"].items():
        dd = h["label_dist_holdout"]
        tot = sum(dd.values()) or 1
        L.append(f"| {H}s | ±{h['barrier_bps']} bps | {dd[-1]/tot:.0%} | {dd[0]/tot:.0%} | {dd[1]/tot:.0%} |")
    L += ["", "## Walk-forward en dev (diagnóstico)", "",
          "| H | modelo | fold (inicio test) | n train | n test | AUC ↑vs↓ |", "|---|---|---|---|---|---|"]
    for H, h in r["horizons"].items():
        for m, d in h["models"].items():
            for f in d["folds"]:
                auc = "—" if f["auc_up_vs_dn"] is None else f"{f['auc_up_vs_dn']:.4f}"
                L.append(f"| {H}s | {m} | {f['test_start']} | {f['n_train']:,} | {f['n_test']:,} | {auc} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
