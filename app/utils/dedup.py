from app.database.models import TokenSnapshot


def should_send_deduped_alert(
    latest_alert: dict | None,
    alert_type: str,
    score: int,
    risk_level: str,
    snapshot: TokenSnapshot,
    estimated_gain_pct: float | None = None,
) -> tuple[bool, str]:
    if latest_alert is None:
        return True, "Sin alerta reciente para este token y tipo."

    previous_score = int(latest_alert.get("score") or 0)
    previous_risk = str(latest_alert.get("risk_level") or "")

    if alert_type == "SECURITY_RISK" and previous_risk != "critical":
        return True, "El tipo cambió a SECURITY_RISK."

    if risk_level == "critical" and previous_risk != "critical":
        return True, "El riesgo cambió a crítico."

    if alert_type == "POSSIBLE_HONEYPOT" and previous_risk != "critical":
        return True, "Apareció posible honeypot."

    if score - previous_score >= 20:
        return True, "El score subió más de 20 puntos."

    previous_estimated_gain = float(latest_alert.get("estimated_gain_pct") or 0)
    if (
        estimated_gain_pct is not None
        and previous_estimated_gain > 0
        and estimated_gain_pct - previous_estimated_gain >= 250
    ):
        return True, "La subida estimada mejoró al menos 250 puntos porcentuales."

    previous_liquidity = float(latest_alert.get("liquidity_usd") or 0)
    current_liquidity = snapshot.liquidity_usd or 0
    if previous_liquidity > 0 and current_liquidity >= previous_liquidity * 3:
        return True, "La liquidez subió de forma extraordinaria."

    previous_volume = float(latest_alert.get("volume_1h") or 0)
    current_volume = snapshot.volume_1h or 0
    if previous_volume > 0 and current_volume >= previous_volume * 3:
        return True, "El volumen subió de forma extraordinaria."

    return False, "Alerta duplicada dentro de la ventana configurada."
