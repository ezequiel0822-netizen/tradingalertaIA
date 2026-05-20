"""CSV export helpers para outcomes, paper trades, horizons, walk-forward.

Path saneado con safe_resolve_within (no permite traversal fuera de PROJECT_ROOT).
"""

import csv
import logging
from pathlib import Path
from typing import Any

from app.utils.safe_path import safe_resolve_within


logger = logging.getLogger(__name__)


def _ensure_safe_path(path: Path, root: Path) -> Path | None:
    """Asegura que el path este bajo root. Crea directorio si hace falta."""
    target = path if path.is_absolute() else (root / path)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    safe = safe_resolve_within(target, root)
    return safe if safe else None


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def export_outcomes_csv(
    repository: Any,
    start_iso: str,
    end_iso: str,
    path: Path,
    root: Path | None = None,
) -> int:
    """Exporta signal_outcomes en un rango temporal. Retorna # filas."""
    root = root or Path.cwd()
    safe = _ensure_safe_path(path, root)
    if safe is None:
        logger.warning("Refused export to unsafe path")
        return 0
    try:
        rows = repository.fetch_signal_outcomes(limit=10000) or []
    except Exception:
        rows = []
    # Filtro temporal
    filtered = [
        r for r in rows
        if start_iso <= str(r.get("evaluated_at") or "") <= end_iso
    ]
    return _write_rows(safe, filtered)


def export_paper_trades_csv(
    repository: Any,
    status: str | None,
    path: Path,
    root: Path | None = None,
) -> int:
    root = root or Path.cwd()
    safe = _ensure_safe_path(path, root)
    if safe is None:
        return 0
    try:
        rows = repository.fetch_paper_trades(status=status, limit=10000) or []
    except Exception:
        rows = []
    return _write_rows(safe, rows)


def export_horizons_csv(
    repository: Any,
    horizon_hours: int | None,
    path: Path,
    root: Path | None = None,
) -> int:
    root = root or Path.cwd()
    safe = _ensure_safe_path(path, root)
    if safe is None:
        return 0
    try:
        rows = repository.fetch_alert_outcome_horizons(
            horizon_hours=horizon_hours, status=None, limit=10000
        ) or []
    except Exception:
        rows = []
    return _write_rows(safe, rows)


def export_walk_forward_csv(
    repository: Any,
    strategy_name: str | None,
    path: Path,
    root: Path | None = None,
) -> int:
    root = root or Path.cwd()
    safe = _ensure_safe_path(path, root)
    if safe is None:
        return 0
    try:
        rows = repository.fetch_walk_forward_results(
            strategy_name=strategy_name, limit=10000
        ) or []
    except Exception:
        rows = []
    return _write_rows(safe, rows)
