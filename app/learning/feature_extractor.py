import json
from typing import Any


def extract_features(alert: dict[str, Any]) -> list[str]:
    text = " ".join(
        [
            str(alert.get("alert_type") or ""),
            str(alert.get("risk_level") or ""),
            _json_text(alert.get("reasons")),
            _json_text(alert.get("estimate_summary")),
            str(alert.get("security_summary") or ""),
        ]
    ).lower()
    category = str(alert.get("category") or "unknown").lower()
    score = _to_float(alert.get("score")) or 0
    confidence = _to_float(alert.get("estimate_confidence")) or 0
    gain = _to_float(alert.get("estimated_gain_pct")) or 0

    features = {
        f"category:{category}",
        f"alert:{str(alert.get('alert_type') or 'unknown').lower()}",
        f"risk:{str(alert.get('risk_level') or 'unknown').lower()}",
        _bucket("score", score, [40, 65, 80, 90]),
        _bucket("confidence", confidence, [35, 55, 70, 85]),
        _bucket("gain_estimate", gain, [8, 100, 500, 1000]),
    }

    keyword_features = {
        "ia_pro": ["ia pro", "pro_high_conviction", "pro_watchlist"],
        "bullish_pattern": ["bullish_breakout", "bullish_watch", "macd alcista"],
        "bearish_pattern": ["bearish_breakdown", "bearish_risk", "macd bajista"],
        "positive_news": ["positive_catalyst", "sesgo positivo", "guidance"],
        "negative_news": ["negative_catalyst", "sesgo negativo", "lawsuit", "probe"],
        "sec_catalyst": ["positive_filing_catalyst", "sec filings"],
        "sec_risk": ["filing_risk", "offering", "prospectus"],
        "anti_hype": ["anti-hype"],
        "volume_strength": ["volumen relativo", "volumen fuerte", "volumen 1h"],
        "liquidity_strength": ["liquidez util", "liquidez media", "liquidez alta"],
        "low_liquidity": ["liquidez baja", "bajo minimo"],
        "security_unknown": ["seguridad unknown", "raw_summary\":\"unknown", "unknown"],
        "critical_security": ["honeypot", "blacklist", "riesgo critico"],
        "boosted_or_trending": ["boost", "trending"],
    }
    for feature, needles in keyword_features.items():
        if any(needle in text for needle in needles):
            features.add(feature)

    return sorted(feature for feature in features if feature)


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, list):
            return " ".join(str(item) for item in parsed)
        return str(parsed)
    return str(value)


def _bucket(name: str, value: float, cutoffs: list[float]) -> str:
    previous = "-inf"
    for cutoff in cutoffs:
        if value < cutoff:
            return f"{name}:{previous}-{cutoff}"
        previous = str(cutoff)
    return f"{name}:{cutoffs[-1]}+"


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
