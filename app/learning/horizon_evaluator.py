from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.config.settings import Settings
from app.database.repository import Repository
from app.learning.training_engine import _outcome_label
from app.utils.time_utils import parse_iso_datetime, utc_now, utc_now_iso


HORIZONS = (1, 6, 24, 168)


@dataclass
class HorizonResult:
    alert_id: int
    horizon_hours: int
    return_pct: float | None
    mfe_pct: float | None
    mae_pct: float | None
    snapshots_used: int
    outcome_label: str
    status: str


def evaluate_horizons(settings: Settings, repository: Repository) -> dict[str, int]:
    if not settings.enable_horizon_evaluator:
        return {"horizons_created": 0, "horizons_updated": 0}

    alerts = repository.fetch_alerts_for_learning(
        settings.learning_min_alert_age_minutes,
        settings.learning_max_alerts_per_run,
    )

    created = 0
    updated = 0
    now = utc_now()
    for alert in alerts:
        entry = _to_float(alert.get("price"))
        if entry is None or entry <= 0:
            continue
        created_at = parse_iso_datetime(str(alert.get("created_at") or ""))
        if created_at is None:
            continue

        existing = {
            int(row["horizon_hours"]): row
            for row in repository.fetch_alert_outcome_horizons(
                alert_id=int(alert["id"]), limit=len(HORIZONS) + 2
            )
        }

        for horizon in HORIZONS:
            window_end = created_at + timedelta(hours=horizon)
            if now < window_end:
                # Ventana aun no cerrada; no creamos entrada todavia.
                continue
            previous = existing.get(horizon)
            if previous and previous.get("status") == "final":
                continue

            snapshots = repository.fetch_snapshots_in_window(
                str(alert.get("chain") or ""),
                str(alert.get("token_address") or ""),
                created_at.isoformat(),
                window_end.isoformat(),
            )
            result = _compute_horizon_result(
                alert_id=int(alert["id"]),
                horizon_hours=horizon,
                entry_price=entry,
                snapshots=snapshots,
                settings=settings,
                category=str(alert.get("category") or "memecoin"),
            )
            payload = {
                "alert_id": result.alert_id,
                "horizon_hours": result.horizon_hours,
                "entry_price": entry,
                "exit_price": (
                    snapshots[-1].get("price") if result.status == "final" and snapshots else None
                ),
                "return_pct": result.return_pct,
                "mfe_pct": result.mfe_pct,
                "mae_pct": result.mae_pct,
                "snapshots_used": result.snapshots_used,
                "outcome_label": result.outcome_label,
                "status": result.status,
                "evaluated_at": utc_now_iso(),
            }
            is_new = repository.upsert_alert_outcome_horizon(payload)
            if is_new:
                created += 1
            else:
                updated += 1

    return {"horizons_created": created, "horizons_updated": updated}


def _compute_horizon_result(
    alert_id: int,
    horizon_hours: int,
    entry_price: float,
    snapshots: list[dict[str, Any]],
    settings: Settings,
    category: str,
) -> HorizonResult:
    if len(snapshots) < settings.horizon_min_snapshots:
        return HorizonResult(
            alert_id=alert_id,
            horizon_hours=horizon_hours,
            return_pct=None,
            mfe_pct=None,
            mae_pct=None,
            snapshots_used=len(snapshots),
            outcome_label="insufficient_data",
            status="pending",
        )

    prices = [
        price for price in (_to_float(s.get("price")) for s in snapshots) if price is not None
    ]
    if len(prices) < settings.horizon_min_snapshots:
        return HorizonResult(
            alert_id=alert_id,
            horizon_hours=horizon_hours,
            return_pct=None,
            mfe_pct=None,
            mae_pct=None,
            snapshots_used=len(prices),
            outcome_label="insufficient_data",
            status="pending",
        )

    exit_price = prices[-1]
    return_pct = ((exit_price - entry_price) / entry_price) * 100
    mfe_pct = ((max(prices) - entry_price) / entry_price) * 100
    mae_pct = ((min(prices) - entry_price) / entry_price) * 100
    label = _outcome_label(return_pct, category, settings)
    return HorizonResult(
        alert_id=alert_id,
        horizon_hours=horizon_hours,
        return_pct=round(return_pct, 4),
        mfe_pct=round(mfe_pct, 4),
        mae_pct=round(mae_pct, 4),
        snapshots_used=len(prices),
        outcome_label=label,
        status="final",
    )


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
