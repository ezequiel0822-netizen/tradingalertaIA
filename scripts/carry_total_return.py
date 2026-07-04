"""CARRY total-return H-D1 (research-only, pre-registrado tanda 2026-07-04b).

Corrige el gate de H-C1: mide el retorno TOTAL del carry (precio + interés) neto
de un swap retail pesimista, no solo el precio. Regla congelada `carry_hold`:
si |diff anual| >= 0.5% -> posición a favor del alto-yield, hold 20 días hábiles.
Retorno = dir*(precio log-ret) + (|diff|/100)*(20/252) - swap_markup*(20/252).

Read-only sobre snapshot de la DB viva + research_rates.db. Anti-lookahead as-of.
Holdout: últimos 2 años excluidos (un tiro si pasa).

Uso:  python scripts/carry_total_return.py [--markup 1.0] [--include-holdout]
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # pragma: no cover
    pass

# Reusa loaders del event-study (misma lógica anti-lookahead).
from scripts.carry_study import (  # noqa: E402
    _PAIRS, load_daily_closes, load_rate_series, one_sample_t, resolve_db_path, snapshot_db,
)

HOLD_BARS = 20
DIFF_THRESHOLD = 0.5   # % anual, congelado
YEAR_DAYS = 252.0
HOLDOUT_YEARS = 2
T_THRESHOLD = 2.0      # k=1, return-space


def main() -> int:
    ap = argparse.ArgumentParser(description="Carry total-return H-D1 (pre-registrado)")
    ap.add_argument("--db", default=None)
    ap.add_argument("--rates", default=r"C:\Users\LENOVO\tradingalertaIA\trading_data\research_rates.db")
    ap.add_argument("--markup", type=float, default=1.0, help="swap markup anual %% (congelado 1.0)")
    ap.add_argument("--include-holdout", action="store_true")
    args = ap.parse_args()

    rcon = sqlite3.connect(f"file:{Path(args.rates).as_posix()}?mode=ro", uri=True)
    con = sqlite3.connect(f"file:{snapshot_db(resolve_db_path(args.db)).as_posix()}?mode=ro", uri=True)
    ccys = set(sum([[b, q] for b, q in _PAIRS.values()], []))
    rate_series = {c: load_rate_series(rcon, c) for c in ccys}
    have = {c for c, d in rate_series.items() if not d.empty}

    holdout_cut = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=365 * HOLDOUT_YEARS)
    if not args.include_holdout:
        print(f"HOLDOUT: se excluye data posterior a {holdout_cut.date()}")
    print(f"Swap markup anual (congelado): {args.markup}%  | regla: |diff|>={DIFF_THRESHOLD}%, hold {HOLD_BARS}d\n")

    def run(markup: float) -> list[dict]:
        trades: list[dict] = []
        for pair, (base, quote) in _PAIRS.items():
            if base not in have or quote not in have:
                continue
            px = load_daily_closes(con, pair)
            if px.empty:
                continue
            px = px.sort_values("date").reset_index(drop=True)
            for role, ccy in (("base", base), ("quote", quote)):
                m = pd.merge_asof(px[["date"]], rate_series[ccy], left_on="date",
                                  right_on="available_from", direction="backward")
                px[role] = m["rate"].to_numpy()
            px = px.dropna(subset=["base", "quote"]).reset_index(drop=True)
            px["diff"] = px["base"] - px["quote"]
            closes = px["close"].to_numpy(dtype=float)
            dates = px["date"].to_numpy()
            wk = px[px["date"].dt.weekday == 2]
            for _, row in wk.iterrows():
                i = int(np.searchsorted(dates, np.datetime64(row["date"])))
                if i >= len(closes) - HOLD_BARS:
                    continue
                if not args.include_holdout and pd.Timestamp(dates[i]) >= holdout_cut:
                    continue
                diff = float(row["diff"])
                if abs(diff) < DIFF_THRESHOLD:
                    continue
                direction = 1.0 if diff > 0 else -1.0
                price = direction * math.log(closes[i + HOLD_BARS] / closes[i])
                interest = (abs(diff) / 100.0) * (HOLD_BARS / YEAR_DAYS)
                swap = (markup / 100.0) * (HOLD_BARS / YEAR_DAYS)
                trades.append({
                    "pair": pair, "date": pd.Timestamp(dates[i]),
                    "year": int(pd.Timestamp(dates[i]).year),
                    "price": price, "interest": interest,
                    "net": price + interest - swap,
                })
        return trades

    trades = run(args.markup)
    if not trades:
        print("Sin trades.")
        return 0
    df = pd.DataFrame(trades)
    print(f"Trades (semanales): {len(df)} | rango {df['date'].min().date()} -> {df['date'].max().date()}")
    print(f"  precio medio={df['price'].mean()*10000:+.1f} bps | interés medio={df['interest'].mean()*10000:+.1f} bps "
          f"| BRUTO(precio+interés)={df[['price','interest']].sum(axis=1).mean()*10000:+.1f} bps")

    mid = df["date"].quantile(0.5)
    net = df["net"]
    m1 = df.loc[df["date"] < mid, "net"].mean()
    m2 = df.loc[df["date"] >= mid, "net"].mean()
    years = sorted(df["year"].unique())
    oky = sum(1 for y in years if df.loc[df["year"] == y, "net"].mean() > 0)
    yr = oky / len(years)
    t = one_sample_t(df.sort_values("date")["net"].iloc[::4].to_numpy())  # decim ~4 semanas
    mean = net.mean()
    ann = mean * (YEAR_DAYS / HOLD_BARS)  # retorno anualizado aprox del trade medio
    crit = (mean > 0) and (m1 > 0) and (m2 > 0) and (yr >= 0.6) and (t >= T_THRESHOLD)

    print(f"\n=== H-D1 (neto de swap {args.markup}%) ===")
    print(f"  media neta={mean*10000:+.2f} bps/trade (~{ann*100:+.2f}%/año) | mitades=({m1*10000:+.2f}, {m2*10000:+.2f})")
    print(f"  años+={yr:.0%} ({oky}/{len(years)}) | t(decim)={t:+.2f} (umbral {T_THRESHOLD}) -> {'PASA' if crit else 'NO PASA'}")

    print("\n  Sensibilidad al swap markup:")
    for mk in (0.5, 1.0, 1.5, 2.0):
        d2 = pd.DataFrame(run(mk))
        t2 = one_sample_t(d2.sort_values("date")["net"].iloc[::4].to_numpy())
        print(f"    markup {mk}%: media neta={d2['net'].mean()*10000:+.2f} bps | t={t2:+.2f}")

    print("\n=== VEREDICTO H-D1 ===")
    if crit:
        print("  PASA return-space -> tiro al holdout, luego §11 en el harness con stop 2xATR (R-space).")
    else:
        print("  NO PASA -> carry retail en D1 standalone se cierra (familia carry cerrada).")
    con.close()
    rcon.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
