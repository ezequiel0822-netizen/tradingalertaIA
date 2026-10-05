from app.config.settings import Settings
from app.database.models import EstimateResult, SecuritySummary, TokenSnapshot

# v3.13.2 — umbrales de "movimiento notable" (|variación %|) para forex y oro: un
# par mayor rara vez se mueve 0.5 % en una hora o 1.5 % en un día; el oro es ~2x más
# volátil. Solo deciden si la observación merece una alerta; NO son una predicción.
FX_NOTABLE_MOVE_PCT = {
    "forex": {"1h": 0.5, "24h": 1.5},
    "gold": {"1h": 1.0, "24h": 2.5},
}


def estimate_move(
    snapshot: TokenSnapshot,
    security: SecuritySummary,
    score: int,
    settings: Settings,
) -> EstimateResult:
    if snapshot.category == "stock":
        return _estimate_stock_move(snapshot, score, settings)
    if snapshot.category in FX_NOTABLE_MOVE_PCT:
        return _estimate_fx_move(snapshot)

    liquidity = snapshot.liquidity_usd or 0
    volume_5m = snapshot.volume_5m or 0
    volume_1h = snapshot.volume_1h or 0
    volume_24h = snapshot.volume_24h or 0
    reasons: list[str] = []

    gain = 0.0
    if liquidity <= 0:
        reasons.append("No hay liquidez suficiente para estimar con confianza.")
    else:
        volume_liquidity_5m = volume_5m / liquidity
        volume_liquidity_1h = volume_1h / liquidity
        volume_liquidity_24h = volume_24h / liquidity
        gain += min(volume_liquidity_5m * 900, 650)
        gain += min(volume_liquidity_1h * 360, 850)
        gain += min(volume_liquidity_24h * 60, 500)

        if volume_liquidity_1h >= 1:
            reasons.append("Volumen 1h iguala o supera la liquidez: momentum fuerte.")
        elif volume_liquidity_1h >= 0.35:
            reasons.append("Volumen 1h relevante frente a la liquidez.")

    positive_5m = max(snapshot.price_change_5m or 0, 0)
    positive_1h = max(snapshot.price_change_1h or 0, 0)
    positive_24h = max(snapshot.price_change_24h or 0, 0)
    gain += min(positive_5m * 8, 260)
    gain += min(positive_1h * 4, 320)
    gain += min(positive_24h * 1.2, 260)

    if positive_5m >= 15 or positive_1h >= 25:
        reasons.append("Precio ya muestra impulso fuerte en ventanas cortas.")

    if snapshot.is_trending:
        gain += 140
        reasons.append("Pool aparece en trending.")
    if snapshot.is_boosted:
        gain += 80
        reasons.append("Token boosted; esto puede ser hype pagado.")
    if snapshot.is_new:
        gain += 90
        reasons.append("Token/perfil reciente detectado.")

    activity = (
        (snapshot.buys_5m or 0)
        + (snapshot.sells_5m or 0)
        + (snapshot.buys_1h or 0)
        + (snapshot.sells_1h or 0)
    )
    if activity >= 100:
        gain += 120
        reasons.append("Actividad reciente alta.")
    elif activity >= 25:
        gain += 70
        reasons.append("Actividad reciente moderada.")

    loss = _estimate_loss_pct(snapshot, security, settings)
    confidence = _estimate_confidence(snapshot, security, settings)

    if security.is_critical:
        gain *= 0.15
        confidence = min(confidence, 25)
        reasons.append("Riesgo crítico: se reduce el potencial estimado.")
    elif security.contract_risk == "risky":
        gain *= 0.55
        confidence = min(confidence, 45)
        reasons.append("Contrato sospechoso: estimación penalizada.")

    hype_penalty = _anti_hype_penalty(snapshot, security, settings)
    if hype_penalty:
        gain *= hype_penalty[0]
        confidence = max(confidence - hype_penalty[1], 0)
        reasons.extend(hype_penalty[2])

    if liquidity < settings.min_liquidity_usd:
        gain *= 0.7
        reasons.append("Liquidez bajo mínimo: estimación penalizada.")

    if score < settings.alert_score_threshold:
        gain *= 0.85
        reasons.append("Score bajo el umbral general: estimación conservadora.")

    estimated_gain = round(max(0, min(gain, 2500)), 2)
    eligible = (
        estimated_gain >= settings.min_estimated_gain_pct
        and confidence >= settings.min_estimate_confidence
        and not security.is_critical
    )

    label = "high-conviction" if eligible else "watch-only"
    return EstimateResult(
        estimated_gain_pct=estimated_gain,
        estimated_loss_pct=round(loss, 2),
        confidence=confidence,
        label=label,
        reasons=reasons[:8] or ["Sin señales suficientes para estimar una subida grande."],
        eligible_for_gain_alert=eligible,
    )


def _anti_hype_penalty(
    snapshot: TokenSnapshot,
    security: SecuritySummary,
    settings: Settings,
) -> tuple[float, int, list[str]] | None:
    if snapshot.category != "memecoin":
        return None

    reasons: list[str] = []
    multiplier = 1.0
    confidence_penalty = 0
    liquidity = snapshot.liquidity_usd or 0
    volume_1h = snapshot.volume_1h or 0
    price_24h = snapshot.price_change_24h or 0
    price_1h = snapshot.price_change_1h or 0
    is_hype_surface = snapshot.is_boosted or snapshot.is_trending

    if is_hype_surface and liquidity < settings.min_liquidity_usd:
        multiplier *= 0.65
        confidence_penalty += 12
        reasons.append("Filtro anti-hype: boost/trending con liquidez baja.")

    if is_hype_surface and security.contract_risk == "unknown":
        multiplier *= 0.8
        confidence_penalty += 8
        reasons.append("Filtro anti-hype: seguridad unknown en token con hype.")

    if price_24h >= 300 or price_1h >= 120:
        multiplier *= 0.72
        confidence_penalty += 10
        reasons.append("Filtro anti-hype: el precio ya subió demasiado; riesgo de entrada tardía.")

    if liquidity > 0 and volume_1h / liquidity >= 8:
        multiplier *= 0.75
        confidence_penalty += 8
        reasons.append("Filtro anti-hype: volumen muy alto contra liquidez, posible actividad artificial.")

    if multiplier == 1.0:
        return None
    return multiplier, confidence_penalty, reasons[:4]


def _estimate_stock_move(
    snapshot: TokenSnapshot,
    score: int,
    settings: Settings,
) -> EstimateResult:
    reasons: list[str] = []
    change_15m = snapshot.price_change_5m or 0
    change_1h = snapshot.price_change_1h or 0
    change_24h = snapshot.price_change_24h or 0
    dollar_volume_1h = snapshot.volume_1h or 0
    dollar_volume_24h = snapshot.volume_24h or 0

    gain = 0.0
    gain += max(change_15m, 0) * 1.5
    gain += max(change_1h, 0) * 2.2
    gain += max(change_24h, 0) * 0.8

    if change_1h >= 2:
        gain += 4
        reasons.append("Momentum alcista fuerte en la ultima hora.")
    if change_24h >= 5:
        gain += 5
        reasons.append("Movimiento alcista relevante en 24h.")
    if dollar_volume_1h >= 50_000_000:
        gain += 5
        reasons.append("Volumen en dolares fuerte durante la ultima hora.")
    elif dollar_volume_1h >= 10_000_000:
        gain += 3
        reasons.append("Volumen en dolares relevante durante la ultima hora.")
    if dollar_volume_24h >= 500_000_000:
        gain += 3
        reasons.append("Alta liquidez/volumen para bolsa.")

    loss = 20.0
    if change_1h < 0:
        loss += min(abs(change_1h) * 4, 25)
        reasons.append("Presion bajista reciente detectada.")
    if change_24h < 0:
        loss += min(abs(change_24h) * 2, 30)
    if dollar_volume_1h <= 1_000_000:
        loss += 15
        reasons.append("Volumen bajo para una alerta de bolsa.")

    confidence = 35
    if snapshot.price is not None:
        confidence += 10
    if snapshot.price_change_1h is not None:
        confidence += 15
    if snapshot.price_change_24h is not None:
        confidence += 15
    if dollar_volume_1h >= 10_000_000:
        confidence += 15
    if dollar_volume_24h >= 100_000_000:
        confidence += 10
    if score >= settings.alert_score_threshold:
        confidence += 5

    estimated_gain = round(max(0, min(gain, 80)), 2)
    estimated_loss = round(max(0, min(loss, 100)), 2)
    confidence = max(0, min(confidence, 100))
    eligible = (
        estimated_gain >= settings.min_stock_estimated_gain_pct
        and confidence >= settings.min_stock_estimate_confidence
    )

    return EstimateResult(
        estimated_gain_pct=estimated_gain,
        estimated_loss_pct=estimated_loss,
        confidence=confidence,
        label="high-conviction-stock" if eligible else "stock-watch-only",
        reasons=reasons[:8] or ["Sin momentum suficiente para alerta de bolsa."],
        eligible_for_gain_alert=eligible,
    )


def _estimate_fx_move(snapshot: TokenSnapshot) -> EstimateResult:
    """v3.13.2: forex/oro. Antes caían en el estimador de MEMECOINS: sin "liquidez de
    pool" le asignaba caída estimada 90 % y confianza 25 a EURUSD. El bot no tiene un
    modelo con edge para forex/oro (24 familias probadas), así que NO inventa subidas
    ni caídas: reporta el movimiento OBSERVADO y marca elegible para alerta solo un
    movimiento notable para ese mercado. La confianza mide completitud de datos."""
    thresholds = FX_NOTABLE_MOVE_PCT[snapshot.category]
    change_1h = snapshot.price_change_1h
    change_24h = snapshot.price_change_24h
    notable = (change_1h is not None and abs(change_1h) >= thresholds["1h"]) or (
        change_24h is not None and abs(change_24h) >= thresholds["24h"]
    )
    reasons: list[str] = []
    if notable:
        market = "el oro" if snapshot.category == "gold" else "un par de divisas"
        reasons.append(f"Movimiento notable para {market}.")
    if change_1h is not None:
        reasons.append(f"Movimiento 1h: {change_1h:+.2f}%")
    if change_24h is not None:
        reasons.append(f"Movimiento 24h: {change_24h:+.2f}%")
    if not notable:
        reasons.append(
            "Sin movimiento notable. El bot no estima subidas/caídas en forex/oro "
            "(no tiene un modelo con edge)."
        )
    confidence = 35
    if snapshot.price is not None:
        confidence += 10
    if change_1h is not None:
        confidence += 15
    if change_24h is not None:
        confidence += 15
    return EstimateResult(
        estimated_gain_pct=0.0,
        estimated_loss_pct=0.0,
        confidence=confidence,
        label="fx-movimiento-notable" if notable else "fx-observacion",
        reasons=reasons,
        eligible_for_gain_alert=notable,
    )


def _estimate_loss_pct(
    snapshot: TokenSnapshot,
    security: SecuritySummary,
    settings: Settings,
) -> float:
    if security.is_critical:
        return 95

    liquidity = snapshot.liquidity_usd or 0
    loss = 35.0
    if liquidity <= 0:
        loss = 90
    elif liquidity < 1_000:
        loss = 85
    elif liquidity < settings.min_liquidity_usd:
        loss = 70

    if security.contract_risk == "risky":
        loss = max(loss, 80)
    if security.sell_tax is not None and security.sell_tax >= 20:
        loss = max(loss, 85)
    if security.buy_tax is not None and security.buy_tax >= 20:
        loss = max(loss, 75)

    negative_5m = abs(min(snapshot.price_change_5m or 0, 0))
    negative_1h = abs(min(snapshot.price_change_1h or 0, 0))
    loss += min(negative_5m * 1.2, 15)
    loss += min(negative_1h * 0.8, 20)

    if (snapshot.volume_1h or 0) >= settings.min_volume_1h_usd and liquidity < settings.min_liquidity_usd:
        loss += 12

    return max(0, min(loss, 100))


def _estimate_confidence(
    snapshot: TokenSnapshot,
    security: SecuritySummary,
    settings: Settings,
) -> int:
    confidence = 15
    if snapshot.liquidity_usd is not None:
        confidence += 12
    if (snapshot.liquidity_usd or 0) >= settings.min_liquidity_usd:
        confidence += 12
    if snapshot.volume_1h is not None:
        confidence += 12
    if snapshot.volume_5m is not None:
        confidence += 8
    if snapshot.price_change_1h is not None:
        confidence += 10
    if (snapshot.buys_1h is not None) or (snapshot.sells_1h is not None):
        confidence += 8
    if security.raw_summary not in {
        "unknown",
        "GoPlus request failed",
        "GoPlus returned no data",
        "GoPlus unavailable for this chain",
    }:
        confidence += 13
    if snapshot.is_trending:
        confidence += 5
    if security.is_critical:
        confidence -= 35

    return max(0, min(confidence, 100))
