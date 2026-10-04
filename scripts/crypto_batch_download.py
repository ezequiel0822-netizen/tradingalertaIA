"""Descarga de la tanda cripto 2026-10-04b (H-FC2, H-XS1, H-POS1).

Pre-registro: research/HIPOTESIS_2026-10-04b_cripto_batch.md (commiteado antes).
Universo point-in-time: perpetuos USDⓈ-M con funding (incluye deslistados) que tienen
par spot del mismo nombre; sin "1000…", no-ASCII ni bases estables. Meses 2024-07 →
2026-09 (si falta el mensual de spot del último mes, completa con diarios). Además
`metrics` diario de BTCUSDT y ETHUSDT. Manifest con checksums oficiales.

Uso: python scripts/crypto_batch_download.py --out <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
BASE = "https://data.binance.vision/data"
UA = {"User-Agent": "Mozilla/5.0 (research)"}
MONTHS = pd.period_range("2024-07", "2026-09", freq="M").strftime("%Y-%m").tolist()
METRICS_START, METRICS_END = date(2024, 6, 1), date(2026, 9, 30)
STABLE = ("USDC", "FDUSD", "TUSD", "BUSD", "USDP", "DAI", "EUR", "AEUR", "USDE")
KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume"]

_local = threading.local()


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(UA)
    return _local.s


def get(url: str) -> bytes | None:
    for _ in range(3):
        try:
            r = session().get(url, timeout=60)
            if r.status_code == 404:
                return None
            if r.ok:
                return r.content
        except requests.RequestException:
            pass
    return None


def prefixes(prefix: str) -> list[str]:
    out, marker = [], ""
    while True:
        x = get(f"{S3}?delimiter=/&prefix={prefix}&marker={marker}").decode()
        ps = re.findall(r"<Prefix>([^<]+)</Prefix>", x)[1:]
        out += ps
        if "<IsTruncated>true</IsTruncated>" not in x:
            return [p.rstrip("/").split("/")[-1] for p in out]
        marker = ps[-1]


def universe() -> list[str]:
    fut = [s for s in prefixes("data/futures/um/monthly/fundingRate/") if s.endswith("USDT")]
    spot = set(prefixes("data/spot/monthly/klines/"))
    keep = []
    for s in fut:
        base = s[:-4]
        if s not in spot or not s.isascii() or s.startswith("1000") or base in STABLE:
            continue
        keep.append(s)
    return sorted(keep)


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
    return df, entry


def norm_klines(df: pd.DataFrame) -> pd.DataFrame:
    df = df.iloc[:, :8].copy()
    df.columns = KCOLS
    df = df.apply(pd.to_numeric, errors="coerce")
    for c in ("open_time", "close_time"):
        v = df[c].astype("int64")
        df[c] = v.where(v < 10**14, v // 1000)  # spot 2025+ en microsegundos
    return df


def norm_funding(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"calc_time": pd.to_numeric(df.iloc[:, 0], errors="coerce"),
                         "funding_rate": pd.to_numeric(df.iloc[:, -1], errors="coerce")})


def job_symbol(sym: str) -> tuple[dict, list]:
    out: dict = {"funding": [], "perp": [], "spot": []}
    manifest: list = []
    for m in MONTHS:
        for kind, path, name in (
            ("funding", f"futures/um/monthly/fundingRate/{sym}", f"{sym}-fundingRate-{m}"),
            ("perp", f"futures/um/monthly/klines/{sym}/8h", f"{sym}-8h-{m}"),
            ("spot", f"spot/monthly/klines/{sym}/8h", f"{sym}-8h-{m}"),
        ):
            df, entry = fetch(path, name)
            if df is None and kind == "spot" and m == MONTHS[-1]:
                parts = []
                for d in pd.date_range(f"{m}-01", f"{m}-30", freq="D"):
                    p, e = fetch(f"spot/daily/klines/{sym}/8h", f"{sym}-8h-{d:%Y-%m-%d}")
                    if p is not None:
                        parts.append(norm_klines(p))
                        manifest.append({**e, "symbol": sym, "kind": kind})
                if parts:
                    out[kind].append(pd.concat(parts, ignore_index=True))
                continue
            if df is None:
                continue
            manifest.append({**entry, "symbol": sym, "kind": kind})
            out[kind].append(norm_funding(df) if kind == "funding" else norm_klines(df))
    frames = {}
    for kind, parts in out.items():
        if parts:
            f = pd.concat(parts, ignore_index=True)
            f.insert(0, "symbol", sym)
            frames[kind] = f
    return frames, manifest


def job_metrics(sym: str) -> tuple[pd.DataFrame | None, list]:
    parts, manifest = [], []
    d = METRICS_START
    while d <= METRICS_END:
        df, e = fetch(f"futures/um/daily/metrics/{sym}", f"{sym}-metrics-{d:%Y-%m-%d}")
        if df is not None:
            parts.append(df)
            manifest.append({**e, "symbol": sym, "kind": "metrics"})
        d += timedelta(days=1)
    return (pd.concat(parts, ignore_index=True) if parts else None), manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=16)
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    syms = universe()
    log(f"universo: {len(syms)} símbolos")
    (out / "universe.txt").write_text("\n".join(syms), encoding="utf-8")
    acc: dict = {"funding": [], "perp": [], "spot": []}
    manifest: list = []
    done = 0
    with ThreadPoolExecutor(max_workers=args_workers(ap)) as ex:
        for frames, man in ex.map(job_symbol, syms):
            for k, f in frames.items():
                acc[k].append(f)
            manifest += man
            done += 1
            if done % 25 == 0:
                log(f"  {done}/{len(syms)} símbolos")
    for k, parts in acc.items():
        df = pd.concat(parts, ignore_index=True)
        bad = int(df.drop(columns="symbol").isna().any(axis=1).sum())
        if bad:
            raise ValueError(f"{k}: {bad} filas con NaN")
        df.to_parquet(out / f"{k}_all.parquet", index=False)
        log(f"{k}: {len(df):,} filas, {df['symbol'].nunique()} símbolos")
    for sym in ("BTCUSDT", "ETHUSDT"):
        met, man = job_metrics(sym)
        manifest += man
        met.to_parquet(out / f"metrics_{sym}.parquet", index=False)
        log(f"metrics {sym}: {len(met):,} filas")
    m = pd.DataFrame(manifest)
    m.to_csv(out / "manifest.csv", index=False)
    log(f"manifest: {len(m):,} archivos, checksums OK {int(m['checksum_ok'].sum()):,}/{len(m):,}")
    return 0


def args_workers(ap: argparse.ArgumentParser) -> int:
    return ap.parse_args().workers


if __name__ == "__main__":
    sys.exit(main())
