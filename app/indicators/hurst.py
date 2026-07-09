"""v3.12.0 — Hurst exponent como indicador puro (deteccion de regimen).

Estima H sobre los ultimos `window` closes via ESCALADO DE VARIANZA (difusion):
    Var(x[t+q] - x[t]) ~ q^(2H)   con x = log(close)
Se calcula la varianza media de las diferencias a lags q = 1,2,4,8,16 y H es
la mitad de la pendiente de log(Var) vs log(q) (minimos cuadrados).

Por que este estimador y no R/S clasico: el R/S tiene sesgo alcista conocido en
ventanas cortas (E[H]~0.55-0.60 para ruido blanco con n=100-500 sin correccion
Anis-Lloyd); el escalado de varianza da H=0.5 exacto en esperanza para ruido
blanco, es O(n) y no necesita numpy. Menos sesgo = thresholds mas honestos.

Interpretacion (3 regimenes, thresholds conservadores):
    H > 0.55  -> "persistent"     (tendencial: los movimientos se continuan)
    H < 0.45  -> "antipersistent" (reversivo: los movimientos se revierten)
    si no     -> "random"         (sin memoria util)

HONESTIDAD ESTADISTICA (INAMOVIBLE): el error de estimacion en ventanas cortas
es GRANDE (con 100 barras, +-0.1 es normal). Por eso:
- window minimo 64 closes; menos -> None (jamas un H inventado).
- hurst_features prefiere la ventana MAS LARGA disponible para el regimen.
- Este indicador es INFORMATIVO + feature de research (ML sigue OFF). NO toca
  el regime gate vivo ni el strategy router: cualquier uso en un gate requiere
  validacion previa en el backtest harness + flag propio (downward-only).

Sin reloj de pared, sin I/O: mismas garantias de replayabilidad que vwap.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Ventanas default (en closes). Configurables por parametro en cada funcion;
# se mantienen fuera de Settings a proposito: son parametros de research, no
# de operacion (cambiarlos no altera ningun comportamiento vivo).
DEFAULT_WINDOWS = (100, 200, 500)

# Lags para el escalado de varianza. Con window>=64 entran todos.
_LAGS = (1, 2, 4, 8, 16)

# Minimo de closes para estimar: bajo esto el error domina -> None.
MIN_WINDOW = 64

# Thresholds conservadores para los 3 regimenes.
PERSISTENT_THRESHOLD = 0.55
ANTIPERSISTENT_THRESHOLD = 0.45


@dataclass
class HurstReading:
    """H estimado para una ventana. value=None => data insuficiente/degenerada."""

    window: int
    value: float | None
    regime: str  # "persistent" | "antipersistent" | "random" | "insufficient_data"
    n_used: int = 0


def classify_regime(
    h: float | None,
    persistent_threshold: float = PERSISTENT_THRESHOLD,
    antipersistent_threshold: float = ANTIPERSISTENT_THRESHOLD,
) -> str:
    if h is None:
        return "insufficient_data"
    if h > persistent_threshold:
        return "persistent"
    if h < antipersistent_threshold:
        return "antipersistent"
    return "random"


def hurst_exponent(closes: list[float], window: int = 200) -> HurstReading:
    """Estima H sobre los ultimos `window` closes (escalado de varianza).

    Filtra closes no-positivos (log requiere >0). Devuelve None si quedan menos
    de MIN_WINDOW puntos, o si la serie es degenerada (varianza ~0 en algun lag:
    precios congelados/alternancia exacta no dan pendiente fiable).
    """
    valid = [c for c in closes if isinstance(c, (int, float)) and c > 0]
    tail = valid[-window:]
    n = len(tail)
    # Etiquetado honesto: hurst_500 significa H sobre 500 barras — con menos
    # data la ventana NO estima (seria un H de otra ventana con otro nombre).
    if n < max(window, MIN_WINDOW):
        return HurstReading(window=window, value=None, regime="insufficient_data")

    x = [math.log(c) for c in tail]
    log_q: list[float] = []
    log_v: list[float] = []
    for q in _LAGS:
        if q >= n:
            break
        diffs = [x[i + q] - x[i] for i in range(n - q)]
        variance = sum(d * d for d in diffs) / len(diffs)
        if variance <= 0.0:
            # Serie degenerada (precios planos a este lag): sin pendiente honesta.
            return HurstReading(
                window=window, value=None, regime="insufficient_data", n_used=n
            )
        log_q.append(math.log(q))
        log_v.append(math.log(variance))

    if len(log_q) < 3:
        return HurstReading(window=window, value=None, regime="insufficient_data", n_used=n)

    slope = _ols_slope(log_q, log_v)
    if slope is None:
        return HurstReading(window=window, value=None, regime="insufficient_data", n_used=n)
    # Var ~ q^(2H) -> pendiente = 2H. Clamp a [0,1]: fuera de eso es artefacto.
    h = max(0.0, min(1.0, slope / 2.0))
    return HurstReading(window=window, value=h, regime=classify_regime(h), n_used=n)


def hurst_features(
    closes: list[float],
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
) -> dict[str, float | str | None]:
    """Features planas de Hurst para analyzer/ML/display (nombres estables).

    hurst_<w> por ventana pedida (None si no alcanza la data) y hurst_regime /
    hurst_best derivados de la ventana MAS LARGA con estimacion valida (menos
    error). Todo None-safe.
    """
    out: dict[str, float | str | None] = {}
    best: HurstReading | None = None
    for w in windows:
        reading = hurst_exponent(closes, w)
        out[f"hurst_{w}"] = round(reading.value, 4) if reading.value is not None else None
        if reading.value is not None:
            best = reading  # windows viene ascendente: gana la mas larga valida
    out["hurst_best"] = round(best.value, 4) if best and best.value is not None else None
    out["hurst_best_window"] = best.window if best else None
    out["hurst_regime"] = best.regime if best else "insufficient_data"
    return out


def _ols_slope(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return sxy / sxx
