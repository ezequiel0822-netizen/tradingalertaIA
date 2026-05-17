from app.database.models import EstimateResult, SecuritySummary, TokenSnapshot
from app.database.models import AlertRecord


def _money(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 0.01:
        return f"{value:.10f}"
    return f"{value:,.2f}"


def _percent(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:,.2f}%"


def _value(value: object | None) -> str:
    if value is None or value == "":
        return "unknown"
    return str(value)


def format_telegram_alert(
    alert_type: str,
    snapshot: TokenSnapshot,
    score: int,
    risk_level: str,
    reasons: list[str],
    security: SecuritySummary,
    estimate: EstimateResult,
    app_version: str,
) -> str:
    short_comment = _short_comment(alert_type, snapshot, security, estimate, app_version)
    formatted_reasons = "\n".join(f"- {reason}" for reason in reasons[:5])
    title = "ALERTA BOLSA" if snapshot.category == "stock" else "ALERTA TOKEN / MEMECOIN"
    address_label = "Ticker" if snapshot.category == "stock" else "Address"

    return f"""🚨 Trading Alert AI {app_version} / {title}

Tipo: {alert_type}
Token: {_value(snapshot.symbol)} / {_value(snapshot.name)}
Chain: {_value(snapshot.chain)}
{address_label}: {_value(snapshot.token_address)}
Fuente: {_value(snapshot.source)}

Precio: ${_money(snapshot.price)}
Liquidez: ${_money(snapshot.liquidity_usd)}
Volumen 5m: ${_money(snapshot.volume_5m)}
Volumen 1h: ${_money(snapshot.volume_1h)}
Score: {score}/100
Riesgo: {risk_level}

Estimación IA:
- Subida estimada: {_percent(estimate.estimated_gain_pct)}
- Caída estimada: {_percent(estimate.estimated_loss_pct)}
- Confianza: {estimate.confidence}/100
- Modo: {_value(estimate.label)}

Motivo:
{formatted_reasons}

Seguridad:
- Honeypot: {_value(security.honeypot_status)}
- Buy tax: {_value(security.buy_tax)}
- Sell tax: {_value(security.sell_tax)}
- Ownership: {_value(security.owner_status)}
- Contrato sospechoso: {_value(security.contract_risk)}

Comentario:
{short_comment}

⚠️ No es recomendación financiera. Es una estimación heurística con datos públicos; revisar manualmente antes de tomar cualquier decisión."""


def _short_comment(
    alert_type: str,
    snapshot: TokenSnapshot,
    security: SecuritySummary,
    estimate: EstimateResult,
    app_version: str,
) -> str:
    if snapshot.category == "stock" and estimate.eligible_for_gain_alert:
        return f"Alerta {app_version} bolsa: entra al ranking de mejores movimientos con cupo diario limitado."
    if estimate.eligible_for_gain_alert:
        return f"Alerta {app_version} memecoin: potencial estimado >= 500% y entra al ranking diario limitado."
    if security.is_critical:
        return "Riesgo crítico detectado. Revisar contrato y datos públicos antes de cualquier acción."
    if alert_type == "BOOSTED_TOKEN":
        return "Token boosted detectado. Un boost puede ser hype pagado; conviene revisar manualmente."
    if alert_type == "TRENDING_POOL":
        return "Pool trending detectado con actividad reciente. Revisar liquidez, volumen y contrato."
    if alert_type == "VOLUME_SPIKE":
        return "Volumen inusual detectado. Verificar si hay actividad orgánica o manipulación."
    if alert_type == "LIQUIDITY_SPIKE":
        return "Liquidez creciente detectada. Revisar si el movimiento se sostiene."
    if alert_type == "PRICE_SPIKE":
        return "Movimiento fuerte de precio detectado. Revisar volatilidad y liquidez."
    if snapshot.is_new:
        return "Token o perfil reciente detectado. Interesante para revisar, pero con riesgo alto por novedad."
    return "Evento guardado para historial y seguimiento."


def format_grouped_telegram_alert(
    records: list[AlertRecord],
    category: str,
    app_version: str,
) -> str:
    title = "TOP BOLSA" if category == "stock" else "TOP MEMECOINS"
    lines = [f"🚨 Trading Alert AI {app_version} / {title}", ""]
    lines.append(f"Señales seleccionadas: {len(records)}")
    lines.append("")

    for index, record in enumerate(records, start=1):
        snapshot = record.snapshot
        top_reason = record.reasons[0] if record.reasons else "Candidato rankeado por el sistema."
        lines.extend(
            [
                f"{index}. {_value(snapshot.symbol)} / {_value(snapshot.name)}",
                f"Tipo: {record.alert_type}",
                f"Chain/Fuente: {_value(snapshot.chain)} / {_value(snapshot.source)}",
                f"Precio: ${_money(snapshot.price)}",
                f"Subida est.: {_percent(record.estimate.estimated_gain_pct)} | Caída est.: {_percent(record.estimate.estimated_loss_pct)}",
                f"Confianza: {record.estimate.confidence}/100 | Score: {record.score}/100",
                f"Motivo: {top_reason}",
                "",
            ]
        )

    lines.append("⚠️ No es recomendación financiera. Son señales para revisión manual.")
    return "\n".join(lines)
