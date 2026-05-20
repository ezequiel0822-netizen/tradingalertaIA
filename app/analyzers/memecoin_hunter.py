"""Memecoin Hunter Pro: scoring extra para memecoins con foco en early entry y anti-rug.

Devuelve `MemecoinHunterResult` con `early_bonus` (pts a sumar al score) y
`anti_rug_multiplier` (0.5-1.0 que penaliza red flags). El consumer aplica:

    adjusted_score = int((base_score + hunter.early_bonus) * hunter.anti_rug_multiplier)

Holder concentration y liquidity_locked quedan opcionales (None) en v2.4.0; futuro
collector RPC los completara. anti_rug_multiplier ya funciona con la data de
GoPlus (security) ya disponible.

Read-only: solo lee snapshot + security + settings. No persiste nada.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config.settings import Settings
from app.database.models import SecuritySummary, TokenSnapshot


@dataclass
class MemecoinHunterResult:
    is_early: bool
    age_hours: float | None
    volume_velocity_ratio: float | None
    holder_concentration_pct: float | None  # 0-1.0; None si no disponible
    liquidity_locked: bool | None
    top_buyer_concentration: int | None
    early_bonus: int
    anti_rug_multiplier: float
    reasons: list[str] = field(default_factory=list)


def _pool_age_hours(snapshot: TokenSnapshot, now_utc: datetime) -> float | None:
    """Calcula edad en horas del pool. None si no hay pool_created_at."""
    created = snapshot.pool_created_at
    if not created:
        return None
    try:
        created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    return (now_utc - created_dt).total_seconds() / 3600.0


def _volume_velocity_ratio(snapshot: TokenSnapshot) -> float | None:
    """Aceleracion: volumen 5m extrapolado a hora vs volumen 1h real.
    >1 = volumen creciendo; >2 = aceleracion fuerte. None si data insuficiente."""
    vol_5m = snapshot.volume_5m or 0
    vol_1h = snapshot.volume_1h or 0
    if vol_5m <= 0 or vol_1h <= 0:
        return None
    return (vol_5m * 12) / vol_1h


def _top_buyer_concentration(snapshot: TokenSnapshot) -> int | None:
    """Heuristica: cantidad de buys recientes (5m). Mas alto = mas presion compradora."""
    buys = snapshot.buys_5m
    if buys is None:
        return None
    return int(buys)


def _compute_early_bonus(
    is_early: bool,
    snapshot: TokenSnapshot,
    volume_velocity: float | None,
    settings: Settings,
) -> tuple[int, list[str]]:
    """Calcula early_bonus (cap 20) + reasons."""
    bonus = 0
    reasons: list[str] = []
    if is_early and (snapshot.volume_5m or 0) > 1000:
        bonus += 10
        reasons.append(
            f"Early pool con volumen ${(snapshot.volume_5m or 0):.0f} en 5m"
        )
        if snapshot.is_boosted:
            bonus += 5
            reasons.append("Boost activo en pool early")
    if (
        volume_velocity is not None
        and volume_velocity >= settings.memecoin_hunter_min_volume_velocity_ratio
    ):
        bonus += 5
        reasons.append(
            f"Aceleracion de volumen {volume_velocity:.1f}x (5m vs 1h)"
        )
    return min(bonus, 20), reasons


def _compute_anti_rug_multiplier(
    security: SecuritySummary,
    holder_concentration_pct: float | None,
    liquidity_locked: bool | None,
) -> tuple[float, list[str]]:
    """Multiplier 0.5-1.0 que penaliza red flags. 1.0 = sin penalty."""
    multiplier = 1.0
    reasons: list[str] = []

    if security.honeypot_status == "possible_honeypot":
        multiplier *= 0.5
        reasons.append("ANTI-RUG: posible honeypot detectado")
    if security.contract_risk == "risky":
        multiplier *= 0.7
        reasons.append("ANTI-RUG: contrato risky")
    if liquidity_locked is False:  # explicito false; None no penaliza
        multiplier *= 0.7
        reasons.append("ANTI-RUG: liquidez sin lock")
    if holder_concentration_pct is not None and holder_concentration_pct > 0.5:
        multiplier *= 0.7
        reasons.append(
            f"ANTI-RUG: top holders concentran {holder_concentration_pct:.0%}"
        )

    # Clamp por seguridad
    multiplier = max(0.3, min(1.0, multiplier))
    return round(multiplier, 4), reasons


def analyze_memecoin(
    snapshot: TokenSnapshot,
    security: SecuritySummary,
    settings: Settings,
    now_utc: datetime | None = None,
) -> MemecoinHunterResult:
    """Aplica el motor Memecoin Hunter sobre un snapshot.

    En v2.4.0 holder_concentration_pct y liquidity_locked son None (requieren
    RPC blockchain que esta fuera de scope). anti_rug_multiplier ya usa la
    data de GoPlus disponible.
    """
    now = now_utc or datetime.now(timezone.utc)
    age = _pool_age_hours(snapshot, now)
    is_early = age is not None and age < settings.max_early_pool_age_hours
    vol_velocity = _volume_velocity_ratio(snapshot)
    top_buyers = _top_buyer_concentration(snapshot)

    # v2.4.0: opcionales que requieren RPC quedan en None
    holder_concentration_pct: float | None = None
    liquidity_locked: bool | None = None

    early_bonus, early_reasons = _compute_early_bonus(
        is_early, snapshot, vol_velocity, settings
    )
    anti_rug_mult, anti_rug_reasons = _compute_anti_rug_multiplier(
        security, holder_concentration_pct, liquidity_locked
    )

    reasons = early_reasons + anti_rug_reasons
    if is_early:
        reasons.insert(0, f"Pool joven ({age:.1f}h de edad)")
    elif age is not None:
        reasons.append(f"Pool maduro ({age:.1f}h)")

    return MemecoinHunterResult(
        is_early=is_early,
        age_hours=round(age, 2) if age is not None else None,
        volume_velocity_ratio=round(vol_velocity, 2) if vol_velocity is not None else None,
        holder_concentration_pct=holder_concentration_pct,
        liquidity_locked=liquidity_locked,
        top_buyer_concentration=top_buyers,
        early_bonus=early_bonus,
        anti_rug_multiplier=anti_rug_mult,
        reasons=reasons[:6],
    )
