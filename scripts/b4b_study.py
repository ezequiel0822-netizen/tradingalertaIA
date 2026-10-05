"""B4b — evaluación: short perp Hyperliquid / long perp Binance, BTC y ETH (k = 2).

Implementa EXACTAMENTE research/HIPOTESIS_2026-10-04_B4b_forward.md (commit 8febc1a,
commiteado antes de bajar datos). Research-only: no importa `app`, no toca el bot.

  python scripts/b4b_study.py download-secondary --out <dir>
  python scripts/b4b_study.py secondary --data <dir> --report <dir>
  python scripts/b4b_study.py forward --collector <dir> --out <dir> --report <dir>
      (se niega a correr antes de T1 + 1 día: pre-registro §8)
Verificación con datos sintéticos: python scripts/b4b_selftest.py

Detalles de implementación que el pre-registro no fija (decididos ANTES de ver datos):
  a) Salida al CIERRE de la última vela 1 h (= apertura de la siguiente, mercado
     continuo). Así la secundaria no necesita bajar la vela de las 00:00 del 2024-10-01,
     que cae en la ventana prohibida. Igual en ambas ventanas.
  b) S0 se corre hacia adelante (≤ 6 días) para que S1 − S0 sea un número entero de
     semanas (los retornos son bloques de 7 días).
  c) Vela faltante: o = h = l = c = cierre anterior; cuenta para el gate del 1 %.
  d) Funding de Binance: faltantes contra la grilla de 8 h (00/08/16 UTC); liquidaciones
     fuera de esa grilla se reportan y se cobran igual. Marcas redondeadas a la hora.
  e) Funding de BOTH venues en τ se valúa al cierre de la vela que termina en τ.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# ---- parámetros CONGELADOS por el pre-registro (8febc1a) ---------------------------
PREREG = "research/HIPOTESIS_2026-10-04_B4b_forward.md @ 8febc1a"
T0 = pd.Timestamp("2026-10-06 00:00", tz="UTC")   # commit 2026-10-05 05:35 UTC
T1 = T0 + pd.Timedelta(days=182)                   # 2027-04-06 00:00 UTC
S1 = pd.Timestamp("2024-10-01 00:00", tz="UTC")
SEC_EARLIEST = pd.Timestamp("2023-05-01 00:00", tz="UTC")
# Adenda 1 (antes de correr la secundaria): Hyperliquid liquidó funding cada 8 h hasta
# 2023-06-08 00:00 UTC y cada hora desde 01:00 (verificado SOLO con marcas de tiempo,
# BTC y ETH). El §4 modela funding horario -> la secundaria arranca en el régimen horario.
SEC_HOURLY_FROM = pd.Timestamp("2023-06-08 01:00", tz="UTC")
LEV = 3.0
REB_TRIGGER = 0.20
REB_DELAY = pd.Timedelta(hours=24)
MM = {"BTC": (0.0125, 0.010), "ETH": (0.020, 0.010)}   # (Hyperliquid, Binance)
FEE_HL, FEE_BN, SLIP = 0.00045, 0.0005, 0.0002
SLIP_HL_PROXY = 0.0003
XFER_PCT, XFER_FIX = 0.0010, 5.0 / 10_000
T_CRIT, MAX_DD, NW_LAGS, MAX_MISSING = 2.50, 0.10, 4, 0.01
COINS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
H = pd.Timedelta(hours=1)
H_MS = 3_600_000

UA = {"User-Agent": "Mozilla/5.0 (research)"}
HL_INFO = "https://api.hyperliquid.xyz/info"
BN_FAPI = "https://fapi.binance.com/fapi/v1"
ARCHIVE = "https://data.binance.vision/data/futures/um"
NYFED = ("https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json"
         "?startDate={a}&endDate={b}")

_session: requests.Session | None = None


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


# ================================ RED ===============================================
def request(method: str, url: str, **kw) -> bytes | None:
    """Bytes de la respuesta; None si 404 (archivo inexistente)."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(UA)
    last: Exception | None = None
    for attempt in range(6):
        try:
            r = _session.request(method, url, timeout=90, **kw)
            if r.status_code == 404:
                return None
            if r.status_code in (418, 429) or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{method} {url} falló: {last}")


def record(manifest: list, name: str, raw: bytes, rows: int | None = None,
           official: str | None = None, raw_dir: Path | None = None) -> dict:
    sha = hashlib.sha256(raw).hexdigest()
    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)
        with gzip.open(raw_dir / f"{name}.gz", "wb") as f:
            f.write(raw)
    entry = {"file": name, "bytes": len(raw), "rows": rows, "sha256": sha,
             "official_sha256": official or "",
             "checksum_ok": (sha == official) if official else ""}
    manifest.append(entry)
    return entry


def hl_paged(kind: str, coin: str, start: int, end: int, manifest: list,
             raw_dir: Path) -> list[dict]:
    """fundingHistory o candleSnapshot 1h, paginado (máx. 500 por respuesta)."""
    out, t, page = [], start, 0
    while t <= end:
        if kind == "funding":
            body = {"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": end}
        else:
            body = {"type": "candleSnapshot",
                    "req": {"coin": coin, "interval": "1h", "startTime": t, "endTime": end}}
        raw = request("POST", HL_INFO, json=body)
        d = json.loads(raw)
        if not isinstance(d, list):
            raise RuntimeError(f"Hyperliquid {kind} {coin}: {str(d)[:200]}")
        record(manifest, f"hl_{kind}_{coin}_{page:04d}.json", raw, len(d), raw_dir=raw_dir)
        if not d:
            break
        out += d
        tkey = "time" if kind == "funding" else "t"
        last = max(int(x[tkey]) for x in d)
        if last < t:
            break
        t, page = last + (1 if kind == "funding" else H_MS), page + 1
        time.sleep(0.4)
    return out


def archive_csv(path: str, name: str, manifest: list) -> pd.DataFrame | None:
    """Archivo de data.binance.vision con checksum oficial; si no coincide se descarta."""
    url = f"{ARCHIVE}/{path}/{name}.zip"
    raw = request("GET", url)
    if raw is None:
        return None
    ck = request("GET", url + ".CHECKSUM")
    official = ck.decode().split()[0] if ck else "UNAVAILABLE"
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    first = text.split("\n", 1)[0].split(",")[0].strip()
    header = 0 if not first.lstrip("-").replace(".", "").isdigit() else None
    df = pd.read_csv(io.StringIO(text), header=header)
    e = record(manifest, f"{name}.zip", raw, len(df), official)
    return df if e["checksum_ok"] is True else None


def norm_klines(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza POR ARCHIVO y por posición (unos traen encabezado y otros no)."""
    k = df.iloc[:, :5].copy()
    k.columns = ["open_time_ms", "o", "h", "l", "c"]
    k = k.apply(pd.to_numeric, errors="coerce")
    if k.isna().any().any():
        raise ValueError("klines con NaN tras normalizar")
    ot = k["open_time_ms"].astype("int64")
    k["open_time_ms"] = ot.where(ot < 10**14, ot // 1000)   # µs -> ms
    return k


def norm_funding(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame({"time_ms": pd.to_numeric(df.iloc[:, 0], errors="coerce"),
                      "fundingRate": pd.to_numeric(df.iloc[:, -1], errors="coerce")})
    if f.isna().any().any():
        raise ValueError("funding con NaN tras normalizar")
    return f


def months(a: pd.Timestamp, b: pd.Timestamp) -> list[str]:
    return pd.period_range(a.strftime("%Y-%m"), b.strftime("%Y-%m"), freq="M").strftime("%Y-%m").tolist()


def effr_download(a: pd.Timestamp, b: pd.Timestamp, manifest: list) -> pd.DataFrame:
    raw = request("GET", NYFED.format(a=a.strftime("%Y-%m-%d"), b=b.strftime("%Y-%m-%d")))
    js = json.loads(raw)["refRates"]
    record(manifest, f"effr_{a:%Y%m%d}_{b:%Y%m%d}.json", raw, len(js))
    return pd.DataFrame({"date": [r["effectiveDate"] for r in js],
                         "rate": [float(r["percentRate"]) / 100 for r in js]}).sort_values("date")


# ================================ SERIES ============================================
def utc_index(ms_values) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(np.asarray(ms_values, dtype="int64"), unit="ms",
                                           utc=True)).as_unit("ns")


def funding_series(df: pd.DataFrame) -> tuple[pd.Series, int]:
    """Columnas time_ms, fundingRate -> serie por hora de liquidación (redondeo a la hora)."""
    idx = utc_index(df["time_ms"].astype("int64")).floor("h")
    s = pd.Series(df["fundingRate"].astype(float).to_numpy(), index=idx)
    dup = int(s.index.duplicated().sum())
    return s.groupby(level=0).sum().sort_index(), dup


def px_frame(df: pd.DataFrame, tcol: str) -> pd.DataFrame:
    idx = utc_index(df[tcol].astype("int64"))
    p = pd.DataFrame({c: df[c].astype(float).to_numpy() for c in ("o", "h", "l", "c")}, index=idx)
    return p[~p.index.duplicated(keep="last")].sort_index()


def build_grid(start: pd.Timestamp, end: pd.Timestamp, bn_px: pd.DataFrame,
               hl_px: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    """Grilla horaria [start, end): velas por apertura. hl_px None -> proxy = Binance."""
    idx = pd.date_range(start, end - H, freq="h", unit="ns")

    def fill(px: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        p = px.reindex(idx)
        miss = int(p["c"].isna().sum())
        c = p["c"].ffill().bfill()
        for col in ("o", "h", "l"):
            p[col] = p[col].fillna(c)
        p["c"] = c
        return p, miss

    bn, mb = fill(bn_px)
    if hl_px is None:
        hl, mh = bn.copy(), None
    else:
        hl, mh = fill(hl_px)
    g = pd.DataFrame({"hl_o": hl["o"], "hl_h": hl["h"], "hl_l": hl["l"], "hl_c": hl["c"],
                      "bn_o": bn["o"], "bn_h": bn["h"], "bn_l": bn["l"], "bn_c": bn["c"]},
                     index=idx)
    return g, {"bars": len(idx), "missing_bn_bars": mb, "missing_hl_bars": mh}


def funding_quality(f_hl: pd.Series, f_bn: pd.Series, start: pd.Timestamp,
                    end: pd.Timestamp) -> dict:
    exp_hl = pd.date_range(start + H, end, freq="h", unit="ns")
    miss_hl = int((~exp_hl.isin(f_hl.index)).sum())
    grid8 = pd.date_range(start.ceil("8h") if start.ceil("8h") > start else start + pd.Timedelta(hours=8),
                          end, freq="8h", unit="ns")
    miss_bn = int((~grid8.isin(f_bn.index)).sum())
    in_win = f_bn.index[(f_bn.index > start) & (f_bn.index <= end)]
    off_grid = int((in_win.hour % 8 != 0).sum())
    return {"expected_hl_funding": len(exp_hl), "missing_hl_funding": miss_hl,
            "expected_bn_funding": len(grid8), "missing_bn_funding": miss_bn,
            "bn_funding_off_grid": off_grid}


def quality_verdict(gq: dict, fq: dict) -> dict:
    fr = {"hl_funding": fq["missing_hl_funding"] / max(fq["expected_hl_funding"], 1),
          "bn_funding": fq["missing_bn_funding"] / max(fq["expected_bn_funding"], 1),
          "bn_bars": gq["missing_bn_bars"] / max(gq["bars"], 1)}
    if gq["missing_hl_bars"] is not None:
        fr["hl_bars"] = gq["missing_hl_bars"] / max(gq["bars"], 1)
    return {**gq, **fq, "missing_fraction": fr,
            "valid": all(v <= MAX_MISSING for v in fr.values())}


# ================================ SIMULACIÓN =========================================
def simulate(grid: pd.DataFrame, f_hl: pd.Series, f_bn: pd.Series, coin: str,
             cost_mult: float = 1.0, slip_hl_extra: float = 0.0) -> dict:
    """Libro de un activo, capital 1 (mitad por venue), pre-registro §4-§5."""
    mm_hl, mm_bn = MM[coin]
    c_hl = cost_mult * (FEE_HL + SLIP + slip_hl_extra)
    c_bn = cost_mult * (FEE_BN + SLIP)
    xp, xf = cost_mult * XFER_PCT, cost_mult * XFER_FIX
    idx = grid.index
    n = len(idx)
    taus = idx + H
    fh = f_hl.reindex(taus).fillna(0.0).to_numpy(float)
    fb = f_bn.reindex(taus).fillna(0.0).to_numpy(float)
    ho, hh, hc = (grid[c].to_numpy(float) for c in ("hl_o", "hl_h", "hl_c"))
    bo, bl, bc = (grid[c].to_numpy(float) for c in ("bn_o", "bn_l", "bn_c"))

    q = LEV * 0.5 / bo[0]                       # N = 1.5 C con C = 1; mismas monedas
    entry = c_hl * q * ho[0] + c_bn * q * bo[0]
    e_hl, e_bn = 0.5 - c_hl * q * ho[0], 0.5 - c_bn * q * bo[0]
    m_hl, m_bn = ho[0], bo[0]
    curve = np.empty(n + 1)
    curve[0] = 1.0
    alive, pending = True, None
    liqs, rebs = [], []
    fund_hl = fund_bn = 0.0
    cost_trade, cost_xfer = entry, 0.0
    for k in range(n):
        tau = taus[k]
        if alive:
            lh = e_hl - q * (hh[k] - m_hl) <= mm_hl * q * hh[k]
            lb = e_bn + q * (bl[k] - m_bn) <= mm_bn * q * bl[k]
            if lh or lb:
                ch = 0.0 if lh else c_hl * q * hc[k]
                cb = 0.0 if lb else c_bn * q * bc[k]
                e_hl = 0.0 if lh else max(e_hl - q * (hc[k] - m_hl) - ch, 0.0)
                e_bn = 0.0 if lb else max(e_bn + q * (bc[k] - m_bn) - cb, 0.0)
                cost_trade += ch + cb
                liqs.append({"time": str(idx[k]), "legs": ("HL " if lh else "") + ("BN" if lb else "")})
                alive, q, pending = False, 0.0, None
            else:
                ph, pb = q * hc[k] * fh[k], q * bc[k] * fb[k]
                e_hl += ph
                e_bn -= pb
                fund_hl += ph
                fund_bn += pb
                e_hl -= q * (hc[k] - m_hl)
                e_bn += q * (bc[k] - m_bn)
                m_hl, m_bn = hc[k], bc[k]
                if k == n - 1:                   # salida al cierre de la última vela
                    ch, cb = c_hl * q * hc[k], c_bn * q * bc[k]
                    e_hl -= ch
                    e_bn -= cb
                    cost_trade += ch + cb
                else:
                    if pending is not None and tau >= pending:
                        E = e_hl + e_bn
                        X = abs(e_hl - E / 2)
                        tc = xp * X + xf
                        Ea = E - tc
                        qn = LEV * 0.5 * Ea / bc[k]
                        dq = abs(qn - q)
                        th, tb = c_hl * dq * hc[k], c_bn * dq * bc[k]
                        e_hl, e_bn = Ea / 2 - th, Ea / 2 - tb
                        rebs.append({"time": str(tau), "transfer": X, "q_old": q, "q_new": qn})
                        q, pending = qn, None
                        cost_xfer += tc
                        cost_trade += th + tb
                    if pending is None and min(e_hl / (q * hc[k]), e_bn / (q * bc[k])) < REB_TRIGGER:
                        pending = tau + REB_DELAY
        curve[k + 1] = e_hl + e_bn
    times = pd.DatetimeIndex([idx[0]]).append(taus)
    return {"curve": pd.Series(curve, index=times), "liquidations": liqs, "rebalances": rebs,
            "funding_hl_received": fund_hl, "funding_bn_paid": fund_bn,
            "cost_trading": cost_trade, "cost_transfer": cost_xfer}


# ================================ EVALUACIÓN =========================================
def effr_daily(effr: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    days = pd.date_range(start.normalize(), (end - pd.Timedelta(days=1)).normalize(),
                         freq="D", unit="ns")
    s = effr.sort_index()
    out = s.reindex(s.index.union(days)).ffill().reindex(days)
    if out.isna().any():
        raise ValueError("EFFR sin dato as-of para algún día de la ventana")
    return out


def nw_t(x, lags: int = NW_LAGS) -> float | None:
    """t de la media con varianza de largo plazo Newey-West (kernel de Bartlett)."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 3:
        return None
    d = x - x.mean()
    lrv = float(d @ d) / n
    for lag in range(1, min(lags, n - 1) + 1):
        lrv += 2.0 * (1.0 - lag / (lags + 1.0)) * float(d[lag:] @ d[:-lag]) / n
    if lrv <= 0:
        return None
    return float(x.mean() / math.sqrt(lrv / n))


def evaluate(curve: pd.Series, effr: pd.Series, start: pd.Timestamp,
             end: pd.Timestamp) -> dict:
    bounds = pd.date_range(start, end, freq="7D", unit="ns")
    if bounds[-1] != end:
        raise ValueError("la ventana no es un número entero de semanas")
    eq = curve.reindex(bounds)
    if eq.isna().any():
        raise ValueError("faltan puntos de la curva en los bordes semanales")
    e = eq.to_numpy()
    r = e[1:] / e[:-1] - 1.0
    rf_d = effr_daily(effr, start, end)
    rf = np.array([np.prod(1.0 + rf_d[(rf_d.index >= a) & (rf_d.index < b)].to_numpy() / 360.0) - 1.0
                   for a, b in zip(bounds[:-1], bounds[1:])])
    exc = r - rf
    n = len(exc)
    h = n // 2
    sd = exc.std(ddof=1) if n > 1 else 0.0
    return {"weeks": n, "total_return": float(e[-1] / e[0] - 1.0),
            "excess_ann": float(exc.mean() * 52), "t_nw": nw_t(exc),
            "t_simple": float(exc.mean() / (sd / math.sqrt(n))) if sd > 0 else None,
            "max_dd": float((curve / curve.cummax() - 1.0).min()),
            "excess_half1_ann": float(exc[:h].mean() * 52) if h else None,
            "excess_half2_ann": float(exc[h:].mean() * 52),
            "rf_ann_mean": float(rf.mean() * 52), "weekly_excess": [float(v) for v in exc]}


def verdict(ev: dict, ev2: dict, n_liq: int, quality: dict) -> dict:
    checks = {
        "1_exceso_neto>0": ev["excess_ann"] > 0,
        "2_t_NW>=2.50": ev["t_nw"] is not None and ev["t_nw"] >= T_CRIT,
        "3_maxDD<=10%": ev["max_dd"] >= -MAX_DD,
        "4_cero_liquidaciones": n_liq == 0,
        "5_ambas_mitades>0": (ev["excess_half1_ann"] or 0) > 0 and ev["excess_half2_ann"] > 0,
        "6_costos_x2>0": ev2["excess_ann"] > 0,
        "7_datos_validos": bool(quality["valid"]),
    }
    return {"checks": checks, "pasa": all(checks.values())}


def run_window(coin: str, grid: pd.DataFrame, f_hl: pd.Series, f_bn: pd.Series,
               effr: pd.Series, start: pd.Timestamp, end: pd.Timestamp,
               slip_hl_extra: float, quality: dict) -> dict:
    base = simulate(grid, f_hl, f_bn, coin, 1.0, slip_hl_extra)
    stress = simulate(grid, f_hl, f_bn, coin, 2.0, slip_hl_extra)
    ev = evaluate(base["curve"], effr, start, end)
    ev2 = evaluate(stress["curve"], effr, start, end)
    v = verdict(ev, ev2, len(base["liquidations"]), quality)
    years = (end - start) / pd.Timedelta(days=365.25)
    wf = (f_hl.index > start) & (f_hl.index <= end)
    bf = (f_bn.index > start) & (f_bn.index <= end)
    diag = {  # descriptivo, NO decide
        "hl_funding_ann": float(f_hl[wf].sum() / years),
        "bn_funding_ann": float(f_bn[bf].sum() / years),
        "spread_ann": float(f_hl[wf].sum() / years - f_bn[bf].sum() / years),
        "n_rebalances": len(base["rebalances"]),
        "cost_trading": base["cost_trading"], "cost_transfer": base["cost_transfer"],
        "funding_hl_received": base["funding_hl_received"],
        "funding_bn_paid": base["funding_bn_paid"],
    }
    return {"coin": coin, "start": str(start), "end": str(end), "quality": quality,
            "base": {k: v2 for k, v2 in ev.items() if k != "weekly_excess"},
            "stress_x2": {k: v2 for k, v2 in ev2.items() if k != "weekly_excess"},
            "weekly_excess_base": ev["weekly_excess"],
            "liquidations": base["liquidations"], "liquidations_x2": stress["liquidations"],
            "rebalances": base["rebalances"], "diagnostics_posthoc": diag, **v}


def align_start(s0_raw: pd.Timestamp, end: pd.Timestamp) -> pd.Timestamp:
    weeks = int((end - s0_raw) // pd.Timedelta(days=7))
    return end - pd.Timedelta(days=7 * weeks)


def secondary_start(first_hl: pd.Timestamp, first_bn: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(S0 crudo, S0 alineado a semanas enteras antes de S1). Adenda 1: régimen horario."""
    s0_raw = max(first_hl, first_bn, SEC_EARLIEST, SEC_HOURLY_FROM).ceil("D")
    return s0_raw, align_start(s0_raw, S1)


def assert_forward_allowed(now: pd.Timestamp) -> None:
    if now < T1 + pd.Timedelta(days=1):
        raise SystemExit(f"pre-registro §8: la ventana decisoria no se evalúa antes de "
                         f"{T1 + pd.Timedelta(days=1)} (ahora {now}). Nada se calculó.")


# ================================ SECUNDARIA ==========================================
def download_secondary(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    raw_dir = out / "raw"
    end_ms = ms(S1) + 1000                       # τ = S1 cuenta (apertura < τ <= cierre)
    for coin, sym in COINS.items():
        d = hl_paged("funding", coin, ms(SEC_EARLIEST), end_ms, manifest, raw_dir)
        f = pd.DataFrame({"time_ms": [int(x["time"]) for x in d],
                          "fundingRate": [str(x["fundingRate"]) for x in d],
                          "premium": [str(x.get("premium", "")) for x in d]})
        f = f.drop_duplicates("time_ms").sort_values("time_ms")
        f = f[(f["time_ms"] >= ms(SEC_EARLIEST)) & (f["time_ms"] <= end_ms)]
        f.to_csv(out / f"hl_funding_{coin}.csv", index=False)
        log(f"HL funding {coin}: {len(f):,} filas, desde "
            f"{pd.to_datetime(f['time_ms'].min(), unit='ms', utc=True)}")

        frames = []
        for m in months(SEC_EARLIEST, S1 - pd.Timedelta(days=1)):
            df = archive_csv(f"monthly/fundingRate/{sym}", f"{sym}-fundingRate-{m}", manifest)
            if df is not None:
                frames.append(norm_funding(df))
            else:
                log(f"  falta/descartado funding {sym} {m}")
        # la liquidación de τ = S1 (2024-10-01 00:00) está en el mensual de octubre
        # (ventana prohibida): se pide SOLO esa fila por REST.
        raw = request("GET", f"{BN_FAPI}/fundingRate",
                      params={"symbol": sym, "startTime": ms(S1), "endTime": ms(S1) + 60_000})
        rows = json.loads(raw)
        record(manifest, f"bn_funding_rest_{sym}_S1.json", raw, len(rows), raw_dir=raw_dir)
        frames.append(pd.DataFrame({"time_ms": [int(x["fundingTime"]) for x in rows],
                                    "fundingRate": [float(x["fundingRate"]) for x in rows]}))
        bf = pd.concat(frames, ignore_index=True).drop_duplicates("time_ms").sort_values("time_ms")
        bf = bf[(bf["time_ms"] >= ms(SEC_EARLIEST)) & (bf["time_ms"] <= ms(S1) + 60_000)]
        bf.to_csv(out / f"bn_funding_{sym}.csv", index=False)
        log(f"Binance funding {sym}: {len(bf):,} filas")

        frames = []
        for m in months(SEC_EARLIEST, S1 - pd.Timedelta(days=1)):
            df = archive_csv(f"monthly/klines/{sym}/1h", f"{sym}-1h-{m}", manifest)
            if df is not None:
                frames.append(norm_klines(df))
            else:
                log(f"  falta/descartado klines {sym} {m}")
        kl = pd.concat(frames, ignore_index=True).drop_duplicates("open_time_ms")
        kl = kl[(kl["open_time_ms"] >= ms(SEC_EARLIEST)) & (kl["open_time_ms"] < ms(S1))]
        kl.sort_values("open_time_ms").to_csv(out / f"bn_klines_1h_{sym}.csv", index=False)
        log(f"Binance klines 1h {sym}: {len(kl):,} velas")

    effr_download(SEC_EARLIEST - pd.Timedelta(days=15), S1, manifest).to_csv(out / "effr.csv", index=False)
    man = pd.DataFrame(manifest)
    man.to_csv(out / "manifest.csv", index=False)
    arch = man[man["official_sha256"] != ""]
    log(f"manifest: {len(man)} archivos; checksums oficiales OK "
        f"{int((arch['checksum_ok'] == True).sum())}/{len(arch)}")  # noqa: E712


def load_effr(path: Path) -> pd.Series:
    d = pd.read_csv(path)
    return pd.Series(d["rate"].astype(float).to_numpy(),
                     index=pd.DatetimeIndex(pd.to_datetime(d["date"], utc=True)).as_unit("ns")).sort_index()


def secondary(data: Path, report: Path) -> dict:
    report.mkdir(parents=True, exist_ok=True)
    effr = load_effr(data / "effr.csv")
    results = {}
    for coin, sym in COINS.items():
        f_hl, dup_h = funding_series(pd.read_csv(data / f"hl_funding_{coin}.csv"))
        f_bn, dup_b = funding_series(pd.read_csv(data / f"bn_funding_{sym}.csv"))
        f_hl, f_bn = f_hl[f_hl.index <= S1], f_bn[f_bn.index <= S1]
        bn_px = px_frame(pd.read_csv(data / f"bn_klines_1h_{sym}.csv"), "open_time_ms")
        bn_px = bn_px[bn_px.index < S1]
        s0_raw, s0 = secondary_start(f_hl.index.min(), bn_px.index.min())
        grid, gq = build_grid(s0, S1, bn_px, None)
        q = quality_verdict(gq, funding_quality(f_hl, f_bn, s0, S1))
        q.update({"dup_hl_funding": dup_h, "dup_bn_funding": dup_b, "s0_raw": str(s0_raw)})
        res = run_window(coin, grid, f_hl, f_bn, effr, s0, S1, SLIP_HL_PROXY, q)
        results[coin] = res
        log(f"{coin} secundaria {s0:%Y-%m-%d} -> {S1:%Y-%m-%d}: PASA={res['pasa']} "
            f"exceso {res['base']['excess_ann']:+.4f} t_NW {res['base']['t_nw']} "
            f"DD {res['base']['max_dd']:.4f} liq {len(res['liquidations'])}")
    out = {"prereg": PREREG, "window": "secundaria", "generated_utc": str(pd.Timestamp.now(tz="UTC")),
           "results": results}
    (report / "b4b_secondary_result.json").write_text(json.dumps(out, indent=2, default=str),
                                                      encoding="utf-8")
    return out


# ================================ DECISORIA (hacia adelante) ==========================
def forward(collector: Path, out: Path, report: Path, now: pd.Timestamp | None = None) -> dict:
    assert_forward_allowed(now or pd.Timestamp.now(tz="UTC"))
    out.mkdir(parents=True, exist_ok=True)
    report.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    raw_dir = out / "raw"
    cdata = collector / "data"
    effr_df = effr_download(T0 - pd.Timedelta(days=15), T1, manifest)
    effr_df.to_csv(out / "effr.csv", index=False)
    effr = load_effr(out / "effr.csv")
    results, notes = {}, {}
    for coin, sym in COINS.items():
        note: dict = {}
        # funding HL: se re-baja (inmutable) y se compara con el colector (§7)
        d = hl_paged("funding", coin, ms(T0) - H_MS, ms(T1) + 1000, manifest, raw_dir)
        rep = pd.DataFrame({"time_ms": [int(x["time"]) for x in d],
                            "fundingRate": [str(x["fundingRate"]) for x in d]}).drop_duplicates("time_ms")
        col = pd.read_csv(cdata / f"hl_funding_{coin}.csv", dtype=str)
        col["time_ms"] = col["time_ms"].astype("int64")
        m = rep.merge(col[["time_ms", "fundingRate"]], on="time_ms", how="outer",
                      suffixes=("_repull", "_collector"))
        both = m.dropna()
        note["hl_funding_mismatch"] = int((both["fundingRate_repull"] != both["fundingRate_collector"]).sum())
        only_col = m[m["fundingRate_repull"].isna() & (m["time_ms"] > ms(T0) - H_MS)
                     & (m["time_ms"] <= ms(T1) + 1000)]
        note["hl_funding_only_in_collector"] = len(only_col)
        hlf = pd.concat([rep, only_col.rename(columns={"fundingRate_collector": "fundingRate"})[["time_ms", "fundingRate"]]])
        f_hl, dup_h = funding_series(hlf)

        # velas HL: colector + re-bajada si T0 todavía está dentro de las 5000 velas
        hc = pd.read_csv(cdata / f"hl_candles_1h_{coin}.csv", dtype=str)
        frames = [hc[["t_ms", "o", "h", "l", "c"]]]
        try:
            dc = hl_paged("candles", coin, ms(T0), ms(T1) - 1, manifest, raw_dir)
            rc = pd.DataFrame({"t_ms": [str(int(x["t"])) for x in dc], "o": [str(x["o"]) for x in dc],
                               "h": [str(x["h"]) for x in dc], "l": [str(x["l"]) for x in dc],
                               "c": [str(x["c"]) for x in dc]})
            mm_ = rc.merge(hc[["t_ms", "o", "h", "l", "c"]], on="t_ms", suffixes=("_r", "_c"))
            note["hl_candle_mismatch"] = int(sum((mm_[f"{x}_r"] != mm_[f"{x}_c"]).sum() for x in "ohlc"))
            frames.append(rc)
        except Exception as e:  # noqa: BLE001
            note["hl_candle_repull_error"] = str(e)
        hl_all = pd.concat(frames, ignore_index=True).drop_duplicates("t_ms", keep="first")
        hl_px = px_frame(hl_all.astype({"t_ms": "int64"}), "t_ms")

        # Binance: archivos oficiales; lo que falte, REST del colector (rotulado)
        bfr, kfr = [], []
        for mth in months(T0, T1):
            df = archive_csv(f"monthly/fundingRate/{sym}", f"{sym}-fundingRate-{mth}", manifest)
            if df is not None:
                bfr.append(norm_funding(df))
            dk = archive_csv(f"monthly/klines/{sym}/1h", f"{sym}-1h-{mth}", manifest)
            if dk is not None:
                kfr.append(norm_klines(dk))
            else:
                for day in pd.date_range(f"{mth}-01", periods=31, freq="D"):
                    if day.strftime("%Y-%m") != mth or day >= T1.tz_localize(None):
                        continue
                    dd = archive_csv(f"daily/klines/{sym}/1h", f"{sym}-1h-{day:%Y-%m-%d}", manifest)
                    if dd is not None:
                        kfr.append(norm_klines(dd))
        rest_f = pd.read_csv(cdata / f"bn_funding_{sym}.csv")[["time_ms", "fundingRate"]]
        rest_k = pd.read_csv(cdata / f"bn_klines_1h_{sym}.csv")[["open_time_ms", "o", "h", "l", "c"]]
        arch_f = pd.concat(bfr, ignore_index=True) if bfr else rest_f.iloc[0:0]
        arch_k = pd.concat(kfr, ignore_index=True) if kfr else rest_k.iloc[0:0]
        ov = arch_f.merge(rest_f, on="time_ms", suffixes=("_a", "_r"))
        note["bn_funding_archive_vs_rest_maxdiff"] = float((ov["fundingRate_a"] - ov["fundingRate_r"]).abs().max()) if len(ov) else None
        ovk = arch_k.merge(rest_k, on="open_time_ms", suffixes=("_a", "_r"))
        note["bn_klines_archive_vs_rest_maxreldiff"] = float(max(((ovk[f"{x}_a"] - ovk[f"{x}_r"]).abs() / ovk[f"{x}_a"]).max() for x in "ohlc")) if len(ovk) else None
        fill_f = rest_f[~rest_f["time_ms"].floordiv(H_MS).isin(arch_f["time_ms"].floordiv(H_MS))]
        fill_k = rest_k[~rest_k["open_time_ms"].isin(arch_k["open_time_ms"])]
        note["bn_funding_from_rest"] = len(fill_f)
        note["bn_klines_from_rest"] = len(fill_k)
        f_bn, dup_b = funding_series(pd.concat([arch_f, fill_f], ignore_index=True))
        bn_px = px_frame(pd.concat([arch_k, fill_k], ignore_index=True), "open_time_ms")

        f_hl = f_hl[(f_hl.index > T0 - H) & (f_hl.index <= T1)]
        f_bn = f_bn[(f_bn.index > T0 - pd.Timedelta(hours=8)) & (f_bn.index <= T1)]
        grid, gq = build_grid(T0, T1, bn_px[(bn_px.index >= T0) & (bn_px.index < T1)],
                              hl_px[(hl_px.index >= T0) & (hl_px.index < T1)])
        q = quality_verdict(gq, funding_quality(f_hl, f_bn, T0, T1))
        q.update({"dup_hl_funding": dup_h, "dup_bn_funding": dup_b})
        results[coin] = run_window(coin, grid, f_hl, f_bn, effr, T0, T1, 0.0, q)
        notes[coin] = note
        log(f"{coin} decisoria: PASA={results[coin]['pasa']}")
    pd.DataFrame(manifest).to_csv(out / "manifest.csv", index=False)
    res = {"prereg": PREREG, "window": "decisoria", "generated_utc": str(pd.Timestamp.now(tz="UTC")),
           "results": results, "data_notes": notes}
    (report / "b4b_forward_result.json").write_text(json.dumps(res, indent=2, default=str),
                                                    encoding="utf-8")
    return res


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consola cp1252
    ap = argparse.ArgumentParser(description="B4b (pre-registro 8febc1a)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("download-secondary")
    a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("secondary")
    b.add_argument("--data", type=Path, required=True)
    b.add_argument("--report", type=Path, required=True)
    c = sub.add_parser("forward")
    c.add_argument("--collector", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "download-secondary":
        download_secondary(args.out)
    elif args.cmd == "secondary":
        secondary(args.data, args.report)
    else:
        forward(args.collector, args.out, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
