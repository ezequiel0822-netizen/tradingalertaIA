"""v3.12.0 — Anatomia de velas y "footprint lite" (indicador puro).

Metricas por vela (body/wick ratios, close location value, fuerza direccional
normalizada por ATR) + secuencias multi-vela clasicas con thresholds basados
en ATR (nada de patrones "de manual" sin escala: un martillo de 0.1xATR es
ruido, no martillo).

Convenciones del paquete indicators (INAMOVIBLES):
- Velas estandar del proyecto (dict open/high/low/close/volume); puro stdlib,
  sin reloj de pared, sin I/O -> replayable en el harness por construccion.
- Soft-fail honesto: sin data suficiente -> None/"neutral"/lista vacia.
- INFORMATIVO + feature de research: NO toca scores vivos ni gates. Cualquier
  uso en gate/router requiere harness + flag propio (downward-only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Umbral de cuerpo (fraccion del rango) bajo el cual la vela es doji.
DOJI_BODY_RATIO = 0.10

# Rango minimo en ATRs para que un patron de vela "cuente" (anti-ruido).
MIN_PATTERN_RANGE_ATR = 0.8

# Fuerza direccional (vela actual): thresholds congelados y documentados.
STRONG_BODY_RATIO = 0.60
STRONG_RANGE_ATR = 1.2
STRONG_CLV_BULL = 0.70   # cierre en el 30% superior del rango
STRONG_CLV_BEAR = 0.30   # cierre en el 30% inferior


@dataclass
class CandleAnatomy:
    """Anatomia de UNA vela. Ratios en [0,1]; range_atr None sin ATR."""

    direction: str          # "bull" | "bear" | "doji"
    body_ratio: float       # |close-open| / (high-low)
    upper_wick_ratio: float
    lower_wick_ratio: float
    clv: float              # close location value: 0=close en low, 1=en high
    range_atr: float | None  # (high-low) / ATR(14) — fuerza normalizada


def candle_anatomy(candle: dict[str, Any], atr: float | None = None) -> CandleAnatomy | None:
    """Anatomia de la vela. None si faltan OHLC o el rango es invalido."""
    try:
        o = float(candle["open"])
        h = float(candle["high"])
        low = float(candle["low"])
        c = float(candle["close"])
    except (KeyError, TypeError, ValueError):
        return None
    rng = h - low
    if rng <= 0:
        # Vela plana (o data mala): anatomia degenerada pero definida.
        return CandleAnatomy(
            direction="doji", body_ratio=0.0, upper_wick_ratio=0.0,
            lower_wick_ratio=0.0, clv=0.5, range_atr=0.0 if atr else None,
        )
    body = abs(c - o)
    body_ratio = body / rng
    upper_wick = (h - max(o, c)) / rng
    lower_wick = (min(o, c) - low) / rng
    clv = (c - low) / rng
    if body_ratio < DOJI_BODY_RATIO:
        direction = "doji"
    else:
        direction = "bull" if c > o else "bear"
    range_atr = (rng / atr) if atr and atr > 0 else None
    return CandleAnatomy(
        direction=direction,
        body_ratio=round(body_ratio, 4),
        upper_wick_ratio=round(upper_wick, 4),
        lower_wick_ratio=round(lower_wick, 4),
        clv=round(clv, 4),
        range_atr=round(range_atr, 4) if range_atr is not None else None,
    )


def atr_absolute(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    """ATR absoluto (misma mecanica que technical_patterns._atr_pct, sin %)."""
    rows = [c for c in candles if c.get("close") is not None]
    if len(rows) <= period:
        return None
    ranges: list[float] = []
    for i in range(1, len(rows)):
        h = float(rows[i].get("high") or rows[i]["close"])
        low = float(rows[i].get("low") or rows[i]["close"])
        prev_close = float(rows[i - 1]["close"])
        ranges.append(max(h - low, abs(h - prev_close), abs(low - prev_close)))
    atr = sum(ranges[-period:]) / period
    return atr if atr > 0 else None


def candle_strength(candles: list[dict[str, Any]], atr_period: int = 14) -> str:
    """Fuerza direccional de la ULTIMA vela, normalizada por ATR.

    strong_bull / bull / neutral / bear / strong_bear. "strong" exige cuerpo
    dominante (>=0.6 del rango), rango >=1.2xATR y cierre en el tercio extremo.
    """
    if not candles:
        return "neutral"
    atr = atr_absolute(candles, atr_period)
    anatomy = candle_anatomy(candles[-1], atr)
    if anatomy is None or anatomy.direction == "doji":
        return "neutral"
    strong_range = anatomy.range_atr is not None and anatomy.range_atr >= STRONG_RANGE_ATR
    if anatomy.direction == "bull":
        if (anatomy.body_ratio >= STRONG_BODY_RATIO and strong_range
                and anatomy.clv >= STRONG_CLV_BULL):
            return "strong_bull"
        return "bull" if anatomy.body_ratio >= 0.4 and anatomy.clv >= 0.6 else "neutral"
    if (anatomy.body_ratio >= STRONG_BODY_RATIO and strong_range
            and anatomy.clv <= STRONG_CLV_BEAR):
        return "strong_bear"
    return "bear" if anatomy.body_ratio >= 0.4 and anatomy.clv <= 0.4 else "neutral"


def detect_sequences(candles: list[dict[str, Any]], atr_period: int = 14) -> list[str]:
    """Patrones de 1-3 velas al CIERRE de la ultima, con escala ATR (anti-ruido).

    Single: hammer, shooting_star, doji. Dobles: engulfing_bull/bear, inside_bar.
    Triples: three_soldiers, three_crows. Lista vacia si nada califica.
    """
    if len(candles) < 2:
        return []
    atr = atr_absolute(candles, atr_period)
    out: list[str] = []
    last = candle_anatomy(candles[-1], atr)
    prev = candle_anatomy(candles[-2], atr)
    if last is None:
        return []

    big_enough = last.range_atr is None or last.range_atr >= MIN_PATTERN_RANGE_ATR

    # --- 1 vela ---
    if last.direction == "doji":
        out.append("doji")
    if big_enough and last.lower_wick_ratio >= 0.6 and last.clv >= 0.6:
        out.append("hammer")
    if big_enough and last.upper_wick_ratio >= 0.6 and last.clv <= 0.4:
        out.append("shooting_star")

    # --- 2 velas ---
    if prev is not None:
        lo, lc = float(candles[-1]["open"]), float(candles[-1]["close"])
        po, pc = float(candles[-2]["open"]), float(candles[-2]["close"])
        if (prev.direction == "bear" and last.direction == "bull"
                and lo <= pc and lc >= po and big_enough):
            out.append("engulfing_bull")
        if (prev.direction == "bull" and last.direction == "bear"
                and lo >= pc and lc <= po and big_enough):
            out.append("engulfing_bear")
        lh, ll = float(candles[-1]["high"]), float(candles[-1]["low"])
        ph, pl = float(candles[-2]["high"]), float(candles[-2]["low"])
        if lh <= ph and ll >= pl:
            out.append("inside_bar")

    # --- 3 velas ---
    if len(candles) >= 3:
        anatomies = [candle_anatomy(c, atr) for c in candles[-3:]]
        closes = [float(c["close"]) for c in candles[-3:]]
        if all(a is not None for a in anatomies):
            if (all(a.direction == "bull" and a.body_ratio >= 0.5 for a in anatomies)
                    and closes[0] < closes[1] < closes[2]):
                out.append("three_soldiers")
            if (all(a.direction == "bear" and a.body_ratio >= 0.5 for a in anatomies)
                    and closes[0] > closes[1] > closes[2]):
                out.append("three_crows")
    return out


def volume_anomaly(candles: list[dict[str, Any]], lookback: int = 20) -> float | None:
    """Volumen de la ultima vela / promedio de las `lookback` previas.

    None si no hay volumen real (forex Yahoo) o data insuficiente. >1 = mas
    volumen que lo normal; ~3+ = anomalia clara.
    """
    if len(candles) < lookback + 1:
        return None
    try:
        current = float(candles[-1].get("volume") or 0.0)
        prev = [float(c.get("volume") or 0.0) for c in candles[-lookback - 1:-1]]
    except (TypeError, ValueError):
        return None
    avg = sum(prev) / len(prev) if prev else 0.0
    if avg <= 0 or current <= 0:
        return None
    return round(current / avg, 2)


def footprint_features(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Features planas del footprint lite para analyzer/ML/display.

    Nombres estables (columnas de dataset a futuro). None-safe integral.
    """
    if not candles:
        return {
            "candle_direction": "neutral", "candle_body_ratio": None,
            "candle_upper_wick": None, "candle_lower_wick": None,
            "candle_clv": None, "candle_range_atr": None,
            "candle_strength": "neutral", "candle_patterns": "",
            "volume_anomaly": None,
        }
    atr = atr_absolute(candles)
    anatomy = candle_anatomy(candles[-1], atr)
    patterns = detect_sequences(candles)
    return {
        "candle_direction": anatomy.direction if anatomy else "neutral",
        "candle_body_ratio": anatomy.body_ratio if anatomy else None,
        "candle_upper_wick": anatomy.upper_wick_ratio if anatomy else None,
        "candle_lower_wick": anatomy.lower_wick_ratio if anatomy else None,
        "candle_clv": anatomy.clv if anatomy else None,
        "candle_range_atr": anatomy.range_atr if anatomy else None,
        "candle_strength": candle_strength(candles),
        "candle_patterns": ",".join(patterns),
        "volume_anomaly": volume_anomaly(candles),
    }
