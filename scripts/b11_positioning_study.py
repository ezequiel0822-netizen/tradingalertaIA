"""B11 — posicionamiento en perps de Binance: H-OI1, H-TT1, H-TK1 (k = 3).

Implementa EXACTAMENTE research/HIPOTESIS_2026-10-05_B11_posicionamiento.md (commit
e80f809, ANTES de bajar datos). Research-only: no importa `app`, no toca el bot.

  python scripts/b11_positioning_study.py download --out <dir>
  python scripts/b11_positioning_study.py study --data <dir> --report <dir>
Verificación con datos sintéticos: python scripts/b11_selftest.py

Detalles de implementación (decididos ANTES de ver datos):
  a) Serie diaria con nocional constante dentro del trade (posición × retorno del día),
     como dice el §4; la t por trade de H-POS1 (retorno simple del trade) se reporta aparte.
  b) Costo de entrada el día de entrada y de salida el último día del trade.
  c) Tasa libre diaria = EFFR as-of / 360 (ACT/360), igual que B4b.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b4b_study as B  # noqa: E402  (nw_t, effr_download, norm_funding, verificados)

# ---- parámetros CONGELADOS por el pre-registro (e80f809) ---------------------------
PREREG = "research/HIPOTESIS_2026-10-05_B11_posicionamiento.md @ e80f809"
W0 = pd.Timestamp("2021-12-01", tz="UTC")
W1 = pd.Timestamp("2024-10-01", tz="UTC")
TT1B_W0 = pd.Timestamp("2022-12-15", tz="UTC")     # adenda 1c (fuente sin top traders antes)
METRICS_FROM = {"BTCUSDT": pd.Timestamp("2020-09-01", tz="UTC"),
                "ETHUSDT": pd.Timestamp("2021-12-01", tz="UTC")}
METRICS_TO = pd.Timestamp("2024-09-30", tz="UTC")
KLINES_FROM, FUNDING_FROM = "2020-06", "2021-11"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
Z, HOLD_D, LOOKBACK_D, MIN_VALID = 1.5, 3, 90, 60
FEE, SLIP = 0.0005, 0.0002
MIN_RECORDS, MIN_COVERAGE, MIN_N = 144, 0.90, 30
T_CRIT, NW_LAGS = 2.50, 5
HYPS = ("H-OI1", "H-TT1", "H-TK1")
DAY = pd.Timedelta(days=1)

ARCHIVE = "https://data.binance.vision/data/futures/um"
UA = {"User-Agent": "Mozilla/5.0 (research)"}
_local = threading.local()


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ================================ DESCARGA ==========================================
def _get(url: str) -> bytes | None:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(UA)
    for attempt in range(5):
        try:
            r = _local.s.get(url, timeout=90)
            if r.status_code == 404:
                return None
            if r.ok:
                return r.content
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET {url} falló")


def fetch(path: str, name: str) -> tuple[pd.DataFrame | None, dict | None]:
    url = f"{ARCHIVE}/{path}/{name}.zip"
    raw = _get(url)
    if raw is None:
        return None, None
    ck = _get(url + ".CHECKSUM")
    official = ck.decode().split()[0] if ck else "UNAVAILABLE"
    sha = hashlib.sha256(raw).hexdigest()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    first = text.split("\n", 1)[0].split(",")[0].strip()
    header = 0 if not first.lstrip("-").replace(".", "").isdigit() else None
    df = pd.read_csv(io.StringIO(text), header=header)
    entry = {"file": f"{name}.zip", "bytes": len(raw), "rows": len(df), "sha256": sha,
             "official_sha256": official, "checksum_ok": sha == official}
    return (df if sha == official else None), entry


def norm_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Por NOMBRE de columna; create_time texto UTC o ms."""
    ct = df["create_time"]
    if pd.api.types.is_numeric_dtype(ct):
        ts = ct.astype("int64")
        ts = ts.where(ts < 10**14, ts // 1000)
    else:
        ts = pd.DatetimeIndex(pd.to_datetime(ct, utc=True)).as_unit("ms").asi8
    out = pd.DataFrame({"ts_ms": np.asarray(ts, dtype="int64")})
    for src, dst in (("sum_open_interest", "oi"), ("sum_toptrader_long_short_ratio", "tt")):
        out[dst] = pd.to_numeric(df[src], errors="coerce").to_numpy() if src in df.columns else np.nan
    return out


def norm_klines_1d(df: pd.DataFrame) -> pd.DataFrame:
    k = df.iloc[:, [0, 4, 5, 9]].copy()
    k.columns = ["open_time_ms", "close", "volume", "taker_buy_volume"]
    k = k.apply(pd.to_numeric, errors="coerce")
    if k.isna().any().any():
        raise ValueError("klines 1d con NaN tras normalizar")
    ot = k["open_time_ms"].astype("int64")
    k["open_time_ms"] = ot.where(ot < 10**14, ot // 1000)
    return k


def download(out: Path, workers: int = 8) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for sym in SYMBOLS:
        days = pd.date_range(METRICS_FROM[sym], METRICS_TO, freq="D")
        with ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(lambda d: fetch(f"daily/metrics/{sym}", f"{sym}-metrics-{d:%Y-%m-%d}"), days))
        parts, missing = [], []
        for d, (df, e) in zip(days, res):
            if e is not None:
                manifest.append({**e, "symbol": sym, "kind": "metrics"})
            if df is None:
                missing.append(f"{d:%Y-%m-%d}")
            else:
                parts.append(norm_metrics(df))
        m = pd.concat(parts, ignore_index=True).drop_duplicates("ts_ms").sort_values("ts_ms")
        m.to_csv(out / f"metrics_{sym}.csv", index=False)
        log(f"metrics {sym}: {len(m):,} registros, {len(parts)} días, faltan/descartados {len(missing)}: {missing[:5]}")

        frames = []
        for mth in B.months(pd.Timestamp(f"{KLINES_FROM}-01", tz="UTC"), METRICS_TO):
            df, e = fetch(f"monthly/klines/{sym}/1d", f"{sym}-1d-{mth}")
            if e is not None:
                manifest.append({**e, "symbol": sym, "kind": "klines_1d"})
            if df is None:
                log(f"  falta/descartado klines 1d {sym} {mth}")
                continue
            frames.append(norm_klines_1d(df))
        k = pd.concat(frames, ignore_index=True).drop_duplicates("open_time_ms").sort_values("open_time_ms")
        k.to_csv(out / f"klines_1d_{sym}.csv", index=False)
        log(f"klines 1d {sym}: {len(k):,} velas")

        frames = []
        for mth in B.months(pd.Timestamp(f"{FUNDING_FROM}-01", tz="UTC"), METRICS_TO):
            df, e = fetch(f"monthly/fundingRate/{sym}", f"{sym}-fundingRate-{mth}")
            if e is not None:
                manifest.append({**e, "symbol": sym, "kind": "funding"})
            if df is None:
                log(f"  falta/descartado funding {sym} {mth}")
                continue
            frames.append(B.norm_funding(df))
        f = pd.concat(frames, ignore_index=True).drop_duplicates("time_ms").sort_values("time_ms")
        f.to_csv(out / f"funding_{sym}.csv", index=False)
        log(f"funding {sym}: {len(f):,} liquidaciones")
    effr_manifest: list[dict] = []
    B.effr_download(W0 - pd.Timedelta(days=45), W1, effr_manifest).to_csv(out / "effr.csv", index=False)
    manifest += [{**e, "symbol": "", "kind": "effr"} for e in effr_manifest]
    man = pd.DataFrame(manifest)
    man.to_csv(out / "manifest.csv", index=False)
    arch = man[man["kind"] != "effr"]
    log(f"manifest: {len(man)} archivos; checksums oficiales OK "
        f"{int((arch['checksum_ok'] == True).sum())}/{len(arch)}")  # noqa: E712


# ================================ SEÑALES ===========================================
def daily_stock(m: pd.DataFrame, col: str) -> tuple[pd.Series, pd.Series]:
    """Último registro en (d, d+1] y conteo de registros válidos; NaN si < 144."""
    ts = B.utc_index(m["ts_ms"].astype("int64"))
    day = (ts - pd.Timedelta(seconds=1)).floor("D")
    s = pd.Series(m[col].astype(float).to_numpy(), index=ts)
    s = s.where(s > 0)          # adenda 1b: OI o ratio <= 0 es imposible -> faltante
    g = s.groupby(day)
    last, cnt = g.last(), g.count()
    return last.where(cnt >= MIN_RECORDS), cnt


def zscore(v: pd.Series) -> pd.Series:
    prev = v.shift(1).rolling(LOOKBACK_D, min_periods=MIN_VALID)
    return (v - prev.mean()) / prev.std()


def signals(metrics: pd.DataFrame, kl: pd.DataFrame, days: pd.DatetimeIndex) -> dict:
    """Por hipótesis: (valor diario v_d, z_d, lado si dispara) en el índice calendario `days`."""
    close = pd.Series(kl["close"].to_numpy(float), index=B.utc_index(kl["open_time_ms"])).reindex(days)
    oi, _ = daily_stock(metrics, "oi")
    tt, _ = daily_stock(metrics, "tt")
    oi, tt = oi.reindex(days), tt.reindex(days)
    v_oi = np.log(oi / oi.shift(1))
    r_d = np.log(close / close.shift(1))
    vol = pd.Series(kl["volume"].to_numpy(float), index=B.utc_index(kl["open_time_ms"])).reindex(days)
    tb = pd.Series(kl["taker_buy_volume"].to_numpy(float), index=B.utc_index(kl["open_time_ms"])).reindex(days)
    v_tk = (tb / vol).where(vol > 0)
    out = {}
    for hyp, v in (("H-OI1", v_oi), ("H-TT1", tt), ("H-TK1", v_tk)):
        z = zscore(v)
        fire = z.abs() > Z
        if hyp == "H-OI1":
            side = -np.sign(r_d)
        elif hyp == "H-TT1":
            side = np.sign(z)
        else:
            side = -np.sign(z)
        side = side.where(fire, 0.0).fillna(0.0)
        out[hyp] = {"v": v, "z": z, "side": side}
    return out


def trades_for(side: pd.Series, close: pd.Series) -> list[dict]:
    """Mecánica de H-POS1: entra al cierre del día d (= d+1 00:00), 3 días, sin solapar."""
    rows, free_at = [], W0
    for d, s in side.items():
        if s == 0 or np.isnan(s):
            continue
        t_in = d + DAY
        t_out = t_in + HOLD_D * DAY
        if t_in < max(W0, free_at) or t_out > W1:
            continue
        p_in, p_out = close.get(d), close.get(d + HOLD_D * DAY)
        if p_in is None or p_out is None or np.isnan(p_in) or np.isnan(p_out):
            continue
        rows.append({"day": d, "entry": t_in, "exit": t_out, "side": float(s),
                     "p_in": float(p_in), "p_out": float(p_out)})
        free_at = t_out
    return rows


def book_daily(trades: list[dict], close: pd.Series, fund: pd.Series, rf_d: pd.Series,
               cost_mult: float = 1.0) -> pd.Series:
    """Excesos diarios del libro de un símbolo en [W0, W1). `close` indexado por día d =
    cierre de la vela d (precio en d+1 00:00); `fund` por hora de liquidación."""
    days = pd.date_range(W0, W1 - DAY, freq="D", unit="ns")
    exc = pd.Series(0.0, index=days)
    c = cost_mult * (FEE + SLIP)
    for tr in trades:
        for t in pd.date_range(tr["entry"], tr["exit"] - DAY, freq="D", unit="ns"):
            p0, p1 = close.get(t - DAY), close.get(t)       # precio en t y en t+1
            ret = tr["side"] * (p1 / p0 - 1.0)
            f = float(fund[(fund.index > t) & (fund.index <= t + DAY)].sum())
            x = ret - tr["side"] * f - rf_d.get(t, 0.0)
            if t == tr["entry"]:
                x -= c
            if t == tr["exit"] - DAY:
                x -= c
            exc.loc[t] = x
    return exc


def trade_stats(trades: list[dict], fund: pd.Series, rf_d: pd.Series, cost_mult: float = 1.0) -> list[float]:
    out = []
    for tr in trades:
        f = float(fund[(fund.index > tr["entry"]) & (fund.index <= tr["exit"])].sum())
        r = tr["side"] * (tr["p_out"] / tr["p_in"] - 1.0) - tr["side"] * f - 2 * cost_mult * (FEE + SLIP)
        rfr = float(np.prod(1.0 + rf_d.reindex(pd.date_range(tr["entry"], tr["exit"] - DAY, freq="D",
                                                              unit="ns")).fillna(0.0).to_numpy()) - 1.0)
        out.append(r - rfr)
    return out


def coverage(v: pd.Series, start: pd.Timestamp) -> float:
    w = v[(v.index >= max(W0, start)) & (v.index < W1)]
    return float(w.notna().mean()) if len(w) else 0.0


def evaluate(port: pd.Series, port_x2: pd.Series, n_trades: int, valid: bool,
             per_trade: list[float]) -> dict:
    mid = W0 + (W1 - W0) / 2
    h1, h2 = port[port.index < mid], port[port.index >= mid]
    x = np.asarray(per_trade)
    t_trade = float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std() > 0 else None
    res = {"excess_ann": float(port.mean() * 365), "t_nw": B.nw_t(port.to_numpy(), lags=NW_LAGS),
           "n_trades": n_trades, "excess_h1_ann": float(h1.mean() * 365),
           "excess_h2_ann": float(h2.mean() * 365), "excess_x2_ann": float(port_x2.mean() * 365),
           "per_trade_mean_excess": float(x.mean()) if len(x) else None, "t_per_trade_H-POS1": t_trade,
           "days": len(port), "days_in_market_frac": float((port != 0).mean())}
    checks = {"1_exceso>0": res["excess_ann"] > 0,
              "2_t_NW>=2.50": res["t_nw"] is not None and res["t_nw"] >= T_CRIT,
              "3_n>=30": n_trades >= MIN_N,
              "4_mitades>0": res["excess_h1_ann"] > 0 and res["excess_h2_ann"] > 0,
              "5_costos_x2>0": res["excess_x2_ann"] > 0,
              "6_datos_validos": valid}
    return {**res, "checks": checks, "pasa": all(checks.values())}


def run_hypothesis(hyp: str, books: dict) -> dict:
    """books[sym] = dict(sig, close, fund, rf_d, start)."""
    valid_syms, cov = [], {}
    for sym, b in books.items():
        cov[sym] = coverage(b["sig"][hyp]["v"], b["start"])
        if cov[sym] >= MIN_COVERAGE:
            valid_syms.append(sym)
    if not valid_syms:
        empty = pd.Series(0.0, index=pd.date_range(W0, W1 - DAY, freq="D", unit="ns"))
        return {**evaluate(empty, empty, 0, False, []), "coverage": cov, "symbols": []}
    exc, exc2, per_trade, n, detail = [], [], [], 0, {}
    for sym in valid_syms:
        b = books[sym]
        trs = trades_for(b["sig"][hyp]["side"], b["close"])
        exc.append(book_daily(trs, b["close"], b["fund"], b["rf_d"], 1.0))
        exc2.append(book_daily(trs, b["close"], b["fund"], b["rf_d"], 2.0))
        per_trade += trade_stats(trs, b["fund"], b["rf_d"])
        n += len(trs)
        detail[sym] = {"n": len(trs), "longs": sum(t["side"] > 0 for t in trs),
                       "shorts": sum(t["side"] < 0 for t in trs)}
    port = sum(exc) / len(valid_syms)
    port2 = sum(exc2) / len(valid_syms)
    return {**evaluate(port, port2, n, True, per_trade), "coverage": cov, "symbols": valid_syms,
            "by_symbol": detail}


def load_books(data: Path) -> dict:
    effr = B.load_effr(data / "effr.csv")
    days_all = pd.date_range(pd.Timestamp(f"{KLINES_FROM}-01", tz="UTC"), W1, freq="D", unit="ns")
    rf_d = B.effr_daily(effr, W0, W1) / 360.0
    books = {}
    for sym in SYMBOLS:
        m = pd.read_csv(data / f"metrics_{sym}.csv")
        kl = pd.read_csv(data / f"klines_1d_{sym}.csv")
        fund, _ = B.funding_series(pd.read_csv(data / f"funding_{sym}.csv"))
        close = pd.Series(kl["close"].to_numpy(float), index=B.utc_index(kl["open_time_ms"])).reindex(days_all)
        books[sym] = {"sig": signals(m, kl, days_all), "close": close, "fund": fund, "rf_d": rf_d,
                      "start": METRICS_FROM[sym]}
    return books


def study(data: Path, report: Path) -> dict:
    report.mkdir(parents=True, exist_ok=True)
    books = load_books(data)
    results = {}
    for hyp in HYPS:
        r = run_hypothesis(hyp, books)
        results[hyp] = r
        log(f"{hyp}: PASA={r['pasa']} exceso {r['excess_ann']:+.4f} t_NW {r['t_nw']} n {r['n_trades']} "
            f"cov {r['coverage']}")
    out = {"prereg": PREREG, "window": f"{W0:%Y-%m-%d} -> {W1:%Y-%m-%d}",
           "generated_utc": str(pd.Timestamp.now(tz="UTC")), "results": results}
    (report / "b11_result.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


def study_tt1b(data: Path, report: Path) -> dict:
    """Adenda 1c: H-TT1b = regla de H-TT1 en 2022-12-15 -> 2024-10-01."""
    global W0
    W0 = TT1B_W0
    report.mkdir(parents=True, exist_ok=True)
    r = run_hypothesis("H-TT1", load_books(data))
    log(f"H-TT1b: PASA={r['pasa']} exceso {r['excess_ann']:+.4f} t_NW {r['t_nw']} n {r['n_trades']} "
        f"cov {r['coverage']}")
    out = {"prereg": PREREG + " (adenda 1c)", "window": f"{W0:%Y-%m-%d} -> {W1:%Y-%m-%d}",
           "generated_utc": str(pd.Timestamp.now(tz="UTC")), "results": {"H-TT1b": r}}
    (report / "b11_tt1b_result.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consola cp1252
    ap = argparse.ArgumentParser(description="B11 (pre-registro e80f809)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("download")
    a.add_argument("--out", type=Path, required=True)
    for name in ("study", "study-tt1b"):
        b = sub.add_parser(name)
        b.add_argument("--data", type=Path, required=True)
        b.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "download":
        download(args.out)
    elif args.cmd == "study":
        study(args.data, args.report)
    else:
        study_tt1b(args.data, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
