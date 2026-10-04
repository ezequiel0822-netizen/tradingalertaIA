"""Backfill H-MS1: BTCUSDT perp (Binance USDⓈ-M) bookTicker + aggTrades -> grilla 1 s.

Pre-registro: research/HIPOTESIS_2026-10-03_microestructura.md (commiteado ANTES).
Fuente pública: data.binance.vision (sin key). Por cada día: baja los dos zips,
agrega a 1 segundo (tiempo de exchange, UTC) y guarda un parquet chico; el zip se
borra al terminar (el disco casi no se usa). Reanudable: saltea días ya hechos.

Por segundo:
  bid, ask, bq, aq  -> estado L1 al cierre del segundo (NaN si aún no hubo update
                       ese día; el estudio hace forward-fill entre días)
  ofi               -> suma del OFI de Cont-Kukanov-Stoikov sobre los eventos L1
  n_upd             -> nº de updates del bookTicker
  buy_vol, sell_vol -> volumen agresor comprador / vendedor (is_buyer_maker)
  n_tr              -> nº de aggTrades

Research-only: no importa nada de `app`, no toca la DB viva ni el bot.

Uso:
  python scripts/microstructure_backfill.py --start 2023-08-01 --end 2023-10-31 \
      --out C:/Users/LENOVO/tradingalertaIA/trading_data/binance_micro/BTCUSDT_1s
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/daily"
SYMBOL = "BTCUSDT"
UA = {"User-Agent": "Mozilla/5.0 (research)"}

BOOK_COLS = ["update_id", "best_bid_price", "best_bid_qty", "best_ask_price",
             "best_ask_qty", "transaction_time", "event_time"]
AGG_COLS = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
            "transact_time", "is_buyer_maker"]


def _download(url: str, dest: Path, retries: int = 5) -> None:
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
            with zipfile.ZipFile(dest) as zf:  # integridad
                if zf.testzip() is not None:
                    raise IOError("zip corrupto")
            return
        except Exception as exc:  # reintento con backoff
            if attempt == retries:
                raise
            print(f"  retry {attempt} {url}: {exc}", flush=True)
            time.sleep(10 * attempt)


def _read_zip_csv(path: Path, names: list[str], usecols: list[str], dtypes: dict) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        inner = zf.namelist()[0]
        with zf.open(inner) as fh:
            first = fh.readline().decode("utf-8", "replace")
    has_header = not first.split(",")[0].strip().lstrip("-").isdigit()
    return pd.read_csv(
        path, compression="zip", header=0 if has_header else None,
        names=names, usecols=usecols, dtype=dtypes, engine="c",
    )


def _book_per_second(path: Path, day_start: int) -> pd.DataFrame:
    df = _read_zip_csv(
        path, BOOK_COLS,
        ["update_id", "best_bid_price", "best_bid_qty", "best_ask_price",
         "best_ask_qty", "transaction_time"],
        {"update_id": "int64", "best_bid_price": "float64", "best_bid_qty": "float64",
         "best_ask_price": "float64", "best_ask_qty": "float64",
         "transaction_time": "int64"},
    )
    df = df.sort_values(["transaction_time", "update_id"], kind="mergesort")
    pb = df["best_bid_price"].to_numpy()
    qb = df["best_bid_qty"].to_numpy()
    pa = df["best_ask_price"].to_numpy()
    qa = df["best_ask_qty"].to_numpy()
    # OFI de Cont-Kukanov-Stoikov por evento (el 1er evento del día queda en 0).
    e = np.zeros(len(df))
    e[1:] = ((pb[1:] >= pb[:-1]) * qb[1:] - (pb[1:] <= pb[:-1]) * qb[:-1]
             - (pa[1:] <= pa[:-1]) * qa[1:] + (pa[1:] >= pa[:-1]) * qa[:-1])
    sec = (df["transaction_time"].to_numpy() // 1000).astype("int64")
    tmp = pd.DataFrame({"sec": sec, "bid": pb, "ask": pa, "bq": qb, "aq": qa, "ofi": e})
    g = tmp.groupby("sec", sort=True)
    out = g[["bid", "ask", "bq", "aq"]].last()
    out["ofi"] = g["ofi"].sum()
    out["n_upd"] = g.size().astype("int32")
    grid = pd.RangeIndex(day_start, day_start + 86_400, name="sec")
    out = out.reindex(grid)
    out[["bid", "ask", "bq", "aq"]] = out[["bid", "ask", "bq", "aq"]].ffill()
    out["ofi"] = out["ofi"].fillna(0.0)
    out["n_upd"] = out["n_upd"].fillna(0).astype("int32")
    return out


def _agg_per_second(path: Path, day_start: int) -> pd.DataFrame:
    df = _read_zip_csv(
        path, AGG_COLS, ["quantity", "transact_time", "is_buyer_maker"],
        {"quantity": "float64", "transact_time": "int64", "is_buyer_maker": "object"},
    )
    maker = df["is_buyer_maker"].astype(str).str.lower().isin(["true", "1"])
    sec = (df["transact_time"].to_numpy() // 1000).astype("int64")
    q = df["quantity"].to_numpy()
    tmp = pd.DataFrame({"sec": sec,
                        "buy_vol": np.where(maker, 0.0, q),   # taker comprador
                        "sell_vol": np.where(maker, q, 0.0)})  # taker vendedor
    g = tmp.groupby("sec", sort=True)
    out = g[["buy_vol", "sell_vol"]].sum()
    out["n_tr"] = g.size().astype("int32")
    grid = pd.RangeIndex(day_start, day_start + 86_400, name="sec")
    out = out.reindex(grid).fillna(0.0)
    out["n_tr"] = out["n_tr"].astype("int32")
    return out


def process_day(day: date, out_dir: Path, tmp_dir: Path) -> str:
    target = out_dir / f"{day.isoformat()}.parquet"
    if target.exists():
        return f"{day} skip (ya existe)"
    t0 = time.time()
    d = day.isoformat()
    day_start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    book_zip = tmp_dir / f"{SYMBOL}-bookTicker-{d}.zip"
    agg_zip = tmp_dir / f"{SYMBOL}-aggTrades-{d}.zip"
    try:
        _download(f"{BASE}/bookTicker/{SYMBOL}/{SYMBOL}-bookTicker-{d}.zip", book_zip)
        _download(f"{BASE}/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-{d}.zip", agg_zip)
        book = _book_per_second(book_zip, day_start)
        agg = _agg_per_second(agg_zip, day_start)
        out = book.join(agg, how="left").reset_index()
        tmpfile = target.with_suffix(".tmp")
        out.to_parquet(tmpfile, index=False)
        tmpfile.replace(target)
        filled = int(out["bid"].notna().sum())
        return (f"{day} ok {time.time() - t0:.0f}s | updates={int(out['n_upd'].sum()):,} "
                f"trades={int(out['n_tr'].sum()):,} seg_con_libro={filled}")
    finally:
        for z in (book_zip, agg_zip):
            z.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_dir / "_zips"
    tmp_dir.mkdir(exist_ok=True)
    d0 = date.fromisoformat(args.start)
    d1 = date.fromisoformat(args.end)
    days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
    print(f"H-MS1 backfill {SYMBOL}: {len(days)} días -> {out_dir}", flush=True)
    failed: list[str] = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_day, d, out_dir, tmp_dir): d for d in days}
        for fut in as_completed(futs):
            d = futs[fut]
            try:
                print(fut.result(), flush=True)
            except Exception as exc:
                failed.append(d.isoformat())
                print(f"{d} FALLO: {exc}", flush=True)
    print(f"LISTO. fallidos={failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
