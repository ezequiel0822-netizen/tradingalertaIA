"""v3.13.0 — vector de contexto del agente IA (funciones puras, sin I/O).

Todas las features están acotadas y valen 0 cuando falta el dato (con prior en 0,
"no sé" no empuja la decisión hacia ningún lado). Las direccionales se firman con el
lado del trade: +1 significa "a favor del trade" (ej. RSI alto en un long).
"""

from __future__ import annotations

import math
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
