"""Macro Context: sesiones FX.

Fase 2.5 minimo: solo sesiones de mercado (asian/london/ny).
VIX, DXY y calendario economico quedan para Fase 3.
"""

from datetime import datetime, timezone


def current_session(now_utc: datetime | None = None) -> dict:
    now = now_utc or datetime.now(timezone.utc)
    hour = now.hour
    asian = (23 <= hour) or (hour < 8)
    london = 8 <= hour < 17
    ny = 13 <= hour < 22

    active: list[str] = []
    if asian:
        active.append("asian")
    if london:
        active.append("london")
    if ny:
        active.append("ny")

    is_high_liquidity = ("london" in active and "ny" in active) or len(active) >= 2
    return {
        "asian": asian,
        "london": london,
        "ny": ny,
        "active_sessions": active,
        "is_high_liquidity": is_high_liquidity,
        "utc_hour": hour,
    }


def is_in_session(session_name: str, now_utc: datetime | None = None) -> bool:
    ctx = current_session(now_utc)
    return bool(ctx.get(session_name, False))
