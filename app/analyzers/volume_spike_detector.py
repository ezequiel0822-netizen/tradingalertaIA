from typing import Any

from app.config.settings import Settings
from app.database.models import TokenSnapshot


def detect_volume_spike(
    snapshot: TokenSnapshot,
    previous: dict[str, Any] | None,
    settings: Settings,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    volume_5m = snapshot.volume_5m or 0
    volume_1h = snapshot.volume_1h or 0
    previous_5m = float((previous or {}).get("latest_volume_5m") or 0)
    previous_1h = float((previous or {}).get("latest_volume_1h") or 0)

    if volume_5m >= settings.min_volume_5m_usd:
        reasons.append(f"Volumen 5m supera el mínimo configurado: ${volume_5m:,.2f}.")
    if volume_1h >= settings.min_volume_1h_usd:
        reasons.append(f"Volumen 1h supera el mínimo configurado: ${volume_1h:,.2f}.")

    spike = False
    if previous_5m > 0 and volume_5m >= previous_5m * 3:
        spike = True
        reasons.append("Volumen 5m subió más de 3x contra la última lectura.")
    if previous_1h > 0 and volume_1h >= previous_1h * 3:
        spike = True
        reasons.append("Volumen 1h subió más de 3x contra la última lectura.")

    if not previous and (volume_5m >= settings.min_volume_5m_usd or volume_1h >= settings.min_volume_1h_usd):
        spike = True

    return spike, reasons
