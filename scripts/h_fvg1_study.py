"""H-FVG1 / H-IFVG1 — Fair Value Gaps e inverse FVG en forex/oro H1 (familia 27).

Pre-registro: research/HIPOTESIS_2026-10-07_fvg.md (commiteado ANTES de bajar datos).
Research-only: no toca el bot, ni flags, ni el .env (Settings = defaults del código);
a MT5 solo le LEE velas H1 (`initialize()` sin credenciales).

  python scripts/h_fvg1_study.py --selftest   # datos sintéticos, sin red ni MT5
  python scripts/h_fvg1_study.py --download   # baja H1 + manifest (sha256)
  python scripts/h_fvg1_study.py --run        # un tiro -> research/H-FVG1_result.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import h_fade1_study as fade  # noqa: E402  (hora del servidor, NW, días hábiles, settings)

DATA_DIR = ROOT / "trading_data" / "h_fvg1"
RESULT_PATH = ROOT / "research" / "H-FVG1_result.json"
MANIFEST_PATH = ROOT / "research" / "H-FVG1_manifest.csv"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD"]

# (nombre, desde, hasta exclusivo) en UTC; el "hasta" corta ANTES de la ventana vista.
SEGMENTS = {
    "primary": (datetime(2010, 9, 1, tzinfo=timezone.utc),
                datetime(2017, 12, 1, tzinfo=timezone.utc)),
    "secondary": (datetime(2026, 5, 1, tzinfo=timezone.utc),
                  datetime(2026, 10, 7, tzinfo=timezone.utc)),
}
PRIMARY = (date(2011, 1, 3), date(2017, 11, 30))
HALF_SPLIT = date(2014, 7, 1)
SECONDARY = (date(2026, 6, 16), date(2026, 10, 6))

ATR_N = 14
MIN_GAP_ATR = 0.5
STOP_BUFFER_ATR = 0.1
TP_R = 2.0
FILL_BARS = 24
INVALIDATE_BARS = 48
HOLD_BARS = 48
NW_LAGS = 5
HYPS = ("fvg", "ifvg")
CRIT = {"n_min": 100, "mean_min": 0.05, "t_min": 2.50}
MIN_YEARS = 5
MIN_SYMBOLS = 6


# ----------------------------------------------------------------- indicadores
def atr(bars: list[dict], n: int, period: int = ATR_N) -> float | None:
    """Media simple del true range de las velas n−period+1 … n (solo pasado)."""
    if n < period or n >= len(bars):
        return None
    total = 0.0
    for i in range(n - period + 1, n + 1):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        total += max(h, pc) - min(l, pc)
    return total / period


@dataclass(frozen=True)
class Gap:
    n: int          # vela de formación (la 3ª)
    side: str       # 'bull' | 'bear'
    lo: float
    hi: float
    atr: float


def detect_gap(bars: list[dict], n: int) -> Gap | None:
    """FVG formado al cierre de la vela n (usa n−2 … n y el ATR hasta n)."""
    if n < 2:
        return None
    a = atr(bars, n)
    if not a or a <= 0:
        return None
    if bars[n - 2]["high"] < bars[n]["low"]:
        lo, hi, side = bars[n - 2]["high"], bars[n]["low"], "bull"
    elif bars[n - 2]["low"] > bars[n]["high"]:
        lo, hi, side = bars[n]["high"], bars[n - 2]["low"], "bear"
    else:
        return None
    if hi - lo < MIN_GAP_ATR * a:
        return None
    return Gap(n, side, lo, hi, a)


# -------------------------------------------------------------------- órdenes
@dataclass(frozen=True)
class Order:
    hyp: str
    direction: str
    limit: float
    stop: float
    tp: float
    valid_from: int
    valid_to: int
    event: int      # vela del evento (formación para fvg, inversión para ifvg)
    atr: float


def order_fvg(g: Gap) -> Order:
    if g.side == "bull":
        limit, stop = g.hi, g.lo - STOP_BUFFER_ATR * g.atr
        direction = "long"
    else:
        limit, stop = g.lo, g.hi + STOP_BUFFER_ATR * g.atr
        direction = "short"
    risk = abs(limit - stop)
    tp = limit + TP_R * risk if direction == "long" else limit - TP_R * risk
    return Order("fvg", direction, limit, stop, tp, g.n + 1, g.n + FILL_BARS, g.n, g.atr)


def order_ifvg(g: Gap, m: int, atr_m: float) -> Order:
    """FVG invertido en la vela m: el alcista roto se vende en su borde inferior; el
    bajista roto se compra en su borde superior."""
    if g.side == "bull":
        limit, stop, direction = g.lo, g.hi + STOP_BUFFER_ATR * atr_m, "short"
    else:
        limit, stop, direction = g.hi, g.lo - STOP_BUFFER_ATR * atr_m, "long"
    risk = abs(limit - stop)
    tp = limit + TP_R * risk if direction == "long" else limit - TP_R * risk
    return Order("ifvg", direction, limit, stop, tp, m + 1, m + FILL_BARS, m, atr_m)


def run_order(bars: list[dict], o: Order, slip_price: float) -> dict | None:
    """Llenado al límite dentro de [valid_from, valid_to] y salida pesimista.
    None si no se llena. r_gross en R del riesgo inicial |límite − stop|."""
    is_long = o.direction == "long"
    entry, stop, tp = o.limit, o.stop, o.tp
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    last = min(o.valid_to, len(bars) - 1)
    fill = None
    for j in range(o.valid_from, last + 1):
        b = bars[j]
        if (b["low"] <= entry) if is_long else (b["high"] >= entry):
            fill = j
            break
    if fill is None:
        return None

    def r(px: float) -> float:
        return (px - entry) / risk if is_long else (entry - px) / risk

    def worse(px: float) -> float:
        return px - slip_price if is_long else px + slip_price

    def out(exit_idx: int, px: float, reason: str, held: int) -> dict:
        return {"fill_idx": fill, "exit_idx": exit_idx, "r_gross": r(px),
                "exit_reason": reason, "bars_held": held}

    b = bars[fill]
    beyond_stop = (lambda p: p <= stop) if is_long else (lambda p: p >= stop)
    beyond_tp = (lambda p: p >= tp) if is_long else (lambda p: p <= tp)
    if beyond_stop(b["open"]):                       # abrió más allá del stop
        return out(fill, worse(b["open"]), "gap_sl", 0)
    if beyond_stop(b["low"] if is_long else b["high"]):   # en la vela del llenado: solo stop
        return out(fill, worse(stop), "sl", 0)
    for k in range(1, HOLD_BARS + 1):
        j = fill + k
        if j >= len(bars):                            # se acabaron los datos
            return out(len(bars) - 1, bars[-1]["close"], "eod", k - 1)
        b = bars[j]
        if k == HOLD_BARS:
            return out(j, b["open"], "time", k)
        if beyond_stop(b["open"]):
            return out(j, worse(b["open"]), "gap_sl", k)
        if beyond_tp(b["open"]):
            return out(j, tp, "tp", k)                # el extra no se acredita
        if beyond_stop(b["low"] if is_long else b["high"]):
            return out(j, worse(stop), "sl", k)       # empate intrabar: gana el stop
        if beyond_tp(b["high"] if is_long else b["low"]):
            return out(j, tp, "tp", k)
    raise AssertionError("inalcanzable")


# --------------------------------------------------------------------- replay
def _epoch(d: date) -> int:
    return int(datetime.combine(d, datetime.min.time(), timezone.utc).timestamp())


def replay(bars: list[dict], window: tuple[date, date], slip_atr: float) -> list[dict]:
    """Recorre las velas y devuelve los trades brutos de las dos hipótesis. Eventos
    (formación / inversión) dentro de la ventana; una orden pendiente o abierta por
    hipótesis a la vez; los eventos mientras está ocupada se ignoran."""
    w0, w1 = _epoch(window[0]), _epoch(window[1] + timedelta(days=1))
    busy = {h: -1 for h in HYPS}
    watch: list[Gap] = []                 # FVG vivos para la inversión
    trades: list[dict] = []

    def take(o: Order) -> None:
        a = o.atr
        res = run_order(bars, o, slip_atr * a)
        if res is None:
            busy[o.hyp] = o.valid_to
            return
        busy[o.hyp] = res["exit_idx"]
        trades.append({"hyp": o.hyp, "direction": o.direction, "entry": o.limit,
                       "stop": o.stop, "event_idx": o.event, **res,
                       "fill_utc": int(bars[res["fill_idx"]]["time"])})

    for n in range(len(bars)):
        t = int(bars[n]["time"])
        in_window = w0 <= t < w1
        # 1) inversiones con el cierre de esta vela (gaps formados ANTES de n)
        still: list[Gap] = []
        for g in watch:
            if n - g.n > INVALIDATE_BARS:
                continue
            c = bars[n]["close"]
            inverted = c < g.lo if g.side == "bull" else c > g.hi
            if not inverted:
                still.append(g)
                continue
            a = atr(bars, n)
            if in_window and a and n > busy["ifvg"]:
                take(order_ifvg(g, n, a))
        watch = still
        # 2) FVG nuevo formado al cierre de esta vela
        g = detect_gap(bars, n)
        if g is None:
            continue
        watch.append(g)
        if in_window and n > busy["fvg"]:
            take(order_fvg(g))
    return trades


# ---------------------------------------------------------------------- datos
def download() -> int:
    import MetaTrader5 as mt5  # type: ignore[import-not-found]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not mt5.initialize():              # SIN credenciales: solo se engancha a la terminal
        print("MT5 no inicializó:", mt5.last_error())
        return 1
    manifest = []
    try:
        for sym in SYMBOLS:
            mt5.symbol_select(sym, True)
            for seg, (a, b) in SEGMENTS.items():
                rows = []
                for y in range(a.year, b.year + 1):   # por año: tope de velas por llamada
                    ya = max(a - timedelta(days=1), datetime(y, 1, 1, tzinfo=timezone.utc))
                    yb = min(b + timedelta(days=1), datetime(y + 1, 1, 1, tzinfo=timezone.utc))
                    if ya >= yb:
                        continue
                    rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_H1, ya, yb)
                    if rates is not None:
                        rows.extend(rates.tolist())
                seen, bars = set(), []
                lo, hi = int(a.timestamp()), int(b.timestamp())
                for r in rows:
                    t_srv = int(r[0])
                    if t_srv in seen:
                        continue
                    seen.add(t_srv)
                    t_utc = fade.server_to_utc(t_srv)
                    if lo <= t_utc < hi:
                        bars.append((t_utc, float(r[1]), float(r[2]), float(r[3]),
                                     float(r[4]), int(r[5]), int(r[6]), t_srv))
                bars.sort()
                path = DATA_DIR / f"{sym}_H1_{seg}.csv"
                with path.open("w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    w.writerow(["time_utc", "open", "high", "low", "close", "tick_volume",
                                "spread", "time_server"])
                    w.writerows(bars)
                row = fade._manifest_row(f"{sym}_{seg}", path, bars)
                manifest.append(row)
                print(f"{sym} {seg}: {row['bars']} velas, {row['first_utc']} → "
                      f"{row['last_utc']}, huecos>3d hábiles: {row['gaps']}")
    finally:
        mt5.shutdown()
    with MANIFEST_PATH.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(manifest[0].keys()))
        w.writeheader()
        w.writerows(manifest)
    print("manifest:", MANIFEST_PATH, "sha256", fade._sha256(MANIFEST_PATH))
    return 0


def load_bars(sym: str, seg: str) -> list[dict]:
    out = []
    with (DATA_DIR / f"{sym}_H1_{seg}.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.append({"time": int(r["time_utc"]), "open": float(r["open"]),
                        "high": float(r["high"]), "low": float(r["low"]),
                        "close": float(r["close"])})
    return out


def verify_manifest() -> list[str]:
    """Rechequea los sha256 de los CSV contra el manifest commiteado."""
    bad = []
    with MANIFEST_PATH.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            path = DATA_DIR / row["file"]
            if not path.exists() or fade._sha256(path) != row["sha256"]:
                bad.append(row["file"])
    return bad


# -------------------------------------------------------------- estadística
def with_costs(trades: list[dict], category: str, settings) -> list[dict]:
    from app.backtest.trade_simulator import net_r

    out = []
    for t in trades:
        c, rn = net_r(t["r_gross"], t["entry"], t["stop"], category, settings,
                      bars_held=t["bars_held"], direction=t["direction"])
        _, rs = net_r(t["r_gross"], t["entry"], t["stop"], category, settings, stress=True,
                      bars_held=t["bars_held"], direction=t["direction"])
        out.append({**t, "cost_r": c, "r_net": rn, "r_net_stress": rs})
    return out


def _mean(x: list[float]) -> float | None:
    return sum(x) / len(x) if x else None


def _round(x, nd=4):
    return None if x is None else round(float(x), nd)


def _group(ts: list[dict], key) -> dict:
    g: dict = defaultdict(list)
    for t in ts:
        g[key(t)].append(t["r_net"])
    return {k: {"n": len(v), "mean_r_net": _round(_mean(v))} for k, v in sorted(g.items())}


def evaluate(primary: list[dict], secondary: list[dict]) -> dict:
    from app.learning.trade_outcomes import session_of

    days = fade.weekdays(*PRIMARY)
    out: dict = {"k": len(HYPS), "by_hyp": {}}
    iso = lambda e: datetime.fromtimestamp(e, tz=timezone.utc).isoformat()
    for h in HYPS:
        ts = [t for t in primary if t["hyp"] == h]
        sec = [t for t in secondary if t["hyp"] == h]
        series = fade.daily_series([{"entry_utc": t["fill_utc"], "r_net": t["r_net"]}
                                    for t in ts], days)
        h1 = [v for d, v in zip(days, series) if d < HALF_SPLIT]
        h2 = [v for d, v in zip(days, series) if d >= HALF_SPLIT]
        mean_r = _mean([t["r_net"] for t in ts])
        stress = _mean([t["r_net_stress"] for t in ts])
        sec_mean = _mean([t["r_net"] for t in sec])
        t_nw = fade.newey_west_t(series, NW_LAGS)
        crit = {
            "1_n_ge_100": len(ts) >= CRIT["n_min"],
            "2_mean_ge_0.05R": mean_r is not None and mean_r >= CRIT["mean_min"],
            "3_t_nw_ge_2.50": t_nw is not None and t_nw >= CRIT["t_min"],
            "4_both_halves_pos": bool(h1) and bool(h2) and _mean(h1) > 0 and _mean(h2) > 0,
            "5_stress_pos": stress is not None and stress > 0,
            "6_secondary_pos": sec_mean is not None and sec_mean > 0,
        }
        out["by_hyp"][h] = {
            "verdict": "PASA" if all(crit.values()) else "NO PASA",
            "criteria": crit,
            "n": len(ts), "mean_r_net": _round(mean_r), "mean_r_net_stress": _round(stress),
            "t_nw_daily": _round(t_nw), "half1_daily_mean": _round(_mean(h1)),
            "half2_daily_mean": _round(_mean(h2)),
            "secondary": {"n": len(sec), "mean_r_net": _round(sec_mean)},
            "descriptive": {
                "mean_r_gross": _round(_mean([t["r_gross"] for t in ts])),
                "mean_cost_r": _round(_mean([t["cost_r"] for t in ts])),
                "mean_bars_held": _round(_mean([t["bars_held"] for t in ts])),
                "exit_reasons": {k: round(sum(1 for t in ts if t["exit_reason"] == k) / len(ts), 3)
                                 for k in sorted({t["exit_reason"] for t in ts})} if ts else {},
                "by_symbol": _group(ts, lambda t: t["symbol"]),
                "by_year": _group(ts, lambda t: iso(t["fill_utc"])[:4]),
                "by_session": _group(ts, lambda t: session_of(iso(t["fill_utc"]))),
                "by_direction": _group(ts, lambda t: t["direction"]),
            },
        }
    return out


def run() -> int:
    bad = verify_manifest()
    if bad:
        print("manifest NO coincide:", bad)
        return 1
    settings = fade.default_settings()
    slip = float(settings.backtest_sl_slippage_atr)
    primary, secondary, availability = [], [], {}
    for sym in SYMBOLS:
        category = "gold" if sym == "XAUUSD" else "forex"
        pb = load_bars(sym, "primary")
        in_w = [b for b in pb if _epoch(PRIMARY[0]) <= b["time"] < _epoch(PRIMARY[1] + timedelta(days=1))]
        years = (in_w[-1]["time"] - in_w[0]["time"]) / (365.25 * 86400) if in_w else 0.0
        availability[sym] = round(years, 2)
        if years < MIN_YEARS:
            print(f"{sym}: {years:.1f} años en la ventana < {MIN_YEARS} -> excluido")
            continue
        for t in with_costs(replay(pb, PRIMARY, slip), category, settings):
            primary.append({**t, "symbol": sym})
        sb = load_bars(sym, "secondary")
        for t in with_costs(replay(sb, SECONDARY, slip), category, settings):
            secondary.append({**t, "symbol": sym})
    used = [s for s, y in availability.items() if y >= MIN_YEARS]
    result = {"family": 27, "prereg": "research/HIPOTESIS_2026-10-07_fvg.md",
              "manifest_sha256": fade._sha256(MANIFEST_PATH),
              "availability_years": availability, "symbols_used": used}
    if len(used) < MIN_SYMBOLS:
        result["verdict"] = "NO TESTEABLE"
    else:
        result.update(evaluate(primary, secondary))
    RESULT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({h: {k: v for k, v in r.items() if k != "descriptive"}
                      for h, r in result.get("by_hyp", {}).items()}, indent=2, ensure_ascii=False))
    print("resultado:", RESULT_PATH)
    return 0


# ------------------------------------------------------------------ selftest
def _bars_from(ohlc: list[tuple[float, float, float, float]], t0: int = 1_300_000_000) -> list[dict]:
    return [{"time": t0 + 3600 * i, "open": o, "high": h, "low": l, "close": c}
            for i, (o, h, l, c) in enumerate(ohlc)]


def selftest() -> int:
    import math

    checks = 0

    def ok(cond: bool, msg: str) -> None:
        nonlocal checks
        if not cond:
            raise AssertionError(msg)
        checks += 1

    flat = [(1.0, 1.001, 0.999, 1.0)] * 20          # TR = 0.002 → ATR 0.002
    b = _bars_from(flat)
    ok(abs(atr(b, 15) - 0.002) < 1e-12, "ATR media simple del true range")
    ok(atr(b, 5) is None, "ATR sin historia suficiente = None")

    # FVG alcista: vela 18 high 1.001 < vela 20 low 1.004 (gap 0.003 ≥ 0.5×ATR)
    seq = flat[:18] + [(1.0, 1.001, 0.999, 1.0005), (1.001, 1.0045, 1.0008, 1.0042),
                       (1.0042, 1.0060, 1.0040, 1.0055)]
    b = _bars_from(seq)
    g = detect_gap(b, 20)
    ok(g is not None and g.side == "bull" and abs(g.lo - 1.001) < 1e-12 and abs(g.hi - 1.004) < 1e-12,
       "detecta FVG alcista con sus bordes")
    ok(detect_gap(b, 19) is None, "no hay FVG en la vela 19")
    small = flat[:18] + [(1.0, 1.001, 0.999, 1.0), (1.0, 1.0015, 1.0, 1.0015),
                         (1.0015, 1.0025, 1.00105, 1.002)]
    ok(detect_gap(_bars_from(small), 20) is None, "filtro de tamaño (gap < 0.5 ATR)")
    bear = flat[:18] + [(1.0, 1.001, 0.999, 0.9995), (0.999, 0.9992, 0.9955, 0.9958),
                        (0.9958, 0.996, 0.994, 0.9945)]
    gb = detect_gap(_bars_from(bear), 20)
    ok(gb is not None and gb.side == "bear" and abs(gb.lo - 0.996) < 1e-12 and abs(gb.hi - 0.999) < 1e-12,
       "detecta FVG bajista")
    # no mira el futuro: cambiar velas > 20 no cambia el gap detectado en 20
    later = _bars_from(seq + [(9.0, 9.0, 0.0, 5.0)] * 5)
    ok(detect_gap(later, 20) == g, "detección sin mirar el futuro")

    # orden de continuación: límite 1.004, stop 1.001 − 0.1×ATR, TP 2R
    o = order_fvg(g)
    a = g.atr
    ok(o.direction == "long" and abs(o.limit - 1.004) < 1e-12
       and abs(o.stop - (1.001 - 0.1 * a)) < 1e-12, "orden FVG alcista")
    risk = o.limit - o.stop
    ok(abs(o.tp - (o.limit + 2 * risk)) < 1e-12, "TP 2R")

    def series_after(rows):
        return _bars_from(seq + rows)

    # 1) llena en 21 y en esa misma vela toca TP: el TP NO cuenta en la vela del llenado;
    #    llega al TP en 22 -> +2R
    tp = o.tp
    bb = series_after([(1.0050, tp + 0.001, 1.0039, 1.0045), (1.0045, tp + 0.0005, 1.0041, tp)])
    res = run_order(bb, o, 0.0)
    ok(res and res["exit_reason"] == "tp" and res["exit_idx"] == 22 and abs(res["r_gross"] - 2.0) < 1e-9,
       "TP no cuenta en la vela del llenado; luego +2R")
    # 2) la vela del llenado toca el stop -> −1R − slippage
    bb = series_after([(1.0050, 1.0052, o.stop - 0.0001, 1.0000)])
    res = run_order(bb, o, 0.0001)
    ok(res and res["exit_reason"] == "sl" and abs(res["r_gross"] - (-1 - 0.0001 / risk)) < 1e-9,
       "stop en la vela del llenado")
    # 3) abre por debajo del stop -> gap_sl al open (peor que −1R)
    bb = series_after([(o.stop - 0.001, 1.0001, o.stop - 0.0015, o.stop - 0.0005)])
    res = run_order(bb, o, 0.0)
    ok(res and res["exit_reason"] == "gap_sl" and res["r_gross"] < -1, "gap más allá del stop")
    # 4) empate intrabar después del llenado: gana el stop
    bb = series_after([(1.0050, 1.0052, 1.0039, 1.0041), (1.0041, tp + 0.001, o.stop - 0.001, 1.0041)])
    res = run_order(bb, o, 0.0)
    ok(res and res["exit_reason"] == "sl", "empate SL/TP: gana el SL")
    # 5) abre por encima del TP: sale AL TP (el extra no se acredita)
    bb = series_after([(1.0050, 1.0052, 1.0039, 1.0041), (tp + 0.01, tp + 0.02, tp + 0.005, tp + 0.01)])
    res = run_order(bb, o, 0.0)
    ok(res and res["exit_reason"] == "tp" and abs(res["r_gross"] - 2.0) < 1e-9, "gap a favor: solo 2R")
    # 6) salida por tiempo al open de la vela 48 después del llenado
    hold = [(1.0050, 1.0052, 1.0039, 1.0045)] + [(1.0045, 1.0050, 1.0042, 1.0046)] * 60
    res = run_order(series_after(hold), o, 0.0)
    ok(res and res["exit_reason"] == "time" and res["bars_held"] == 48
       and res["exit_idx"] == res["fill_idx"] + 48, "time exit a las 48 velas")
    # 7) sin retesteo en 24 velas -> no hay trade
    away = [(1.0060, 1.0070, 1.0055, 1.0065)] * 30
    ok(run_order(series_after(away), o, 0.0) is None, "sin llenado no hay trade")
    # 8) retesteo en la vela 25 (fuera de la ventana de 24) -> no hay trade
    late = [(1.0060, 1.0070, 1.0055, 1.0065)] * 24 + [(1.0050, 1.0052, 1.0039, 1.0045)] * 5
    ok(run_order(series_after(late), o, 0.0) is None, "límite vencido a las 24 velas")

    # espejo short (FVG bajista): límite en el borde inferior 0.996, stop arriba
    ob = order_fvg(gb)
    ok(ob.direction == "short" and abs(ob.limit - 0.996) < 1e-12 and ob.stop > 0.999, "orden FVG bajista")
    bbs = _bars_from(bear + [(0.9950, 0.9962, 0.9948, 0.9955), (0.9955, 0.9958, ob.tp - 0.001, ob.tp)])
    res = run_order(bbs, ob, 0.0)
    ok(res and res["exit_reason"] == "tp" and abs(res["r_gross"] - 2.0) < 1e-9, "short llega a 2R")

    # replay: FVG alcista + retesteo + TP -> 1 trade fvg; un 2º FVG mientras está ocupado se ignora
    rows = seq + [(1.0050, 1.0052, 1.0039, 1.0045), (1.0045, tp + 0.0005, 1.0041, tp)]
    rb = _bars_from(rows)
    win = (datetime.fromtimestamp(rb[0]["time"], tz=timezone.utc).date(),
           datetime.fromtimestamp(rb[-1]["time"], tz=timezone.utc).date())
    tr = [t for t in replay(rb, win, 0.0) if t["hyp"] == "fvg"]
    ok(len(tr) == 1 and abs(tr[0]["r_gross"] - 2.0) < 1e-9, "replay: un trade de continuación +2R")
    # fuera de la ventana no hay trades
    far = (date(2030, 1, 1), date(2030, 2, 1))
    ok(replay(rb, far, 0.0) == [], "eventos fuera de la ventana no cuentan")

    # inversión: el FVG alcista (1.001-1.004) se rompe con un cierre < 1.001 -> venta
    # límite en 1.001; retestea desde abajo y cae al TP
    inv = seq + [(1.0050, 1.0052, 1.0030, 1.0035),          # 21: llena la continuación...
                 (1.0035, 1.0036, 1.0000, 1.0005),          # 22: cierre < 1.001 -> inversión
                 (1.0005, 1.0012, 1.0003, 1.0008)]          # 23: retestea 1.001 -> llena short
    ib = _bars_from(inv)
    a22 = atr(ib, 22)
    oi = order_ifvg(g, 22, a22)
    ok(oi.direction == "short" and abs(oi.limit - 1.001) < 1e-12
       and abs(oi.stop - (1.004 + 0.1 * a22)) < 1e-12 and oi.valid_from == 23, "orden iFVG")
    ib = _bars_from(inv + [(1.0008, 1.0009, oi.tp - 0.0005, oi.tp)])
    tri = [t for t in replay(ib, (date(2011, 1, 1), date(2012, 1, 1)), 0.0) if t["hyp"] == "ifvg"]
    ok(len(tri) == 1 and tri[0]["direction"] == "short" and abs(tri[0]["r_gross"] - 2.0) < 1e-9,
       "replay: inversión -> short +2R")
    # inversión tardía (> 48 velas) no cuenta
    slow = seq + [(1.0050, 1.0060, 1.0045, 1.0055)] * 50 + [(1.0050, 1.0052, 1.0000, 1.0005),
                                                         (1.0005, 1.0012, 1.0003, 1.0008)]
    sb = _bars_from(slow)
    ok(not [t for t in replay(sb, (date(2011, 1, 1), date(2012, 1, 1)), 0.0) if t["hyp"] == "ifvg"],
       "la inversión vale solo dentro de 48 velas")

    # costos: net_r del harness (forex 0.02 % × 1.25 / riesgo %)
    settings = fade.default_settings()
    t = {"r_gross": 2.0, "entry": 1.004, "stop": 1.001, "bars_held": 2, "direction": "long"}
    c = with_costs([t], "forex", settings)[0]
    expected = 0.02 * 1.25 / ((1.004 - 1.001) / 1.004 * 100)
    ok(abs(c["cost_r"] - round(expected, 6)) < 1e-6 and c["r_net"] < 2.0 < c["r_net"] + 1, "costo forex")
    cg = with_costs([t], "gold", settings)[0]
    ok(cg["cost_r"] > c["cost_r"] and cg["r_net_stress"] < cg["r_net"], "oro más caro; stress peor")

    # NW igual a la cuenta a mano (reusa la de H-FADE1)
    x = [1.0, -0.5, 2.0, 0.3, -1.2, 0.8, 1.5, -0.2]
    n, m = len(x), sum(x) / len(x)
    d = [v - m for v in x]
    gk = lambda k: sum(d[i] * d[i - k] for i in range(k, n)) / n
    lrv = gk(0) + 2 * sum((1 - k / 6) * gk(k) for k in range(1, 6))
    ok(abs(fade.newey_west_t(x, 5) - m / math.sqrt(lrv / n)) < 1e-12, "t de Newey-West")

    # evaluate: criterios con trades sintéticos (+0.5R netos todos los días hábiles)
    days = fade.weekdays(*PRIMARY)
    fake = [{"hyp": h, "fill_utc": _epoch(dd) + 3600 * (9 + (i % 7)), "r_net": 0.5 + 0.1 * ((i % 5) - 2),
             "r_net_stress": 0.3, "r_gross": 0.8, "cost_r": 0.3, "bars_held": 5,
             "exit_reason": "tp", "symbol": "EURUSD", "direction": "long"}
            for h in HYPS for i, dd in enumerate(days[::3])]
    sec = [next(f for f in fake if f["hyp"] == h) for h in HYPS]
    ev = evaluate(fake, sec)
    ok(all(ev["by_hyp"][h]["verdict"] == "PASA" for h in HYPS), "evaluate: un edge plantado PASA")
    ev2 = evaluate([{**f, "r_net": -f["r_net"]} for f in fake], [])
    ok(all(ev2["by_hyp"][h]["verdict"] == "NO PASA" for h in HYPS), "evaluate: el reverso NO PASA")
    ok(ev2["by_hyp"]["fvg"]["criteria"]["6_secondary_pos"] is False, "secundaria vacía no pasa")

    print(f"selftest OK: {checks}/{checks} chequeos")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--selftest", action="store_true")
    g.add_argument("--download", action="store_true")
    g.add_argument("--run", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.download:
        return download()
    return run()


if __name__ == "__main__":
    sys.exit(main())
