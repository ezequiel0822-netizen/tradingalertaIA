"""B13 — factores cruzados en perps USDⓈ-M: H-REV1 (reversión semanal) y H-FND1 (funding
como predictor), k = 2.

Implementa EXACTAMENTE research/HIPOTESIS_2026-10-05_B13_factores_cruzados.md (commit
595d964, ANTES de bajar datos). Motor = el de H-XS1 (scripts/crypto_batch_study.py,
run_xs1) generalizado a una señal cualquiera, con q >= 2. Research-only.

  python scripts/b13_cross_factors.py download --out <dir>
  python scripts/b13_cross_factors.py study --data <dir> --report <dir>
Verificación con datos sintéticos: python scripts/b13_selftest.py

Detalles de implementación (decididos ANTES de ver datos):
  a) La curva guarda en cada lunes el equity ANTES de pagar el rebalanceo, así el costo de
     cada rebalanceo cae dentro de la semana que abre; el último lunes (2024-09-30) se
     cierra todo pagando costos.
  b) Empates en la señal (frecuentes en H-FND1: muchas alts liquidan exactamente la tasa
     base): orden estable por nombre de símbolo (alfabético). Arbitrario pero determinista
     e independiente de los retornos.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
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
import b4b_study as B  # noqa: E402  (evaluate con NW, EFFR: verificados)

# ---- parámetros CONGELADOS por el pre-registro (595d964) ---------------------------
PREREG = "research/HIPOTESIS_2026-10-05_B13_factores_cruzados.md @ 595d964"
START = pd.Timestamp("2020-01-06", tz="UTC")         # primer rebalanceo (lunes)
END = pd.Timestamp("2024-09-30", tz="UTC")           # cierre final (lunes)
DATA_FROM, DATA_TO = "2019-11", "2024-09"
STEP = pd.Timedelta(hours=8)
LB = 21                                              # 7 días en velas de 8 h
FEE, SLIP = 0.0005, 0.0005
LIQ = 20e6
MIN_Q, MAX_DD, MIN_WEEKS = 2, 0.30, 104
DELIST_PENALTY = 0.02
T_CRIT = 2.50
STABLE = ("USDC", "FDUSD", "TUSD", "BUSD", "USDP", "DAI", "EUR", "AEUR", "USDE")
HYPS = ("H-REV1", "H-FND1")

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
BASE = "https://data.binance.vision/data"
UA = {"User-Agent": "Mozilla/5.0 (research)"}
_local = threading.local()


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ================================ DESCARGA ==========================================
def get(url: str) -> bytes | None:
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


def s3_list(prefix: str, delimiter: bool) -> list[str]:
    out, marker = [], ""
    while True:
        q = f"{S3}?prefix={prefix}&marker={marker}" + ("&delimiter=/" if delimiter else "")
        x = get(q).decode()
        items = re.findall(r"<Prefix>([^<]+)</Prefix>", x)[1:] if delimiter else re.findall(r"<Key>([^<]+)</Key>", x)
        out += items
        if "<IsTruncated>true</IsTruncated>" not in x or not items:
            return out
        marker = items[-1]


def universe() -> list[str]:
    syms = [p.rstrip("/").split("/")[-1] for p in s3_list("data/futures/um/monthly/fundingRate/", True)]
    return sorted(s for s in syms if s.endswith("USDT") and s.isascii() and s[:-4] not in STABLE)


def fetch(path: str, name: str) -> tuple[pd.DataFrame | None, dict | None]:
    url = f"{BASE}/{path}/{name}.zip"
    raw = get(url)
    if raw is None:
        return None, None
    ck = get(url + ".CHECKSUM")
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


def norm_klines_8h(df: pd.DataFrame) -> pd.DataFrame:
    k = df.iloc[:, [0, 4, 7]].copy()
    k.columns = ["open_time", "close", "quote_volume"]
    k = k.apply(pd.to_numeric, errors="coerce")
    if k.isna().any().any():
        raise ValueError("klines 8h con NaN tras normalizar")
    ot = k["open_time"].astype("int64")
    k["open_time"] = ot.where(ot < 10**14, ot // 1000)
    return k


def job_symbol(sym: str) -> tuple[dict, list]:
    months = set(pd.period_range(DATA_FROM, DATA_TO, freq="M").strftime("%Y-%m"))
    out, manifest = {}, []
    for kind, prefix, norm in (
        ("perp", f"futures/um/monthly/klines/{sym}/8h", norm_klines_8h),
        ("funding", f"futures/um/monthly/fundingRate/{sym}", B.norm_funding),
    ):
        keys = [k for k in s3_list(f"data/{prefix}/", False) if k.endswith(".zip")]
        avail = sorted(m for m in (re.search(r"(\d{4}-\d{2})\.zip$", k).group(1) for k in keys) if m in months)
        parts = []
        for m in avail:
            name = f"{sym}-8h-{m}" if kind == "perp" else f"{sym}-fundingRate-{m}"
            df, e = fetch(prefix, name)
            if e is not None:
                manifest.append({**e, "symbol": sym, "kind": kind})
            if df is not None:
                parts.append(norm(df))
        if parts:
            f = pd.concat(parts, ignore_index=True)
            f.insert(0, "symbol", sym)
            out[kind] = f
    return out, manifest


def download(out: Path, workers: int = 16) -> None:
    out.mkdir(parents=True, exist_ok=True)
    uni = universe()
    (out / "universe.txt").write_text("\n".join(uni), encoding="utf-8")
    log(f"universo (USDT, ASCII, no estables, incluye deslistados y 1000…): {len(uni)} símbolos")
    perps, funds, manifest = [], [], []
    with ThreadPoolExecutor(workers) as ex:
        for i, (frames, man) in enumerate(ex.map(job_symbol, uni), 1):
            manifest += man
            if "perp" in frames:
                perps.append(frames["perp"])
            if "funding" in frames:
                funds.append(frames["funding"])
            if i % 100 == 0:
                log(f"  {i}/{len(uni)} símbolos")
    pd.concat(perps, ignore_index=True).to_parquet(out / "perp_8h.parquet", index=False)
    pd.concat(funds, ignore_index=True).to_parquet(out / "funding.parquet", index=False)
    em: list[dict] = []
    B.effr_download(pd.Timestamp(f"{DATA_FROM}-01", tz="UTC"), END, em).to_csv(out / "effr.csv", index=False)
    man = pd.DataFrame(manifest + [{**e, "symbol": "", "kind": "effr"} for e in em])
    man.to_csv(out / "manifest.csv", index=False)
    arch = man[man["kind"] != "effr"]
    log(f"símbolos con velas en la ventana: {len(perps)}; manifest {len(man)} archivos; checksums "
        f"oficiales OK {int((arch['checksum_ok'] == True).sum())}/{len(arch)}")  # noqa: E712


# ================================ MOTOR =============================================
def load_wide(data: Path) -> dict:
    """Matrices T × símbolo; T = fin de la vela de 8 h (open_time + 8 h)."""
    k = pd.read_parquet(data / "perp_8h.parquet")
    k["T"] = B.utc_index(k["open_time"].astype("int64")) + STEP
    k = k.drop_duplicates(["symbol", "T"])
    perp = k.pivot(index="T", columns="symbol", values="close")
    qv = k.pivot(index="T", columns="symbol", values="quote_volume")
    fr = pd.read_parquet(data / "funding.parquet")
    t = B.utc_index(fr["time_ms"].astype("int64")).floor("h")
    fr["T"] = t.ceil("8h")                         # eventos de 4 h -> al cierre de 8 h
    fund = fr.groupby(["T", "symbol"])["fundingRate"].sum().unstack()
    grid = perp.index.sort_values()
    return {"perp": perp.reindex(grid), "perp_qv": qv.reindex(grid),
            "funding": fund.reindex(grid).reindex(columns=perp.columns).fillna(0.0)}


def daily_median_volume(qv: pd.DataFrame) -> pd.DataFrame:
    """Idéntica a H-XS1: mediana de los 30 días COMPLETOS previos (shift)."""
    day = (qv.index - STEP).floor("D")
    daily = qv.groupby(day).sum(min_count=1)
    return daily.rolling(30, min_periods=20).median().shift(1)


def signal_at(hyp: str, w: dict, i: int, cand: list[str]) -> pd.Series:
    perp = w["perp"]
    if hyp == "H-REV1":
        return perp.iloc[i][cand] / perp.iloc[i - LB][cand] - 1.0
    fund = w["funding"]
    return fund.iloc[i - LB + 1:i + 1][cand].sum()          # liquidado en (T − 7 d, T]


def run(hyp: str, w: dict, cost_mult: float = 1.0, start=START, end=END) -> dict:
    cost = (FEE + SLIP) * cost_mult
    perp, fund = w["perp"], w["funding"]
    last = perp.apply(pd.Series.last_valid_index)
    med = daily_median_volume(w["perp_qv"])
    grid = perp.index[(perp.index >= start) & (perp.index <= end)]
    eq, qty, prev_px = 1.0, {}, {}
    times, values = [], []
    st = {"rebalances": 0, "weeks_invested": 0, "delistings": 0, "n_side": [], "turnover": []}
    for T in grid:
        for sym in list(qty):
            if T > last[sym]:
                Pl = perp.at[last[sym], sym]
                eq += qty[sym] * (Pl - prev_px[sym]) - DELIST_PENALTY * abs(qty[sym] * Pl)
                eq -= cost * abs(qty[sym] * Pl)
                qty.pop(sym), prev_px.pop(sym)
                st["delistings"] += 1
                continue
            P = perp.at[T, sym]
            if np.isnan(P):
                continue
            eq += qty[sym] * (P - prev_px[sym]) - qty[sym] * P * fund.at[T, sym]
            prev_px[sym] = P
        times.append(T)
        values.append(eq)                          # antes del costo del rebalanceo
        if T == end:
            eq -= cost * sum(abs(v * prev_px[s]) for s, v in qty.items())
            qty = {}
            values[-1] = eq
            break
        if T.weekday() == 0 and T.hour == 0:
            i = perp.index.get_loc(T)
            d = T.floor("D")
            mp = med.loc[d] if d in med.index else pd.Series(dtype=float)
            cand = []
            if i >= LB:
                now, past = perp.iloc[i], perp.iloc[i - LB]
                cand = [s for s in perp.columns
                        if pd.notna(now[s]) and pd.notna(past[s]) and mp.get(s, 0) >= LIQ]
            target = {}
            q = len(cand) // 5
            if q >= MIN_Q:
                sig = signal_at(hyp, w, i, cand).sort_values(kind="mergesort")
                for s in sig.index[:q]:                      # señal BAJA -> long
                    target[s] = 0.5 * eq / q / perp.at[T, s]
                for s in sig.index[-q:]:                     # señal ALTA -> short
                    target[s] = -0.5 * eq / q / perp.at[T, s]
                st["weeks_invested"] += 1
            turnover = 0.0
            for s in set(qty) | set(target):
                P = perp.at[T, s]
                if np.isnan(P):
                    P = prev_px[s]                   # hueco puntual: último precio válido
                turnover += abs(target.get(s, 0.0) - qty.get(s, 0.0)) * P
            eq -= cost * turnover
            qty = dict(target)
            prev_px = {s: perp.at[T, s] for s in qty}
            st["rebalances"] += 1
            st["n_side"].append(q)
            st["turnover"].append(turnover / max(eq, 1e-12))
    st["curve"] = pd.Series(values, index=pd.DatetimeIndex(times))
    return st


def evaluate_hyp(hyp: str, w: dict, effr: pd.Series) -> dict:
    a, b = run(hyp, w, 1.0), run(hyp, w, 2.0)
    ev, ev2 = B.evaluate(a["curve"], effr, START, END), B.evaluate(b["curve"], effr, START, END)
    checks = {"1_exceso>0": ev["excess_ann"] > 0,
              "2_t_NW>=2.50": ev["t_nw"] is not None and ev["t_nw"] >= T_CRIT,
              "3_maxDD<=30%": ev["max_dd"] >= -MAX_DD,
              "4_mitades>0": (ev["excess_half1_ann"] or 0) > 0 and ev["excess_half2_ann"] > 0,
              "5_costos_x2>0": ev2["excess_ann"] > 0,
              "6_semanas_con_posicion>=104": a["weeks_invested"] >= MIN_WEEKS}
    return {"hyp": hyp, **{k: v for k, v in ev.items() if k != "weekly_excess"},
            "excess_x2_ann": ev2["excess_ann"], "weeks_invested": a["weeks_invested"],
            "delistings": a["delistings"],
            "median_per_side": float(np.median([x for x in a["n_side"] if x >= MIN_Q])) if a["weeks_invested"] else 0,
            "median_weekly_turnover": float(np.median(a["turnover"])) if a["turnover"] else 0,
            "weekly_excess": ev["weekly_excess"], "checks": checks, "pasa": all(checks.values())}


def study(data: Path, report: Path) -> dict:
    report.mkdir(parents=True, exist_ok=True)
    w = load_wide(data)
    effr = B.load_effr(data / "effr.csv")
    res = {}
    for hyp in HYPS:
        r = evaluate_hyp(hyp, w, effr)
        res[hyp] = r
        log(f"{hyp}: PASA={r['pasa']} exceso {r['excess_ann']:+.4f} t_NW {r['t_nw']} DD {r['max_dd']:.3f} "
            f"semanas {r['weeks_invested']}")
    out = {"prereg": PREREG, "window": f"{START:%Y-%m-%d} -> {END:%Y-%m-%d}",
           "generated_utc": str(pd.Timestamp.now(tz="UTC")), "results": res}
    (report / "b13_result.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consola cp1252
    ap = argparse.ArgumentParser(description="B13 (pre-registro 595d964)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("download")
    a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("study")
    b.add_argument("--data", type=Path, required=True)
    b.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "download":
        download(args.out)
    else:
        study(args.data, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
