"""H-FADE1 — ¿operar el REVERSO de las señales del bot tiene edge? (familia 26)

Pre-registro: research/HIPOTESIS_2026-10-06_fade.md (commiteado ANTES de bajar datos).
Research-only: no toca el bot, ni flags, ni el .env (Settings = defaults del código);
a MT5 solo le LEE velas M15 (`initialize()` sin credenciales).

  python scripts/h_fade1_study.py --selftest          # datos sintéticos, sin red ni MT5
  python scripts/h_fade1_study.py --download          # baja M15 + manifest (sha256)
  python scripts/h_fade1_study.py --run [--workers 4] # un tiro -> research/H-FADE1_result.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "trading_data" / "h_fade1"
RESULT_PATH = ROOT / "research" / "H-FADE1_result.json"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD"]
DOWNLOAD_FROM = datetime(2022, 11, 1, tzinfo=timezone.utc)
DOWNLOAD_TO = datetime(2026, 1, 1, tzinfo=timezone.utc)
WINDOW_START = date(2023, 1, 2)
WINDOW_END = date(2025, 12, 31)
HALF_SPLIT = date(2024, 7, 1)          # 1ª mitad < split <= 2ª mitad
TF_MINUTES = 15
LOOKBACK = 250
NW_LAGS = 5
STRATEGIES = ("mean_reversion", "momentum", "forex_session_breakout")
CRIT = {"n_min": 100, "mean_min": 0.05, "t_min": 2.50}


# ------------------------------------------------------------------ settings
def default_settings():
    """Settings = defaults del CÓDIGO: no se lee el .env (ni el del bot ni otro)."""
    import app.config.settings as cfg

    cfg.load_dotenv = lambda *a, **k: None   # type: ignore[assignment]
    return cfg.load_settings()


# ----------------------------------------------------------------------- hora
def _last_sunday(year: int, month: int) -> date:
    d = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def eu_summer(utc_dt: datetime) -> bool:
    """Horario de verano de la UE: último domingo de marzo 01:00 UTC → último
    domingo de octubre 01:00 UTC."""
    y = utc_dt.year
    start = datetime.combine(_last_sunday(y, 3), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    end = datetime.combine(_last_sunday(y, 10), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    return start <= utc_dt < end


def server_to_utc(server_epoch: int) -> int:
    """Época de MT5 (hora del servidor EET/EEST, regla UE) → época UTC real."""
    as_summer = server_epoch - 3 * 3600
    if eu_summer(datetime.fromtimestamp(as_summer, tz=timezone.utc)):
        return as_summer
    return server_epoch - 2 * 3600


# --------------------------------------------------------------------- datos
def download() -> int:
    import MetaTrader5 as mt5  # type: ignore[import-not-found]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not mt5.initialize():                # SIN credenciales: solo se engancha a la terminal
        print("MT5 no inicializó:", mt5.last_error())
        return 1
    manifest = []
    try:
        for sym in SYMBOLS:
            mt5.symbol_select(sym, True)
            rows = []
            # por año: copy_rates_range tiene tope de velas por llamada
            for y in range(DOWNLOAD_FROM.year, DOWNLOAD_TO.year + 1):
                a = max(DOWNLOAD_FROM, datetime(y, 1, 1, tzinfo=timezone.utc))
                b = min(DOWNLOAD_TO, datetime(y + 1, 1, 1, tzinfo=timezone.utc))
                if a >= b:
                    continue
                rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M15, a, b)
                if rates is None:
                    print(sym, y, "sin datos", mt5.last_error())
                    continue
                rows.extend(rates.tolist())
            seen, bars = set(), []
            for r in rows:
                t_srv = int(r[0])
                if t_srv in seen:
                    continue
                seen.add(t_srv)
                bars.append((server_to_utc(t_srv), float(r[1]), float(r[2]), float(r[3]),
                             float(r[4]), int(r[5]), int(r[6]), t_srv))
            bars.sort()
            path = DATA_DIR / f"{sym}_M15.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["time_utc", "open", "high", "low", "close", "tick_volume",
                            "spread", "time_server"])
                w.writerows(bars)
            manifest.append(_manifest_row(sym, path, bars))
            print(f"{sym}: {len(bars)} velas, {manifest[-1]['first_utc']} → "
                  f"{manifest[-1]['last_utc']}, huecos>3d hábiles: {manifest[-1]['gaps']}")
    finally:
        mt5.shutdown()
    mpath = DATA_DIR / "manifest.csv"
    with mpath.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(manifest[0].keys()))
        w.writeheader()
        w.writerows(manifest)
    print("manifest:", mpath, "sha256", _sha256(mpath))
    return 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_row(sym: str, path: Path, bars: list) -> dict:
    gaps = 0
    for a, b in zip(bars, bars[1:]):
        da = datetime.fromtimestamp(a[0], tz=timezone.utc)
        db = datetime.fromtimestamp(b[0], tz=timezone.utc)
        weekdays = sum(1 for k in range(1, (db.date() - da.date()).days)
                       if (da.date() + timedelta(days=k)).weekday() < 5)
        if weekdays > 3:
            gaps += 1
    iso = lambda e: datetime.fromtimestamp(e, tz=timezone.utc).isoformat(timespec="minutes")
    return {"symbol": sym, "file": path.name, "bars": len(bars),
            "first_utc": iso(bars[0][0]) if bars else "", "last_utc": iso(bars[-1][0]) if bars else "",
            "gaps": gaps, "sha256": _sha256(path)}


def load_bars(sym: str) -> list[dict]:
    out = []
    with (DATA_DIR / f"{sym}_M15.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.append({"time": int(r["time_utc"]), "open": float(r["open"]),
                        "high": float(r["high"]), "low": float(r["low"]),
                        "close": float(r["close"]), "volume": float(r["tick_volume"])})
    return out


# ------------------------------------------------------------------- replay
@dataclass
class Trade:
    strategy: str
    symbol: str
    entry_utc: int
    signal_dir: str
    r_net: float
    r_net_stress: float
    r_gross: float
    cost_r: float
    exit_reason: str
    bars_held: int
    direct_r_net: float
    direct_r_gross: float


def _setup(direction: str, entry_utc: int, entry: float, dist: float, k_bars: int):
    from app.backtest.trade_simulator import TradeSetup

    if direction == "long":
        sl, tp = entry - dist, entry + dist
    else:
        sl, tp = entry + dist, entry - dist
    return TradeSetup(direction=direction, entry_utc=entry_utc, entry_price=entry,
                      sl_initial=sl, tp_initial=tp, time_exit_bars=k_bars)


def replay_symbol(sym: str, bars: list[dict], strategies: dict, settings,
                  category: str, window: tuple[date, date]) -> list[Trade]:
    """Recorre las velas; en cada señal simula el REVERSO 1:1 (y el directo como
    control). Una posición por (símbolo, estrategia) a la vez (sobre el reverso)."""
    from app.analyzers.technical_patterns import atr_pct_from_candles
    from app.backtest.context_builder import build_context
    from app.backtest.trade_simulator import net_r, simulate_trade

    w0 = int(datetime.combine(window[0], datetime.min.time(), timezone.utc).timestamp())
    w1 = int(datetime.combine(window[1] + timedelta(days=1), datetime.min.time(),
                              timezone.utc).timestamp())
    next_free = {name: 0 for name in strategies}
    trades: list[Trade] = []
    min_conf = int(settings.strategy_min_confidence)
    for n in range(LOOKBACK, len(bars) - 1):
        t_sig = int(bars[n]["time"])
        if t_sig < w0:
            continue
        if t_sig >= w1:
            break
        ctx = None
        for name, strat in strategies.items():
            if n < next_free[name]:
                continue
            if ctx is None:
                ctx = build_context(bars, n, symbol=sym, category=category, lookback=LOOKBACK)
            try:
                sig = strat.evaluate(ctx, settings)
            except Exception:
                continue
            if sig is None or sig.confidence < min_conf:
                continue
            dist = abs(float(sig.entry) - float(sig.stop))
            entry_bar = bars[n + 1]
            entry = float(entry_bar["open"])
            if dist <= 0 or entry <= 0:
                continue
            k_bars = max(1, math.ceil(int(sig.time_horizon_hours or 1) * 60 / TF_MINUTES))
            window_bars = bars[max(0, n - LOOKBACK + 1): n + 1]
            atr_pct = atr_pct_from_candles(window_bars) or 0.0
            slip = float(settings.backtest_sl_slippage_atr) * (atr_pct / 100.0) * entry
            fwd = bars[n + 1: n + 2 + k_bars]
            fade_dir = "short" if sig.direction == "long" else "long"
            res = {}
            for label, d in (("fade", fade_dir), ("direct", sig.direction)):
                setup = _setup(d, int(entry_bar["time"]), entry, dist, k_bars)
                sim = simulate_trade(setup, fwd, sl_slippage_price=slip)
                c, rn = net_r(sim.r_gross, entry, setup.sl_initial, category, settings,
                              bars_held=sim.bars_held, direction=d)
                _, rs = net_r(sim.r_gross, entry, setup.sl_initial, category, settings,
                              stress=True, bars_held=sim.bars_held, direction=d)
                res[label] = (sim, c, rn, rs)
            sim, c, rn, rs = res["fade"]
            trades.append(Trade(name, sym, int(entry_bar["time"]), sig.direction, rn, rs,
                                sim.r_gross, c, sim.exit_reason, sim.bars_held,
                                res["direct"][2], res["direct"][0].r_gross))
            next_free[name] = n + 1 + sim.bars_held   # B12 del harness: libre al cerrar
    return trades


def _real_strategies() -> dict:
    from app.strategies.forex_session_breakout import ForexSessionBreakoutStrategy
    from app.strategies.mean_reversion import MeanReversionStrategy
    from app.strategies.momentum import MomentumStrategy

    return {"mean_reversion": MeanReversionStrategy(), "momentum": MomentumStrategy(),
            "forex_session_breakout": ForexSessionBreakoutStrategy()}


def _replay_worker(sym: str) -> list[dict]:
    settings = default_settings()
    category = "gold" if sym == "XAUUSD" else "forex"
    bars = load_bars(sym)
    trades = replay_symbol(sym, bars, _real_strategies(), settings, category,
                           (WINDOW_START, WINDOW_END))
    return [t.__dict__ for t in trades]


# -------------------------------------------------------------- estadística
def newey_west_t(series: list[float], lags: int = NW_LAGS) -> float | None:
    n = len(series)
    if n < 3:
        return None
    m = sum(series) / n
    d = [x - m for x in series]
    lrv = sum(v * v for v in d) / n
    for k in range(1, min(lags, n - 1) + 1):
        lrv += 2.0 * (1.0 - k / (lags + 1.0)) * sum(d[i] * d[i - k] for i in range(k, n)) / n
    return None if lrv <= 0 else m / math.sqrt(lrv / n)


def weekdays(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)
            if (a + timedelta(days=i)).weekday() < 5]


def daily_series(trades: list[dict], days: list[date], key: str = "r_net") -> list[float]:
    acc: dict[date, float] = defaultdict(float)
    for t in trades:
        acc[datetime.fromtimestamp(t["entry_utc"], tz=timezone.utc).date()] += float(t[key])
    return [acc.get(d, 0.0) for d in days]


def _mean(x: list[float]) -> float | None:
    return sum(x) / len(x) if x else None


def evaluate(trades: list[dict], window=(WINDOW_START, WINDOW_END)) -> dict:
    from app.learning.trade_outcomes import session_of

    days = weekdays(*window)
    out: dict = {"by_strategy": {}, "k": len(STRATEGIES)}
    for s in STRATEGIES:
        ts = [t for t in trades if t["strategy"] == s]
        series = daily_series(ts, days)
        h1 = [v for d, v in zip(days, series) if d < HALF_SPLIT]
        h2 = [v for d, v in zip(days, series) if d >= HALF_SPLIT]
        mean_r = _mean([t["r_net"] for t in ts])
        stress = _mean([t["r_net_stress"] for t in ts])
        t_nw = newey_west_t(series)
        crit = {
            "1_n_ge_100": len(ts) >= CRIT["n_min"],
            "2_mean_ge_0.05R": mean_r is not None and mean_r >= CRIT["mean_min"],
            "3_t_nw_ge_2.50": t_nw is not None and t_nw >= CRIT["t_min"],
            "4_both_halves_pos": bool(h1) and bool(h2) and _mean(h1) > 0 and _mean(h2) > 0,
            "5_stress_pos": stress is not None and stress > 0,
        }
        desc = {
            "by_symbol": _group(ts, lambda t: t["symbol"]),
            "by_year": _group(ts, lambda t: str(datetime.fromtimestamp(
                t["entry_utc"], tz=timezone.utc).year)),
            "by_session": _group(ts, lambda t: session_of(datetime.fromtimestamp(
                t["entry_utc"], tz=timezone.utc).isoformat())),
            "by_signal_dir": _group(ts, lambda t: t["signal_dir"]),
            "exit_reasons": {k: round(v / len(ts), 3) for k, v in _count(
                ts, lambda t: t["exit_reason"]).items()} if ts else {},
            "mean_cost_r": _round(_mean([t["cost_r"] for t in ts])),
            "mean_r_gross_fade": _round(_mean([t["r_gross"] for t in ts])),
            "mean_r_gross_direct": _round(_mean([t["direct_r_gross"] for t in ts])),
            "mean_r_net_direct": _round(_mean([t["direct_r_net"] for t in ts])),
            "mean_bars_held": _round(_mean([t["bars_held"] for t in ts])),
        }
        out["by_strategy"][s] = {
            "n": len(ts), "mean_r_net": _round(mean_r), "mean_r_net_stress": _round(stress),
            "t_nw_daily": _round(t_nw), "half1_daily_mean": _round(_mean(h1)),
            "half2_daily_mean": _round(_mean(h2)), "criteria": crit,
            "verdict": "PASA" if all(crit.values()) else "NO PASA", "descriptive": desc,
        }
    out["family_verdict"] = ("PASA" if any(v["verdict"] == "PASA"
                                           for v in out["by_strategy"].values()) else "NO PASA")
    return out


def _round(x, nd=4):
    return None if x is None else round(float(x), nd)


def _count(ts, key):
    c: dict[str, int] = defaultdict(int)
    for t in ts:
        c[key(t)] += 1
    return dict(c)


def _group(ts, key):
    g: dict[str, list[float]] = defaultdict(list)
    for t in ts:
        g[key(t)].append(float(t["r_net"]))
    return {k: {"n": len(v), "mean_r_net": round(sum(v) / len(v), 4)} for k, v in sorted(g.items())}


def run(workers: int) -> int:
    mpath = DATA_DIR / "manifest.csv"
    if not mpath.exists():
        print("Falta el manifest: corré --download primero")
        return 1
    with mpath.open(encoding="utf-8") as fh:
        manifest = list(csv.DictReader(fh))
    for m in manifest:
        if _sha256(DATA_DIR / m["file"]) != m["sha256"]:
            print("checksum distinto:", m["file"])
            return 1
    with ProcessPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(_replay_worker, SYMBOLS))
    trades = [t for p in parts for t in p]
    result = evaluate(trades)
    result.update({
        "hypothesis": "H-FADE1 (familia 26)",
        "preregistration": "research/HIPOTESIS_2026-10-06_fade.md",
        "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "manifest_sha256": _sha256(mpath),
        "n_trades_total": len(trades),
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    RESULT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({s: {k: v for k, v in r.items() if k != "descriptive"}
                      for s, r in result["by_strategy"].items()}, indent=2, ensure_ascii=False))
    print("FAMILIA:", result["family_verdict"], "->", RESULT_PATH)
    return 0


# ------------------------------------------------------------------ selftest
def selftest() -> int:
    """Datos SINTÉTICOS (sin red ni MT5): verifica cada pieza antes del tiro."""
    from app.backtest.trade_simulator import simulate_trade
    from app.strategies.base import StrategySignal

    settings = default_settings()
    checks: list[tuple[str, bool]] = []

    def ok(name, cond):
        checks.append((name, bool(cond)))

    # 1. hora del servidor → UTC (cambios de horario 2023-2025)
    u = lambda *a: int(datetime(*a, tzinfo=timezone.utc).timestamp())
    ok("invierno: srv 12:00 = 10:00 UTC", server_to_utc(u(2024, 1, 15, 12)) == u(2024, 1, 15, 10))
    ok("verano: srv 12:00 = 09:00 UTC", server_to_utc(u(2024, 7, 1, 12)) == u(2024, 7, 1, 9))
    for y, m, d in ((2023, 3, 26), (2024, 3, 31), (2025, 3, 30)):
        ok(f"marzo {y}: 00:30 UTC = srv 02:30", server_to_utc(u(y, m, d, 2, 30)) == u(y, m, d, 0, 30))
        ok(f"marzo {y}: 01:30 UTC = srv 04:30", server_to_utc(u(y, m, d, 4, 30)) == u(y, m, d, 1, 30))
    for y, m, d in ((2023, 10, 29), (2024, 10, 27), (2025, 10, 26)):
        ok(f"octubre {y}: 00:30 UTC = srv 03:30", server_to_utc(u(y, m, d, 3, 30)) == u(y, m, d, 0, 30))
        ok(f"octubre {y}: 02:00 UTC = srv 04:00", server_to_utc(u(y, m, d, 4)) == u(y, m, d, 2))
    ok("último domingo de marzo 2024", _last_sunday(2024, 3) == date(2024, 3, 31))

    # 2. geometría del reverso
    s = _setup("short", 0, 1.1000, 0.0010, 4)
    ok("reverso short: SL arriba / TP abajo", math.isclose(s.sl_initial, 1.1010)
       and math.isclose(s.tp_initial, 1.0990))
    s = _setup("long", 0, 1.1000, 0.0010, 4)
    ok("reverso long: SL abajo / TP arriba", math.isclose(s.sl_initial, 1.0990)
       and math.isclose(s.tp_initial, 1.1010))

    # 3. empate en la misma vela -> stop; 4. salida por tiempo; TP limpio
    bar = lambda o, h, l, c, t=0: {"time": t, "open": o, "high": h, "low": l, "close": c}
    tie = simulate_trade(_setup("long", 0, 1.1, 0.001, 4), [bar(1.1, 1.102, 1.098, 1.1)])
    ok("empate -> stop (-1R)", tie.exit_reason == "sl" and math.isclose(tie.r_gross, -1.0))
    flat = [bar(1.1, 1.1005, 1.0995, 1.1, i) for i in range(6)]
    tx = simulate_trade(_setup("long", 0, 1.1, 0.001, 4), flat)
    ok("salida por tiempo en la vela K", tx.exit_reason == "time" and tx.bars_held == 4)
    tp = simulate_trade(_setup("short", 0, 1.1, 0.001, 4), [bar(1.1, 1.1002, 1.0985, 1.099)])
    ok("TP del reverso short = +1R", tp.exit_reason == "tp" and math.isclose(tp.r_gross, 1.0))

    # 5. costos en R (forex 0.02 % × 1.25 / riesgo %)
    from app.backtest.trade_simulator import net_r
    c, rn = net_r(1.0, 1.1, 1.099, "forex", settings)
    ok("costo en R", math.isclose(c, 0.02 * 1.25 / (0.001 / 1.1 * 100), rel_tol=1e-4)
       and math.isclose(rn, 1.0 - c, rel_tol=1e-6))
    cs, _ = net_r(1.0, 1.1, 1.099, "forex", settings, stress=True)
    ok("estrés × 1.5", math.isclose(cs / c, 1.5 / 1.25, rel_tol=1e-4))

    # 6. serie diaria con ceros (solo días hábiles)
    days = weekdays(date(2024, 1, 1), date(2024, 1, 14))
    ok("10 días hábiles en 2 semanas", len(days) == 10)
    ser = daily_series([{"entry_utc": u(2024, 1, 3, 10), "r_net": 1.0},
                        {"entry_utc": u(2024, 1, 3, 15), "r_net": -0.5}], days)
    ok("serie diaria suma por día y pone ceros", ser[2] == 0.5 and sum(ser) == 0.5
       and ser.count(0.0) == 9)

    # 7. t de Newey-West contra el cálculo a mano
    x = [1.0, -0.5, 2.0, 0.3, -1.2, 0.8, 1.5, -0.2]
    n, m = len(x), sum(x) / len(x)
    dd = [v - m for v in x]
    g = lambda k: sum(dd[i] * dd[i - k] for i in range(k, n)) / n
    lrv = g(0) + 2 * sum((1 - k / 6) * g(k) for k in range(1, 6))
    ok("t Newey-West (5 rezagos)", math.isclose(newey_west_t(x), m / math.sqrt(lrv / n)))

    # 8-9. señal plantada + una posición por (símbolo, estrategia)
    class Planted:
        name = "planted"

        def evaluate(self, ctx, st):
            p = ctx.snapshot.price
            return StrategySignal(strategy_name="planted", direction="long", entry=p,
                                  stop=p * 0.999, targets=[p * 1.002], confidence=70,
                                  reasoning=[], time_horizon_hours=1)

    t0 = u(2023, 1, 2)
    bars = []
    for i in range(LOOKBACK + 40):
        # precio que BAJA 0.06 % por vela: la señal long pierde, el reverso gana
        p = 1.1 * (1 - 0.0006) ** i
        bars.append({"time": t0 - LOOKBACK * 900 + i * 900, "open": p * 1.00005,
                     "high": p * 1.0001, "low": p * 0.9993, "close": p, "volume": 1.0})
    tr = replay_symbol("SYN", bars, {"planted": Planted()}, settings, "forex",
                       (date(2023, 1, 2), date(2023, 1, 3)))
    ok("hay trades plantados", len(tr) >= 3)
    ok("el reverso de una señal perdedora gana (bruto > 0)",
       all(t.r_gross > 0 for t in tr) and all(t.direct_r_gross < 0 for t in tr))
    spans = sorted((t.entry_utc, t.entry_utc + t.bars_held * 900) for t in tr)
    ok("una posición a la vez", all(b[0] > a[1] for a, b in zip(spans, spans[1:])))
    ok("entrada en la apertura de N+1", all((t.entry_utc - t0) % 900 == 0 for t in tr))

    # 10. criterio: PASA exige todo
    fake = [{"strategy": "mean_reversion", "symbol": "S", "entry_utc": u(2023, 1, 2) + 86400 * i,
             "signal_dir": "long", "r_net": 0.3 + (0.2 if i % 2 else -0.2), "r_net_stress": 0.2,
             "r_gross": 0.5, "cost_r": 0.2, "exit_reason": "tp", "bars_held": 3,
             "direct_r_net": -0.7, "direct_r_gross": -0.5} for i in range(0, 1090)]
    ev = evaluate(fake)
    ok("caso positivo fuerte -> PASA", ev["by_strategy"]["mean_reversion"]["verdict"] == "PASA")
    ok("estrategias sin trades -> NO PASA", ev["by_strategy"]["momentum"]["verdict"] == "NO PASA")
    ok("familia PASA si alguna pasa", ev["family_verdict"] == "PASA")
    ok("settings sin .env: min_confidence 60", int(settings.strategy_min_confidence) == 60)

    for name, good in checks:
        print(("OK   " if good else "FALLA"), name)
    failed = sum(1 for _, good in checks if not good)
    print(f"selftest: {len(checks) - failed}/{len(checks)}")
    return 1 if failed else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--selftest", action="store_true")
    g.add_argument("--download", action="store_true")
    g.add_argument("--run", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.download:
        return download()
    return run(args.workers)


if __name__ == "__main__":
    sys.exit(main())
