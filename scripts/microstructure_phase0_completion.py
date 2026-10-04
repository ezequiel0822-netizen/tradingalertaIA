"""Completa la Fase 0 de H-MS1 según la spec v5.0 — diagnósticos, NO cambian el gate.

Implementa el addendum 2026-10-04 de research/HIPOTESIS_2026-10-03_microestructura.md
(commiteado antes de correr): manifest con checksums, verificación de claims previos,
canary de leakage, OFI contemporáneo vs predictivo, calibración separada del holdout,
break-even de acierto. Reusa las funciones de microstructure_study (mismas features,
labels y simulador que el estudio pre-registrado).

Uso:
  python scripts/microstructure_phase0_completion.py \
      --data C:/Users/LENOVO/tradingalertaIA/trading_data/binance_micro/BTCUSDT_1s \
      --out  C:/Users/LENOVO/tradingalertaIA/exports/microstructure_study
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import microstructure_study as ms  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SRC = "https://data.binance.vision/data/futures/um/daily"
UA = {"User-Agent": "Mozilla/5.0 (research)"}
CAL_DAYS = 14
CANARY_N = 200
CANARY_HISTORY = 1200
TAKER_ROUNDTRIP_BPS = 8.0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def longest_true_run(mask: np.ndarray) -> int:
    if not mask.any():
        return 0
    m = np.concatenate([[0], mask.astype(np.int8), [0]])
    d = np.diff(m)
    return int((np.flatnonzero(d == -1) - np.flatnonzero(d == 1)).max())


def official_checksum(kind: str, day: str) -> str:
    url = f"{SRC}/{kind}/BTCUSDT/BTCUSDT-{kind}-{day}.zip.CHECKSUM"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode().split()[0]
    except Exception as exc:  # se registra, no se inventa
        return f"UNAVAILABLE ({type(exc).__name__})"


# ---- 1. manifest -----------------------------------------------------------------
def build_manifest(data_dir: Path) -> pd.DataFrame:
    days = []
    d = ms.WINDOW_START
    while d <= ms.WINDOW_END:
        days.append(d.isoformat())
        d += timedelta(days=1)
    with ThreadPoolExecutor(max_workers=8) as ex:
        book_ck = list(ex.map(lambda x: official_checksum("bookTicker", x), days))
        agg_ck = list(ex.map(lambda x: official_checksum("aggTrades", x), days))
    rows = []
    for day, bck, ack in zip(days, book_ck, agg_ck):
        f = data_dir / f"{day}.parquet"
        df = pd.read_parquet(f)
        sec = df["sec"].to_numpy()
        nup = df["n_upd"].to_numpy()
        mid = (df["bid"] + df["ask"]) / 2
        rows.append({
            "date": day, "rows": len(df), "first_sec": int(sec[0]), "last_sec": int(sec[-1]),
            "contiguous": bool((np.diff(sec) == 1).all()),
            "book_updates": int(nup.sum()), "trades": int(df["n_tr"].sum()),
            "seconds_without_book_update": int((nup == 0).sum()),
            "max_gap_seconds": longest_true_run(nup == 0),
            "seconds_without_state": int(df["bid"].isna().sum()),
            "spread_bps_median": round(float(((df["ask"] - df["bid"]) / mid * 1e4).median()), 4),
            "parquet_sha256": sha256_file(f),
            "source_bookTicker_zip_sha256": bck, "source_aggTrades_zip_sha256": ack,
        })
    return pd.DataFrame(rows)


# ---- 2. claims ---------------------------------------------------------------------
def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def verify_commits(commits: list[str]) -> list[dict]:
    out = []
    for c in commits:
        kind = git("cat-file", "-t", c)
        on_origin = subprocess.run(
            ["git", "-C", str(REPO), "merge-base", "--is-ancestor", c, "origin/main"],
            capture_output=True).returncode == 0 if kind else False
        out.append({"commit": c, "exists_locally": kind == "commit",
                    "full_hash": git("rev-parse", c) if kind else None,
                    "on_origin_main": on_origin})
    return out


# ---- métricas de calibración -------------------------------------------------------
def brier(proba: np.ndarray, y: np.ndarray, cls: list) -> float:
    onehot = np.stack([(y == c).astype(float) for c in cls], axis=1)
    return float(((proba - onehot) ** 2).sum(axis=1).mean())


def logloss(proba: np.ndarray, y: np.ndarray, cls: list) -> float:
    idx = np.array([cls.index(v) for v in y])
    p = np.clip(proba[np.arange(len(y)), idx], 1e-12, 1.0)
    return float(-np.log(p).mean())


def ece_top(proba: np.ndarray, y: np.ndarray, cls: list, bins: int = 10) -> float:
    conf = proba.max(axis=1)
    pred = np.array(cls)[proba.argmax(axis=1)]
    correct = (pred == y).astype(float)
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(total)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    data_dir, out_dir = Path(args.data), Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {}

    ms.log("1. manifest + checksums oficiales...")
    man = build_manifest(data_dir)
    man_path = REPO / "research" / "H-MS1_data_manifest.csv"
    man.to_csv(man_path, index=False, lineterminator="\n")
    res["manifest"] = {
        "file": str(man_path.relative_to(REPO)), "data_manifest_hash": sha256_file(man_path),
        "days": len(man), "all_86400_rows": bool((man["rows"] == 86_400).all()),
        "all_contiguous": bool(man["contiguous"].all()),
        "seconds_without_state": int(man["seconds_without_state"].sum()),
        "max_gap_seconds": int(man["max_gap_seconds"].max()),
        "official_checksums_found": int((~man["source_bookTicker_zip_sha256"].str.startswith("UNAVAILABLE")).sum()
                                        + (~man["source_aggTrades_zip_sha256"].str.startswith("UNAVAILABLE")).sum()),
        "spread_bps_median_overall": float(man["spread_bps_median"].median()),
    }
    aug1 = man.loc[man["date"] == "2023-08-01"].iloc[0]
    res["claims"] = {
        "commits": verify_commits(["270888b", "2512199", "38b25e1", "8d20f56", "ac35840"]),
        "aug01_book_updates": int(aug1["book_updates"]), "aug01_trades": int(aug1["trades"]),
    }

    ms.log("cargando 1s + features...")
    df, _ = ms.load(data_dir)
    feats = ms.build_features(df)
    X_all = feats.to_numpy()
    feat_ok = np.isfinite(X_all).all(axis=1)
    bid, ask = df["bid"].to_numpy(), df["ask"].to_numpy()
    logmid = np.log((bid + ask) / 2.0)
    sec = df.index.to_numpy()
    dev_start, hold_start = ms.epoch(ms.WINDOW_START), ms.epoch(ms.HOLDOUT_START)
    dev_end_excl = ms.epoch(ms.DEV_END) + 86_400
    hold_idx = np.flatnonzero(sec >= hold_start)

    ms.log("3. canary de leakage (truncamiento)...")
    rng = np.random.default_rng(0)
    picks = rng.choice(hold_idx[hold_idx >= CANARY_HISTORY], CANARY_N, replace=False)
    max_diff = 0.0
    for p in picks:
        trunc = ms.build_features(df.iloc[p - CANARY_HISTORY: p + 1]).iloc[-1].to_numpy()
        full = X_all[p]
        both = np.isfinite(trunc) & np.isfinite(full)
        assert (np.isfinite(trunc) == np.isfinite(full)).all(), f"NaN distinto en {p}"
        max_diff = max(max_diff, float(np.abs(trunc[both] - full[both]).max(initial=0.0)))
    res["leakage"] = {"canary_points": CANARY_N, "max_abs_diff": max_diff,
                      "canary_pass": bool(max_diff < 1e-3)}

    ms.log("4. OFI contemporáneo vs predictivo...")
    res["ofi_contemp_vs_pred"] = []
    for w in ms.OFI_CVD_WINDOWS:
        x = feats[f"ofi_{w}"].to_numpy(dtype=float)
        y_c = feats[f"ret_{w}"].to_numpy(dtype=float)
        y_p = np.full(len(sec), np.nan)
        y_p[: len(sec) - w] = (logmid[w:] - logmid[: len(sec) - w]) * 1e4
        idx = hold_idx[::w]
        idx = idx[idx + w < len(sec)]
        row = {"window_s": w}
        for name, y in (("contemporaneo", y_c), ("predictivo", y_p)):
            m = np.isfinite(x[idx]) & np.isfinite(y[idx])
            r = np.corrcoef(x[idx][m], y[idx][m])[0, 1]
            row[f"r2_{name}"] = float(r * r)
            row[f"n_{name}"] = int(m.sum())
        res["ofi_contemp_vs_pred"].append(row)

    ms.log("5-6. calibración + reproducción + break-even...")
    prior = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    res["calibration"], res["reproduction"], res["break_even"] = [], [], []
    cal_start = dev_end_excl - CAL_DAYS * 86_400
    for H, b in ms.HORIZONS.items():
        label, tau, lab_ok = ms.triple_barrier(logmid, H, b)
        assert int(tau[lab_ok].min()) >= 1, "label empieza antes del fin de la feature"
        valid = feat_ok & lab_ok
        stride = (sec - dev_start) % ms.TRAIN_STRIDE == 0
        ho = valid & (sec >= hold_start)

        # calibración: train = dev sin sus últimos 14 días; calibra en esos 14 días
        tr = valid & (sec >= dev_start) & (sec < cal_start - (H + ms.NORM_WINDOW)) & stride
        cb = valid & (sec >= cal_start) & (sec < hold_start - H)
        model = ms.make_model("hgb").fit(X_all[tr], label[tr])
        cls = list(model.classes_)
        p_cb, p_ho = model.predict_proba(X_all[cb]), model.predict_proba(X_all[ho])
        p_cal = np.zeros_like(p_ho)
        for k, c in enumerate(cls):
            iso = IsotonicRegression(out_of_bounds="clip").fit(p_cb[:, k], (label[cb] == c).astype(float))
            p_cal[:, k] = iso.predict(p_ho[:, k])
        s = p_cal.sum(axis=1, keepdims=True)
        p_cal = np.where(s > 0, p_cal / np.where(s > 0, s, 1), 1.0 / len(cls))
        y_ho = label[ho]
        res["calibration"].append({
            "H": H, "n_cal": int(cb.sum()), "n_holdout": int(ho.sum()),
            "brier_raw": brier(p_ho, y_ho, cls), "brier_cal": brier(p_cal, y_ho, cls),
            "logloss_raw": logloss(p_ho, y_ho, cls), "logloss_cal": logloss(p_cal, y_ho, cls),
            "ece_raw": ece_top(p_ho, y_ho, cls), "ece_cal": ece_top(p_cal, y_ho, cls),
        })

        # reproducción del modelo final pre-registrado + break-even sobre sus trades
        trf = valid & (sec >= dev_start) & (sec < hold_start - (H + ms.NORM_WINDOW)) & stride
        s_ho, _, _ = ms.fit_predict("hgb", X_all[trf], label[trf], X_all[ho])
        nz = y_ho != 0
        auc = float(roc_auc_score(y_ho[nz] == 1, s_ho[nz]))
        prev = prior["horizons"][str(H)]["models"]["hgb"]
        theta = prev["theta"]
        s_full = np.full(len(sec), np.nan)
        s_full[ho] = s_ho
        pnl = ms.executable_pnl(bid, ask, tau, lab_ok)
        ts, gross = ms.simulate(s_full, theta, ho, tau, pnl[0][0], pnl[0][1], 0)
        res["reproduction"].append({
            "H": H, "auc_now": auc, "auc_preregistered_run": prev["auc_holdout"],
            "gross_mean_now": float(gross.mean()), "gross_mean_run": prev["econ"]["lat0"]["bruto"]["mean"],
            "n_now": int(len(ts)), "n_run": prev["econ"]["lat0"]["bruto"]["n"],
        })
        direction = np.sign(s_full[ts])
        outcome = label[ts] * direction
        wins, losses, tos = int((outcome > 0).sum()), int((outcome < 0).sum()), int((outcome == 0).sum())
        decided = wins + losses
        res["break_even"].append({
            "H": H, "barrier_bps": b, "trades": int(len(ts)),
            "first_touch_win": wins, "first_touch_loss": losses, "timeout": tos,
            "hit_rate_decided": wins / decided if decided else None,
            "hit_rate_needed": (1 + TAKER_ROUNDTRIP_BPS / b) / 2,
        })
        ms.log(f"   H={H}s listo")

    res["funding_note"] = "holding <= 300 s; funding cada 8 h -> ~0.01% x 300/28800 ~ 0.001 bps, despreciable"
    (out_dir / "phase0_completion.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    ms.log("LISTO")
    print(json.dumps({k: v for k, v in res.items() if k != "manifest"} | {"manifest": res["manifest"]},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
