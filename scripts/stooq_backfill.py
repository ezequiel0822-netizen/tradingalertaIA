"""Backfill de OHLC diario de índices/ETFs de acciones desde Stooq (gratis, sin key,
sin el throttle 429 de Yahoo). Para las anomalías de equities (turn-of-month,
overnight/intraday) que el cache no tenía (SPY nunca entró por el 429 de Yahoo).

Guarda en el sqlite de research (research_rates.db, tabla equity_ohlc) — NO toca
el schema vivo. Idempotente (INSERT OR REPLACE por (symbol, date)).

Uso:  python scripts/stooq_backfill.py
"""

from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # pragma: no cover
    pass

_SYMBOLS = {"SPY": "spy.us", "QQQ": "qqq.us", "IWM": "iwm.us", "GLD": "gld.us"}
_URL = "https://stooq.com/q/d/l/?s={sid}&i=d"


def fetch(session: requests.Session, sid: str) -> list[tuple]:
    """Devuelve [(date, open, high, low, close, volume)] de Stooq. [] si falla."""
    try:
        resp = session.get(_URL.format(sid=sid), timeout=40)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    text = resp.text
    if "Date,Open" not in text[:60]:  # Stooq devuelve "Exceeded..." o HTML si limita
        return []
    rows = []
    reader = io.StringIO(text)
    reader.readline()  # header
    for line in reader:
        p = line.strip().split(",")
        if len(p) < 5:
            continue
        try:
            rows.append((p[0][:10], float(p[1]), float(p[2]), float(p[3]),
                         float(p[4]), float(p[5]) if len(p) > 5 and p[5] else 0.0))
        except ValueError:
            continue
    return rows


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
    print(f"Stooq backfill -> {db.name}\n")
    total = 0
    for name, sid in _SYMBOLS.items():
        rows = fetch(session, sid)
        if len(rows) < 100:
            print(f"  {name} ({sid}): FALLO / vacío ({len(rows)} filas)")
            continue
        con.execute("DELETE FROM equity_ohlc WHERE symbol=?", (name,))
        con.executemany(
            "INSERT OR REPLACE INTO equity_ohlc (symbol, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(name, *r) for r in rows],
        )
        con.commit()
        total += len(rows)
        print(f"  {name:<4} {len(rows):>5} filas  {rows[0][0]} -> {rows[-1][0]}")
    print(f"\nListo: {total} filas en equity_ohlc.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
