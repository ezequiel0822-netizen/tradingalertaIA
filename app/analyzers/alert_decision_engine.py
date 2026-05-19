from app.config.settings import Settings
from app.database.models import EstimateResult, SecuritySummary, TokenSnapshot


ALERT_PRIORITY = {
    "POSSIBLE_HONEYPOT": 100,
    "SECURITY_RISK": 95,
    "STOCK_DROP_RISK": 88,
    "STOCK_BREAKOUT": 84,
    "PRICE_SPIKE": 80,
    "VOLUME_SPIKE": 75,
    "LIQUIDITY_SPIKE": 70,
    "BOOSTED_TOKEN": 65,
    "TRENDING_POOL": 60,
    "NEW_TOKEN": 55,
    "WATCHLIST_MOVEMENT": 10,
    "STOCK_MOVEMENT": 10,
}


def risk_level_for_score(score: int, critical_risk: bool = False) -> str:
    if critical_risk:
        return "critical"
    if score >= 90:
        return "red"
    if score >= 80:
        return "orange"
    if score >= 65:
        return "yellow"
    if score >= 40:
        return "watch"
    return "low"


def should_send_alert(
    score: int,
    critical_risk: bool,
    estimate: EstimateResult,
    settings: Settings,
    category: str = "memecoin",
) -> bool:
    # Forex/oro acumulan snapshots para aprendizaje pero no alertan en Fase 2.
    # Fase 3 construye el modulo de analisis especifico (price action, sesiones, calendario).
    if category in {"forex", "gold"}:
        return False
    # Memecoins quedan como lab de aprendizaje desde Fase 2.5: alimentan
    # strategy_lessons y outcomes por horizonte pero NO van a Telegram salvo
    # que el usuario active explicitamente el flag.
    if category == "memecoin" and not settings.enable_memecoin_telegram:
        return False
    if category == "stock":
        return estimate.eligible_for_gain_alert
    if estimate.eligible_for_gain_alert:
        return True
    if (
        critical_risk
        and settings.critical_risk_alerts
        and settings.alert_critical_risks_without_gain
    ):
        return True
    return False


def candidate_for_security_check(snapshot: TokenSnapshot, settings: Settings) -> bool:
    if snapshot.category in {"stock", "forex", "gold"}:
        return False
    if snapshot.event_type in {"BOOSTED_TOKEN", "TRENDING_POOL", "NEW_TOKEN"}:
        return True
    if (snapshot.liquidity_usd or 0) >= settings.min_liquidity_usd:
        return True
    if (snapshot.volume_5m or 0) >= settings.min_volume_5m_usd:
        return True
    if (snapshot.volume_1h or 0) >= settings.min_volume_1h_usd:
        return True
    if abs(snapshot.price_change_5m or 0) >= 15:
        return True
    if abs(snapshot.price_change_1h or 0) >= 25:
        return True
    return False


def choose_primary_alert(events: list[str]) -> str:
    if not events:
        return "WATCHLIST_MOVEMENT"
    return sorted(events, key=lambda event: ALERT_PRIORITY.get(event, 0), reverse=True)[0]


def security_event_types(security: SecuritySummary) -> list[str]:
    events = []
    if security.honeypot_status == "possible_honeypot":
        events.append("POSSIBLE_HONEYPOT")
    if security.is_critical or security.contract_risk == "risky":
        events.append("SECURITY_RISK")
    return events
