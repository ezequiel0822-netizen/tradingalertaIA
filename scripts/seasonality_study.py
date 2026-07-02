"""Estacionalidad sobre el cache propio — H-B1/B2/B3 (research-only, pre-registrado).

Testea la familia B de research/HIPOTESIS_2026-07-02.md sobre `mt5_historical_cache`
(cero descargas nuevas):
  H-B1: turn-of-month en SPY (último día del mes + 3 primeros del siguiente).
  H-B2: viernes del oro (XAUUSD).
  H-B3: agosto+septiembre del oro (XAUUSD).

Umbral pre-registrado (cada una): diferencia en la dirección esperada, positiva en
AMBAS mitades, ≥60% de años consistentes, t-Welch ≥ 2.39 (Bonferroni k=3).
Read-only sobre snapshot. Si falta la data (ej. SPY), la hipótesis se reporta como
"no testeable hoy" — NO se sustituye el símbolo post-hoc.

Uso:  python scripts/seasonality_study.py [--db PATH]
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # pragma: no cover
    pass

T_THRESHOLD = 2.39  # Bonferroni k=3


def resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    try:
        from dotenv import load_dotenv

        env = Path(r"C:\Users\LENOVO\tradingalertaIA\.env")
        if env.exists():
            load_dotenv(env)
    except ImportError:
        pass
    from app.config.settings import load_settings

    return Path(load_settings().sqlite_path)


def snapshot_db(live_path: Path) -> Path:
    tmp = Path(tempfile.gettempdir()) / "seasonality_snapshot.db"
    src = sqlite3.connect(f"file:{live_path.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return tmp


def load_daily(con: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    """D1 del cache con retorno log diario. Detecta el timeframe D1 por espaciado."""
    tfs = [r[0] for r in con.execute(
        "SELECT DISTINCT timeframe FROM mt5_historical_cache WHERE symbol=?", (symbol,)
    )]
    best: tuple[int, int] | None = None
    for tf in tfs:
        rows = con.execute(
            "SELECT time FROM mt5_historical_cache WHERE symbol=? AND timeframe=? "
            "ORDER BY time LIMIT 500", (symbol, tf),
        ).fetchall()
        if len(rows) < 50:
            continue
        med = float(np.median(np.diff([r[0] for r in rows])))
        if 80000 <= med <= 400000:
            n = con.execute(
                "SELECT COUNT(*) FROM mt5_historical_cache WHERE symbol=? AND timeframe=?",
                (symbol, tf),
            ).fetchone()[0]
            if best is None or n > best[1]:
                best = (tf, n)
    if best is None:
        return pd.DataFrame()
    df = pd.read_sql_query(
        "SELECT time, close FROM mt5_historical_cache "
        "WHERE symbol=? AND timeframe=? ORDER BY time",
        con, params=(symbol, best[0]),
    ).dropna()
    df["date"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_localize(None)
    df["ret"] = np.log(df["close"] / df["close"].shift(1))
    return df.dropna(subset=["ret"]).reset_index(drop=True)


def welch_t(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 5 or len(b) < 5:
        return float("nan")
    va, vb = a.var(ddof=1), b.var(ddof=1)
    denom = math.sqrt(va / len(a) + vb / len(b))
    return float((a.mean() - b.mean()) / denom) if denom > 0 else float("nan")


def evaluate(name: str, df: pd.DataFrame, in_mask: pd.Series) -> None:
    """Evalúa una hipótesis: retornos in-window vs out-window con el umbral pre-registrado."""
    a = df.loc[in_mask, "ret"].to_numpy()
    b = df.loc[~in_mask, "ret"].to_numpy()
    if len(a) < 30 or len(b) < 30:
        print(f"  {name}: muestra insuficiente (in={len(a)}, out={len(b)}) -> NO TESTEABLE")
        return
    diff = a.mean() - b.mean()
    mid = df["date"].quantile(0.5)
    first, second = df["date"] < mid, df["date"] >= mid
    d1 = df.loc[in_mask & first, "ret"].mean() - df.loc[(~in_mask) & first, "ret"].mean()
    d2 = df.loc[in_mask & second, "ret"].mean() - df.loc[(~in_mask) & second, "ret"].mean()
    years = sorted(df["date"].dt.year.unique())
    ok = 0
    valid_years = 0
    for y in years:
        ymask = df["date"].dt.year == y
        ia, ib = df.loc[in_mask & ymask, "ret"], df.loc[(~in_mask) & ymask, "ret"]
        if len(ia) >= 5 and len(ib) >= 20:
            valid_years += 1
            if ia.mean() - ib.mean() > 0:
                ok += 1
    yr_frac = ok / valid_years if valid_years else float("nan")
    t = welch_t(a, b)
    crit = (diff > 0) and (d1 > 0) and (d2 > 0) and (yr_frac >= 0.6) and (t >= T_THRESHOLD)
    print(f"  {name}:")
    print(f"    in={len(a)} out={len(b)} | diff={diff*10000:+.2f} bps/día | mitades=({d1*10000:+.2f}, {d2*10000:+.2f})")
    print(f"    años+={yr_frac:.0%} ({valid_years}) | t={t:+.2f} (umbral {T_THRESHOLD}) -> {'PASA' if crit else 'NO PASA'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Estacionalidad pre-registrada sobre el cache")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    snap = snapshot_db(resolve_db_path(args.db))
    con = sqlite3.connect(f"file:{snap.as_posix()}?mode=ro", uri=True)

    print("=== Inventario del cache (symbol, timeframe, n, rango) ===")
    for r in con.execute(
        "SELECT symbol, timeframe, COUNT(*), MIN(time), MAX(time) "
        "FROM mt5_historical_cache GROUP BY symbol, timeframe ORDER BY symbol"
    ):
        lo = pd.to_datetime(r[3], unit="s").date()
        hi = pd.to_datetime(r[4], unit="s").date()
        print(f"  {r[0]:<8} tf={r[1]:<6} n={r[2]:<7} {lo} -> {hi}")

    print("\n=== Familia B (umbral: dirección esperada + ambas mitades + >=60% años + t>=2.39) ===")

    # H-B1 — turn-of-month SPY
    spy = load_daily(con, "SPY")
    if spy.empty:
        print("  H-B1 (ToM SPY): sin data de SPY en el cache -> NO TESTEABLE HOY (no se sustituye símbolo).")
    else:
        ym = spy["date"].dt.to_period("M")
        # último día hábil del mes (cambio de período en la barra siguiente) + 3 primeros
        is_last = ym != ym.shift(-1)
        pos_in_month = spy.groupby(ym).cumcount()
        tom = is_last | (pos_in_month <= 2)
        evaluate("H-B1 ToM SPY [-1,+3]", spy, tom)

    gold = load_daily(con, "XAUUSD")
    if gold.empty:
        print("  H-B2/H-B3: sin data de XAUUSD en el cache -> NO TESTEABLES.")
    else:
        evaluate("H-B2 viernes XAUUSD", gold, gold["date"].dt.weekday == 4)
        evaluate("H-B3 ago+sep XAUUSD", gold, gold["date"].dt.month.isin([8, 9]))

    print("\n(Recordar: tanda 2026-07-02 con k=6; lo que no pasa, muere sin re-cortes.)")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
