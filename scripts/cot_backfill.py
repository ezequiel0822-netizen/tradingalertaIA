"""COT backfill — baja la HISTORIA del Commitments of Traders (CFTC) e inserta en
`cot_snapshots`, para poder calcular COT index / percentiles a futuro.

El COT collector vivo (`app/collectors/cot_collector.py`) solo guarda el ULTIMO reporte
(1 fila por mercado por semana). Sin historia no se puede normalizar el posicionamiento
(p.ej. percentil del net non-commercial a 1-3 años), que es lo que lo haria util. Este
script trae N reportes por mercado de una sola vez (sin `$limit=1`).

Manual / opt-in (no corre en el ciclo vivo), soft-fail por mercado, idempotente
(`insert_cot_snapshot` usa INSERT OR IGNORE por UNIQUE(report_date, market_code)).
Escribe en la tabla `cot_snapshots` REAL (es data de research, no de trading).

Uso (desde la raiz del repo):
    python scripts/cot_backfill.py            # ~5 años (260 reportes/mercado)
    python scripts/cot_backfill.py --weeks 520
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import requests

# Bootstrap: permitir `python scripts/cot_backfill.py` (la carpeta del script queda en
# sys.path, no la raiz) -> insertamos la raiz para que `import app...` resuelva.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors.cot_collector import (  # noqa: E402
    _COT_ENDPOINT,
    _COT_MARKETS,
    _F_REPORT_DATE,
    parse_cot_row,
)
from app.config.settings import load_settings  # noqa: E402
from app.database.db import init_db  # noqa: E402
from app.database.repository import Repository  # noqa: E402
from app.utils.safe_http import safe_json  # noqa: E402

logger = logging.getLogger(__name__)


def fetch_history(session: requests.Session, cftc_code: str, weeks: int, timeout: int) -> list[dict]:
    """Trae hasta `weeks` reportes (mas recientes primero) de un mercado. Soft-fail -> []."""
    params = {
        "cftc_contract_market_code": cftc_code,
        "$order": f"{_F_REPORT_DATE} DESC",
        "$limit": str(int(weeks)),
    }
    try:
        resp = session.get(_COT_ENDPOINT, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = safe_json(resp, default=[])
    except (requests.RequestException, ValueError):
        logger.warning("COT history fetch failed for %s", cftc_code)
        return []
    return payload if isinstance(payload, list) else []


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description="COT backfill historico (CFTC)")
    parser.add_argument(
        "--weeks", type=int, default=260, help="reportes por mercado (~5 años; default 260)"
    )
    args = parser.parse_args()

    settings = load_settings()
    init_db(settings.sqlite_path)
    repo = Repository(settings.sqlite_path)
    session = requests.Session()
    session.headers.update({"User-Agent": "TradingAlertAI/3.9 (COT backfill)"})

    print(f"COT backfill: hasta {args.weeks} reportes/mercado -> cot_snapshots\n")
    total_new = 0
    for code, (label, cftc_code) in _COT_MARKETS.items():
        rows = fetch_history(
            session, cftc_code, args.weeks, settings.request_timeout_seconds
        )
        new = 0
        for row in rows:
            snap = parse_cot_row(row, code, label)
            if snap and repo.insert_cot_snapshot(snap):
                new += 1
        total_new += new
        print(f"  {code:<5} {label:<20} {len(rows):>4} reportes, {new:>4} nuevos")
        time.sleep(1.0)  # pacing cortes con la API publica de CFTC

    print(f"\nListo: {total_new} filas nuevas en cot_snapshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
