from dataclasses import dataclass

from app.config.settings import Settings
from app.database.models import EstimateResult, TokenSnapshot


@dataclass
class TradeReadiness:
    grade: str
    score: int
    thesis: str
    entry_zone: str
    stop_loss: float | None
    take_profit_1: float | None
    take_profit_2: float | None
    invalidation: str
    checklist: list[str]
    blocked: bool = False


def build_trade_readiness(
    snapshot: TokenSnapshot,
    estimate: EstimateResult,
    score: int,
    risk_level: str,
    settings: Settings,
    reasons: list[str] | None = None,
) -> TradeReadiness:
    price = snapshot.price
    confidence = estimate.confidence
    reasons = reasons or []
    readiness = 0

    if score >= settings.readiness_min_score:
        readiness += 25
    else:
        readiness += max(0, int(score * 0.25))
    if confidence >= settings.readiness_min_confidence:
        readiness += 25
    else:
        readiness += max(0, int(confidence * 0.25))
    if estimate.eligible_for_gain_alert:
        readiness += 20
    if any("IA Pro" in reason or "pro_high_conviction" in reason for reason in reasons):
        readiness += 15
    if any("Riesgo pro" in reason or "anti-hype" in reason for reason in reasons):
        readiness -= 12
    if risk_level == "critical":
        return _blocked(snapshot, price, "Riesgo critico: no simular entrada.")

    if price is None or price <= 0:
        return _blocked(snapshot, price, "Sin precio valido para construir plan.")

    readiness = max(0, min(100, readiness))
    grade = _grade(readiness)
    entry_zone = _entry_zone(price, snapshot.category)
    stop_loss = _stop_loss(price, estimate, snapshot.category)
    take_profit_1, take_profit_2 = _targets(price, estimate, snapshot.category)
    invalidation = _invalidation(snapshot, risk_level, stop_loss)
    thesis = (
        f"{snapshot.symbol}: setup {grade}, score {score}/100, "
        f"confianza {confidence}/100, subida estimada {estimate.estimated_gain_pct:.2f}%."
    )
    checklist = [
        "Confirmar volumen y cierre de vela antes de cualquier accion manual.",
        "Revisar noticias/catalizador y liquidez actual.",
        "No aumentar riesgo si la tesis queda invalidada.",
        "Registrar resultado para aprendizaje.",
    ]
    return TradeReadiness(
        grade=grade,
        score=readiness,
        thesis=thesis,
        entry_zone=entry_zone,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        invalidation=invalidation,
        checklist=checklist,
    )


def _blocked(snapshot: TokenSnapshot, price: float | None, reason: str) -> TradeReadiness:
    return TradeReadiness(
        grade="BLOCKED",
        score=0,
        thesis=f"{snapshot.symbol}: bloqueado. {reason}",
        entry_zone="N/A",
        stop_loss=None,
        take_profit_1=None,
        take_profit_2=None,
        invalidation=reason,
        checklist=["No simular trade en este activo.", "Guardar solo para aprendizaje."],
        blocked=True,
    )


def _grade(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def _entry_zone(price: float, category: str) -> str:
    wiggle = 0.01 if category == "stock" else 0.03
    low = price * (1 - wiggle)
    high = price * (1 + wiggle)
    return f"{low:.8g} - {high:.8g}"


def _stop_loss(price: float, estimate: EstimateResult, category: str) -> float:
    if category == "stock":
        loss_pct = min(max(estimate.estimated_loss_pct, 3), 12)
    else:
        loss_pct = min(max(estimate.estimated_loss_pct, 20), 70)
    return round(price * (1 - loss_pct / 100), 10)


def _targets(
    price: float,
    estimate: EstimateResult,
    category: str,
) -> tuple[float, float]:
    if category == "stock":
        first = min(max(estimate.estimated_gain_pct * 0.4, 2), 12)
        second = min(max(estimate.estimated_gain_pct, 4), 30)
    else:
        first = min(max(estimate.estimated_gain_pct * 0.25, 30), 300)
        second = min(max(estimate.estimated_gain_pct * 0.75, 80), 1000)
    return round(price * (1 + first / 100), 10), round(price * (1 + second / 100), 10)


def _invalidation(snapshot: TokenSnapshot, risk_level: str, stop_loss: float | None) -> str:
    pieces = []
    if stop_loss is not None:
        pieces.append(f"perder stop simulado {stop_loss:g}")
    if risk_level in {"red", "critical"}:
        pieces.append(f"riesgo {risk_level}")
    if snapshot.category == "memecoin":
        pieces.append("liquidez cae o contrato marca riesgo")
    else:
        pieces.append("noticia/catalizador cambia a negativo")
    return "; ".join(pieces)
