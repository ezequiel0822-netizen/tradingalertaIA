from typing import Any

from app.config.settings import Settings
from app.database.models import TokenSnapshot


def detect_liquidity_spike(
    snapshot: TokenSnapshot,
    previous: dict[str, Any] | None,
    settings: Settings,
) -> tuple[bool, list[str]]:
    liquidity = snapshot.liquidity_usd or 0
    previous_liquidity = float((previous or {}).get("latest_liquidity_usd") or 0)
    reasons: list[str] = []

    if liquidity >= settings.min_liquidity_usd:
        reasons.append(f"Liquidez supera el mínimo configurado: ${liquidity:,.2f}.")

    if previous_liquidity > 0 and liquidity >= previous_liquidity * 2:
        reasons.append("Liquidez subió más de 2x contra la última lectura.")
        return True, reasons

    if not previous and liquidity >= settings.min_liquidity_usd * 3:
        reasons.append("Liquidez inicial alta para revisión manual.")
        return True, reasons

    return False, reasons


def detect_price_spike(snapshot: TokenSnapshot) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if snapshot.price_change_5m is not None and abs(snapshot.price_change_5m) >= 15:
        reasons.append(f"Movimiento fuerte de precio en 5m: {snapshot.price_change_5m:.2f}%.")
    if snapshot.price_change_1h is not None and abs(snapshot.price_change_1h) >= 25:
        reasons.append(f"Movimiento fuerte de precio en 1h: {snapshot.price_change_1h:.2f}%.")
    if snapshot.price_change_24h is not None and abs(snapshot.price_change_24h) >= 60:
        reasons.append(f"Movimiento fuerte de precio en 24h: {snapshot.price_change_24h:.2f}%.")
    return bool(reasons), reasons
