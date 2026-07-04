"""COT commercials (smart money) F1 — pre-registrado tanda 2026-07-05.

Espejo de cot_price_study pero sobre `net_comm` (hedgers/commercials) en vez de
non-commercial (specs, que ya murió en H-A1). Hipótesis: commercials extremo-long
→ precio sube. Reusa la maquinaria anti-lookahead de cot_price_study.

Uso:  python scripts/cot_commercials_study.py [--include-holdout]
"""

from __future__ import annotations

import argparse
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.cot_price_study import (  # noqa: E402
    HI, LO, HORIZONS, LAG_DAYS, _MARKET_TO_PAIR, cot_index, load_daily_closes,
    resolve_db_path, snapshot_db, welch_t,
)

T_THRESHOLD = 2.40
HOLDOUT_YEARS = 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--include-holdout", action="store_true")
    args = ap.parse_args()

    snap = snapshot_db(resolve_db_path(args.db))
    con = sqlite3.connect(f"file:{snap.as_posix()}?mode=ro", uri=True)
    cot = pd.read_sql_query(
        "SELECT market_code, report_date, net_comm FROM cot_snapshots "
        "WHERE net_comm IS NOT NULL ORDER BY market_code, report_date", con)
    print(f"cot_snapshots (net_comm): {len(cot)} filas")
    holdout = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=365 * HOLDOUT_YEARS)
    if not args.include_holdout:
        print(f"HOLDOUT: excluye posterior a {holdout.date()}\n")

    events = []
    for market, (pair, sign) in _MARKET_TO_PAIR.items():
        g = cot[cot["market_code"] == market].copy()
        if len(g) < 52:
            continue
        g["report_dt"] = pd.to_datetime(g["report_date"])
        g["idx"] = cot_index(g["net_comm"].astype(float))
        g["available_from"] = g["report_dt"] + pd.Timedelta(days=LAG_DAYS)
        g = g.dropna(subset=["idx"])
        px = load_daily_closes(con, pair)
        if px.empty:
            continue
        dates, closes = px["date"].to_numpy(), px["close"].to_numpy(dtype=float)
        for _, row in g.iterrows():
            if not args.include_holdout and row["available_from"] >= holdout:
                continue
            i = int(np.searchsorted(dates, np.datetime64(row["available_from"])))
            if i >= len(closes) - max(HORIZONS):
                continue
            e = {"market": market, "idx": float(row["idx"]),
                 "year": int(pd.Timestamp(dates[i]).year), "date": pd.Timestamp(dates[i])}
            for h in HORIZONS:
                e[f"fwd{h}"] = sign * math.log(closes[i + h] / closes[i])
            events.append(e)

    df = pd.DataFrame(events)
    if df.empty:
        print("Sin eventos."); return 0
    hi, lo = df[df["idx"] >= HI], df[df["idx"] <= LO]
    print(f"Eventos: {len(df)} | ALTO(commercials long): {len(hi)} | BAJO: {len(lo)} | "
          f"{df['date'].min().date()} -> {df['date'].max().date()}")
    mid = df["date"].quantile(0.5)
    print("\n=== F1: spread (commercials ALTO - BAJO), retorno forward del par ===")
    passed = True
    for h in HORIZONS:
        c = f"fwd{h}"
        spread = hi[c].mean() - lo[c].mean()
        s1 = hi[hi["date"] < mid][c].mean() - lo[lo["date"] < mid][c].mean()
        s2 = hi[hi["date"] >= mid][c].mean() - lo[lo["date"] >= mid][c].mean()
        years = sorted(set(hi["year"]) & set(lo["year"]))
        oky = sum(1 for y in years if hi[hi["year"] == y][c].mean() - lo[lo["year"] == y][c].mean() > 0)
        yr = oky / len(years) if years else float("nan")
        k = max(1, math.ceil(h / 5))
        t = welch_t(hi.sort_values("date").iloc[::k][c].to_numpy(),
                    lo.sort_values("date").iloc[::k][c].to_numpy())
        crit = (spread > 0) and (s1 > 0) and (s2 > 0) and (yr >= 0.6) and (t >= T_THRESHOLD)
        passed = passed and crit
        print(f"  fwd {h:>2}d: spread={spread*10000:+7.1f} bps | mitades=({s1*10000:+.1f},{s2*10000:+.1f}) "
              f"| años+={yr:.0%} | t={t:+.2f} -> {'PASA' if crit else 'NO PASA'}")
    print(f"\n  F1 -> {'PASA' if passed else 'NO PASA'}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
