"""Backfill de tasas de interés (FRED, gratis, sin key) para el estudio del carry.

Baja los CSV de FRED de tasa de política / interbancaria 3M por divisa y los
persiste en un sqlite de RESEARCH aparte (trading_data/research_rates.db, tabla
interest_rates) — NO toca el schema vivo. Idempotente (INSERT OR REPLACE por
(currency, date)). Robusto: prueba varias series por divisa y reporta cuál sirvió.

Uso:  python scripts/rates_backfill.py
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

# Candidatos de serie FRED por divisa (se usa la 1a que devuelva CSV valido).
# freq: 'D' diaria, 'M' mensual (se anota para el as-of del estudio).
_SERIES: dict[str, list[tuple[str, str]]] = {
    "USD": [("DFF", "D")],                              # Fed Funds efectiva
    "EUR": [("ECBDFR", "D"), ("IR3TIB01EZM156N", "M")],  # ECB deposit / 3M EZ
    "GBP": [("IUDSOIA", "D"), ("IR3TIB01GBM156N", "M")],  # SONIA / 3M UK
    "JPY": [("IR3TIB01JPM156N", "M"), ("INTDSRJPM193N", "M")],
    "AUD": [("IR3TIB01AUM156N", "M")],
    "CAD": [("IR3TIB01CAM156N", "M"), ("IRSTCB01CAM156N", "M")],
    "CHF": [("IR3TIB01CHM156N", "M")],
    "NZD": [("IR3TIB01NZM156N", "M")],
}

_FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def fetch_series(session: requests.Session, sid: str) -> list[tuple[str, float]]:
    """Devuelve [(YYYY-MM-DD, rate)] de una serie FRED. [] si falla o vacía."""
    try:
        resp = session.get(_FRED_CSV.format(sid=sid), timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    if "text/csv" not in resp.headers.get("Content-Type", "") and "," not in resp.text[:200]:
        return []
    rows: list[tuple[str, float]] = []
    reader = io.StringIO(resp.text)
    header = reader.readline()  # "observation_date,SERIESID" o "DATE,SERIESID"
    if "," not in header:
        return []
    for line in reader:
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        date, val = parts[0], parts[1]
        if val in (".", "", "NA"):  # FRED marca faltante con '.'
            continue
        try:
            rows.append((date[:10], float(val)))
        except ValueError:
            continue
    return rows


def main() -> int:
    db_path = Path(r"C:\Users\LENOVO\tradingalertaIA\trading_data\research_rates.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS interest_rates (
            currency TEXT NOT NULL,
            date TEXT NOT NULL,
            rate REAL NOT NULL,
            freq TEXT NOT NULL,
            series_id TEXT NOT NULL,
            UNIQUE(currency, date)
        )
        """
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "TradingAlertAI/3.11 (rates research)"})

    print(f"Rates backfill (FRED) -> {db_path.name}\n")
    total = 0
    for ccy, candidates in _SERIES.items():
        got = False
        for sid, freq in candidates:
            rows = fetch_series(session, sid)
            if len(rows) < 24:
                continue
            con.execute("DELETE FROM interest_rates WHERE currency=?", (ccy,))
            con.executemany(
                "INSERT OR REPLACE INTO interest_rates (currency, date, rate, freq, series_id) "
                "VALUES (?, ?, ?, ?, ?)",
                [(ccy, d, r, freq, sid) for d, r in rows],
            )
            con.commit()
            total += len(rows)
            print(f"  {ccy}  {sid:<16} freq={freq}  {len(rows):>5} filas  "
                  f"{rows[0][0]} -> {rows[-1][0]}")
            got = True
            break
        if not got:
            print(f"  {ccy}  -> NINGUNA serie valida ({[c[0] for c in candidates]})")

    print(f"\nListo: {total} filas en interest_rates ({db_path}).")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
