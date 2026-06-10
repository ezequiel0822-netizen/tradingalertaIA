"""v3.4.0 — Exit shadow: mide HONESTO si un trailing stop mejoraria las salidas.

Hallazgo que lo motiva: en `lifecycle_manager`, los trades de forex/oro caen al `else`
y usan los params de trailing de MEMECOIN (activacion +50%), que en forex NUNCA se
alcanza -> forex/oro no tienen trailing efectivo y devuelven ganancia (capture ratio
~0.68, 24% de winners devuelven >=1R desde el pico).

Pero el "techo" con solo mfe/mae es optimista (ignora recuperaciones). Este modulo
simula el trailing sobre el CAMINO REAL de R de cada trade (muestreado cada ciclo en
`trade_r_samples`), exitando en el PRIMER giveback — no en el pico global. Asi el
numero es honesto: dice cuanto habria mejorado/empeorado una politica, sin adivinar.

SOLO medicion / shadow: NO cambia ninguna salida real. Opt-in OFF
(`enable_exit_shadow`), soft-fail. El comando /exit_analysis reporta el resultado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def simulate_trailing_exit(
    r_path: list[float], distance: float, activation: float = 0.0
) -> float:
    """Dado el camino cronologico de R no-realizado de un trade, devuelve el R con el
    que habria salido un trailing stop que: se arma cuando el pico llega a `activation`,
    y exita cuando el R cae `distance` por debajo del pico CORRIENTE (no del global).

    Exita en el PRIMER giveback (maneja recuperaciones): un trade que sube, baja y vuelve
    a subir, el trailing lo corta en la primera caida — exactamente lo que el techo
    optimista (mfe/mae) ignoraba. Si nunca se dispara, devuelve el R final real."""
    if not r_path:
        return 0.0
    peak = r_path[0]
    armed = False
    for r in r_path:
        if r > peak:
            peak = r
        if not armed and peak >= activation:
            armed = True
        if armed and (peak - r) >= distance:
            return round(peak - distance, 4)  # salio en el nivel del trail
    return round(r_path[-1], 4)  # nunca se disparo -> salida real


@dataclass
class TrailingComparison:
    distance: float
    trades: int = 0
    actual_avg_r: float = 0.0
    policy_avg_r: float = 0.0
    delta_avg_r: float = 0.0
    improved: int = 0   # trades donde el trailing dio MAS R
    hurt: int = 0       # trades donde el trailing dio MENOS R (corto un runner)


def compare_trailing(
    paths: list[list[float]], distances: list[float], activation: float = 0.0
) -> list[TrailingComparison]:
    """Para cada distancia, compara el R real (ultimo del camino) vs el R del trailing
    simulado, agregando sobre todos los caminos. `paths` = lista de caminos de R
    (uno por trade cerrado). Resultado honesto (no es el techo optimista)."""
    results: list[TrailingComparison] = []
    for d in distances:
        comp = TrailingComparison(distance=d)
        sum_actual = 0.0
        sum_policy = 0.0
        for path in paths:
            if not path:
                continue
            actual = path[-1]
            policy = simulate_trailing_exit(path, d, activation)
            comp.trades += 1
            sum_actual += actual
            sum_policy += policy
            if policy > actual + 1e-9:
                comp.improved += 1
            elif policy < actual - 1e-9:
                comp.hurt += 1
        if comp.trades:
            comp.actual_avg_r = round(sum_actual / comp.trades, 3)
            comp.policy_avg_r = round(sum_policy / comp.trades, 3)
            comp.delta_avg_r = round(comp.policy_avg_r - comp.actual_avg_r, 3)
        results.append(comp)
    return results


# -- integracion con el repo (captura por ciclo + analisis del comando) ------ #
def record_open_trade_samples(
    repository: Any, open_trades: list[dict[str, Any]], now_iso: str
) -> int:
    """Por cada trade ABIERTO con R computable, registra una muestra del camino de R.
    Solo registro; no toca ninguna salida. Devuelve cuantas muestras registro."""
    from app.learning.trade_outcomes import r_multiple

    recorded = 0
    for trade in open_trades:
        tid = trade.get("id")
        if tid is None:
            continue
        r = r_multiple(trade)
        if r is None:
            continue
        try:
            repository.insert_r_sample(int(tid), r, now_iso)
            recorded += 1
        except Exception:
            continue
    return recorded


def analyze_closed_trades(
    repository: Any,
    distances: list[float],
    category: str | None = None,
    since_iso: str = "",
    min_samples: int = 3,
) -> list[TrailingComparison]:
    """Toma los trades cerrados no-artifact (opcionalmente de una categoria), reconstruye
    su camino de R desde trade_r_samples y compara el trailing simulado vs la salida real.
    Honesto: usa el camino, no el techo mfe/mae."""
    from app.learning.trade_outcomes import is_artifact

    if since_iso:
        trades = repository.fetch_closed_trades_since(since_iso)
    else:
        trades = repository.fetch_closed_paper_trades(limit=5000)
    paths: list[list[float]] = []
    for trade in trades:
        if is_artifact(trade):
            continue
        if category and str(trade.get("category")) != category:
            continue
        tid = trade.get("id")
        if tid is None:
            continue
        path = repository.fetch_r_path(int(tid))
        if len(path) >= min_samples:
            paths.append(path)
    return compare_trailing(paths, distances)
