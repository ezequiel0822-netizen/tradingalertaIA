"""H-FC1 — funding carry delta-neutral (long spot + short perp) en BTC y ETH.

Implementa EXACTAMENTE research/HIPOTESIS_2026-10-04_funding_carry.md (commiteado
antes de bajar datos). Research-only: no importa `app`, no toca el bot ni la DB viva.

Etapas:
  python scripts/funding_carry_study.py download --out <dir>   # data + manifest
  python scripts/funding_carry_study.py study    --data <dir> --report <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "https://data.binance.vision/data"
UA = {"User-Agent": "Mozilla/5.0 (research)"}
FRED_DFF = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
FIRST_MONTH = date(2020, 1, 1)
LAST_MONTH = date(2026, 9, 1)

# ---- parámetros CONGELADOS por el pre-registro ---------------------------------
DECISION_START = pd.Timestamp("2024-10-01", tz="UTC")
DECISION_END = pd.Timestamp("2026-10-01", tz="UTC")          # exclusivo
CONTEXT_START = pd.Timestamp("2020-01-01", tz="UTC")
MARGIN_RATIO = 0.5
REBALANCE_BAND = 0.20
MAINT_RATIO = 0.005
FEE_SPOT, FEE_PERP, SLIP = 0.0010, 0.0005, 0.0002
V1_LOOKBACK = 21
V1_ENTER, V1_EXIT = 0.10, 0.0
T_CRIT = 2.50
MAX_DD = 0.10
STEP = pd.Timedelta(hours=8)


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ================================ DESCARGA =======================================
def _get(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except Exception:
        return None


def _csv_from_zip(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    first = text.split("\n", 1)[0].split(",")[0].strip()
    has_header = not first.lstrip("-").replace(".", "").isdigit()
    return pd.read_csv(io.StringIO(text), header=0 if has_header else None)


def _months() -> list[str]:
    out, d = [], FIRST_MONTH
    while d <= LAST_MONTH:
        out.append(f"{d:%Y-%m}")
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def _fetch(kind_path: str, name: str, manifest: list) -> pd.DataFrame | None:
    url = f"{BASE}/{kind_path}/{name}.zip"
    raw = _get(url)
    if raw is None:
        return None
    official = _get(url + ".CHECKSUM")
    official = official.decode().split()[0] if official else "UNAVAILABLE"
    sha = hashlib.sha256(raw).hexdigest()
    df = _csv_from_zip(raw)
    manifest.append({"file": f"{name}.zip", "url": url, "bytes": len(raw), "rows": len(df),
                     "sha256": sha, "official_sha256": official,
                     "checksum_ok": sha == official})
    return df


def download(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for sym in SYMBOLS:
        for kind, path, cols in (
            ("funding", f"futures/um/monthly/fundingRate/{sym}", None),
            ("perp8h", f"futures/um/monthly/klines/{sym}/8h", "k"),
            ("spot8h", f"spot/monthly/klines/{sym}/8h", "k"),
        ):
            frames, missing = [], []
            for m in _months():
                name = (f"{sym}-fundingRate-{m}" if kind == "funding" else f"{sym}-8h-{m}")
                df = _fetch(path, name, manifest)
                if df is None and kind != "funding":
                    daily = path.replace("/monthly/", "/daily/")
                    days = pd.date_range(f"{m}-01", periods=31, freq="D")
                    days = [d for d in days if d.strftime("%Y-%m") == m]
                    parts = [_fetch(daily, f"{sym}-8h-{d:%Y-%m-%d}", manifest) for d in days]
                    parts = [p for p in parts if p is not None]
                    df = pd.concat(parts, ignore_index=True) if parts else None
                if df is None:
                    missing.append(m)
                    continue
                # Normalizar POR ARCHIVO y por posición: unos traen encabezado y otros
                # no, y concatenarlos crudos desalinea columnas (NaN silenciosos).
                if cols == "k":
                    df = df.iloc[:, :6].copy()
                    df.columns = ["open_time", "open", "high", "low", "close", "volume"]
                else:
                    df = pd.DataFrame({"calc_time": df.iloc[:, 0],
                                       "funding_rate": df.iloc[:, -1]})
                frames.append(df.apply(pd.to_numeric, errors="coerce"))
            data = pd.concat(frames, ignore_index=True)
            bad = int(data.isna().any(axis=1).sum())
            if bad:
                raise ValueError(f"{sym} {kind}: {bad} filas con NaN tras normalizar")
            if cols == "k":
                ot = data["open_time"].astype("int64")
                data["open_time"] = np.where(ot > 10**14, ot // 1000, ot)  # spot 2025+ en µs
            data.to_parquet(out / f"{sym}_{kind}.parquet", index=False)
            log(f"{sym} {kind}: {len(data):,} filas, meses faltantes={missing}")
    dff = pd.read_csv(io.StringIO(_get(FRED_DFF).decode()))
    dff.to_csv(out / "DFF.csv", index=False)
    log(f"DFF: {len(dff):,} filas hasta {dff.iloc[-1, 0]}")
    man = pd.DataFrame(manifest)
    man.to_csv(out / "manifest.csv", index=False)
    log(f"manifest: {len(man)} archivos, checksums OK {int(man['checksum_ok'].sum())}/{len(man)}")


# ================================ ESTUDIO ========================================
def build_grid(data: Path, sym: str) -> pd.DataFrame:
    """Grilla de 8 h en los horarios de funding: precio spot y perp al cierre de la
    vela que termina en T, máximo del perp en esa vela y funding liquidado en T."""
    fr = pd.read_parquet(data / f"{sym}_funding.parquet")
    tcol = [c for c in fr.columns if "time" in str(c).lower()][0]
    rcol = [c for c in fr.columns if "rate" in str(c).lower()][0]
    ft = pd.to_datetime(fr[tcol].astype("int64"), unit="ms", utc=True)
    fr = pd.DataFrame({"T": ft.dt.floor("h"), "rate": fr[rcol].astype(float)})
    on_grid = fr["T"].dt.hour.isin([0, 8, 16])
    # funding fuera de la grilla de 8 h (si el intervalo cambió) se suma al próximo T
    fr.loc[~on_grid, "T"] = fr.loc[~on_grid, "T"].dt.ceil("8h")
    funding = fr.groupby("T")["rate"].sum()

    def bars(kind: str) -> pd.DataFrame:
        k = pd.read_parquet(data / f"{sym}_{kind}.parquet")
        k["T"] = pd.to_datetime(k["open_time"].astype("int64"), unit="ms", utc=True) + STEP
        return k.drop_duplicates("T").set_index("T")[["high", "close"]].astype(float)

    perp, spot = bars("perp8h"), bars("spot8h")
    g = pd.DataFrame({"perp": perp["close"], "perp_high": perp["high"], "spot": spot["close"]})
    g["rate"] = funding.reindex(g.index).fillna(0.0)
    g = g.dropna(subset=["perp", "spot"]).sort_index()
    g.attrs["off_grid_funding"] = int((~on_grid).sum())
    return g


def simulate(g: pd.DataFrame, start, end, variant: str, cost_mult: float = 1.0) -> dict:
    """Simula la estrategia del pre-registro sobre la grilla g en [start, end)."""
    fs, fp = (FEE_SPOT + SLIP) * cost_mult, (FEE_PERP + SLIP) * cost_mult
    w = g.loc[(g.index >= start) & (g.index < end)]
    cash, in_pos = 1.0, False
    spot_qty = perp_qty = perp_ref = margin = last_px = 0.0
    eq, liquidations, rebalances, entries = [], 0, 0, 0
    rates = w["rate"].to_numpy()
    for i, (T, row) in enumerate(w.iterrows()):
        S, P, H, r = row["spot"], row["perp"], row["perp_high"], row["rate"]
        if in_pos:
            # 1) liquidación con el máximo intra-vela del perpetuo
            m_eq_high = margin + perp_qty * (perp_ref - H)
            if m_eq_high <= MAINT_RATIO * perp_qty * H:
                liquidations += 1
                cash = spot_qty * S * (1 - fs)
                in_pos, spot_qty, perp_qty, margin = False, 0.0, 0.0, 0.0
            else:
                # 2) funding liquidado en T (el short cobra si r > 0)
                margin += r * perp_qty * P
                # 3) rebalanceo por banda de precio
                if abs(S / last_px - 1) >= REBALANCE_BAND:
                    margin += perp_qty * (perp_ref - P)        # realiza el PnL del perp
                    perp_ref = P
                    equity = spot_qty * S + margin
                    n_new = equity / (1 + MARGIN_RATIO)
                    fee = fs * abs(n_new - spot_qty * S) + fp * abs(n_new - perp_qty * P)
                    n_new = (equity - fee) / (1 + MARGIN_RATIO)
                    spot_qty, perp_qty = n_new / S, n_new / P
                    margin = MARGIN_RATIO * n_new
                    last_px, rebalances = S, rebalances + 1
        # 4) señal (V1) o entrada/salida fija (V0)
        last = i == len(w) - 1
        if variant == "V0":
            want = not last
        else:
            lo = max(0, i - V1_LOOKBACK + 1)
            avg = rates[lo:i + 1].mean() * 3 * 365 if i + 1 >= V1_LOOKBACK else np.nan
            want = in_pos
            if not in_pos and avg > V1_ENTER:
                want = True
            elif in_pos and avg < V1_EXIT:
                want = False
            if last:
                want = False
        if want and not in_pos:
            n = cash / (1 + MARGIN_RATIO + fs + fp)
            spot_qty, perp_qty, perp_ref = n / S, n / P, P
            margin = cash - n - (fs + fp) * n
            cash, in_pos, last_px, entries = 0.0, True, S, entries + 1
        elif in_pos and not want:
            cash = (spot_qty * S * (1 - fs) + margin + perp_qty * (perp_ref - P)
                    - perp_qty * P * fp)
            in_pos, spot_qty, perp_qty, margin = False, 0.0, 0.0, 0.0
        equity = (spot_qty * S + margin + perp_qty * (perp_ref - P)) if in_pos else cash
        eq.append((T, equity))
    curve = pd.Series([e for _, e in eq], index=[t for t, _ in eq])
    return {"curve": curve, "liquidations": liquidations, "rebalances": rebalances,
            "entries": entries}


def risk_free(dff_csv: Path) -> pd.Series:
    d = pd.read_csv(dff_csv)
    d.columns = ["date", "rate"]
    d["date"] = pd.to_datetime(d["date"], utc=True)
    d["rate"] = pd.to_numeric(d["rate"], errors="coerce") / 100.0
    return d.dropna().set_index("date")["rate"]


def evaluate(curve: pd.Series, rf: pd.Series) -> dict:
    weekly = curve.resample("W-SUN").last().dropna()
    ret = weekly.pct_change().dropna()
    rf_w = rf.reindex(ret.index, method="ffill").fillna(0.0)
    exc = ret - ((1 + rf_w) ** (1 / 52) - 1)
    n = len(exc)
    t = float(exc.mean() / (exc.std(ddof=1) / np.sqrt(n))) if n > 2 and exc.std() > 0 else None
    dd = float((curve / curve.cummax() - 1).min())
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    return {"weeks": n, "total_return": float(curve.iloc[-1] / curve.iloc[0] - 1),
            "cagr": float((curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1) if years > 0 else None,
            "excess_ann": float(exc.mean() * 52), "t_weekly": t, "max_dd": dd,
            "rf_ann_mean": float(rf_w.mean())}


def study(data: Path, report: Path) -> None:
    report.mkdir(parents=True, exist_ok=True)
    rf = risk_free(data / "DFF.csv")
    mid = DECISION_START + (DECISION_END - DECISION_START) / 2
    res: dict = {"combos": {}, "context": {}, "funding_stats": {}}
    for sym in SYMBOLS:
        g = build_grid(data, sym)
        res["funding_stats"][sym] = {
            "off_grid_funding_events": g.attrs["off_grid_funding"],
            "grid": [str(g.index[0]), str(g.index[-1]), len(g)],
            "by_year_apr": {str(y): float(s.mean() * 3 * 365)
                            for y, s in g["rate"].groupby(g.index.year)},
            "decision_apr": float(g.loc[DECISION_START:DECISION_END, "rate"].mean() * 3 * 365),
            "decision_pct_negative": float((g.loc[DECISION_START:DECISION_END, "rate"] < 0).mean()),
        }
        for v in ("V0", "V1"):
            key = f"{sym}_{v}"
            base = simulate(g, DECISION_START, DECISION_END, v)
            ev = evaluate(base["curve"], rf)
            h1 = evaluate(base["curve"].loc[:mid], rf)
            h2 = evaluate(base["curve"].loc[mid:], rf)
            x2 = evaluate(simulate(g, DECISION_START, DECISION_END, v, cost_mult=2.0)["curve"], rf)
            checks = {
                "excess_pos": ev["excess_ann"] > 0,
                "t_ok": ev["t_weekly"] is not None and ev["t_weekly"] >= T_CRIT,
                "dd_ok": ev["max_dd"] >= -MAX_DD,
                "no_liq": base["liquidations"] == 0,
                "halves_pos": h1["excess_ann"] > 0 and h2["excess_ann"] > 0,
                "cost_x2_pos": x2["excess_ann"] > 0,
            }
            res["combos"][key] = {**ev, "liquidations": base["liquidations"],
                                  "rebalances": base["rebalances"], "entries": base["entries"],
                                  "excess_h1": h1["excess_ann"], "excess_h2": h2["excess_ann"],
                                  "excess_cost_x2": x2["excess_ann"], "checks": checks,
                                  "passes": all(checks.values())}
            ctx = simulate(g, CONTEXT_START, DECISION_START, v)
            yearly = ctx["curve"].resample("YE").last()
            yr = (yearly / yearly.shift(1).fillna(ctx["curve"].iloc[0]) - 1)
            res["context"][key] = {"by_year_return": {str(k.year): float(x) for k, x in yr.items()},
                                   "liquidations": ctx["liquidations"]}
            log(f"{key}: exceso {ev['excess_ann']:+.2%} t={ev['t_weekly']} "
                f"-> {'PASA' if res['combos'][key]['passes'] else 'NO PASA'}")
    res["verdict"] = any(c["passes"] for c in res["combos"].values())
    (report / "results.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    log(f"VEREDICTO H-FC1: {'PASA' if res['verdict'] else 'NO PASA'}")
    print(json.dumps(res, indent=1, default=str))


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--out", required=True)
    s = sub.add_parser("study")
    s.add_argument("--data", required=True)
    s.add_argument("--report", required=True)
    a = ap.parse_args()
    if a.cmd == "download":
        download(Path(a.out))
    else:
        study(Path(a.data), Path(a.report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
