"""Anomalías de equities E1 (turn-of-month) + E2 (overnight vs intraday) — pre-registrado
tanda 2026-07-05. Data: equity_ohlc de Stooq (correr stooq_backfill.py antes).
Read-only. Holdout 2 años excluido de E1.

Uso:  python scripts/equity_anomaly_study.py [--include-holdout]
"""

from __future__ import annotations

import argparse
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

T_THRESHOLD = 2.40  # Bonferroni k=3
HOLDOUT_YEARS = 2
INDICES = ("SPY", "QQQ", "IWM")


def welch_t(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 5 or len(b) < 5:
        return float("nan")
    va, vb = a.var(ddof=1), b.var(ddof=1)
    d = math.sqrt(va / len(a) + vb / len(b))
    return float((a.mean() - b.mean()) / d) if d > 0 else float("nan")


def one_sample_t(x: np.ndarray) -> float:
    if len(x) < 5:
        return float("nan")
    s = x.std(ddof=1)
    return float(x.mean() / (s / math.sqrt(len(x)))) if s > 0 else float("nan")


def load(con: sqlite3.Connection, sym: str) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT date, open, close FROM equity_ohlc WHERE symbol=? ORDER BY date",
                           con, params=(sym,))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["ret"] = np.log(df["close"] / df["close"].shift(1))
    df["overnight"] = np.log(df["open"] / df["close"].shift(1))
    df["intraday"] = np.log(df["close"] / df["open"])
    df["year"] = df["date"].dt.year
    return df.dropna().reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rates", default=r"C:\Users\LENOVO\tradingalertaIA\trading_data\research_rates.db")
    ap.add_argument("--include-holdout", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{Path(args.rates).as_posix()}?mode=ro", uri=True)
    cut = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=365 * HOLDOUT_YEARS)
    if not args.include_holdout:
        print(f"HOLDOUT (E1/F1): se excluye data posterior a {cut.date()}\n")

    print("=== E1 — Turn-of-month [-1, +3] (umbral t>=2.40) ===")
    pooled_in, pooled_out = [], []
    e1_pass = True
    for sym in INDICES:
        df = load(con, sym)
        if df.empty:
            print(f"  {sym}: sin data en Stooq -> NO TESTEABLE"); e1_pass = False; continue
        d = df if args.include_holdout else df[df["date"] < cut]
        ym = d["date"].dt.to_period("M")
        is_last = ym != ym.shift(-1)
        pos = d.groupby(ym).cumcount()
        tom = (is_last | (pos <= 2)).to_numpy()
        a, b = d.loc[tom, "ret"].to_numpy(), d.loc[~tom, "ret"].to_numpy()
        pooled_in += list(a); pooled_out += list(b)
        mid = d["date"].quantile(0.5)
        d1 = d.loc[tom & (d["date"] < mid), "ret"].mean() - d.loc[(~tom) & (d["date"] < mid), "ret"].mean()
        d2 = d.loc[tom & (d["date"] >= mid), "ret"].mean() - d.loc[(~tom) & (d["date"] >= mid), "ret"].mean()
        years = sorted(d["year"].unique())
        oky = sum(1 for y in years
                  if d.loc[tom & (d["year"] == y).to_numpy(), "ret"].mean()
                  > d.loc[(~tom) & (d["year"] == y).to_numpy(), "ret"].mean())
        t = welch_t(a, b)
        crit = (a.mean() > b.mean()) and (d1 > 0) and (d2 > 0) and (oky/len(years) >= 0.6) and (t >= T_THRESHOLD)
        e1_pass = e1_pass and crit
        print(f"  {sym}: ToM={a.mean()*10000:+.1f} vs resto={b.mean()*10000:+.1f} bps/día "
              f"| mitades=({d1*10000:+.1f},{d2*10000:+.1f}) | años+={oky/len(years):.0%} | t={t:+.2f} -> {'PASA' if crit else 'NO PASA'}")
    if pooled_in:
        tp = welch_t(np.array(pooled_in), np.array(pooled_out))
        print(f"  POOL: ToM={np.mean(pooled_in)*10000:+.1f} vs {np.mean(pooled_out)*10000:+.1f} bps | t={tp:+.2f}")
    print(f"  E1 -> {'PASA' if e1_pass else 'NO PASA'}")

    print("\n=== E2 — Overnight vs intraday (umbral: overnight t>=2.40 Y overnight>intraday) ===")
    for sym in INDICES:
        df = load(con, sym)
        if df.empty:
            print(f"  {sym}: sin data"); continue
        on, intra = df["overnight"].to_numpy(), df["intraday"].to_numpy()
        t_on = one_sample_t(on)
        crit = (on.mean() > 0) and (t_on >= T_THRESHOLD) and (on.mean() > intra.mean())
        # anualizado aprox (252 días)
        print(f"  {sym}: overnight={on.mean()*10000:+.2f} bps/día (~{on.mean()*252*100:+.1f}%/año, t={t_on:+.2f}) "
              f"| intraday={intra.mean()*10000:+.2f} bps (~{intra.mean()*252*100:+.1f}%/año) -> {'PASA' if crit else 'NO PASA'}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
