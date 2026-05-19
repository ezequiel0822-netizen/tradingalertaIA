"""Position sizing puro: calcula tamano basado en % cuenta arriesgado y distancia al stop.

Funcion sin estado; testeable de forma directa.
"""

from dataclasses import dataclass


@dataclass
class PositionSizing:
    size_notional: float
    size_units: float
    risk_amount: float
    risk_pct_actual: float
    invalid_reason: str | None = None


def calculate_position_size(
    entry: float,
    stop: float,
    account_balance: float,
    risk_pct: float,
    direction: str = "long",
) -> PositionSizing:
    if account_balance <= 0:
        return PositionSizing(0, 0, 0, 0, invalid_reason="balance <= 0")
    if risk_pct <= 0:
        return PositionSizing(0, 0, 0, 0, invalid_reason="risk_pct <= 0")
    if entry <= 0:
        return PositionSizing(0, 0, 0, 0, invalid_reason="entry <= 0")

    risk_amount = account_balance * (risk_pct / 100.0)

    if direction == "long":
        per_unit_risk = entry - stop
    elif direction == "short":
        per_unit_risk = stop - entry
    else:
        return PositionSizing(0, 0, 0, 0, invalid_reason=f"unknown direction {direction}")

    if per_unit_risk <= 0:
        return PositionSizing(0, 0, 0, 0, invalid_reason="invalid stop relative to entry")

    size_units = risk_amount / per_unit_risk
    size_notional = size_units * entry
    risk_pct_actual = (risk_amount / account_balance) * 100.0

    return PositionSizing(
        size_notional=round(size_notional, 4),
        size_units=round(size_units, 8),
        risk_amount=round(risk_amount, 4),
        risk_pct_actual=round(risk_pct_actual, 4),
    )
