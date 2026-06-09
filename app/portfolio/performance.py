"""v3.3.0 — Performance desde un baseline limpio (post-correccion de bugs).

El balance real del demo es el que es; esto NO lo falsea ni borra trades. Mide la
performance REALIZADA de los trades que efectivamente se ejecutaron a MT5 demo (con
demo_order 'sent') y que NO son artifacts, desde una fecha baseline configurable. Sirve
para ver el % que se lleva la cuenta LIMPIO del periodo buggeado de mayo (feedback-loop /
instant-kill / posiciones huerfanas, corregidos en v2.6.7-v2.7.1).

Pura (sin DB): testeable con dicts. Reusa `trade_outcomes` para el R/return NETO de
costos, y el mismo USD-PnL/balance de `realized_pnl_today` (v2.7.1) para el impacto en
la cuenta. Honestidad: el re-baseline solo recorta el periodo medido; NO inventa edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.learning.trade_outcomes import is_artifact, r_multiple, realized_return_pct


@dataclass
class PerformanceSummary:
    since: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    net_r: float = 0.0
    account_pct: float = 0.0  # impacto USD / balance * 100 (mismo metodo que realized_pnl_today)


def _to_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def performance_since(
    trades: list[dict[str, Any]],
    baseline_iso: str,
    executed_ids: set[int],
    balance: float,
    cost_pct_by_category: dict[str, float] | None = None,
) -> PerformanceSummary:
    """Resume los trades cerrados, ejecutados a MT5 y no-artifact con closed_at >=
    baseline. `executed_ids` = paper_trade_id con demo_order 'sent' (los que tocaron el
    balance real). net_r y win/loss usan R realizado NETO de costos; account_pct usa
    el retorno final almacenado * notional / balance (idem realized_pnl_today)."""
    costs = cost_pct_by_category or {}
    summary = PerformanceSummary(since=baseline_iso or "inicio")
    total_usd = 0.0
    for t in trades:
        if str(t.get("status") or "") == "open" or not t.get("closed_at"):
            continue
        if baseline_iso and str(t.get("closed_at") or "") < baseline_iso:
            continue
        tid = t.get("id")
        if tid is None or int(tid) not in executed_ids:
            continue  # solo trades que tocaron el balance MT5 real
        if is_artifact(t):
            continue
        cat = str(t.get("category") or "unknown")
        cost = float(costs.get(cat, 0.0) or 0.0)
        r = r_multiple(t, cost_pct=cost)
        ret = realized_return_pct(t, cost_pct=cost)
        if r is None or ret is None:
            continue
        summary.trades += 1
        summary.net_r += r
        if r > 0:
            summary.wins += 1
        elif r < 0:
            summary.losses += 1
        # Impacto USD en la cuenta: retorno final almacenado * notional real de MT5.
        final_ret = _to_float(t.get("unrealized_return_pct"))
        notional = _to_float(t.get("size_notional"))
        if final_ret is not None and notional and notional > 0:
            total_usd += notional * (final_ret / 100.0)

    decided = summary.wins + summary.losses
    summary.win_rate = round(summary.wins / decided, 4) if decided else 0.0
    summary.net_r = round(summary.net_r, 2)
    summary.account_pct = round((total_usd / balance) * 100.0, 4) if balance > 0 else 0.0
    return summary
