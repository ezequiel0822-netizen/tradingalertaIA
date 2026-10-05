"""H-NN1 — red neuronal vs boosting en microestructura L1 de BTCUSDT perp.

Implementa EXACTAMENTE research/HIPOTESIS_2026-10-05_redes_neuronales.md (commit
8853632, ANTES de bajar datos). Reusa SIN CAMBIOS las funciones de H-MS1
(`microstructure_study`: features, triple barrera, PnL ejecutable, simulación,
estadísticas, HGB) y la agregación a 1 s de `microstructure_backfill`, para que la
comparación sea justa por construcción. Research-only: no importa `app`.

  python scripts/nn_microstructure_experiment.py download --start 2023-05-17 --end 2023-07-31 --out <dir>
  python scripts/nn_microstructure_experiment.py study --train <dir H-MS1> --test <dir> --report <dir>
Verificación con datos sintéticos: python scripts/nn_selftest.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import microstructure_backfill as MB  # noqa: E402
import microstructure_study as MS  # noqa: E402

# ---- parámetros CONGELADOS por el pre-registro (8853632) ---------------------------
PREREG = "research/HIPOTESIS_2026-10-05_redes_neuronales.md @ 8853632"
TRAIN_START, TRAIN_END = date(2023, 8, 1), date(2023, 10, 31)
CALIB_SPLIT = date(2023, 10, 18)
TEST_START, TEST_END = date(2023, 5, 17), date(2023, 7, 31)
CAUSAL_START, CAUSAL_END = date(2023, 11, 1), date(2023, 11, 10)
SEQ_SERIES = ("obi", "micro_dev_bps", "ofi_1", "cvd_1", "ret_1")
SEQ_LAGS = 30
MODELS = ("hgb", "mlp23", "mlpseq")
MLP_LAYERS = {"mlp23": (64, 32), "mlpseq": (128, 64)}
MLP_EPOCHS = 15
MIN_DAUC, T_CRIT_A, T_CRIT_B = 0.010, 2.50, 2.64
MAX_MISSING_FRAC = 0.10
PRIMARY_H = 30
CHUNK = 400_000


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


# ================================ DESCARGA (con checksum oficial) ======================
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_checksum(text: str | None) -> str | None:
    """'<sha256>  archivo.zip' -> sha256 (o None)."""
    if not text:
        return None
    tok = text.strip().split()
    return tok[0].lower() if tok and len(tok[0]) == 64 else None


def _get_text(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers=MB.UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode()
    except Exception:
        return None


def process_day_verified(day: date, out_dir: Path, tmp_dir: Path) -> dict:
    d = day.isoformat()
    row: dict = {"day": d}
    target = out_dir / f"{d}.parquet"
    if target.exists():
        row["status"] = "ya existía"
        row["parquet_sha256"] = sha256_file(target)
        return row
    day_start = epoch(day)
    zips = {}
    try:
        for kind in ("bookTicker", "aggTrades"):
            url = f"{MB.BASE}/{kind}/{MB.SYMBOL}/{MB.SYMBOL}-{kind}-{d}.zip"
            path = tmp_dir / f"{MB.SYMBOL}-{kind}-{d}.zip"
            try:
                MB._download(url, path)
            except Exception as exc:
                row["status"] = f"falta {kind}: {type(exc).__name__}"
                return row
            official = parse_checksum(_get_text(url + ".CHECKSUM"))
            local = sha256_file(path)
            row[f"{kind}_sha256"], row[f"{kind}_official"] = local, official or "UNAVAILABLE"
            if official is None or official != local:
                row["status"] = f"checksum {kind} NO coincide -> día excluido"
                return row
            zips[kind] = path
        book = MB._book_per_second(zips["bookTicker"], day_start)
        agg = MB._agg_per_second(zips["aggTrades"], day_start)
        out = book.join(agg, how="left").reset_index()
        tmpf = target.with_suffix(".tmp")
        out.to_parquet(tmpf, index=False)
        tmpf.replace(target)
        row.update(status="ok", parquet_sha256=sha256_file(target),
                   updates=int(out["n_upd"].sum()), trades=int(out["n_tr"].sum()))
        return row
    finally:
        for p in list(zips.values()) + [tmp_dir / f"{MB.SYMBOL}-{k}-{d}.zip"
                                        for k in ("bookTicker", "aggTrades")]:
            p.unlink(missing_ok=True)


def download(start: date, end: date, out: Path, workers: int = 3) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_zips"
    tmp.mkdir(exist_ok=True)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(process_day_verified, d, out, tmp): d for d in days}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception as exc:
                r = {"day": futs[f].isoformat(), "status": f"FALLO {type(exc).__name__}"}
            rows.append(r)
            log(f"{r['day']} {r['status']}")
    man = pd.DataFrame(rows).sort_values("day")
    man_path = out / f"manifest_{start}_{end}.csv"
    man.to_csv(man_path, index=False)
    ok = int((man["status"].isin(["ok", "ya existía"])).sum())
    log(f"manifest {man_path.name}: {ok}/{len(days)} días OK; sha256 {sha256_file(man_path)}")


# ================================ DATOS ================================================
@dataclass
class Window:
    name: str
    sec: np.ndarray
    X: np.ndarray          # (n, 23) float32, features de H-MS1
    Xs: np.ndarray         # (n, 5) float32, las 5 series de la historia
    feat_ok: np.ndarray
    bid: np.ndarray
    ask: np.ndarray
    logmid: np.ndarray
    missing: list
    n_days: int


def window_from_df(name: str, df: pd.DataFrame, missing: list, n_days: int) -> Window:
    feats = MS.build_features(df)
    X = feats.to_numpy()
    bid, ask = df["bid"].to_numpy(), df["ask"].to_numpy()
    return Window(name=name, sec=df.index.to_numpy(), X=X,
                  Xs=np.ascontiguousarray(X[:, seq_index()]),
                  feat_ok=np.isfinite(X).all(axis=1), bid=bid, ask=ask,
                  logmid=np.log((bid + ask) / 2.0), missing=missing, n_days=n_days)


def load_window(name: str, data_dir: Path, d0: date, d1: date) -> Window:
    """Como MS.load pero con fechas propias: cada ventana se carga SOLA."""
    frames, missing, d = [], [], d0
    while d <= d1:
        f = data_dir / f"{d.isoformat()}.parquet"
        if f.exists():
            frames.append(pd.read_parquet(f))
        else:
            missing.append(d.isoformat())
        d += timedelta(days=1)
    df = pd.concat(frames, ignore_index=True).sort_values("sec")
    grid = pd.RangeIndex(epoch(d0), epoch(d1) + 86_400)
    df = df.set_index("sec").reindex(grid)
    df.index.name = "sec"
    return window_from_df(name, df, missing, (d1 - d0).days + 1)


FEATURE_NAMES = None  # se llena al primer uso (orden de MS.build_features)


def seq_index() -> list[int]:
    global FEATURE_NAMES
    if FEATURE_NAMES is None:
        probe = pd.DataFrame({c: [1.0] * 400 for c in
                              ("bid", "ask", "bq", "aq", "ofi", "buy_vol", "sell_vol", "n_tr")})
        FEATURE_NAMES = list(MS.build_features(probe).columns)
    return [FEATURE_NAMES.index(s) for s in SEQ_SERIES]


def seq_ok_mask(X: np.ndarray, Xs: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """True si la fila tiene features válidas en t y 30 s de historia sin NaN
    (filas r-30 .. r-1), sin construir la matriz (suma acumulada de inválidos)."""
    rows = np.asarray(rows, dtype=np.int64)
    bad = np.concatenate([[0], np.cumsum(~np.isfinite(Xs).all(axis=1))])
    ok = rows >= SEQ_LAGS
    safe = np.where(ok, rows, SEQ_LAGS)
    ok &= (bad[safe] - bad[safe - SEQ_LAGS]) == 0
    ok &= np.isfinite(X[safe]).all(axis=1)
    return ok


def seq_matrix(X: np.ndarray, Xs: np.ndarray, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """23 features en t + historia de 30 s (lags 1..30) de las 5 series -> (m, 173).
    Solo pasado estricto (lag >= 1). ok=False si falta historia o hay NaN."""
    rows = np.asarray(rows, dtype=np.int64)
    ok = seq_ok_mask(X, Xs, rows)
    safe = np.where(rows >= SEQ_LAGS, rows, SEQ_LAGS)
    lag_rows = safe[:, None] - np.arange(1, SEQ_LAGS + 1)[None, :]
    lagged = Xs[lag_rows].reshape(len(rows), SEQ_LAGS * Xs.shape[1])
    return np.concatenate([X[safe], lagged], axis=1).astype(np.float32), ok


def inputs(kind: str, W: Window, rows: np.ndarray) -> np.ndarray:
    return seq_matrix(W.X, W.Xs, rows)[0] if kind == "mlpseq" else W.X[rows]


# ================================ MODELOS ==============================================
def make_mlp(kind: str) -> MLPClassifier:
    return MLPClassifier(hidden_layer_sizes=MLP_LAYERS[kind], activation="relu", solver="adam",
                         alpha=1e-4, batch_size=2048, learning_rate_init=1e-3,
                         max_iter=MLP_EPOCHS, n_iter_no_change=MLP_EPOCHS + 1, shuffle=True,
                         random_state=0, early_stopping=False)


def fit(kind: str, Xtr: np.ndarray, ytr: np.ndarray):
    if kind == "hgb":
        m = MS.make_model("hgb")
        m.fit(Xtr, ytr)
        return None, m
    sc = StandardScaler().fit(Xtr)
    m = make_mlp(kind)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)   # épocas fijas a propósito
        m.fit(sc.transform(Xtr), ytr)
    return sc, m


def predict_s(fitted, kind: str, W: Window, rows: np.ndarray) -> np.ndarray:
    sc, m = fitted
    cls = list(m.classes_)
    out = np.empty(len(rows), dtype=np.float64)
    for a in range(0, len(rows), CHUNK):
        r = rows[a:a + CHUNK]
        Xc = inputs(kind, W, r)
        p = m.predict_proba(sc.transform(Xc) if sc is not None else Xc)
        up = p[:, cls.index(1)] if 1 in cls else 0.0
        dn = p[:, cls.index(-1)] if -1 in cls else 0.0
        out[a:a + CHUNK] = up - dn
    return out


# ================================ MÉTRICAS =============================================
def daily_auc(sec: np.ndarray, y: np.ndarray, s: np.ndarray, start_epoch: int) -> dict[int, float]:
    day = (sec - start_epoch) // 86_400
    out = {}
    for d in np.unique(day):
        m = (day == d) & (y != 0)
        if m.sum() >= 100 and len(np.unique(y[m])) == 2:
            out[int(d)] = float(roc_auc_score(y[m] == 1, s[m]))
    return out


def paired_days(a: dict[int, float], b: dict[int, float]) -> dict:
    days = sorted(set(a) & set(b))
    d = np.array([a[k] - b[k] for k in days])
    if len(d) < 3:
        return {"days": len(d), "mean_delta": None, "t": None}
    sd = d.std(ddof=1)
    return {"days": len(d), "mean_delta": float(d.mean()),
            "t": float(d.mean() / (sd / np.sqrt(len(d)))) if sd > 0 else None}


def economics(W: Window, s_rows: np.ndarray, rows: np.ndarray, theta: float,
              tau: np.ndarray, lab_ok: np.ndarray) -> dict:
    s_full = np.full(len(W.sec), np.nan)
    s_full[rows] = s_rows
    mask = np.zeros(len(W.sec), bool)
    mask[rows] = True
    pnl = MS.executable_pnl(W.bid, W.ask, tau, lab_ok)
    t_mid = int(np.searchsorted(W.sec, W.sec[0] + (W.sec[-1] + 1 - W.sec[0]) // 2))
    res = {}
    for lat in (0, 1):
        ts, gross = MS.simulate(s_full, theta, mask, tau, pnl[lat][0], pnl[lat][1], lat)
        res[f"lat{lat}"] = {k: MS.trade_stats(ts, gross, fee, t_mid)
                            for k, fee in MS.FEE_SCENARIOS.items()}
    return res


def econ_pass(e: dict) -> bool:
    p = e["lat0"][MS.PRIMARY_FEE]
    return bool(p["mean"] is not None and p["mean"] > 0 and p["t"] is not None
                and p["t"] >= T_CRIT_B and p["n"] >= MS.MIN_TRADES
                and (p["h1"] or 0) > 0 and (p["h2"] or 0) > 0)


# ================================ UN HORIZONTE =========================================
def run_horizon(H: int, b: float, train: Window, calib_split: int, test: Window,
                causal: Window | None, models=MODELS, train_stride: int = MS.TRAIN_STRIDE) -> dict:
    lab = {}
    for W in (train, test) + ((causal,) if causal is not None else ()):
        y, tau, ok = MS.triple_barrier(W.logmid, H, b)
        base = W.feat_ok & ok
        all_rows = np.flatnonzero(base)
        sok = seq_ok_mask(W.X, W.Xs, all_rows)
        lab[W.name] = (y, tau, ok, all_rows[sok])           # filas comunes a los 3 modelos
    y_tr, _, _, rows_tr_all = lab[train.name]
    stride = rows_tr_all[(train.sec[rows_tr_all] - train.sec[0]) % train_stride == 0]
    cal_tr = stride[train.sec[stride] < calib_split - (H + MS.NORM_WINDOW)]
    cal_pr = rows_tr_all[train.sec[rows_tr_all] >= calib_split]
    out: dict = {"barrier_bps": b, "n_train": int(len(stride)), "models": {}}
    s_test, s_causal = {}, {}
    for kind in models:
        t0 = time.time()
        fc = fit(kind, inputs(kind, train, cal_tr), y_tr[cal_tr])
        theta = float(np.quantile(np.abs(predict_s(fc, kind, train, cal_pr)), MS.THRESHOLD_QUANTILE))
        ff = fit(kind, inputs(kind, train, stride), y_tr[stride])
        y_te, tau_te, ok_te, rows_te = lab[test.name]
        s_te = predict_s(ff, kind, test, rows_te)
        s_test[kind] = s_te
        nz = y_te[rows_te] != 0
        res = {"theta": theta,
               "auc_test": float(roc_auc_score(y_te[rows_te][nz] == 1, s_te[nz])),
               "daily_auc": daily_auc(test.sec[rows_te], y_te[rows_te], s_te, int(test.sec[0])),
               "econ_test": economics(test, s_te, rows_te, theta, tau_te, ok_te)}
        if causal is not None:
            y_c, tau_c, ok_c, rows_c = lab[causal.name]
            s_c = predict_s(ff, kind, causal, rows_c)
            s_causal[kind] = s_c
            nzc = y_c[rows_c] != 0
            res["auc_causal"] = float(roc_auc_score(y_c[rows_c][nzc] == 1, s_c[nzc]))
            res["econ_causal"] = economics(causal, s_c, rows_c, theta, tau_c, ok_c)
        res["econ_pass_test"] = econ_pass(res["econ_test"])
        res["minutes"] = round((time.time() - t0) / 60, 1)
        out["models"][kind] = res
        p = res["econ_test"]["lat0"][MS.PRIMARY_FEE]
        log(f"  H={H} [{kind}] AUC test {res['auc_test']:.4f} | taker n={p['n']} "
            f"neto {p['mean']} t {p['t']} ({res['minutes']} min)")
    if "hgb" in out["models"]:
        for kind in models:
            if kind != "hgb":
                out["models"][kind]["vs_hgb_daily"] = paired_days(
                    out["models"][kind]["daily_auc"], out["models"]["hgb"]["daily_auc"])
    return out


def verdict(results: dict) -> dict:
    a = {}
    for kind in ("mlp23", "mlpseq"):
        v = results["horizons"][str(PRIMARY_H)]["models"][kind]["vs_hgb_daily"]
        a[kind] = bool(v["mean_delta"] is not None and v["mean_delta"] >= MIN_DAUC
                       and v["t"] is not None and v["t"] >= T_CRIT_A)
    b = {}
    for H, hres in results["horizons"].items():
        for kind in ("mlp23", "mlpseq"):
            m = hres["models"][kind]
            ok = m["econ_pass_test"]
            lat1 = m["econ_test"]["lat1"][MS.PRIMARY_FEE]["mean"]
            caus = m.get("econ_causal", {}).get("lat0", {}).get(MS.PRIMARY_FEE, {}).get("mean")
            b[f"{kind}_H{H}"] = bool(ok and lat1 is not None and lat1 > 0
                                     and caus is not None and caus > 0)
    return {"A_red_modela_mejor": a, "B_economia": b,
            "integrar_redes": any(b.values())}


def study(train_dir: Path, test_dir: Path, report: Path) -> dict:
    report.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log("cargando ventanas por separado...")
    train = load_window("train", train_dir, TRAIN_START, TRAIN_END)
    test = load_window("test", test_dir, TEST_START, TEST_END)
    causal = load_window("causal", test_dir, CAUSAL_START, CAUSAL_END)
    miss = len(test.missing) / test.n_days
    log(f"faltan: train {train.missing} | test {test.missing} | causal {causal.missing}")
    results: dict = {"prereg": PREREG, "missing": {"train": train.missing, "test": test.missing,
                                                   "causal": causal.missing},
                     "test_valid": miss <= MAX_MISSING_FRAC, "horizons": {}}
    for H, b in MS.HORIZONS.items():
        log(f"=== H={H}s ±{b}bps")
        results["horizons"][str(H)] = run_horizon(H, b, train, epoch(CALIB_SPLIT), test, causal)
    results["verdict"] = verdict(results) if results["test_valid"] else {"invalid": True}
    results["runtime_min"] = round((time.time() - t0) / 60, 1)
    (report / "nn_result.json").write_text(json.dumps(results, indent=2, default=str),
                                           encoding="utf-8")
    log(f"LISTO ({results['runtime_min']} min). veredicto={results['verdict']}")
    return results


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="H-NN1 (pre-registro 8853632)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("download")
    a.add_argument("--start", required=True)
    a.add_argument("--end", required=True)
    a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("study")
    b.add_argument("--train", type=Path, required=True)
    b.add_argument("--test", type=Path, required=True)
    b.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "download":
        download(date.fromisoformat(args.start), date.fromisoformat(args.end), args.out)
    else:
        study(args.train, args.test, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
