from dataclasses import dataclass
from typing import Any

from app.indicators.candles import footprint_features
from app.indicators.hurst import hurst_features
from app.indicators.vwap import vwap_features


@dataclass
class TechnicalPattern:
    label: str
    score: int
    rsi: float | None
    trend: str
    reasons: list[str]
    macd: float | None = None
    macd_signal: float | None = None
    atr_pct: float | None = None
    relative_volume: float | None = None
    support: float | None = None
    resistance: float | None = None
    volatility_label: str = "unknown"
    sparkline: str = ""
    # v3.12.0 — VWAP (informativo: NO entra al score; el gate vivo no cambia).
    # session = reset diario por bar-time; week = anclado al lunes UTC.
    # None/"unknown" cuando no hay volumen real (Yahoo forex) — soft-fail.
    vwap: float | None = None
    vwap_dist_pct: float | None = None
    vwap_position: str = "unknown"
    vwap_week_dist_pct: float | None = None
    # v3.12.0 — Hurst (regimen estadistico) y footprint lite. Igual que el VWAP:
    # informativos + features de research, JAMAS entran al score del pattern.
    hurst: float | None = None
    hurst_regime: str = "insufficient_data"
    candle_strength: str = "neutral"
    candle_clv: float | None = None
    candle_patterns: str = ""


def analyze_ohlcv(candles: list[dict[str, float]]) -> TechnicalPattern:
    closes = [candle["close"] for candle in candles if candle.get("close") is not None]
    highs = [candle.get("high", candle["close"]) for candle in candles if candle.get("close") is not None]
    lows = [candle.get("low", candle["close"]) for candle in candles if candle.get("close") is not None]
    volumes = [candle.get("volume", 0.0) for candle in candles if candle.get("volume") is not None]
    if len(closes) < 20:
        return TechnicalPattern(
            label="insufficient_chart_data",
            score=0,
            rsi=None,
            trend="unknown",
            reasons=["No hay suficientes velas para analisis tecnico confiable."],
            sparkline=_sparkline(closes),
        )

    reasons: list[str] = []
    score = 0
    sma_9 = _sma(closes, 9)
    sma_20 = _sma(closes, 20)
    sma_50 = _sma(closes, 50) if len(closes) >= 50 else None
    macd, macd_signal = _macd(closes)
    rsi = _rsi(closes, 14)
    current = closes[-1]
    previous = closes[-2]
    high_20 = max(closes[-20:-1])
    low_20 = min(closes[-20:-1])
    avg_volume = sum(volumes[-20:-1]) / max(len(volumes[-20:-1]), 1)
    current_volume = volumes[-1] if volumes else 0
    relative_volume = current_volume / avg_volume if avg_volume else None
    atr_pct = _atr_pct(highs, lows, closes, 14)
    support = min(lows[-20:]) if lows else None
    resistance = max(highs[-20:]) if highs else None
    upper_band, lower_band, band_width = _bollinger(closes, 20)
    # v3.12.0 — VWAP informativo (soft-fail sin volumen; jamas toca el score).
    vwap_feats = vwap_features(candles)
    # v3.12.0 — Hurst sobre los closes del feed + footprint de la ultima vela.
    hurst_feats = hurst_features(closes)
    fp = footprint_features(candles)

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
    if relative_volume and relative_volume >= 3 and current > previous:
        score += 10
        reasons.append(f"Volumen relativo fuerte: {relative_volume:.1f}x promedio.")

    if macd is not None and macd_signal is not None:
        if macd > macd_signal and macd > 0:
            score += 12
            reasons.append("MACD alcista y por encima de senal.")
        elif macd < macd_signal and macd < 0:
            score -= 12
            reasons.append("MACD bajista y por debajo de senal.")

    if upper_band and lower_band and current > upper_band:
        score += 8
        reasons.append("Precio rompe banda superior de Bollinger.")
    elif upper_band and lower_band and current < lower_band:
        score -= 10
        reasons.append("Precio pierde banda inferior de Bollinger.")

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

    volatility_label = "normal"
    if atr_pct is not None:
        if atr_pct >= 8:
            volatility_label = "extreme"
            score -= 8
            reasons.append(f"Volatilidad extrema: ATR {atr_pct:.1f}% del precio.")
        elif atr_pct >= 4:
            volatility_label = "high"
            reasons.append(f"Volatilidad alta: ATR {atr_pct:.1f}% del precio.")
        elif atr_pct <= 1:
            volatility_label = "compressed"
            score += 4
            reasons.append("Volatilidad comprimida: posible preparacion de ruptura.")

    if band_width is not None and band_width <= 0.06:
        score += 6
        reasons.append("Bollinger comprimido: energia acumulada para movimiento.")

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
        macd=round(macd, 6) if macd is not None else None,
        macd_signal=round(macd_signal, 6) if macd_signal is not None else None,
        atr_pct=round(atr_pct, 2) if atr_pct is not None else None,
        relative_volume=round(relative_volume, 2) if relative_volume is not None else None,
        support=round(support, 8) if support is not None else None,
        resistance=round(resistance, 8) if resistance is not None else None,
        volatility_label=volatility_label,
        sparkline=_sparkline(closes),
        vwap=round(vwap_feats["vwap_session"], 8)
        if vwap_feats["vwap_session"] is not None
        else None,
        vwap_dist_pct=round(vwap_feats["vwap_session_dist_pct"], 2)
        if vwap_feats["vwap_session_dist_pct"] is not None
        else None,
        vwap_position=vwap_feats["vwap_session_position"],
        vwap_week_dist_pct=round(vwap_feats["vwap_week_dist_pct"], 2)
        if vwap_feats["vwap_week_dist_pct"] is not None
        else None,
        hurst=hurst_feats["hurst_best"],
        hurst_regime=str(hurst_feats["hurst_regime"]),
        candle_strength=str(fp["candle_strength"]),
        candle_clv=fp["candle_clv"],
        candle_patterns=str(fp["candle_patterns"]),
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


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    multiplier = 2 / (period + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append((value - output[-1]) * multiplier + output[-1])
    return output


def _macd(values: list[float]) -> tuple[float | None, float | None]:
    if len(values) < 35:
        return None, None
    ema_12 = _ema_series(values, 12)
    ema_26 = _ema_series(values, 26)
    macd_series = [
        fast - slow
        for fast, slow in zip(ema_12[-len(ema_26):], ema_26)
    ]
    signal = _ema_series(macd_series, 9)
    if not macd_series or not signal:
        return None, None
    return macd_series[-1], signal[-1]


def analyze_multitf(
    candles_short: list[dict[str, float]],
    candles_long: list[dict[str, float]] | None,
) -> dict:
    """Combina pattern de timeframe corto (M15) con largo (H1).

    Retorna dict con `short_pattern`, `long_pattern`, `aligned`, `confluence_score`.
    Si candles_long es None, aligned=None y confluence_score=0.
    """
    short_pattern = analyze_ohlcv(candles_short)
    if not candles_long or len(candles_long) < 20:
        return {
            "short_pattern": short_pattern,
            "long_pattern": None,
            "aligned": None,
            "confluence_score": 0,
        }
    long_pattern = analyze_ohlcv(candles_long)
    aligned = (
        short_pattern.trend == long_pattern.trend
        and short_pattern.trend in {"bullish", "bearish"}
    )
    confluence_score = 10 if aligned else 0
    return {
        "short_pattern": short_pattern,
        "long_pattern": long_pattern,
        "aligned": aligned,
        "confluence_score": confluence_score,
    }


def atr_pct_from_candles(
    candles: list[dict[str, float]], period: int = 14
) -> float | None:
    closes = [candle["close"] for candle in candles if candle.get("close") is not None]
    if len(closes) <= period:
        return None
    highs = [
        candle.get("high", candle["close"])
        for candle in candles
        if candle.get("close") is not None
    ]
    lows = [
        candle.get("low", candle["close"])
        for candle in candles
        if candle.get("close") is not None
    ]
    return _atr_pct(highs, lows, closes, period)


def _atr_pct(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int,
) -> float | None:
    if len(closes) <= period or len(highs) != len(closes) or len(lows) != len(closes):
        return None
    ranges: list[float] = []
    for index in range(1, len(closes)):
        high = highs[index]
        low = lows[index]
        previous_close = closes[index - 1]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr = sum(ranges[-period:]) / period
    current = closes[-1]
    if current == 0:
        return None
    return (atr / current) * 100


def _bollinger(values: list[float], period: int) -> tuple[float | None, float | None, float | None]:
    if len(values) < period:
        return None, None, None
    window = values[-period:]
    mean = sum(window) / period
    variance = sum((value - mean) ** 2 for value in window) / period
    deviation = variance ** 0.5
    upper = mean + 2 * deviation
    lower = mean - 2 * deviation
    width = (upper - lower) / mean if mean else None
    return upper, lower, width


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


def _sparkline(values: list[float], points: int = 24) -> str:
    if not values:
        return ""
    sample = values[-points:]
    low = min(sample)
    high = max(sample)
    blocks = "▁▂▃▄▅▆▇█"
    if high == low:
        return blocks[0] * len(sample)
    output = []
    for value in sample:
        index = round((value - low) / (high - low) * (len(blocks) - 1))
        output.append(blocks[index])
    return "".join(output)
