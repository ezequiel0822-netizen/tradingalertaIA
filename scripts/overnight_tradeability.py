"""E2 pasó EXISTENCIA → test de TRADEABILIDAD del overnight (el gate pre-registrado).

Regla: comprar al close[t-1], vender al open[t] (hold nocturno), todos los días.
Retorno neto = overnight − costo round-trip. Se reporta con sensibilidad al costo
(0.5 a 3 bps/día) porque el costo real de ejecución vía auctions MOC/MOO es
incierto — NO se elige un costo que haga pasar (eso sería dredging).

Read-only sobre research_rates.db. Honestidad brutal: este NO es un edge que el bot
pueda ejecutar (US equities, órdenes MOC/MOO, fuera del universo MT5-forex demo).

Uso:  python scripts/overnight_tradeability.py
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DB = Path(r"C:\Users\LENOVO\tradingalertaIA\trading_data\research_rates.db")
INDICES = ("SPY", "QQQ", "IWM")
COSTS_BPS = (0.5, 1.0, 2.0, 3.0)  # round-trip por día (spread+slippage de auction)


def main() -> int:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    print("=== E2 tradeabilidad: hold nocturno (buy close, sell open) ===")
    print("    (net = overnight - costo; se reporta sensibilidad, NO se elige el costo)\n")
    for sym in INDICES:
        df = pd.read_sql_query("SELECT date, open, close FROM equity_ohlc WHERE symbol=? ORDER BY date",
                               con, params=(sym,))
        if df.empty:
            print(f"  {sym}: sin data"); continue
        df["date"] = pd.to_datetime(df["date"])
        df["on"] = np.log(df["open"] / df["close"].shift(1))
        df = df.dropna().reset_index(drop=True)
        df["year"] = df["date"].dt.year
        on = df["on"].to_numpy()
        gross_ann = on.mean() * 252 * 100
        sharpe_gross = on.mean() / on.std(ddof=1) * math.sqrt(252)
        print(f"  {sym}: bruto ~{gross_ann:+.1f}%/año, Sharpe {sharpe_gross:.2f}  (n={len(df)}, "
              f"{df['date'].min().year}-{df['date'].max().year})")
        for cost in COSTS_BPS:
            net = on - cost / 10000.0
            ann = net.mean() * 252 * 100
            sharpe = net.mean() / net.std(ddof=1) * math.sqrt(252)
            years = sorted(df["year"].unique())
            oky = sum(1 for y in years if df.loc[df["year"] == y, "on"].mean() - cost/10000.0 > 0)
            # max drawdown de la equity curve neta (compuesta)
            eq = np.cumsum(net)
            dd = float((np.maximum.accumulate(eq) - eq).max())
            print(f"      costo {cost:>3} bps/día: neto ~{ann:+6.1f}%/año | Sharpe {sharpe:+.2f} "
                  f"| años+ {oky}/{len(years)} ({oky/len(years):.0%}) | maxDD {dd*100:.0f}%")
        print()
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
