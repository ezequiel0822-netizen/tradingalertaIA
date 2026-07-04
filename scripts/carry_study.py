"""CARRY — event-study H-C1 + top-minus-bottom H-C3 (research-only, pre-registrado).

Testea research/HIPOTESIS_2026-07-04_carry.md sobre las tasas de FRED
(research_rates.db, correr rates_backfill.py antes) × el D1 propio del cache
(snapshot read-only de la DB viva). Anti-lookahead: as-of con lag (diarias T-1,
mensuales ~mes anterior). Holdout: últimos 2 años excluidos de H-C1.

Uso:  python scripts/carry_study.py [--db PATH] [--rates PATH] [--include-holdout]
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # pragma: no cover
    pass

# pair del cache -> (base, quote). long el par = long base (uniforme para BASE+QUOTE).
_PAIRS = {
    "EURUSD": ("EUR", "USD"), "GBPUSD": ("GBP", "USD"), "USDJPY": ("USD", "JPY"),
    "AUDUSD": ("AUD", "USD"), "USDCAD": ("USD", "CAD"), "USDCHF": ("USD", "CHF"),
    "NZDUSD": ("NZD", "USD"),
}
HORIZONS = (5, 10, 20)
T_THRESHOLD = 2.39   # Bonferroni k=3
HOLDOUT_YEARS = 2


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


def snapshot_db(live: Path) -> Path:
    tmp = Path(tempfile.gettempdir()) / "carry_snapshot.db"
    src = sqlite3.connect(f"file:{live.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return tmp


def load_daily_closes(con: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    tfs = [r[0] for r in con.execute(
        "SELECT DISTINCT timeframe FROM mt5_historical_cache WHERE symbol=?", (symbol,))]
    best = None
    for tf in tfs:
        rows = con.execute("SELECT time FROM mt5_historical_cache WHERE symbol=? AND timeframe=? "
                           "ORDER BY time LIMIT 500", (symbol, tf)).fetchall()
        if len(rows) < 50:
            continue
        med = float(np.median(np.diff([r[0] for r in rows])))
        if 80000 <= med <= 400000:
            n = con.execute("SELECT COUNT(*) FROM mt5_historical_cache WHERE symbol=? AND timeframe=?",
                            (symbol, tf)).fetchone()[0]
            if best is None or n > best[1]:
                best = (tf, n)
    if best is None:
        return pd.DataFrame()
    df = pd.read_sql_query("SELECT time, close FROM mt5_historical_cache "
                           "WHERE symbol=? AND timeframe=? ORDER BY time",
                           con, params=(symbol, best[0])).dropna()
    df["date"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_localize(None)
    return df[["date", "close"]]


def load_rate_series(rcon: sqlite3.Connection, ccy: str) -> pd.DataFrame:
    """Series de tasa con 'available_from' (anti-lookahead): diaria +1 día,
    mensual +32 días (para que un valor de inicio de mes solo se use tras el mes)."""
    df = pd.read_sql_query("SELECT date, rate, freq FROM interest_rates "
                           "WHERE currency=? ORDER BY date", rcon, params=(ccy,))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    lag = np.where(df["freq"] == "D", pd.Timedelta(days=1), pd.Timedelta(days=32))
    df["available_from"] = df["date"] + pd.to_timedelta(lag)
    return df[["available_from", "rate"]].sort_values("available_from")


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Carry study (pre-registrado)")
    ap.add_argument("--db", default=None)
    ap.add_argument("--rates", default=r"C:\Users\LENOVO\tradingalertaIA\trading_data\research_rates.db")
    ap.add_argument("--include-holdout", action="store_true")
    args = ap.parse_args()

    rates_path = Path(args.rates)
    if not rates_path.exists():
        print(f"No existe {rates_path}. Corré primero: python scripts/rates_backfill.py")
        return 1
    rcon = sqlite3.connect(f"file:{rates_path.as_posix()}?mode=ro", uri=True)
    snap = snapshot_db(resolve_db_path(args.db))
    con = sqlite3.connect(f"file:{snap.as_posix()}?mode=ro", uri=True)

    rate_series = {ccy: load_rate_series(rcon, ccy)
                   for ccy in set(sum([[b, q] for b, q in _PAIRS.values()], []))}
    have = {c for c, d in rate_series.items() if not d.empty}
    print(f"Tasas disponibles: {sorted(have)}")

    holdout_cut = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=365 * HOLDOUT_YEARS)
    if not args.include_holdout:
        print(f"HOLDOUT: se excluye data posterior a {holdout_cut.date()}\n")

    # Panel semanal por par: fecha, diff (anti-lookahead), fwd returns, año.
    events: list[dict] = []
    weekly: dict[str, pd.DataFrame] = {}
    for pair, (base, quote) in _PAIRS.items():
        if base not in have or quote not in have:
            print(f"  {pair}: falta tasa de {base if base not in have else quote} -> salteado")
            continue
        px = load_daily_closes(con, pair)
        if px.empty:
            print(f"  {pair}: sin D1 en cache -> salteado")
            continue
        px = px.sort_values("date").reset_index(drop=True)
        # as-of de cada tasa
        for role, ccy in (("base", base), ("quote", quote)):
            m = pd.merge_asof(px[["date"]], rate_series[ccy], left_on="date",
                              right_on="available_from", direction="backward")
            px[role] = m["rate"].to_numpy()
        px = px.dropna(subset=["base", "quote"])
        px["diff"] = px["base"] - px["quote"]  # anual, orientado al par
        # muestreo semanal (miércoles) para reducir solapamiento
        wk = px[px["date"].dt.weekday == 2].reset_index(drop=True)
        closes = px["close"].to_numpy(dtype=float)
        dates = px["date"].to_numpy()
        rec = []
        for _, row in wk.iterrows():
            i = int(np.searchsorted(dates, np.datetime64(row["date"])))
            if i >= len(closes) - max(HORIZONS):
                continue
            if not args.include_holdout and pd.Timestamp(dates[i]) >= holdout_cut:
                continue
            e = {"pair": pair, "date": pd.Timestamp(dates[i]), "diff": float(row["diff"]),
                 "year": int(pd.Timestamp(dates[i]).year), "sign": np.sign(row["diff"])}
            for h in HORIZONS:
                e[f"fwd{h}"] = math.log(closes[i + h] / closes[i])  # retorno del par
            rec.append(e)
            events.append({**e})
        weekly[pair] = pd.DataFrame(rec)
        print(f"  {pair}: {len(rec)} semanas con diff+precio")

    df = pd.DataFrame(events)
    if df.empty:
        print("\nSin eventos -> nada para evaluar.")
        return 0
    df = df[df["sign"] != 0]
    print(f"\nEventos: {len(df)} | rango {df['date'].min().date()} -> {df['date'].max().date()}")
    mid = df["date"].quantile(0.5)

    print("\n=== H-C1: retorno del par orientado por el signo del carry (POOL) ===")
    passed = True
    for h in HORIZONS:
        adj = df["sign"] * df[f"fwd{h}"]  # >0 = alto-yield no se deprecio (carry a favor)
        mean = adj.mean()
        m1 = (df.loc[df["date"] < mid, "sign"] * df.loc[df["date"] < mid, f"fwd{h}"]).mean()
        m2 = (df.loc[df["date"] >= mid, "sign"] * df.loc[df["date"] >= mid, f"fwd{h}"]).mean()
        years = sorted(df["year"].unique())
        ok_years = sum(1 for y in years
                       if (df.loc[df["year"] == y, "sign"] * df.loc[df["year"] == y, f"fwd{h}"]).mean() > 0)
        yr = ok_years / len(years) if years else float("nan")
        k = max(1, math.ceil(h / 5))
        dec = (df.sort_values("date").assign(adj=df["sign"] * df[f"fwd{h}"]).iloc[::k]["adj"]).to_numpy()
        t = one_sample_t(dec)
        crit = (mean > 0) and (m1 > 0) and (m2 > 0) and (yr >= 0.6) and (t >= T_THRESHOLD)
        passed = passed and crit
        print(f"  fwd {h:>2}d: media={mean*10000:+7.1f} bps | mitades=({m1*10000:+.1f}, {m2*10000:+.1f}) "
              f"| años+={yr:.0%} ({len(years)}) | t(decim)={t:+.2f} | {'PASA' if crit else 'NO PASA'}")

    print("\n=== H-C3: top-minus-bottom (long mayor diff, short menor diff; semanal) ===")
    common = None
    for pair, w in weekly.items():
        if w.empty:
            continue
        s = w.set_index("date")
    # arma panel ancho por fecha: diff y fwd10 de cada par
    panels = []
    for pair, w in weekly.items():
        if w.empty:
            continue
        panels.append(w.assign(pair=pair)[["date", "pair", "diff", "fwd10"]])
    allw = pd.concat(panels) if panels else pd.DataFrame()
    tmb: list[float] = []
    tmb_years: dict[int, list[float]] = {}
    if not allw.empty:
        for date, g in allw.groupby("date"):
            if len(g) < 4:
                continue
            g = g.sort_values("diff")
            spread = g.iloc[-1]["fwd10"] - g.iloc[0]["fwd10"]  # long top - short bottom (precio)
            tmb.append(spread)
            tmb_years.setdefault(pd.Timestamp(date).year, []).append(spread)
    if len(tmb) >= 30:
        arr = np.array(tmb)
        ok_y = sum(1 for y, v in tmb_years.items() if np.mean(v) > 0)
        print(f"  n semanas={len(arr)} | media spread fwd10d={arr.mean()*10000:+.1f} bps "
              f"| t={one_sample_t(arr[::2]):+.2f} | años+={ok_y}/{len(tmb_years)} ({ok_y/len(tmb_years):.0%})")
    else:
        print(f"  muestra insuficiente (n={len(tmb)})")

    print("\n=== VEREDICTO H-C1 (Bonferroni k=3) ===")
    if passed:
        print("  PASA exploración -> tiro al holdout, luego regla congelada carry_hold (H-C2)")
        print("  en el harness §11 CON haircut de swap. NADA se prende en vivo.")
    else:
        print("  NO PASA como está pre-registrado. Ver por-mercado abajo para interpretar.")

    print("\n  Por par (media orientada fwd10d, referencia):")
    for pair in _PAIRS:
        d = df[df["pair"] == pair]
        if len(d) >= 20:
            print(f"    {pair}: {(d['sign']*d['fwd10']).mean()*10000:+7.1f} bps "
                  f"(n={len(d)}, diff medio={d['diff'].mean():+.2f}%)")
    con.close()
    rcon.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
