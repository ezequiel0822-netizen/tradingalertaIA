from dataclasses import dataclass

from app.analyzers.technical_patterns import TechnicalPattern
from app.database.models import SecuritySummary, TokenSnapshot


@dataclass
class ProfessionalAnalysis:
    label: str
    score: int
    confidence: int
    setup: str
    bias: str
    reasons: list[str]
    risks: list[str]
    checklist: list[str]


def analyze_professional_setup(
    snapshot: TokenSnapshot,
    security: SecuritySummary,
    pattern: TechnicalPattern | None,
    news_label: str = "no_recent_news",
    news_score: int = 0,
    filing_label: str = "no_recent_filings",
    filing_score: int = 0,
) -> ProfessionalAnalysis:
    score = 0
    confidence = 20
    reasons: list[str] = []
    risks: list[str] = []
    checklist: list[str] = []

    if pattern:
        score += int(pattern.score * 0.9)
        confidence += 20
        reasons.append(f"Grafico: {pattern.label}, tendencia {pattern.trend}, score {pattern.score}.")
        if pattern.relative_volume and pattern.relative_volume >= 2:
            reasons.append(f"Volumen relativo {pattern.relative_volume}x.")
            confidence += 8
        if pattern.atr_pct and pattern.atr_pct >= 6:
            risks.append(f"Volatilidad alta: ATR {pattern.atr_pct}%.")
        if pattern.support is not None and pattern.resistance is not None:
            checklist.append(
                f"Zona tecnica: soporte {pattern.support:g}, resistencia {pattern.resistance:g}."
            )

    if news_score:
        score += news_score
        confidence += 12
        reasons.append(f"Noticias: {news_label}, score {news_score}.")
    elif snapshot.category == "stock":
        risks.append("Sin catalizador reciente claro en titulares.")

    if filing_score:
        score += filing_score
        confidence += 10
        reasons.append(f"SEC/filings: {filing_label}, score {filing_score}.")

    if snapshot.category == "memecoin":
        score += _memecoin_microstructure_score(snapshot, reasons, risks)
        confidence += 8 if snapshot.liquidity_usd and snapshot.volume_1h else 0
        if security.raw_summary == "unknown":
            risks.append("Seguridad unknown: revisar contrato antes de confiar.")
        if security.is_critical:
            score -= 80
            confidence = min(confidence, 25)
            risks.append("Riesgo critico de contrato.")
    else:
        score += _stock_structure_score(snapshot, reasons, risks)

    if snapshot.price_change_1h is not None and snapshot.price_change_1h < -3:
        risks.append("Presion bajista intradia detectada.")
        score -= 8
    if snapshot.price_change_1h is not None and snapshot.price_change_1h > 6:
        risks.append("Movimiento ya extendido: evitar perseguir vela tardia.")
        score -= 4

    if not checklist:
        checklist.append("Esperar confirmacion con volumen y cierre de vela.")
    checklist.append("Revisar manualmente liquidez, catalizador y riesgo antes de actuar.")

    final_score = max(-100, min(100, score))
    confidence = max(0, min(100, confidence))
    bias = _bias(final_score)
    label = _label(final_score, confidence, risks)
    setup = _setup(snapshot, pattern, news_label, filing_label)

    return ProfessionalAnalysis(
        label=label,
        score=final_score,
        confidence=confidence,
        setup=setup,
        bias=bias,
        reasons=reasons[:6] or ["Sin confluencia profesional suficiente."],
        risks=risks[:5] or ["Riesgo normal de mercado; confirmar manualmente."],
        checklist=checklist[:4],
    )


def _memecoin_microstructure_score(
    snapshot: TokenSnapshot,
    reasons: list[str],
    risks: list[str],
) -> int:
    score = 0
    liquidity = snapshot.liquidity_usd or 0
    volume_1h = snapshot.volume_1h or 0
    if liquidity >= 50_000:
        score += 14
        reasons.append("Liquidez util para seguimiento intradia.")
    elif liquidity < 10_000:
        score -= 18
        risks.append("Liquidez baja: riesgo alto de slippage/manipulacion.")

    if liquidity > 0:
        volume_ratio = volume_1h / liquidity
        if 0.5 <= volume_ratio <= 4:
            score += 16
            reasons.append("Volumen fuerte pero aun razonable contra liquidez.")
        elif volume_ratio > 8:
            score -= 16
            risks.append("Volumen demasiado alto contra liquidez: posible wash trading.")

    buys = snapshot.buys_1h or 0
    sells = snapshot.sells_1h or 0
    if buys + sells >= 50:
        score += 8
        if buys > sells * 1.5:
            score += 8
            reasons.append("Compras dominan ventas en actividad reciente.")
    return score


def _stock_structure_score(
    snapshot: TokenSnapshot,
    reasons: list[str],
    risks: list[str],
) -> int:
    score = 0
    volume_1h = snapshot.volume_1h or 0
    if volume_1h >= 50_000_000:
        score += 12
        reasons.append("Volumen institucional intradia fuerte.")
    elif volume_1h < 1_000_000:
        score -= 10
        risks.append("Volumen bajo para lectura confiable.")

    if snapshot.price_change_24h is not None:
        if 1 <= snapshot.price_change_24h <= 7:
            score += 8
            reasons.append("Movimiento diario positivo sin extension extrema.")
        elif snapshot.price_change_24h > 12:
            score -= 8
            risks.append("Movimiento diario demasiado extendido.")
    return score


def _bias(score: int) -> str:
    if score >= 45:
        return "bullish"
    if score <= -25:
        return "bearish"
    return "neutral"


def _label(score: int, confidence: int, risks: list[str]) -> str:
    if score >= 55 and confidence >= 65:
        return "pro_high_conviction"
    if score >= 30:
        return "pro_watchlist"
    if score <= -30:
        return "pro_risk_off"
    if any("critico" in risk.lower() for risk in risks):
        return "pro_security_block"
    return "pro_neutral"


def _setup(
    snapshot: TokenSnapshot,
    pattern: TechnicalPattern | None,
    news_label: str,
    filing_label: str,
) -> str:
    pieces = [snapshot.category]
    if pattern:
        pieces.append(pattern.label)
    if news_label not in {"no_recent_news", "neutral_news"}:
        pieces.append(news_label)
    if filing_label not in {"no_recent_filings", "filing_watch"}:
        pieces.append(filing_label)
    return " + ".join(pieces)
