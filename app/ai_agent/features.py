"""v3.13.0 — vector de contexto del agente IA (funciones puras, sin I/O).

Todas las features están acotadas y valen 0 cuando falta el dato (con prior en 0,
"no sé" no empuja la decisión hacia ningún lado). Las direccionales se firman con el
lado del trade: +1 significa "a favor del trade" (ej. RSI alto en un long).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.learning.trade_outcomes import session_of

FEATURE_NAMES: tuple[str, ...] = (
    "bias",
    "strat_session_breakout",
    "strat_mean_reversion",
    "strat_momentum",
    "short",
    "gold",
    "sess_asia",
    "sess_london",
    "sess_ldn_ny",
    "sess_ny",
    "regime_align",        # +1 a favor del régimen D1, -1 en contra, 0 flat/desconocido
    "vwap_week_signed",    # distancia al VWAP semanal a favor del trade, /3 y acotada
    "hurst_centered",      # (H - 0.5) * 2, acotado a [-1, 1]
    "rsi_signed",          # (RSI - 50)/50 firmado por dirección
    "atr_pct",             # ATR % / 3, acotado a [0, 1]
    "clv_signed",          # (CLV - 0.5) * 2 firmado por dirección
)
DIM = len(FEATURE_NAMES)

_STRATEGIES = {
    "forex_session_breakout": 1,
    "mean_reversion": 2,
    "momentum": 3,
}
_SESSIONS = {"Asia": 6, "London": 7, "LDN-NY": 8, "NY": 9}


def _num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def direction_sign(paper_trade: dict[str, Any]) -> float:
    return -1.0 if str(paper_trade.get("direction") or "long").lower() == "short" else 1.0


def build_features(
    paper_trade: dict[str, Any],
    regime: str | None = None,
    vwap_week_dist_pct: float | None = None,
) -> list[float]:
    """Vector de DIM floats. `regime` ('up'/'down'/'flat'/None) y la distancia al
    VWAP semanal vienen del cache D1 de MT5 (los calcula el job, soft-fail); si no
    hay, se usa el `vwap_week_dist_pct` persistido del trade o 0."""
    x = [0.0] * DIM
    x[0] = 1.0
    sign = direction_sign(paper_trade)

    idx = _STRATEGIES.get(str(paper_trade.get("strategy_name") or ""))
    if idx is not None:
        x[idx] = 1.0
    x[4] = 1.0 if sign < 0 else 0.0
    x[5] = 1.0 if str(paper_trade.get("category") or "").lower() == "gold" else 0.0
    s_idx = _SESSIONS.get(session_of(paper_trade.get("opened_at")))
    if s_idx is not None:
        x[s_idx] = 1.0

    if regime in ("up", "down"):
        x[10] = 1.0 if (regime == "up") == (sign > 0) else -1.0

    vwap = _num(vwap_week_dist_pct)
    if vwap is None:
        vwap = _num(paper_trade.get("vwap_week_dist_pct"))
    if vwap is not None:
        x[11] = _clip(sign * vwap, -3.0, 3.0) / 3.0

    hurst = _num(paper_trade.get("hurst_entry"))
    if hurst is not None:
        x[12] = _clip((hurst - 0.5) * 2.0, -1.0, 1.0)

    rsi = _num(paper_trade.get("rsi_entry"))
    if rsi is not None:
        x[13] = _clip(sign * (rsi - 50.0) / 50.0, -1.0, 1.0)

    atr = _num(paper_trade.get("atr_value"))
    if atr is not None:
        x[14] = _clip(atr, 0.0, 3.0) / 3.0

    clv = _num(paper_trade.get("clv_entry"))          # CLV en [0, 1] (candles.py)
    if clv is not None:
        x[15] = _clip(sign * (clv - 0.5) * 2.0, -1.0, 1.0)
    return x


# ---------------------------------------------------------------------------- v2
# v3.14.0 — 8 features nuevas (research/AGENTE_IA_V2_PREREGISTRO_2026-10-06.md §1.1).
# Todas as-of la apertura del paper trade, acotadas y 0 cuando falta el dato. Las
# que necesitan la DB (calendario, COT, racha) llegan precalculadas en `extras` para
# que esta función siga siendo pura.

FEATURE_NAMES_V2: tuple[str, ...] = FEATURE_NAMES + (
    "event_near",          # cercanía a un evento high de sus monedas (±120 min)
    "cot_signed",          # COT index del neto especulativo, a favor del trade
    "cost_r",              # costo fijo de definición / riesgo % del trade
    "dow_mon",
    "dow_fri",
    "hour_sin",
    "hour_cos",
    "strat_recent_r",      # racha: R medio de los últimos 20 cerrados de la estrategia
)
DIM_V2 = len(FEATURE_NAMES_V2)

EVENT_WINDOW_MIN = 120.0
COT_LAG_DAYS = 4             # como el checkpoint COT (--cot-lag-days 4)
COT_LOOKBACK_REPORTS = 156   # ~3 años de reportes semanales
COT_MIN_REPORTS = 52
RECENT_R_N = 20
RECENT_R_MIN = 5
# Costo de DEFINICIÓN (no el cost model vivo, que el .env puede pisar): así la
# feature vale lo mismo en vivo y en el arranque en caliente.
FEATURE_COST_PCT = {"forex": 0.02, "gold": 0.03}

_IDX_V2 = {name: i for i, name in enumerate(FEATURE_NAMES_V2)}


def parse_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def event_proximity(opened_at: Any, events: list[dict[str, Any]]) -> float:
    """max(1 − |Δmin|/120) sobre los eventos dados (ya filtrados por moneda/impacto)."""
    t = parse_utc(opened_at)
    if t is None:
        return 0.0
    best = 0.0
    for ev in events or ():
        et = parse_utc(ev.get("event_time"))
        if et is None:
            continue
        delta = abs((et - t).total_seconds()) / 60.0
        if delta <= EVENT_WINDOW_MIN:
            best = max(best, 1.0 - delta / EVENT_WINDOW_MIN)
    return best


def cot_market_for(symbol: str) -> tuple[str, float] | None:
    """(mercado COT, signo de la moneda) — long del par = long de esa moneda (+1) o
    short (−1). Oro: GOLD. Cruces sin USD: None (sin dato)."""
    s = str(symbol or "").upper().strip()
    if s in {"GC=F", "XAUUSD", "XAUUSD=X"}:
        return "GOLD", 1.0
    if s.endswith("=X"):
        s = s[:-2]
    if len(s) != 6 or not s.isalpha():
        return None
    base, quote = s[:3], s[3:]
    if quote == "USD" and base != "USD":
        return base, 1.0
    if base == "USD" and quote != "USD":
        return quote, -1.0
    return None


def cot_index_signed(symbol: str, direction: str, opened_at: Any,
                     reports: list[dict[str, Any]]) -> float:
    """COT index (0..1) del neto no-comercial / OI sobre los últimos 156 reportes
    publicados as-of (report_date + 4 días <= fecha de apertura), centrado a [−1, 1]
    y firmado: + = los especuladores están cargados del lado del trade."""
    mk = cot_market_for(symbol)
    t = parse_utc(opened_at)
    if mk is None or t is None:
        return 0.0
    cutoff = (t.date() - timedelta(days=COT_LAG_DAYS)).isoformat()
    vals: list[tuple[str, float]] = []
    for r in reports or ():
        rd = str(r.get("report_date") or "")[:10]
        oi = _num(r.get("open_interest"))
        net = _num(r.get("net_noncomm"))
        if not rd or rd > cutoff or not oi or oi <= 0 or net is None:
            continue
        vals.append((rd, net / oi))
    vals.sort()
    vals = vals[-COT_LOOKBACK_REPORTS:]
    if len(vals) < COT_MIN_REPORTS:
        return 0.0
    series = [v for _, v in vals]
    lo, hi = min(series), max(series)
    if hi <= lo:
        return 0.0
    idx = (series[-1] - lo) / (hi - lo)
    sign = -1.0 if str(direction or "long").lower() == "short" else 1.0
    return _clip(sign * mk[1] * (2.0 * idx - 1.0), -1.0, 1.0)


def cost_r_feature(paper_trade: dict[str, Any]) -> float:
    cost = FEATURE_COST_PCT.get(str(paper_trade.get("category") or "").lower())
    entry = _num(paper_trade.get("entry_price"))
    stop = _num(paper_trade.get("original_stop_loss"))
    if stop is None:
        stop = _num(paper_trade.get("stop_loss"))
    if cost is None or not entry or entry <= 0 or stop is None:
        return 0.0
    risk_pct = abs(entry - stop) / entry * 100.0
    if risk_pct <= 0:
        return 0.0
    return _clip(cost / risk_pct, 0.0, 1.0)


def recent_strategy_r(strategy: str, opened_at: Any, closed_trades: list[dict[str, Any]],
                      exclude_mixed_gold: bool = False) -> float:
    """R medio (recortado a R_CLIP, sin artifacts) de los últimos 20 paper trades
    forex/gold de la estrategia CERRADOS antes de la apertura; acotado [−2, 2] / 2.

    v3.14.1: `exclude_mixed_gold` (PAPER_PRICE_FROM_MT5 / warm start limpio) saca el
    oro de precio mezclado, como a los artifacts (adenda 2026-10-07)."""
    from app.ai_agent.model import R_CLIP
    from app.learning.price_source import is_mixed_price_trade
    from app.learning.trade_outcomes import is_artifact, r_multiple

    t = parse_utc(opened_at)
    if t is None or not strategy:
        return 0.0
    prior: list[tuple[datetime, float]] = []
    for tr in closed_trades or ():
        if str(tr.get("strategy_name") or "") != strategy:
            continue
        if str(tr.get("category") or "").lower() not in {"forex", "gold"}:
            continue
        ct = parse_utc(tr.get("closed_at"))
        if ct is None or ct >= t or str(tr.get("status") or "") == "open":
            continue
        if is_artifact(tr) or (exclude_mixed_gold and is_mixed_price_trade(tr)):
            continue
        r = r_multiple(tr)
        if r is None:
            continue
        prior.append((ct, min(max(float(r), R_CLIP[0]), R_CLIP[1])))
    if len(prior) < RECENT_R_MIN:
        return 0.0
    prior.sort(key=lambda p: p[0])
    last = [r for _, r in prior[-RECENT_R_N:]]
    return _clip(sum(last) / len(last), -2.0, 2.0) / 2.0


def build_features_v2(
    paper_trade: dict[str, Any],
    regime: str | None = None,
    vwap_week_dist_pct: float | None = None,
    extras: dict[str, float] | None = None,
) -> list[float]:
    """Vector de DIM_V2 floats: las 16 de v1 + las 8 de v2. `extras` trae
    event_near / cot_signed / strat_recent_r ya calculados (soft-fail = 0)."""
    x = build_features(paper_trade, regime, vwap_week_dist_pct) + [0.0] * (DIM_V2 - DIM)
    ex = extras or {}
    for key, lo, hi in (("event_near", 0.0, 1.0), ("cot_signed", -1.0, 1.0),
                        ("strat_recent_r", -1.0, 1.0)):
        v = _num(ex.get(key))
        if v is not None:
            x[_IDX_V2[key]] = _clip(v, lo, hi)
    x[_IDX_V2["cost_r"]] = cost_r_feature(paper_trade)
    t = parse_utc(paper_trade.get("opened_at"))
    if t is not None:
        x[_IDX_V2["dow_mon"]] = 1.0 if t.weekday() == 0 else 0.0
        x[_IDX_V2["dow_fri"]] = 1.0 if t.weekday() == 4 else 0.0
        h = t.hour + t.minute / 60.0
        x[_IDX_V2["hour_sin"]] = math.sin(2.0 * math.pi * h / 24.0)
        x[_IDX_V2["hour_cos"]] = math.cos(2.0 * math.pi * h / 24.0)
    return x


def feature_names_for(version: int) -> tuple[str, ...]:
    return FEATURE_NAMES_V2 if int(version) == 2 else FEATURE_NAMES
