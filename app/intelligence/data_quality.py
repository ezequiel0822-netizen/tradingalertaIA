"""Data quality monitor: gaps en price_snapshots, staleness, collector failures.

Read-only: solo lee la DB y produce reportes. No bloquea trades por si mismo.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config.settings import Settings


logger = logging.getLogger(__name__)


def gap_check(
    repository: Any,
    symbol: str,
    expected_interval_min: int = 15,
    lookback_hours: int = 24,
    chain: str = "*",
) -> list[dict]:
    """Detecta gaps en price_snapshots para un simbolo en las ultimas N horas.

    Un gap se considera cuando entre 2 snapshots consecutivos hay mas de
    `expected_interval_min * gap_threshold_multiplier` minutos.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=lookback_hours)
    try:
        snapshots = repository.fetch_snapshots_in_window(
            chain=chain, token_address=symbol,
            start_iso=start.isoformat(), end_iso=end.isoformat(),
        )
    except Exception:
        return []

    if not snapshots:
        return []

    gaps: list[dict] = []
    expected_seconds = expected_interval_min * 60
    threshold_seconds = expected_seconds * 2  # 2x default
    prev_time: datetime | None = None
    for snap in snapshots:
        try:
            captured = datetime.fromisoformat(
                str(snap.get("captured_at")).replace("Z", "+00:00")
            )
        except (ValueError, AttributeError, TypeError):
            continue
        if prev_time is not None:
            delta = (captured - prev_time).total_seconds()
            if delta > threshold_seconds:
                gaps.append({
                    "symbol": symbol,
                    "gap_start": prev_time.isoformat(),
                    "gap_end": captured.isoformat(),
                    "gap_minutes": int(delta / 60),
                })
        prev_time = captured
    return gaps


def staleness_check(
    repository: Any, max_minutes: int = 15
) -> list[dict]:
    """Lista de simbolos cuyo ultimo snapshot es mas viejo que max_minutes."""
    now = datetime.now(timezone.utc)
    stale: list[dict] = []
    try:
        tokens = repository.fetch_tokens(limit=200) if hasattr(
            repository, "fetch_tokens"
        ) else []
    except Exception:
        return []

    for tok in tokens:
        last_seen = tok.get("last_seen_at")
        if not last_seen:
            continue
        try:
            last_dt = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        age_min = (now - last_dt).total_seconds() / 60
        if age_min > max_minutes:
            stale.append({
                "symbol": tok.get("symbol"),
                "category": tok.get("category"),
                "age_minutes": int(age_min),
            })
    return stale


def collector_failure_check(repository: Any, hours: int = 24) -> dict:
    """Resumen de bot_state keys con `*_last_failure_*` en las ultimas N horas.

    Por ahora retorna 0 si no hay un mecanismo de tracking persistido.
    Implementacion mas detallada queda para futuro.
    """
    return {"failures_24h": 0, "details": []}


def run_full_check(repository: Any, settings: Settings) -> dict:
    """Combina los 3 checks + persiste resumen en data_quality_log."""
    staleness_threshold = settings.data_quality_staleness_max_minutes

    stale = staleness_check(repository, max_minutes=staleness_threshold)
    failures = collector_failure_check(repository)

    # Para gaps, chequea solo los simbolos mas activos (los 5 mas recientes)
    gaps_total: list[dict] = []
    try:
        recent_tokens = repository.fetch_tokens(limit=10) if hasattr(
            repository, "fetch_tokens"
        ) else []
    except Exception:
        recent_tokens = []
    for tok in recent_tokens[:5]:
        addr = tok.get("token_address")
        if not addr:
            continue
        # v3.9.3: antes este loop terminaba en `pass` -> gap_check NUNCA corria.
        # fetch_snapshots_in_window matchea el chain EXACTO, asi que pasamos el real.
        try:
            gaps_total.extend(
                gap_check(repository, addr, chain=tok.get("chain") or "*")
            )
        except Exception:
            continue

    summary = {
        "gaps_detected": len(gaps_total),
        "stale_symbols": len(stale),
        "collector_failures": failures.get("failures_24h", 0),
        "stale_list": stale[:10],
    }

    check_at = datetime.now(timezone.utc).isoformat()
    log_row = {
        "check_at": check_at,
        "gaps_detected": summary["gaps_detected"],
        "stale_symbols": summary["stale_symbols"],
        "collector_failures": summary["collector_failures"],
        "summary": json.dumps(summary, ensure_ascii=False),
    }
    try:
        repository.insert_data_quality_log(log_row)
    except Exception:
        logger.warning("Failed to persist data_quality_log")

    return summary
