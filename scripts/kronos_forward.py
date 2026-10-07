"""H-KRON1 — Kronos (modelo base de velas) hacia adelante en forex/oro H1 (familia 28).

Pre-registro: research/HIPOTESIS_2026-10-07_kronos.md (commiteado ANTES del primer
pronóstico). Proceso APARTE del bot, con su propio entorno (.venv_kronos, PyTorch CPU):
no toca el bot, ni flags, ni el .env, ni manda órdenes. A MT5 solo le LEE velas y la
cotización (`initialize()` sin credenciales).

Cada día hábil a las 00:00 y 12:00 UTC (+2 min):
  1. lee las últimas velas H1 COMPLETAS de los 8 símbolos y la cotización (bid/ask);
  2. Kronos-small pronostica las próximas 12 velas; r̂ = cierre pronosticado a 12 h /
     último cierre − 1;
  3. decide long / short si |r̂| ≥ costo de definición, si no "abstain" (no hay decisión
     en la ronda del viernes 12:00: cruzaría el fin de semana);
  4. anota todo en trading_data/kronos_forward/rounds.csv (append).
El resultado de cada decisión sale de la cotización de la ronda siguiente (12 h después):
entra al ask/bid, sale al bid/ask → el spread real está incluido.

  .venv_kronos\\Scripts\\python.exe scripts\\kronos_forward.py --loop      (lo usa start_kronos.ps1)
  .venv_kronos\\Scripts\\python.exe scripts\\kronos_forward.py --once      (una ronda ya)
  python scripts\\kronos_forward.py --status     (solo cuenta filas; no muestra resultados)
  python scripts\\kronos_forward.py --evaluate   (se niega antes del 2027-01-15)
  python scripts\\kronos_forward.py --selftest   (sintético: sin red, sin MT5, sin torch)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------- fijado (pre-registro)
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD"]
KRONOS_REPO = "https://github.com/shiyu-coder/Kronos"
KRONOS_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
MODEL_ID = "NeoQuasar/Kronos-small"
MODEL_REVISION = "901c26c1332695a2a8f243eb2f37243a37bea320"
TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"
LOOKBACK = 400                 # velas H1 de contexto (< 512 de Kronos-small)
PRED_LEN = 12                  # horizonte: 12 velas H1
TEMPERATURE = 1.0
TOP_P = 0.9
SAMPLE_COUNT = 5
TORCH_THREADS = 2              # deja CPU para el bot
ROUND_HOURS_UTC = (0, 12)
ROUND_DELAY_MIN = 2
FRESH_MAX_HOURS = 2.0          # la última vela completa tiene que haber cerrado hace ≤ 2 h
COST_PCT = {"forex": 0.02 * 1.25, "gold": 0.03 * 1.25}   # costo de definición (harness, central)
STRESS_EXTRA_PCT = {"forex": 0.02 * 1.25, "gold": 0.03 * 1.25}  # stress: spread real + otro costo
EXIT_GAP_HOURS = (11.0, 13.0)  # la ronda de salida tiene que estar a 12 h ± 1 h
EVAL_FROM = date(2027, 1, 15)
EVAL_DEADLINE = date(2027, 3, 31)
EVAL_MIN_N = 300
HALF_SPLIT_FRACTION = 0.5
NW_LAGS = 5
T_MIN = 2.50
CRIT_MEAN_MIN_PCT = 0.0

FIELDS = ["round_utc", "symbol", "category", "decision_allowed", "last_bar_utc", "last_close",
          "pred_close", "pred_ret_pct", "cost_pct", "decision", "bid", "ask", "tick_utc",
          "status", "elapsed_s", "model", "model_rev", "tokenizer_rev", "kronos_commit",
          "lookback", "pred_len", "T", "top_p", "sample_count"]

log = logging.getLogger("kronos_forward")


# ----------------------------------------------------------------------- hora
def _last_sunday(year: int, month: int) -> date:
    d = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def server_to_utc(server_epoch: int) -> int:
    """Época de MT5 (hora del servidor EET/EEST, regla UE) → época UTC real."""
    as_summer = server_epoch - 3 * 3600
    t = datetime.fromtimestamp(as_summer, tz=timezone.utc)
    start = datetime.combine(_last_sunday(t.year, 3), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    end = datetime.combine(_last_sunday(t.year, 10), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    return as_summer if start <= t < end else server_epoch - 2 * 3600


def category_of(symbol: str) -> str:
    return "gold" if symbol == "XAUUSD" else "forex"


# ------------------------------------------------------------------- rondas
def next_round(now: datetime) -> datetime:
    """Próxima ronda (00:00 / 12:00 UTC + 2 min) estrictamente después de `now`, en día
    hábil (lunes 00:00 … viernes 12:00)."""
    now = now.astimezone(timezone.utc)
    day = now.date()
    for _ in range(10):
        for h in ROUND_HOURS_UTC:
            t = datetime(day.year, day.month, day.day, h, ROUND_DELAY_MIN, tzinfo=timezone.utc)
            if t > now and t.weekday() < 5:
                return t
        day += timedelta(days=1)
    raise AssertionError("inalcanzable")


def decision_allowed(round_t: datetime) -> bool:
    """Se decide en todas las rondas hábiles menos el viernes 12:00 (cruzaría el finde)."""
    return not (round_t.weekday() == 4 and round_t.hour >= 12)


def completed_bars(bars: list[dict], now: datetime) -> list[dict]:
    """Solo velas H1 YA cerradas (inicio + 1 h ≤ ahora)."""
    cut = now.timestamp() - 3600
    return [b for b in bars if b["time"] <= cut]


def decide(pred_ret_pct: float | None, cost_pct: float) -> str:
    if pred_ret_pct is None or not math.isfinite(pred_ret_pct):
        return "abstain"
    if abs(pred_ret_pct) < cost_pct:
        return "abstain"
    return "long" if pred_ret_pct > 0 else "short"


# ----------------------------------------------------------------------- MT5
def _mt5():
    import MetaTrader5 as mt5  # type: ignore[import-not-found]

    if not mt5.initialize():                   # SIN credenciales: se engancha a la terminal
        raise RuntimeError(f"MT5 no inicializó: {mt5.last_error()}")
    return mt5


SYNC_SETTLE_S = 3.0      # MT5 devuelve velas viejas de un símbolo recién seleccionado
SYNC_RETRIES = 4         # y las actualiza en segundo plano: se espera y se reintenta


def _is_fresh(bars: list[dict], now_s: float) -> bool:
    return bool(bars) and (now_s - (bars[-1]["time"] + 3600)) / 3600.0 <= FRESH_MAX_HOURS


def read_bars(symbols: list[str], count: int) -> dict[str, list[dict]]:
    """{símbolo: velas H1 con hora UTC} leyendo MT5 en solo lectura.

    Medido el 2026-10-07: la primera lectura de un símbolo que no estaba sincronizado
    devuelve la historia vieja (6 de 8 parecían "mercado cerrado" un miércoles) y
    dispara la descarga. Por eso: un pedido inicial a todos, una pausa y, si la última
    vela sigue vieja, hasta SYNC_RETRIES reintentos de 2 s (en finde no hay rondas)."""
    mt5 = _mt5()

    def fetch(s: str) -> list[dict]:
        rates = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, count)
        bars = [] if rates is None else [
            {"time": server_to_utc(int(r["time"])), "open": float(r["open"]),
             "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"]),
             "volume": float(r["tick_volume"])} for r in rates]
        return sorted(bars, key=lambda b: b["time"])

    out = {}
    try:
        for s in symbols:                      # dispara la sincronización de todos
            mt5.symbol_select(s, True)
            mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 1)
        time.sleep(SYNC_SETTLE_S)
        for s in symbols:
            bars = fetch(s)
            for _ in range(SYNC_RETRIES):
                if _is_fresh(bars, time.time()):
                    break
                time.sleep(2.0)
                bars = fetch(s)
            out[s] = bars
    finally:
        mt5.shutdown()                         # cierra SOLO la conexión de este proceso
    return out


def read_ticks(symbols: list[str]) -> dict[str, dict | None]:
    """{símbolo: {bid, ask, time UTC}} (solo lectura)."""
    mt5 = _mt5()
    out = {}
    try:
        for s in symbols:
            mt5.symbol_select(s, True)
            t = mt5.symbol_info_tick(s)
            out[s] = None if t is None else {"bid": float(t.bid), "ask": float(t.ask),
                                             "time": server_to_utc(int(t.time))}
    finally:
        mt5.shutdown()
    return out


# -------------------------------------------------------------------- Kronos
class KronosForecaster:
    def __init__(self, root: Path) -> None:
        os.environ.setdefault("HF_HOME", str(root / "vendor" / "hf_cache"))
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        sys.path.insert(0, str(root / "vendor" / "Kronos"))
        import torch
        from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore

        torch.set_num_threads(TORCH_THREADS)
        torch.manual_seed(20261007)
        tok = KronosTokenizer.from_pretrained(TOKENIZER_ID, revision=TOKENIZER_REVISION)
        mod = Kronos.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
        self.predictor = KronosPredictor(mod, tok, device="cpu", max_context=512)

    def forecast(self, bars: list[dict]) -> float:
        """Cierre pronosticado a PRED_LEN velas (media de SAMPLE_COUNT trayectorias)."""
        import pandas as pd

        ctx = bars[-LOOKBACK:]
        df = pd.DataFrame([{k: b[k] for k in ("open", "high", "low", "close", "volume")}
                           for b in ctx])
        xt = pd.Series(pd.to_datetime([b["time"] for b in ctx], unit="s"))
        last = xt.iloc[-1]
        yt = pd.Series(pd.date_range(last + pd.Timedelta(hours=1), periods=PRED_LEN, freq="h"))
        out = self.predictor.predict(df=df, x_timestamp=xt, y_timestamp=yt, pred_len=PRED_LEN,
                                     T=TEMPERATURE, top_p=TOP_P, sample_count=SAMPLE_COUNT,
                                     verbose=False)
        return float(out["close"].iloc[-1])


# ------------------------------------------------------------------- ronda
def run_round(round_t: datetime, data: dict, forecaster, now: datetime | None = None) -> list[dict]:
    """Arma las filas de una ronda (sin cotización: va después, con `attach_quotes`).
    `data` = {símbolo: velas}; `forecaster.forecast(velas)` → cierre a 12 h."""
    now = now or datetime.now(timezone.utc)
    allowed = decision_allowed(round_t)
    rows = []
    for s in SYMBOLS:
        cat = category_of(s)
        cost = COST_PCT[cat]
        done = completed_bars(data.get(s) or [], now)
        row = {"round_utc": round_t.isoformat(), "symbol": s, "category": cat,
               "decision_allowed": int(allowed), "cost_pct": cost, "decision": "none",
               "status": "ok", "model": MODEL_ID, "model_rev": MODEL_REVISION,
               "tokenizer_rev": TOKENIZER_REVISION, "kronos_commit": KRONOS_COMMIT,
               "lookback": LOOKBACK, "pred_len": PRED_LEN, "T": TEMPERATURE, "top_p": TOP_P,
               "sample_count": SAMPLE_COUNT}
        if not done:
            row["status"] = "sin_velas"
            rows.append(row)
            continue
        last = done[-1]
        last_end = last["time"] + 3600
        row["last_bar_utc"] = datetime.fromtimestamp(last["time"], tz=timezone.utc).isoformat()
        row["last_close"] = last["close"]
        if (now.timestamp() - last_end) / 3600.0 > FRESH_MAX_HOURS:
            row["status"] = "mercado_cerrado"
            rows.append(row)
            continue
        if allowed:
            if len(done) < LOOKBACK:
                row["status"] = "poco_contexto"
            else:
                t0 = time.time()
                try:
                    pc = forecaster.forecast(done)
                    pr = (pc / last["close"] - 1.0) * 100.0
                    row.update({"pred_close": pc, "pred_ret_pct": pr, "decision": decide(pr, cost),
                                "elapsed_s": round(time.time() - t0, 1)})
                except Exception as exc:  # soft-fail por símbolo
                    row["status"] = f"error: {type(exc).__name__}"
        rows.append(row)
    return rows


def attach_quotes(rows: list[dict], ticks: dict) -> list[dict]:
    """Cotización del FINAL de la ronda (después de pronosticar todo). Sin cotización
    válida, la fila queda 'sin_cotizacion' y su decisión no podrá cerrarse."""
    for row in rows:
        t = ticks.get(row["symbol"])
        if not t or t["bid"] <= 0 or t["ask"] <= 0:
            if row["status"] == "ok":
                row["status"] = "sin_cotizacion"
            continue
        row.update({"bid": t["bid"], "ask": t["ask"],
                    "tick_utc": datetime.fromtimestamp(t["time"], tz=timezone.utc).isoformat()})
    return rows


def append_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------- evaluación
def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def pair_trades(rows: list[dict]) -> tuple[list[dict], int]:
    """Une cada decisión con la cotización del MISMO símbolo en la ronda siguiente
    (12 h ± 1 h). Long: entra al ask, sale al bid; short: entra al bid, sale al ask.
    Devuelve (trades, decisiones sin salida)."""
    by_sym: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(r)
    trades, missing = [], 0
    for sym, rs in by_sym.items():
        rs.sort(key=lambda r: r["round_utc"])
        for i, r in enumerate(rs):
            if r.get("decision") not in ("long", "short"):
                continue
            t0 = datetime.fromisoformat(r["round_utc"])
            exit_row = None
            for nx in rs[i + 1:]:
                dt = (datetime.fromisoformat(nx["round_utc"]) - t0).total_seconds() / 3600
                if dt > EXIT_GAP_HOURS[1]:
                    break
                if dt >= EXIT_GAP_HOURS[0] and _f(nx.get("bid")) and _f(nx.get("ask")):
                    exit_row = nx
                    break
            bid0, ask0 = _f(r.get("bid")), _f(r.get("ask"))
            if exit_row is None or not bid0 or not ask0:
                missing += 1
                continue
            bid1, ask1 = float(exit_row["bid"]), float(exit_row["ask"])
            if r["decision"] == "long":
                ret = (bid1 / ask0 - 1.0) * 100.0
            else:
                ret = (bid0 / ask1 - 1.0) * 100.0
            cat = r.get("category") or category_of(sym)
            trades.append({"symbol": sym, "round_utc": r["round_utc"], "decision": r["decision"],
                           "pred_ret_pct": _f(r.get("pred_ret_pct")), "net_pct": ret,
                           "stress_pct": ret - STRESS_EXTRA_PCT[cat],
                           "realized_mid_pct": ((bid1 + ask1) / (bid0 + ask0) - 1.0) * 100.0})
    trades.sort(key=lambda t: t["round_utc"])
    return trades, missing


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


def _spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = float(pos)
        return r

    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else None


def evaluate(rows: list[dict], today: date, force_dates: bool = False) -> dict:
    trades, missing = pair_trades(rows)
    if not force_dates:
        if today < EVAL_FROM:
            return {"status": "TODAVIA_NO", "detail": f"la evaluación es desde {EVAL_FROM}"}
        if len(trades) < EVAL_MIN_N and today < EVAL_DEADLINE:
            return {"status": "TODAVIA_NO", "detail": f"{len(trades)} < {EVAL_MIN_N} trades"}
    daily: dict[str, float] = defaultdict(float)
    for t in trades:
        daily[t["round_utc"][:10]] += t["net_pct"]
    days = sorted(daily)
    series = [daily[d] for d in days]
    half = int(len(series) * HALF_SPLIT_FRACTION)
    net = [t["net_pct"] for t in trades]
    stress = [t["stress_pct"] for t in trades]
    mean = sum(net) / len(net) if net else None
    t_nw = newey_west_t(series)
    crit = {
        "1_n_ge_300": len(trades) >= EVAL_MIN_N,
        "2_mean_net_gt_0": mean is not None and mean > CRIT_MEAN_MIN_PCT,
        "3_t_nw_ge_2.50": t_nw is not None and t_nw >= T_MIN,
        "4_both_halves_pos": bool(half) and sum(series[:half]) > 0 and sum(series[half:]) > 0,
        "5_stress_pos": bool(stress) and sum(stress) / len(stress) > 0,
    }
    pr = [t["pred_ret_pct"] for t in trades if t["pred_ret_pct"] is not None]
    rm = [t["realized_mid_pct"] for t in trades if t["pred_ret_pct"] is not None]
    by_sym: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by_sym[t["symbol"]].append(t["net_pct"])
    return {
        "status": "PASA" if all(crit.values()) else "NO PASA",
        "n_trades": len(trades), "missing_exit": missing, "days": len(series),
        "mean_net_pct": mean, "mean_stress_pct": sum(stress) / len(stress) if stress else None,
        "t_nw_daily": t_nw, "criteria": crit, "low_power": len(trades) < EVAL_MIN_N,
        "descriptive": {
            "hit_rate": (sum(1 for x in net if x > 0) / len(net)) if net else None,
            "ic_spearman_pred_vs_realized": _spearman(pr, rm),
            "by_symbol": {k: {"n": len(v), "mean_net_pct": sum(v) / len(v)} for k, v in sorted(by_sym.items())},
            "decisions": {k: sum(1 for r in rows if r.get("decision") == k) for k in ("long", "short", "abstain")},
        },
    }


def status(rows: list[dict]) -> dict:
    """Salud de la colecta SIN resultados (no se mira la ventana antes de la fecha)."""
    rounds = sorted({r["round_utc"] for r in rows})
    st: dict[str, int] = defaultdict(int)
    for r in rows:
        st[r.get("status") or "?"] += 1
    return {"rounds": len(rounds), "first": rounds[0] if rounds else None,
            "last": rounds[-1] if rounds else None, "rows": len(rows),
            "decisions": sum(1 for r in rows if r.get("decision") in ("long", "short")),
            "abstain": sum(1 for r in rows if r.get("decision") == "abstain"),
            "status": dict(st)}


# ------------------------------------------------------------------- loop
def data_paths(root: Path) -> tuple[Path, Path]:
    d = root / "trading_data" / "kronos_forward"
    return d / "rounds.csv", d / "kronos.log"


def do_round(root: Path, forecaster, round_t: datetime, out_path: Path | None = None) -> int:
    rounds_path = out_path or data_paths(root)[0]
    done_rounds = {r["round_utc"] for r in load_rows(rounds_path)}
    if round_t.isoformat() in done_rounds:
        log.info("ronda %s ya registrada", round_t.isoformat())
        return 0
    rows = run_round(round_t, read_bars(SYMBOLS, LOOKBACK + 50), forecaster)
    attach_quotes(rows, read_ticks(SYMBOLS))     # cotización al FINAL de la ronda
    append_rows(rounds_path, rows)
    n_dec = sum(1 for r in rows if r.get("decision") in ("long", "short"))
    log.info("ronda %s: %d filas, %d decisiones, estados %s", round_t.isoformat(), len(rows),
             n_dec, sorted({r['status'] for r in rows}))
    return len(rows)


def late_round(now: datetime, max_late_min: int = 30) -> datetime | None:
    """La ronda programada más reciente si pasó hace ≤ `max_late_min` minutos."""
    t = next_round(now - timedelta(minutes=max_late_min, seconds=1))
    return t if t <= now else None


def loop(root: Path) -> int:
    forecaster = KronosForecaster(root)
    log.info("Kronos cargado (%s @ %s). Rondas 00:00/12:00 UTC (+2 min), días hábiles.",
             MODEL_ID, MODEL_REVISION[:8])
    late = late_round(datetime.now(timezone.utc))
    if late is not None:                       # arrancó hasta 30 min tarde: se hace igual
        try:
            do_round(root, forecaster, late)
        except Exception:
            log.exception("la ronda %s falló (soft-fail)", late.isoformat())
    while True:
        target = next_round(datetime.now(timezone.utc))
        log.info("próxima ronda: %s", target.isoformat())
        while (wait := (target - datetime.now(timezone.utc)).total_seconds()) > 0:
            time.sleep(min(wait, 60))
        try:
            do_round(root, forecaster, target)
        except Exception:
            log.exception("la ronda %s falló (soft-fail); sigue la próxima", target.isoformat())


# --------------------------------------------------------------- selftest
def selftest() -> int:
    checks = 0

    def ok(cond, msg):
        nonlocal checks
        if not cond:
            raise AssertionError(msg)
        checks += 1

    utc = lambda *a: datetime(*a, tzinfo=timezone.utc)
    ok(next_round(utc(2026, 10, 7, 9)) == utc(2026, 10, 7, 12, 2), "próxima ronda del día")
    ok(next_round(utc(2026, 10, 7, 12, 2)) == utc(2026, 10, 8, 0, 2), "estrictamente después")
    ok(next_round(utc(2026, 10, 9, 13)) == utc(2026, 10, 12, 0, 2), "viernes tarde → lunes 00:02")
    ok(next_round(utc(2026, 10, 10, 5)) == utc(2026, 10, 12, 0, 2), "sábado → lunes")
    ok(decision_allowed(utc(2026, 10, 9, 0, 2)) and not decision_allowed(utc(2026, 10, 9, 12, 2)),
       "viernes 12:00 sin decisión")
    ok(server_to_utc(int(utc(2026, 10, 6, 16, 39).timestamp())) == int(utc(2026, 10, 6, 13, 39).timestamp()),
       "hora del servidor en verano (UTC+3)")
    ok(server_to_utc(int(utc(2026, 12, 1, 12).timestamp())) == int(utc(2026, 12, 1, 10).timestamp()),
       "hora del servidor en invierno (UTC+2)")
    ok(decide(0.10, 0.025) == "long" and decide(-0.10, 0.025) == "short"
       and decide(0.01, 0.025) == "abstain" and decide(None, 0.025) == "abstain", "regla de decisión")

    # velas completas: a las 12:02 la vela de 11:00 está cerrada y la de 12:00 no
    now = utc(2026, 10, 7, 12, 2)
    bars = [{"time": int((now - timedelta(hours=h)).replace(minute=0).timestamp()), "open": 1.0,
             "high": 1.001, "low": 0.999, "close": 1.0 + 0.0001 * (500 - h), "volume": 10.0}
            for h in range(500, -1, -1)]
    done = completed_bars(bars, now)
    ok(datetime.fromtimestamp(done[-1]["time"], tz=timezone.utc) == utc(2026, 10, 7, 11), "solo velas cerradas")

    class Fake:
        def __init__(self):
            self.seen = []

        def forecast(self, b):
            self.seen.append(b[-1]["time"])
            return b[-1]["close"] * 1.001          # +0.10 % → long

    fk = Fake()
    tick = {"bid": 1.0, "ask": 1.0001, "time": int(now.timestamp())}
    data = {s: bars for s in SYMBOLS}
    ticks = {s: tick for s in SYMBOLS}
    rows = attach_quotes(run_round(utc(2026, 10, 7, 12, 2), data, fk, now=now), ticks)
    ok(len(rows) == 8 and all(r["decision"] == "long" and r["bid"] == 1.0 for r in rows),
       "ronda con decisiones y cotización")
    ok(all(t == done[-1]["time"] for t in fk.seen), "el modelo no ve la vela abierta")
    rows_fri = attach_quotes(run_round(utc(2026, 10, 9, 12, 2), data, fk, now=now), ticks)
    ok(all(r["decision"] == "none" and r["bid"] == 1.0 for r in rows_fri), "viernes 12: solo cotiza")
    no_q = attach_quotes(run_round(utc(2026, 10, 7, 12, 2), data, fk, now=now), {"EURUSD": None})
    ok(no_q[0]["status"] == "sin_cotizacion" and "bid" not in no_q[0], "sin cotización se marca")
    ok(late_round(utc(2026, 10, 7, 12, 20)) == utc(2026, 10, 7, 12, 2)
       and late_round(utc(2026, 10, 7, 12, 40)) is None
       and late_round(utc(2026, 10, 10, 0, 10)) is None, "ronda tardía ≤ 30 min (no en finde)")
    stale_now = now + timedelta(hours=5)
    rows_st = run_round(utc(2026, 10, 7, 12, 2), data, fk, now=stale_now)
    ok(all(r["status"] == "mercado_cerrado" for r in rows_st), "vela vieja = mercado cerrado")

    # emparejado y P&L con bid/ask: long entra al ask y sale al bid
    def r(round_t, sym, dec, bid, ask, pred=0.1):
        return {"round_utc": round_t.isoformat(), "symbol": sym, "category": category_of(sym),
                "decision": dec, "bid": bid, "ask": ask, "pred_ret_pct": pred}
    t0 = utc(2026, 10, 7, 0, 2)
    rs = [r(t0, "EURUSD", "long", 1.1000, 1.1001), r(t0 + timedelta(hours=12), "EURUSD", "none", 1.1050, 1.1051),
          r(t0, "USDJPY", "short", 150.00, 150.02, -0.2), r(t0 + timedelta(hours=12), "USDJPY", "abstain", 149.00, 149.02),
          r(t0, "XAUUSD", "long", 4000.0, 4000.3)]                       # sin salida
    tr, miss = pair_trades(rs)
    eu = next(t for t in tr if t["symbol"] == "EURUSD")
    ok(abs(eu["net_pct"] - (1.1050 / 1.1001 - 1) * 100) < 1e-9, "long: ask → bid")
    jp = next(t for t in tr if t["symbol"] == "USDJPY")
    ok(abs(jp["net_pct"] - (150.00 / 149.02 - 1) * 100) < 1e-9, "short: bid → ask")
    ok(miss == 1 and len(tr) == 2, "decisión sin salida no cuenta y se reporta")
    late = [r(t0, "EURUSD", "long", 1.1, 1.1001), r(t0 + timedelta(hours=36), "EURUSD", "none", 1.2, 1.2001)]
    ok(pair_trades(late)[1] == 1, "salida a más de 13 h no vale")

    # evaluación: fechas y criterios
    ok(evaluate(rs, date(2026, 12, 1))["status"] == "TODAVIA_NO", "antes de la fecha se niega")
    base = utc(2026, 10, 12, 0, 2)
    good = []
    for i in range(400):
        rt = base + timedelta(hours=12 * i)
        good.append(r(rt, "EURUSD", "long", 1.0, 1.0001))
        good.append(r(rt + timedelta(hours=12), "EURUSD", "none", 1.0 + 0.002 * (1 + (i % 3)), 1.0002))
    ev = evaluate(good, date(2027, 2, 1), force_dates=True)
    ok(ev["status"] == "PASA" and ev["n_trades"] == 400, "edge plantado PASA")
    bad = [{**x, "bid": 2.0 - float(x["bid"])} if x["decision"] == "none" else x for x in good]
    ok(evaluate(bad, date(2027, 2, 1), force_dates=True)["status"] == "NO PASA", "pérdida plantada NO PASA")
    st = status(rows + rows_fri)
    ok(st["rounds"] == 2 and st["decisions"] == 8 and "mean_net_pct" not in st, "status sin resultados")

    # CSV ida y vuelta
    tmp = Path(os.environ.get("TEMP", ".")) / f"kronos_selftest_{os.getpid()}.csv"
    if tmp.exists():
        tmp.unlink()
    append_rows(tmp, rows)
    append_rows(tmp, rows_fri)
    back = load_rows(tmp)
    tmp.unlink()
    ok(len(back) == 16 and back[0]["decision"] == "long" and back[0]["model_rev"] == MODEL_REVISION,
       "CSV append con encabezado una sola vez")
    x = [1.0, -0.5, 2.0, 0.3, -1.2, 0.8, 1.5, -0.2]
    n, m = len(x), sum(x) / len(x)
    dd = [v - m for v in x]
    g = lambda k: sum(dd[i] * dd[i - k] for i in range(k, n)) / n
    lrv = g(0) + 2 * sum((1 - k / 6) * g(k) for k in range(1, 6))
    ok(abs(newey_west_t(x) - m / math.sqrt(lrv / n)) < 1e-12, "t de Newey-West")
    print(f"selftest OK: {checks}/{checks} chequeos")
    return 0


def download_models(root: Path) -> int:
    os.environ.setdefault("HF_HOME", str(root / "vendor" / "hf_cache"))
    from huggingface_hub import snapshot_download

    for rid, rev in ((MODEL_ID, MODEL_REVISION), (TOKENIZER_ID, TOKENIZER_REVISION)):
        p = snapshot_download(rid, revision=rev)
        print(f"{rid} @ {rev[:12]} -> {p}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    for flag in ("--loop", "--once", "--status", "--evaluate", "--selftest", "--download-models"):
        g.add_argument(flag, action="store_true")
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args()
    root = args.root
    if args.selftest:
        return selftest()
    if args.download_models:
        return download_models(root)
    rounds_path, log_path = data_paths(root)
    if args.status:
        print(json.dumps(status(load_rows(rounds_path)), indent=2, ensure_ascii=False))
        return 0
    if args.evaluate:
        res = evaluate(load_rows(rounds_path), datetime.now(timezone.utc).date())
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        if res.get("status") in ("PASA", "NO PASA"):
            out = ROOT / "research" / "H-KRON1_result.json"
            out.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            print("resultado:", out)
        return 0
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(log_path, encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    if args.once:                                # PRUEBA: no escribe en rounds.csv
        now = datetime.now(timezone.utc)
        rt = datetime(now.year, now.month, now.day, now.hour, now.minute, tzinfo=timezone.utc)
        out = rounds_path.parent / "once_test.csv"
        n = do_round(root, KronosForecaster(root), rt, out_path=out)
        for r in (r for r in load_rows(out) if r["round_utc"] == rt.isoformat()):
            print(r["symbol"], r["status"], r.get("decision"), r.get("elapsed_s"), "s")
        print("prueba guardada en", out, "(NO cuenta para la evaluación)")
        return 0 if n else 1
    return loop(root)


if __name__ == "__main__":
    sys.exit(main())
