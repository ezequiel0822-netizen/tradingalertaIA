"""Realized trade outcomes en R-multiples — la señal HONESTA de aprendizaje.

v2.7.0. El motor previo (signal_outcomes) etiquetaba win/loss por el *drift* de
la alerta a un horizonte fijo, con umbrales absolutos (+5% stock, +30% memecoin).
Resultado: ~99% de los outcomes quedaban 'neutral' y el gate aprendía de una
métrica desacoplada del P&L real del trade (ver /gate_preview: avg_return +6.7%
pero win_rate 0%).

Acá medimos el P&L REALIZADO del paper_trade, normalizado por el riesgo asumido
al entry:

    R = retorno_realizado_% / riesgo_al_entry_%
    expectancy = R promedio por trade

R-multiple normaliza entre instrumentos (memecoin +30% y forex +0.3% no son
comparables en %, pero sí en R) y es la única métrica que se conecta con el
crecimiento de la cuenta.

Además excluye ARTIFACTS del feedback-loop / instant-close (precio nunca se
movió del entry), que pre-v2.7.0 eran ~85% del historial y envenenaban toda stat.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def realized_return_pct(
    trade: dict[str, Any], partial_fraction: float = 0.5, cost_pct: float = 0.0
) -> float | None:
    """Retorno realizado direction-aware (%), NETO de costos.

    Si el trade hizo partial close en TP1, mezcla la fracción cerrada en TP1
    con la pierna final (el resto cerró en latest_price). Esto refleja el P&L
    realizado de verdad, no solo la última pierna.

    `cost_pct` es el costo round-trip estimado (spread + comisión) en % que se
    resta del retorno bruto — siempre resta (empeora el resultado), gane o pierda.
    Sin esto el realized-R es optimista vs MT5 real y el promotion gate podría
    promover a LIVE estrategias positivas en bruto pero negativas netas.
    """
    entry = _f(trade.get("entry_price"))
    latest = _f(trade.get("latest_price"))
    if entry is None or latest is None or entry <= 0:
        return None
    direction = str(trade.get("direction") or "long")
    if direction == "short":
        final = (entry - latest) / entry * 100.0
    else:
        final = (latest - entry) / entry * 100.0

    if int(trade.get("partial_closed") or 0) == 1:
        tp1 = _f(trade.get("take_profit_1"))
        if tp1 is not None:
            if direction == "short":
                tp1_ret = (entry - tp1) / entry * 100.0
            else:
                tp1_ret = (tp1 - entry) / entry * 100.0
            frac = max(0.0, min(1.0, partial_fraction))
            gross = frac * tp1_ret + (1.0 - frac) * final
            return gross - (cost_pct or 0.0)
    return final - (cost_pct or 0.0)


def risk_at_entry_pct(trade: dict[str, Any]) -> float | None:
    """Riesgo asumido al entry (%) = distancia al stop ORIGINAL.

    Usa original_stop_loss (no el stop actual, que pudo moverse por trailing /
    breakeven). Direction-aware.
    """
    entry = _f(trade.get("entry_price"))
    ostop = _f(trade.get("original_stop_loss"))
    if ostop is None:
        ostop = _f(trade.get("stop_loss"))
    if entry is None or ostop is None or entry <= 0:
        return None
    direction = str(trade.get("direction") or "long")
    if direction == "short":
        risk = (ostop - entry) / entry * 100.0
    else:
        risk = (entry - ostop) / entry * 100.0
    return risk if risk > 0 else None


def r_multiple(
    trade: dict[str, Any], partial_fraction: float = 0.5, cost_pct: float = 0.0
) -> float | None:
    ret = realized_return_pct(trade, partial_fraction, cost_pct)
    risk = risk_at_entry_pct(trade)
    if ret is None or risk is None or risk <= 0:
        return None
    return ret / risk


def is_artifact(trade: dict[str, Any]) -> bool:
    """True si el trade cerrado es basura del feedback-loop / instant-close.

    Marca inequívoca: cerró pero `latest_price` nunca se movió del `entry_price`
    (precio congelado → el trade nunca se marcó a mercado). Un trade real que
    cerró por stop/target tiene latest != entry. Pre-v2.7.0 ~85% del historial
    (forex/gold shorts insta-killed) cae acá. Trades abiertos NO son artifacts.
    """
    status = str(trade.get("status") or "")
    if status == "open" or not trade.get("closed_at"):
        return False
    entry = _f(trade.get("entry_price"))
    latest = _f(trade.get("latest_price"))
    if entry is None or latest is None or entry == 0:
        return True  # sin precios utilizables → inservible para aprender
    return abs(latest - entry) < abs(entry) * 1e-9


def outcome_label(
    trade: dict[str, Any],
    partial_fraction: float = 0.5,
    scratch_eps: float = 0.05,
    cost_pct: float = 0.0,
) -> str:
    ret = realized_return_pct(trade, partial_fraction, cost_pct)
    if ret is None:
        return "unknown"
    if ret > scratch_eps:
        return "win"
    if ret < -scratch_eps:
        return "loss"
    return "scratch"


@dataclass
class StrategyPerf:
    strategy_name: str
    category: str
    trades: int
    wins: int
    losses: int
    scratches: int
    win_rate: float
    avg_r: float            # expectancy por trade en R
    avg_return_pct: float
    sum_return_pct: float
    artifacts_excluded: int


def build_strategy_performance(
    trades: list[dict[str, Any]],
    partial_fraction: float = 0.5,
    scratch_eps: float = 0.05,
    cost_pct_by_category: dict[str, float] | None = None,
) -> list[StrategyPerf]:
    """Agrupa paper_trades cerrados por (strategy_name, category) y calcula
    expectancy realizada en R (NETA de costos), excluyendo artifacts.

    `cost_pct_by_category` mapea category -> costo round-trip % (spread+comisión)
    que se resta del retorno bruto de cada trade. Si None/vacío, R queda bruto.
    """
    costs = cost_pct_by_category or {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    artifacts: dict[tuple[str, str], int] = {}

    for t in trades:
        if str(t.get("status") or "") == "open" or not t.get("closed_at"):
            continue  # solo trades cerrados
        strat = str(t.get("strategy_name") or "unknown")
        cat = str(t.get("category") or "unknown")
        key = (strat, cat)
        if is_artifact(t):
            artifacts[key] = artifacts.get(key, 0) + 1
            continue
        groups.setdefault(key, []).append(t)

    results: list[StrategyPerf] = []
    for key, ts in groups.items():
        cost = float(costs.get(key[1], 0.0) or 0.0)
        rets: list[float] = []
        rs: list[float] = []
        for t in ts:
            ret = realized_return_pct(t, partial_fraction, cost)
            if ret is None:
                continue
            rets.append(ret)
            rr = r_multiple(t, partial_fraction, cost)
            if rr is not None:
                rs.append(rr)
        n = len(rets)
        wins = sum(1 for x in rets if x > scratch_eps)
        losses = sum(1 for x in rets if x < -scratch_eps)
        scratches = n - wins - losses
        results.append(
            StrategyPerf(
                strategy_name=key[0],
                category=key[1],
                trades=n,
                wins=wins,
                losses=losses,
                scratches=scratches,
                win_rate=round(wins / n, 4) if n else 0.0,
                avg_r=round(sum(rs) / len(rs), 4) if rs else 0.0,
                avg_return_pct=round(sum(rets) / n, 4) if n else 0.0,
                sum_return_pct=round(sum(rets), 4) if rets else 0.0,
                artifacts_excluded=artifacts.get(key, 0),
            )
        )

    # grupos que fueron 100% artifacts: reportarlos con trades=0 para visibilidad
    for key, cnt in artifacts.items():
        if key not in groups:
            results.append(
                StrategyPerf(
                    strategy_name=key[0], category=key[1], trades=0, wins=0,
                    losses=0, scratches=0, win_rate=0.0, avg_r=0.0,
                    avg_return_pct=0.0, sum_return_pct=0.0, artifacts_excluded=cnt,
                )
            )

    return sorted(results, key=lambda p: (p.trades, p.avg_r), reverse=True)


def should_execute_live(
    strategy_name: str,
    category: str,
    perf_row: dict[str, Any] | None,
    min_samples: int = 30,
    min_expectancy_r: float = 0.0,
) -> tuple[bool, str]:
    """Promotion gate (v2.7.0): ¿esta estrategia puede EJECUTAR a MT5 demo?

    Filosofía 'inocente hasta probarse culpable': permite ejecutar salvo que la
    estrategia tenga expectancy realizada negativa DEMOSTRADA — avg_r <= umbral con
    n >= min_samples trades reales. Las no probadas (pocos trades) pasan para seguir
    juntando data. Las que ya demostraron edge negativo quedan en SHADOW (paper-only)
    hasta que su expectancy mejore.

    NO toca la creación de paper_trades ni el real-money — solo decide si se manda el
    order_send a la cuenta demo. Devuelve (puede_ejecutar, motivo).
    """
    if perf_row is None:
        return True, "sin data de expectancy (allow; juntando muestra)"
    n = int(perf_row.get("trades") or 0)
    if n < min_samples:
        return True, f"muestra insuficiente n={n}<{min_samples} (allow; juntando)"
    avg_r = float(perf_row.get("avg_r") or 0.0)
    if avg_r <= min_expectancy_r:
        return (
            False,
            f"SHADOW: expectancy {avg_r:+.2f}R <= {min_expectancy_r:+.2f}R con n={n} (paper-only)",
        )
    return True, f"LIVE: expectancy {avg_r:+.2f}R con n={n}"


def build_realized_feature_lessons(
    closed_trades: list[dict[str, Any]],
    features_by_alert_id: dict[int, list[str]],
    cost_pct_by_category: dict[str, float] | None = None,
    partial_fraction: float = 0.5,
    min_samples: int = 2,
) -> list[dict[str, Any]]:
    """v2.7.0 Fase 2b: lessons de realized-R por (feature, category) desde
    paper_trades CERRADOS (excluye artifacts).

    Es la versión HONESTA de strategy_lessons: en vez del drift de la alerta a
    horizonte fijo (que dejaba ~99% 'neutral'), cada trade aporta su R realizado
    NETO de costos a cada una de sus features. Lo consumen learned_weights y el
    learning_gate cuando enable_realized_learning=True.

    `win_rate` = fracción de trades con R>0 (consistente con la definición de
    /expectancy y el promotion gate). `confidence` escala con el sample_count.
    Devuelve dicts SIN `updated_at` (lo agrega el caller).
    """
    costs = cost_pct_by_category or {}
    buckets: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for t in closed_trades:
        if str(t.get("status") or "") == "open" or not t.get("closed_at"):
            continue
        if is_artifact(t):
            continue
        cat = str(t.get("category") or "unknown")
        cost = float(costs.get(cat, 0.0) or 0.0)
        rr = r_multiple(t, partial_fraction, cost)
        ret = realized_return_pct(t, partial_fraction, cost)
        if rr is None or ret is None:
            continue
        aid = t.get("alert_id")
        feats: list[str] = []
        if aid is not None:
            try:
                feats = list(features_by_alert_id.get(int(aid), []))
            except (TypeError, ValueError):
                feats = []
        cat_feat = f"category:{cat}"
        if cat_feat not in feats:
            feats.append(cat_feat)
        for f in feats:
            buckets.setdefault((str(f), cat), []).append((rr, ret))

    lessons: list[dict[str, Any]] = []
    for (feature, cat), vals in buckets.items():
        n = len(vals)
        if n < min_samples:
            continue
        rs = [v[0] for v in vals]
        rets = [v[1] for v in vals]
        wins = sum(1 for r in rs if r > 0)
        win_rate = wins / n
        avg_r = sum(rs) / n
        avg_return = sum(rets) / n
        confidence = min(100, int(n * 8 + abs(avg_return) * 0.5))
        lessons.append(
            {
                "feature": feature,
                "category": cat,
                "sample_count": n,
                "wins": wins,
                "win_rate": round(win_rate, 4),
                "avg_r": round(avg_r, 4),
                "avg_return_pct": round(avg_return, 4),
                "confidence": confidence,
            }
        )
    return lessons
