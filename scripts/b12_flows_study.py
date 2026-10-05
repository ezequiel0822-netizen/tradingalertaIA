"""B12 — flujos de baja frecuencia como predictores semanales de BTC/ETH:
H-STB1 (supply de stablecoins), H-EXF1 (flujo neto a exchanges), H-MVRV1 (MVRV). k = 3.

Implementa EXACTAMENTE research/HIPOTESIS_2026-10-05_B12_flujos.md (commit 1e5af5b,
ANTES de bajar datos). Research-only: no importa `app`, no toca el bot.

  python scripts/b12_flows_study.py download --out <dir>
  python scripts/b12_flows_study.py study --data <dir> --prices <dir de B13> --report <dir>
Verificación con datos sintéticos: python scripts/b12_selftest.py

Detalles de implementación (decididos ANTES de ver datos):
  a) Supply de stablecoins = suma de `totalCirculatingUSD` sobre todos los pegs (USD, EUR…).
  b) Valor de un día d = último registro con fecha <= d (as-of).
  c) Regla: exceso semanal = p·(retorno − funding) − costo·|Δp| − |p|·tasa libre; el cierre
     final (2024-09-30) paga costo. Un libro en cero rinde la tasa libre (exceso 0).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b4b_study as B  # noqa: E402  (EFFR, utc_index, funding_series: verificados)

# ---- parámetros CONGELADOS por el pre-registro (1e5af5b) ---------------------------
PREREG = "research/HIPOTESIS_2026-10-05_B12_flujos.md @ 1e5af5b"
START = pd.Timestamp("2020-01-06", tz="UTC")
END = pd.Timestamp("2024-09-30", tz="UTC")
WEEK = pd.Timedelta(days=7)
LAG = pd.Timedelta(days=2)
Z_ENTRY = 1.0
Z_WIN = {"H-STB1": (52, 26), "H-EXF1": (52, 26), "H-MVRV1": (156, 104)}
HORIZON = {"H-STB1": 1, "H-EXF1": 1, "H-MVRV1": 4}
NW_LAGS = {1: 4, 4: 8}
SIGN = {"H-STB1": +1, "H-EXF1": -1, "H-MVRV1": -1}     # +1: z alto -> long
FEE, SLIP = 0.0005, 0.0002
T_CRIT, MIN_WEEKS, MIN_COVERAGE = 2.50, 52, 0.95
HYPS = ("H-STB1", "H-EXF1", "H-MVRV1")
ASSETS = {"btc": "BTCUSDT", "eth": "ETHUSDT"}

LLAMA = ("https://stablecoins.llama.fi/stablecoincharts/all", "https://api.llama.fi/stablecoincharts/all")
CM = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
CM_METRICS = "FlowInExUSD,FlowOutExUSD,CapMrktCurUSD,CapMVRVCur"
CM_FROM, DATA_TO = "2016-06-01", "2024-09-30"
UA = {"User-Agent": "Mozilla/5.0 (research)"}


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ================================ DESCARGA ==========================================
def http_get(url: str, params: dict | None = None) -> bytes:
    last = None
    for attempt in range(6):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=120)
            if r.status_code in (429,) or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"GET {url} falló: {last}")


def save_raw(out: Path, name: str, raw: bytes, manifest: list, rows: int) -> None:
    (out / "raw").mkdir(parents=True, exist_ok=True)
    with gzip.open(out / "raw" / f"{name}.gz", "wb") as f:
        f.write(raw)
    manifest.append({"file": name, "bytes": len(raw), "rows": rows,
                     "sha256": hashlib.sha256(raw).hexdigest()})


def parse_llama(js: list) -> pd.DataFrame:
    rows = []
    for x in js:
        tc = x.get("totalCirculatingUSD", x.get("totalCirculating"))
        val = sum(float(v) for v in tc.values()) if isinstance(tc, dict) else float(tc)
        rows.append((pd.Timestamp(int(x["date"]), unit="s", tz="UTC").normalize(), val))
    d = pd.DataFrame(rows, columns=["date", "supply_usd"]).drop_duplicates("date", keep="last")
    return d.sort_values("date")


def parse_cm(pages: list[dict]) -> pd.DataFrame:
    rows = [r for p in pages for r in p.get("data", [])]
    d = pd.DataFrame(rows)
    d["date"] = pd.to_datetime(d["time"], utc=True).dt.normalize()
    for m in CM_METRICS.split(","):
        d[m] = pd.to_numeric(d[m], errors="coerce") if m in d.columns else np.nan
    return d[["asset", "date"] + CM_METRICS.split(",")].sort_values(["asset", "date"])


def download(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    raw = None
    for url in LLAMA:
        try:
            raw = http_get(url)
            break
        except RuntimeError as e:
            log(f"DefiLlama {url}: {e}")
    js = json.loads(raw)
    st = parse_llama(js)
    st = st[st["date"] <= pd.Timestamp(DATA_TO, tz="UTC")]
    save_raw(out, "defillama_stablecoincharts_all.json", raw, manifest, len(js))
    st.to_csv(out / "stablecoins.csv", index=False)
    log(f"DefiLlama: {len(st):,} días, {st['date'].min():%Y-%m-%d} -> {st['date'].max():%Y-%m-%d}")

    pages, url, params, k = [], CM, {"assets": "btc,eth", "metrics": CM_METRICS, "frequency": "1d",
                                      "start_time": CM_FROM, "end_time": DATA_TO, "page_size": 10000}, 0
    while url:
        raw = http_get(url, params)
        p = json.loads(raw)
        save_raw(out, f"coinmetrics_page_{k:03d}.json", raw, manifest, len(p.get("data", [])))
        pages.append(p)
        url, params, k = p.get("next_page_url"), None, k + 1
        time.sleep(1.0)
    cm = parse_cm(pages)
    cm.to_csv(out / "coinmetrics.csv", index=False)
    log(f"CoinMetrics: {len(cm):,} filas ({cm.groupby('asset').size().to_dict()}), "
        f"nulos por métrica {cm[CM_METRICS.split(',')].isna().sum().to_dict()}")
    em: list[dict] = []
    B.effr_download(pd.Timestamp("2019-12-01", tz="UTC"), END, em).to_csv(out / "effr.csv", index=False)
    pd.DataFrame(manifest + em).to_csv(out / "manifest.csv", index=False)
    log(f"manifest: {len(manifest) + len(em)} respuestas con sha256")


# ================================ PREDICTORES =======================================
def asof(s: pd.Series, d: pd.Timestamp) -> float:
    s = s[s.index <= d].dropna()
    return float(s.iloc[-1]) if len(s) else np.nan


def mondays(a: pd.Timestamp, b: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(a, b, freq="7D", unit="ns")


def x_stb(supply: pd.Series, T: pd.Timestamp) -> float:
    a, b = asof(supply, T - LAG), asof(supply, T - LAG - WEEK)
    return math.log(a / b) if a > 0 and b > 0 else np.nan


def x_exf(cm_a: pd.DataFrame, T: pd.Timestamp) -> float:
    w = cm_a[(cm_a.index >= T - LAG - pd.Timedelta(days=6)) & (cm_a.index <= T - LAG)]
    if len(w) < 7 or w[["FlowInExUSD", "FlowOutExUSD"]].isna().any().any():
        return np.nan
    cap = asof(cm_a["CapMrktCurUSD"], T - LAG)
    return float((w["FlowInExUSD"] - w["FlowOutExUSD"]).sum() / cap) if cap > 0 else np.nan


def x_mvrv(cm_a: pd.DataFrame, T: pd.Timestamp) -> float:
    s = cm_a["CapMVRVCur"]
    return float(s.loc[T - LAG]) if (T - LAG) in s.index and pd.notna(s.loc[T - LAG]) else np.nan


def zscore_weekly(x: pd.Series, win: int, min_n: int) -> pd.Series:
    prev = x.shift(1).rolling(win, min_periods=min_n)
    return (x - prev.mean()) / prev.std()


def predictors(hyp: str, stb: pd.Series, cm: pd.DataFrame, weeks: pd.DatetimeIndex) -> pd.DataFrame:
    """z por activo (columnas btc, eth) en cada lunes; incluye historia previa para el z."""
    win, mn = Z_WIN[hyp]
    hist = pd.date_range(weeks[0] - WEEK * (win + 5), weeks[-1], freq="7D", unit="ns")
    out = {}
    for a in ASSETS:
        if hyp == "H-STB1":
            x = pd.Series([x_stb(stb, T) for T in hist], index=hist)
        else:
            cm_a = cm[cm["asset"] == a].set_index("date").sort_index()
            f = x_exf if hyp == "H-EXF1" else x_mvrv
            x = pd.Series([f(cm_a, T) for T in hist], index=hist)
        out[a] = zscore_weekly(x, win, mn).reindex(weeks)
    return pd.DataFrame(out)


# ================================ PRUEBAS ===========================================
def hac_slope_t(y: np.ndarray, z: np.ndarray, lags: int) -> tuple[float, float | None]:
    """OLS y = a + b z; t de b con varianza HAC Newey-West (Bartlett)."""
    X = np.column_stack([np.ones_like(z), z])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    u = y - X @ beta
    g = X * u[:, None]
    S = g.T @ g
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        G = g[lag:].T @ g[:-lag]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    return float(beta[1]), (float(beta[1] / math.sqrt(V[1, 1])) if V[1, 1] > 0 else None)


def regression(hyp: str, z: pd.DataFrame, px: dict[str, pd.Series]) -> dict:
    h = HORIZON[hyp]
    ys, zs, idx = [], [], []
    for T in z.index:
        T2 = T + h * WEEK
        if T2 > END or z.loc[T].isna().any():
            continue
        r = [math.log(px[a].get(T2, np.nan) / px[a].get(T, np.nan)) for a in ASSETS]
        if any(np.isnan(r)):
            continue
        ys.append(float(np.mean(r)))
        zs.append(float(z.loc[T].mean()))
        idx.append(T)
    b, t = hac_slope_t(np.array(ys), np.array(zs), NW_LAGS[h])
    return {"slope": b, "t_nw": t, "n_obs": len(ys), "horizon_weeks": h, "nw_lags": NW_LAGS[h]}


def rule(hyp: str, z: pd.DataFrame, px: dict[str, pd.Series], fund: dict[str, pd.Series],
         rf_w: pd.Series, cost_mult: float = 1.0) -> pd.Series:
    """Excesos semanales del portafolio 50/50 (una fila por semana T -> T + 1)."""
    c = cost_mult * (FEE + SLIP)
    weeks = mondays(START, END - WEEK)
    books = []
    for a, sym in ASSETS.items():
        p_prev, ex = 0.0, []
        for T in weeks:
            zt = z.loc[T, a]
            p = 0.0 if np.isnan(zt) or abs(zt) <= Z_ENTRY else SIGN[hyp] * float(np.sign(zt))
            ret = px[a].get(T + WEEK, np.nan) / px[a].get(T, np.nan) - 1.0
            f = float(fund[a][(fund[a].index > T) & (fund[a].index <= T + WEEK)].sum())
            x = p * (ret - f) - c * abs(p - p_prev) - abs(p) * rf_w.loc[T]
            if T == weeks[-1]:
                x -= c * abs(p)                      # cierre final
            ex.append(x)
            p_prev = p
        books.append(pd.Series(ex, index=weeks))
    return 0.5 * (books[0] + books[1])


def positions_weeks(hyp: str, z: pd.DataFrame) -> int:
    weeks = mondays(START, END - WEEK)
    zz = z.reindex(weeks)
    return int(((zz.abs() > Z_ENTRY) & zz.notna()).any(axis=1).sum())


def evaluate(hyp: str, z: pd.DataFrame, px: dict, fund: dict, rf_w: pd.Series) -> dict:
    reg = regression(hyp, z, px)
    ex, ex2 = rule(hyp, z, px, fund, rf_w, 1.0), rule(hyp, z, px, fund, rf_w, 2.0)
    n = len(ex)
    h1, h2 = ex.iloc[: n // 2], ex.iloc[n // 2:]
    cov = float(z.reindex(mondays(START, END - WEEK)).notna().all(axis=1).mean())
    wk = positions_weeks(hyp, z)
    res = {**reg, "rule_excess_ann": float(ex.mean() * 52), "rule_h1_ann": float(h1.mean() * 52),
           "rule_h2_ann": float(h2.mean() * 52), "rule_x2_ann": float(ex2.mean() * 52),
           "rule_t_nw_info": B.nw_t(ex.to_numpy(), lags=4), "weeks_with_position": wk,
           "coverage": cov, "weeks": n}
    sgn_ok = res["t_nw"] is not None and np.sign(res["slope"]) == SIGN[hyp] and abs(res["t_nw"]) >= T_CRIT
    checks = {"1_pendiente_signo_tesis_|t_NW|>=2.50": bool(sgn_ok),
              "2_regla_exceso>0": res["rule_excess_ann"] > 0,
              "3_regla_mitades>0": res["rule_h1_ann"] > 0 and res["rule_h2_ann"] > 0,
              "4_regla_costos_x2>0": res["rule_x2_ann"] > 0,
              "5_semanas_con_posicion>=52": wk >= MIN_WEEKS,
              "6_cobertura>=95%": cov >= MIN_COVERAGE}
    return {**res, "checks": checks, "pasa": all(checks.values())}


def load_prices(prices_dir: Path) -> tuple[dict, dict]:
    k = pd.read_parquet(prices_dir / "perp_8h.parquet")
    fr = pd.read_parquet(prices_dir / "funding.parquet")
    px, fund = {}, {}
    for a, sym in ASSETS.items():
        kk = k[k["symbol"] == sym]
        px[a] = pd.Series(kk["close"].to_numpy(float), index=B.utc_index(kk["open_time"]) + pd.Timedelta(hours=8))
        ff = fr[fr["symbol"] == sym]
        fund[a], _ = B.funding_series(ff[["time_ms", "fundingRate"]])
    return px, fund


def study(data: Path, prices: Path, report: Path) -> dict:
    report.mkdir(parents=True, exist_ok=True)
    st = pd.read_csv(data / "stablecoins.csv", parse_dates=["date"])
    stb = pd.Series(st["supply_usd"].to_numpy(float), index=pd.DatetimeIndex(st["date"]).tz_convert("UTC").as_unit("ns"))
    cm = pd.read_csv(data / "coinmetrics.csv", parse_dates=["date"])
    cm["date"] = pd.DatetimeIndex(cm["date"]).tz_convert("UTC").as_unit("ns")
    px, fund = load_prices(prices)
    effr = B.load_effr(data / "effr.csv")
    rf_d = B.effr_daily(effr, START, END)
    weeks = mondays(START, END)
    rf_w = pd.Series([float(np.prod(1 + rf_d[(rf_d.index >= T) & (rf_d.index < T + WEEK)].to_numpy() / 360) - 1)
                      for T in weeks[:-1]], index=weeks[:-1])
    res = {}
    for hyp in HYPS:
        z = predictors(hyp, stb, cm, weeks)
        r = evaluate(hyp, z, px, fund, rf_w)
        res[hyp] = r
        log(f"{hyp}: PASA={r['pasa']} pendiente {r['slope']:+.5f} t_NW {r['t_nw']} regla {r['rule_excess_ann']:+.4f} "
            f"semanas {r['weeks_with_position']} cobertura {r['coverage']:.3f}")
    out = {"prereg": PREREG, "window": f"{START:%Y-%m-%d} -> {END:%Y-%m-%d}",
           "generated_utc": str(pd.Timestamp.now(tz="UTC")), "results": res}
    (report / "b12_result.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consola cp1252
    ap = argparse.ArgumentParser(description="B12 (pre-registro 1e5af5b)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("download")
    a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("study")
    b.add_argument("--data", type=Path, required=True)
    b.add_argument("--prices", type=Path, required=True)
    b.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "download":
        download(args.out)
    else:
        study(args.data, args.prices, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
