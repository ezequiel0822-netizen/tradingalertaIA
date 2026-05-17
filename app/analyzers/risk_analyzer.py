from app.database.models import SecuritySummary


def security_reasons(security: SecuritySummary) -> list[str]:
    reasons: list[str] = []
    if security.honeypot_status == "possible_honeypot":
        reasons.append("GoPlus marca posible honeypot.")
    if security.blacklist_risk == "risky":
        reasons.append("El contrato muestra riesgo de blacklist.")
    if security.owner_status == "risky":
        reasons.append("La propiedad del contrato tiene señales de riesgo.")
    if security.mint_risk == "risky":
        reasons.append("El contrato podría permitir mint adicional.")
    if security.contract_risk == "risky":
        reasons.append("El contrato tiene señales sospechosas.")
    if security.buy_tax is not None and security.buy_tax >= 20:
        reasons.append(f"Buy tax alto: {security.buy_tax:.2f}%.")
    if security.sell_tax is not None and security.sell_tax >= 20:
        reasons.append(f"Sell tax alto: {security.sell_tax:.2f}%.")
    if not reasons and security.raw_summary == "unknown":
        reasons.append("Seguridad no disponible para este token.")
    return reasons
