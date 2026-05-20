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


# Phase 3 v2.2.0 — regime detection
def current_regime(repository) -> dict:
    """Lee el ultimo macro_snapshot y retorna regime + valores."""
    snap = repository.fetch_latest_macro_snapshot()
    if not snap:
        return {
            "regime": "neutral",
            "vix": None,
            "dxy": None,
            "spy": None,
            "captured_at": None,
        }
    return {
        "regime": snap.get("regime") or "neutral",
        "vix": snap.get("vix_value"),
        "dxy": snap.get("dxy_value"),
        "spy": snap.get("spy_value"),
        "captured_at": snap.get("captured_at"),
    }


def full_macro_context(repository, now_utc: datetime | None = None) -> dict:
    """Combina sesion + regime en un solo dict para pasar a strategies."""
    ctx = current_session(now_utc)
    ctx.update(current_regime(repository))
    return ctx
