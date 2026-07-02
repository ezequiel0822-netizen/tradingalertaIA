"""COT × PRECIO — event-study de alta potencia (research-only, pre-registrado).

Testea H-A1 de research/HIPOTESIS_2026-07-02.md: ¿los extremos del índice COT
(Williams sobre net non-commercial, 156 semanas trailing) predicen el retorno
forward del par en la dirección del posicionamiento?

Este es el experimento que SUPERSEDE al de COT-sobre-trades-vivos (~1 mes, n=178):
acá la unidad de análisis es la SEMANA histórica — hasta ~40 años × 8 mercados
sobre el D1 que ya está en `mt5_historical_cache`. Requiere haber corrido antes:
    python scripts/cot_backfill.py --weeks 2100    # ~40 años de cot_snapshots

Read-only sobre un snapshot de la DB viva (backup API). No toca el bot.
Anti-lookahead: available_from = report_date + 7 días calendario (pre-registrado,
cubre el lag de release martes→viernes + festivos CFTC).
Holdout: los últimos 2 años se EXCLUYEN de la exploración (regla 3 del pre-registro).

Uso:  python scripts/cot_price_study.py [--db PATH] [--include-holdout]
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

# mercado COT -> (símbolo del cache D1, signo: +1 si long divisa = long par)
_MARKET_TO_PAIR: dict[str, tuple[str, int]] = {
    "EUR": ("EURUSD", 1),
    "GBP": ("GBPUSD", 1),
    "JPY": ("USDJPY", -1),
    "AUD": ("AUDUSD", 1),
    "CAD": ("USDCAD", -1),
    "CHF": ("USDCHF", -1),
    "NZD": ("NZDUSD", 1),
    "GOLD": ("XAUUSD", 1),
    # USD (Dollar Index) se excluye: no hay serie DXY en el cache (pre-registro).
}

WINDOW_WEEKS = 156
MIN_WEEKS = 52
LAG_DAYS = 7               # calendario, conservador (release + festivos)
HORIZONS = (5, 10, 20)     # días hábiles (barras D1)
HI, LO = 0.8, 0.2
T_THRESHOLD = 2.39         # Bonferroni k=3 (p<0.017)
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


def snapshot_db(live_path: Path) -> Path:
    tmp = Path(tempfile.gettempdir()) / "cot_price_snapshot.db"
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


def load_daily_closes(con: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    """Cierra D1 del cache. El timeframe D1 se detecta por espaciado ~86400s
    (robusto a la constante MT5 usada al cargar)."""
    tfs = [r[0] for r in con.execute(
        "SELECT DISTINCT timeframe FROM mt5_historical_cache WHERE symbol=?", (symbol,)
    )]
    best: tuple[int, int] | None = None  # (timeframe, n)
    for tf in tfs:
        rows = con.execute(
            "SELECT time FROM mt5_historical_cache WHERE symbol=? AND timeframe=? "
            "ORDER BY time LIMIT 500", (symbol, tf),
        ).fetchall()
        if len(rows) < 50:
            continue
        diffs = np.diff([r[0] for r in rows])
        med = float(np.median(diffs))
        if 80000 <= med <= 100000 * 4:  # D1 (con findes ~86400-259200)
            n = con.execute(
                "SELECT COUNT(*) FROM mt5_historical_cache WHERE symbol=? AND timeframe=?",
                (symbol, tf),
            ).fetchone()[0]
            if best is None or n > best[1]:
                best = (tf, n)
    if best is None:
        return pd.DataFrame(columns=["date", "close"])
    df = pd.read_sql_query(
        "SELECT time, close FROM mt5_historical_cache "
        "WHERE symbol=? AND timeframe=? ORDER BY time",
        con, params=(symbol, best[0]),
    )
    df["date"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_localize(None)
    return df[["date", "close"]].dropna()


def cot_index(net: pd.Series) -> pd.Series:
    roll = net.rolling(WINDOW_WEEKS, min_periods=MIN_WEEKS)
    lo, hi = roll.min(), roll.max()
    rng = (hi - lo).replace(0, np.nan)
    return ((net - lo) / rng).clip(0, 1)


def welch_t(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 5 or len(b) < 5:
        return float("nan")
    va, vb = a.var(ddof=1), b.var(ddof=1)
    denom = math.sqrt(va / len(a) + vb / len(b))
    return float((a.mean() - b.mean()) / denom) if denom > 0 else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description="COT x precio (event-study pre-registrado)")
    ap.add_argument("--db", default=None)
    ap.add_argument("--include-holdout", action="store_true",
                    help="incluye los ultimos 2 anios (SOLO para el tiro unico post-pase)")
    args = ap.parse_args()

    snap = snapshot_db(resolve_db_path(args.db))
    con = sqlite3.connect(f"file:{snap.as_posix()}?mode=ro", uri=True)

    cot = pd.read_sql_query(
        "SELECT market_code, report_date, net_noncomm FROM cot_snapshots "
        "WHERE net_noncomm IS NOT NULL ORDER BY market_code, report_date", con)
    print(f"cot_snapshots: {len(cot)} filas | {cot['report_date'].min()} -> {cot['report_date'].max()}")

    holdout_cut = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=365 * HOLDOUT_YEARS)
    if not args.include_holdout:
        print(f"HOLDOUT: se excluye data posterior a {holdout_cut.date()} (regla 3 del pre-registro)\n")

    # eventos: (market, entry_date, idx, adjusted forward returns por horizonte, year)
    events: list[dict] = []
    for market, (pair, sign) in _MARKET_TO_PAIR.items():
        g = cot[cot["market_code"] == market].copy()
        if len(g) < MIN_WEEKS:
            print(f"  {market:<5} sin historia COT suficiente ({len(g)} semanas) -> salteado")
            continue
        g["report_dt"] = pd.to_datetime(g["report_date"])
        g["idx"] = cot_index(g["net_noncomm"].astype(float))
        g["available_from"] = g["report_dt"] + pd.Timedelta(days=LAG_DAYS)
        g = g.dropna(subset=["idx"])

        px = load_daily_closes(con, pair)
        if px.empty:
            print(f"  {market:<5} sin D1 de {pair} en el cache -> salteado")
            continue
        dates = px["date"].to_numpy()
        closes = px["close"].to_numpy(dtype=float)

        for _, row in g.iterrows():
            if not args.include_holdout and row["available_from"] >= holdout_cut:
                continue
            i = int(np.searchsorted(dates, np.datetime64(row["available_from"])))
            if i >= len(closes) - max(HORIZONS):
                continue
            ev = {"market": market, "idx": float(row["idx"]),
                  "year": int(pd.Timestamp(dates[i]).year),
                  "date": pd.Timestamp(dates[i])}
            for h in HORIZONS:
                ev[f"fwd{h}"] = sign * math.log(closes[i + h] / closes[i])
            events.append(ev)
        n_mkt = sum(1 for e in events if e["market"] == market)
        print(f"  {market:<5} {pair}: {n_mkt} semanas-evento con precio")

    df = pd.DataFrame(events)
    if df.empty:
        print("\nSin eventos -> nada para evaluar (corre el backfill primero).")
        return 0

    hi = df[df["idx"] >= HI]
    lo = df[df["idx"] <= LO]
    print(f"\nEventos: {len(df)} | bucket ALTO(idx>={HI}): {len(hi)} | BAJO(idx<={LO}): {len(lo)}")
    print(f"Rango: {df['date'].min().date()} -> {df['date'].max().date()}")

    mid = df["date"].quantile(0.5)
    print("\n=== H-A1: spread direction-adjusted (ALTO - BAJO), POOL de mercados ===")
    verdict_pass = True
    for h in HORIZONS:
        col = f"fwd{h}"
        spread = hi[col].mean() - lo[col].mean()
        # mitades
        s1 = hi[hi["date"] < mid][col].mean() - lo[lo["date"] < mid][col].mean()
        s2 = hi[hi["date"] >= mid][col].mean() - lo[lo["date"] >= mid][col].mean()
        # consistencia anual (años con ambos buckets)
        years = sorted(set(hi["year"]) & set(lo["year"]))
        ok_years = sum(
            1 for y in years
            if hi[hi["year"] == y][col].mean() - lo[lo["year"] == y][col].mean() > 0
        )
        yr_frac = ok_years / len(years) if years else float("nan")
        # t sobre muestras decimadas (no solapadas)
        k = max(1, math.ceil(h / 5))
        hi_d = hi.sort_values("date").iloc[::k][col].to_numpy()
        lo_d = lo.sort_values("date").iloc[::k][col].to_numpy()
        t = welch_t(hi_d, lo_d)
        crit = (spread > 0) and (s1 > 0) and (s2 > 0) and (yr_frac >= 0.6) and (t >= T_THRESHOLD)
        verdict_pass = verdict_pass and crit
        print(f"  fwd {h:>2}d: spread={spread*10000:+7.1f} bps | mitades=({s1*10000:+.1f}, {s2*10000:+.1f}) "
              f"| años+={yr_frac:.0%} ({len(years)}) | t(decim)={t:+.2f} | {'PASA' if crit else 'NO PASA'}")

    print("\n  Por mercado (spread fwd10d, referencia):")
    for market in _MARKET_TO_PAIR:
        hm, lm = hi[hi["market"] == market], lo[lo["market"] == market]
        if len(hm) >= 10 and len(lm) >= 10:
            print(f"    {market:<5} {(hm['fwd10'].mean()-lm['fwd10'].mean())*10000:+7.1f} bps "
                  f"(n={len(hm)}/{len(lm)})")

    print("\n=== VEREDICTO H-A1 (umbral pre-registrado, Bonferroni k=3) ===")
    if verdict_pass:
        print("  PASA en exploración -> tiene UN tiro sobre el holdout (--include-holdout NO es ese tiro;")
        print("  el tiro es re-correr SOLO sobre los 2 años excluidos). Después: regla congelada + harness §11.")
    else:
        print("  NO PASA -> la familia COT-legacy-extremos muere (sin re-cortes post-hoc).")
        print("  Recordar: k=6 en la tanda 2026-07-02; esto se reporta con denominador.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
