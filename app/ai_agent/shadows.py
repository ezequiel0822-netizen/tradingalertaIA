"""v3.15.0 — agentes sombra (research/AGENTE_IA_SOMBRAS_PREREGISTRO_2026-10-07.md).

Tres políticas que deciden sobre los MISMOS candidatos que el agente v2 y NUNCA operan:
se calculan de lo que el agente ya registra en cada decisión (media y desvío de su
posterior, el ajuste de realismo ĝ y el tipo de candidato). Funciones puras: sin
órdenes, sin MT5, sin escribir la DB.

- S1 `codicioso`: mean_r + ĝ > 0.05 (la media del agente, sin muestreo).
- S2 `prudente`:  mean_r − std_r + ĝ > 0.05 (solo con confianza de un desvío).
- S3 `simple`:    modelo propio de 6 features (bias, estrategia, short, gold), re-jugado
                  en orden temporal: antes de cada decisión aprende de TODOS los paper
                  trades forex/oro cerrados antes (sin artifacts ni oro mezclado); su
                  media + ĝ > 0.05.

Sin edge (26 familias, 0 operables), lo esperable es que difieran en cuánto pierden.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from app.ai_agent.features import FEATURE_NAMES, build_features, parse_utc
from app.ai_agent.model import LinearThompson
from app.learning.price_source import is_mixed_price_trade
from app.learning.trade_outcomes import is_artifact, r_multiple

SHADOW_THRESHOLD_R = 0.05
SHADOWS: tuple[str, ...] = ("codicioso", "prudente", "simple")
SHADOW_LABELS = {
    "codicioso": "la media del agente, sin azar",
    "prudente": "solo con confianza",
    "simple": "6 features: estrategia, dirección, oro",
}
SIMPLE_FEATURES: tuple[str, ...] = FEATURE_NAMES[:6]   # bias, 3 estrategias, short, gold
SIMPLE_DIM = len(SIMPLE_FEATURES)


def _num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def candidate_x(row: dict[str, Any]) -> list[float]:
    """Las 6 features de S3 a partir de la estrategia, la dirección y la categoría (las
    mismas 6 primeras que el agente arma para ese candidato)."""
    return build_features({
        "strategy_name": row.get("strategy_name"),
        "direction": row.get("direction"),
        "category": row.get("category"),
    })[:SIMPLE_DIM]


def learnable_trades(trades: Iterable[dict[str, Any]]) -> list[tuple[datetime, list[float], float]]:
    """(cierre, x de 6, R) de los paper trades forex/oro cerrados que sirven para
    aprender (sin artifacts ni oro mezclado), ordenados por cierre."""
    out: list[tuple[datetime, list[float], float]] = []
    for t in trades or ():
        if str(t.get("category") or "").lower() not in {"forex", "gold"}:
            continue
        if str(t.get("status") or "") == "open":
            continue
        closed = parse_utc(t.get("closed_at"))
        if closed is None or is_artifact(t) or is_mixed_price_trade(t):
            continue
        r = r_multiple(t)
        if r is None:
            continue
        out.append((closed, candidate_x(t), float(r)))
    out.sort(key=lambda z: z[0])
    return out


def shadow_decisions(
    decisions: Iterable[dict[str, Any]],
    closed_trades: Iterable[dict[str, Any]],
    prior_var: float = 0.25,
    noise_var: float = 1.0,
    threshold: float = SHADOW_THRESHOLD_R,
) -> dict[int, dict[str, bool]]:
    """{id de la decisión: {'codicioso': bool, 'prudente': bool, 'simple': bool}} para
    cada decisión con media registrada (True = la sombra la ejecutaría).

    S3 se re-juega en orden: antes de cada decisión incorpora lo cerrado ANTES de su
    `created_at` (nunca mira el resultado de la propia decisión ni el futuro)."""
    learn = learnable_trades(closed_trades)
    model = LinearThompson(SIMPLE_FEATURES, prior_var, noise_var)
    rows = []
    for d in decisions or ():
        t = parse_utc(d.get("created_at"))
        if t is None or _num(d.get("mean_r")) is None or d.get("id") is None:
            continue
        rows.append((t, int(d["id"]), d))
    rows.sort(key=lambda z: (z[0], z[1]))
    out: dict[int, dict[str, bool]] = {}
    i = 0
    for t, did, d in rows:
        while i < len(learn) and learn[i][0] < t:
            model.update(learn[i][1], learn[i][2])
            i += 1
        mean = float(d["mean_r"])
        sd = _num(d.get("std_r")) or 0.0
        gap = _num(d.get("realism_gap")) or 0.0
        simple_mean = model.predict(candidate_x(d))[0]
        out[did] = {
            "codicioso": mean + gap > threshold,
            "prudente": mean - sd + gap > threshold,
            "simple": simple_mean + gap > threshold,
        }
    return out


def shadow_values(
    decisions: Iterable[dict[str, Any]], flags: dict[int, dict[str, bool]], name: str
) -> list[tuple[str, float]]:
    """(fecha UTC, v_s) por decisión con R: R_paper si la sombra la ejecutaría, 0 si no."""
    out = []
    for d in decisions or ():
        did = d.get("id")
        if did is None or int(did) not in flags or _num(d.get("reward_r")) is None:
            continue
        v = float(d["reward_r"]) if flags[int(did)][name] else 0.0
        out.append((str(d.get("created_at") or "")[:10], v))
    return out


def daily_series(values: list[tuple[str, float]]) -> list[float]:
    by_day: dict[str, float] = defaultdict(float)
    for day, v in values:
        by_day[day] += v
    return [by_day[k] for k in sorted(by_day)]


def shadow_scoreboard(
    decisions: list[dict[str, Any]], flags: dict[int, dict[str, bool]]
) -> dict[str, dict[str, float]]:
    """Por sombra: decisiones con R, cuántas ejecutaría, suma y media de v_s.
    Quien llama filtra la población (tag, oro mezclado)."""
    res: dict[str, dict[str, float]] = {}
    for name in SHADOWS:
        vals = shadow_values(decisions, flags, name)
        acted = sum(1 for d in decisions
                    if d.get("id") is not None and int(d["id"]) in flags
                    and _num(d.get("reward_r")) is not None and flags[int(d["id"])][name])
        total = sum(v for _, v in vals)
        res[name] = {
            "n": len(vals),
            "executes": acted,
            "sum_r": total,
            "mean_v": total / len(vals) if vals else 0.0,
        }
    return res


def shadow_summary_lines(decisions: list[dict[str, Any]], closed_trades: list[dict[str, Any]],
                         prior_var: float = 0.25, noise_var: float = 1.0) -> list[str]:
    """Líneas para /agente: qué haría cada sombra sobre las decisiones dadas."""
    flags = shadow_decisions(decisions, closed_trades, prior_var, noise_var)
    sb = shadow_scoreboard(decisions, flags)
    n = sb[SHADOWS[0]]["n"] if sb else 0
    lines = [f"Agentes sombra (no operan; sobre {n} decisiones cerradas):"]
    for name in SHADOWS:
        s = sb[name]
        lines.append(f"  {name:10} {s['sum_r']:+.2f}R (ejecutaría {int(s['executes'])}) — "
                     f"{SHADOW_LABELS[name]}")
    return lines
