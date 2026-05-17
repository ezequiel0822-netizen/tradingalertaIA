from dataclasses import dataclass
from typing import Any


@dataclass
class TechnicalPattern:
    label: str
    score: int
    rsi: float | None
    trend: str
    reasons: list[str]


def analyze_ohlcv(candles: list[dict[str, float]]) -> TechnicalPattern:
    closes = [candle["close"] for candle in candles if candle.get("close") is not None]
    volumes = [candle.get("volume", 0.0) for candle in candles if candle.get("volume") is not None]
    if len(closes) < 20:
        return TechnicalPattern(
            label="insufficient_chart_data",
            score=0,
            rsi=None,
            trend="unknown",
            reasons=["No hay suficientes velas para analisis tecnico confiable."],
        )

    reasons: list[str] = []
    score = 0
    sma_9 = _sma(closes, 9)
    sma_20 = _sma(closes, 20)
    sma_50 = _sma(closes, 50) if len(closes) >= 50 else None
    rsi = _rsi(closes, 14)
    current = closes[-1]
    previous = closes[-2]
    high_20 = max(closes[-20:-1])
    low_20 = min(closes[-20:-1])
    avg_volume = sum(volumes[-20:-1]) / max(len(volumes[-20:-1]), 1)
    current_volume = volumes[-1] if volumes else 0

    trend = "neutral"
    if sma_9 and sma_20 and sma_9 > sma_20 and current > sma_20:
        score += 18
        trend = "bullish"
        reasons.append("Precio por encima de medias cortas: sesgo alcista.")
    if sma_9 and sma_20 and sma_9 < sma_20 and current < sma_20:
        score -= 16
        trend = "bearish"
        reasons.append("Precio por debajo de medias cortas: sesgo bajista.")
    if sma_50 and current > sma_50:
        score += 8
        reasons.append("Precio por encima de media 50: tendencia mayor saludable.")
    if sma_50 and current < sma_50:
        score -= 8
        reasons.append("Precio por debajo de media 50: tendencia mayor debil.")

    if current > high_20:
        score += 22
        reasons.append("Ruptura de maximo reciente de 20 velas.")
    if current < low_20:
        score -= 22
        reasons.append("Ruptura bajista de minimo reciente de 20 velas.")

    if current_volume > avg_volume * 2 and current > previous:
        score += 16
        reasons.append("Volumen actual supera 2x el promedio con vela alcista.")
    if current_volume > avg_volume * 2 and current < previous:
        score -= 14
        reasons.append("Volumen actual supera 2x el promedio con vela bajista.")

    if rsi is not None:
        if 52 <= rsi <= 68:
            score += 10
            reasons.append(f"RSI saludable para momentum: {rsi:.1f}.")
        elif rsi > 78:
            score -= 8
            reasons.append(f"RSI sobrecalentado: {rsi:.1f}.")
        elif rsi < 32:
            score -= 6
            reasons.append(f"RSI debil/sobrevendido: {rsi:.1f}.")

    label = "neutral"
    if score >= 35:
        label = "bullish_breakout"
    elif score >= 18:
        label = "bullish_watch"
    elif score <= -30:
        label = "bearish_breakdown"
    elif score <= -12:
        label = "bearish_risk"

    return TechnicalPattern(
        label=label,
        score=max(-100, min(100, score)),
        rsi=round(rsi, 2) if rsi is not None else None,
        trend=trend,
        reasons=reasons[:6] or ["Grafico sin patron fuerte."],
    )


def candles_from_yahoo(result: dict[str, Any]) -> list[dict[str, float]]:
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0]) or {}
    timestamps = result.get("timestamp") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    candles: list[dict[str, float]] = []
    for index, close in enumerate(closes):
        if close is None:
            continue
        candles.append(
            {
                "timestamp": float(timestamps[index]) if index < len(timestamps) else float(index),
                "open": _safe_float(opens[index] if index < len(opens) else close),
                "high": _safe_float(highs[index] if index < len(highs) else close),
                "low": _safe_float(lows[index] if index < len(lows) else close),
                "close": _safe_float(close),
                "volume": _safe_float(volumes[index] if index < len(volumes) else 0),
            }
        )
    return candles


def candles_from_gecko(payload: dict[str, Any]) -> list[dict[str, float]]:
    rows = (((payload.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or [])
    candles: list[dict[str, float]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        candles.append(
            {
                "timestamp": _safe_float(row[0]),
                "open": _safe_float(row[1]),
                "high": _safe_float(row[2]),
                "low": _safe_float(row[3]),
                "close": _safe_float(row[4]),
                "volume": _safe_float(row[5]),
            }
        )
    return list(reversed(candles))


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _rsi(values: list[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    gains = []
    losses = []
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    for change in changes[-period:]:
        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
