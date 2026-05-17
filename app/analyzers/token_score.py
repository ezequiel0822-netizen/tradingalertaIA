from app.config.settings import Settings
from app.analyzers.alert_decision_engine import risk_level_for_score
from app.database.models import ScoreResult, SecuritySummary, TokenSnapshot
from app.utils.time_utils import age_hours_from_iso


def score_token(
    snapshot: TokenSnapshot,
    security: SecuritySummary,
    settings: Settings,
) -> ScoreResult:
    score = 0
    reasons: list[str] = []

    liquidity_points, liquidity_reasons = _liquidity_points(snapshot, settings)
    score += liquidity_points
    reasons.extend(liquidity_reasons)

    volume_points, volume_reasons = _volume_points(snapshot, settings)
    score += volume_points
    reasons.extend(volume_reasons)

    age_points, age_reasons = _age_points(snapshot)
    score += age_points
    reasons.extend(age_reasons)

    boost_points, boost_reasons = _boost_trending_points(snapshot)
    score += boost_points
    reasons.extend(boost_reasons)

    security_points, security_reasons = _security_points(security)
    score += security_points
    reasons.extend(security_reasons)

    activity_points, activity_reasons = _activity_points(snapshot)
    score += activity_points
    reasons.extend(activity_reasons)

    if (snapshot.volume_1h or 0) >= settings.min_volume_1h_usd and (
        snapshot.liquidity_usd or 0
    ) < settings.min_liquidity_usd:
        score = max(score - 12, 0)
        reasons.append("Volumen alto con liquidez baja: posible señal de riesgo.")

    score = max(0, min(100, int(round(score))))
    risk_level = risk_level_for_score(score, security.is_critical)
    return ScoreResult(
        score=score,
        risk_level=risk_level,
        reasons=reasons[:8] or ["Datos insuficientes; se guarda para historial."],
        critical_risk=security.is_critical,
    )


def _liquidity_points(
    snapshot: TokenSnapshot, settings: Settings
) -> tuple[int, list[str]]:
    liquidity = snapshot.liquidity_usd
    if liquidity is None:
        return 4, ["Liquidez no disponible."]
    if liquidity < 1_000:
        return 0, ["Liquidez extremadamente baja."]
    if liquidity < settings.min_liquidity_usd:
        return 5, ["Liquidez por debajo del mínimo configurado."]
    if liquidity < 50_000:
        return 12, ["Liquidez aceptable para monitoreo inicial."]
    if liquidity < 250_000:
        return 16, ["Liquidez media detectada."]
    return 20, ["Liquidez alta detectada."]


def _volume_points(snapshot: TokenSnapshot, settings: Settings) -> tuple[int, list[str]]:
    points = 0
    reasons: list[str] = []
    if (snapshot.volume_5m or 0) >= settings.min_volume_5m_usd:
        points += 8
        reasons.append("Volumen 5m relevante.")
    if (snapshot.volume_1h or 0) >= settings.min_volume_1h_usd:
        points += 9
        reasons.append("Volumen 1h relevante.")
    if (snapshot.volume_24h or 0) >= settings.min_volume_1h_usd * 4:
        points += 8
        reasons.append("Volumen 24h fuerte.")
    if points == 0:
        reasons.append("Volumen bajo o no disponible.")
    return min(points, 25), reasons


def _age_points(snapshot: TokenSnapshot) -> tuple[int, list[str]]:
    if snapshot.is_new:
        return 8, ["Perfil reciente detectado."]
    age_hours = age_hours_from_iso(snapshot.pool_created_at)
    if age_hours is None:
        return 4, ["Edad del pool no disponible."]
    if age_hours <= 6:
        return 8, ["Pool muy nuevo: interesante, pero riesgoso."]
    if age_hours <= 24:
        return 7, ["Pool creado en las últimas 24h."]
    if age_hours <= 7 * 24:
        return 5, ["Pool creado durante la última semana."]
    return 3, ["Pool no es nuevo."]


def _boost_trending_points(snapshot: TokenSnapshot) -> tuple[int, list[str]]:
    points = 0
    reasons: list[str] = []
    if snapshot.is_boosted:
        points += 6
        reasons.append("Token boosted; puede ser hype pagado.")
    if snapshot.is_trending:
        points += 4
        reasons.append("Pool aparece como trending.")
    return points, reasons


def _security_points(security: SecuritySummary) -> tuple[int, list[str]]:
    if security.is_critical:
        return 0, ["Riesgo crítico detectado por análisis de seguridad."]
    unknown_summaries = {
        "unknown",
        "GoPlus request failed",
        "GoPlus returned no data",
        "GoPlus unavailable for this chain",
    }
    if security.raw_summary in unknown_summaries or security.contract_risk == "unknown":
        return 12, ["Seguridad unknown; GoPlus no dio datos concluyentes."]
    if security.contract_risk == "risky":
        return 8, ["Contrato con señales sospechosas."]
    return 25, ["Sin riesgo crítico detectado por GoPlus."]


def _activity_points(snapshot: TokenSnapshot) -> tuple[int, list[str]]:
    buys = (snapshot.buys_5m or 0) + (snapshot.buys_1h or 0)
    sells = (snapshot.sells_5m or 0) + (snapshot.sells_1h or 0)
    activity = buys + sells
    if activity >= 100:
        return 10, ["Actividad reciente alta."]
    if activity >= 25:
        return 7, ["Actividad reciente moderada."]
    if activity > 0:
        return 4, ["Actividad reciente baja."]
    return 2, ["Actividad reciente unknown."]
