"""Backfill de OHLC diario de SPY/QQQ/IWM vía el loader Yahoo del proyecto
(fetch_yahoo_daily, con backoff anti-429). Stooq quedó detrás de un challenge JS.

Guarda en research_rates.db (tabla equity_ohlc) — no toca el schema vivo.
Nota: usa OHLC AJUSTADO por splits/dividendos (consistente); el ajuste por
dividendo distorsiona mínimamente el corte overnight/intraday (declarado).

Uso:  python scripts/equity_backfill.py
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # pragma: no cover
    pass

from app.backtest.stock_historical_loader import fetch_yahoo_daily  # noqa: E402

_SYMBOLS = ("SPY", "QQQ", "IWM")


def main() -> int:
    db = Path(r"C:\Users\LENOVO\tradingalertaIA\trading_data\research_rates.db")
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db))
    con.execute(
        """CREATE TABLE IF NOT EXISTS equity_ohlc (
            symbol TEXT NOT NULL, date TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            UNIQUE(symbol, date))"""
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (research)"})
    print(f"Equity backfill (Yahoo D1 ajustado) -> {db.name}\n")
    total = 0
    for sym in _SYMBOLS:
        candles = fetch_yahoo_daily(sym, session, timeout=30)
        if len(candles) < 100:
            print(f"  {sym}: FALLO / vacío ({len(candles)} velas) — posible 429")
            continue
        con.execute("DELETE FROM equity_ohlc WHERE symbol=?", (sym,))
        con.executemany(
            "INSERT OR REPLACE INTO equity_ohlc (symbol, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(sym, time.strftime("%Y-%m-%d", time.gmtime(c["time"])),
              c["open"], c["high"], c["low"], c["close"], c["volume"]) for c in candles],
        )
        con.commit()
        total += len(candles)
        first = time.strftime("%Y-%m-%d", time.gmtime(candles[0]["time"]))
        last = time.strftime("%Y-%m-%d", time.gmtime(candles[-1]["time"]))
        print(f"  {sym:<4} {len(candles):>6} velas  {first} -> {last}")
        time.sleep(2.0)  # pacing anti-429
    print(f"\nListo: {total} filas en equity_ohlc.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
