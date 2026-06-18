"""COTCollector: pull semanal del Commitments of Traders (CFTC, gratis).

Captura el posicionamiento institucional (large speculators / commercials) de los
futuros de divisas y oro que el bot opera. Es "informacion que el precio no digirio"
(MAPA_DE_EDGE_Y_RUTA §3.4 + ESPEC §17.2): el primer input informacional fuera del
OHLCV publico que todos miran.

NO genera senal ni gate: SOLO captura y persiste para research. La maquinaria de edge
(slicing por posicionamiento, COT index, etc.) se construye DESPUES, sobre data ya
acumulada — el edge se descubre, no se inyecta. Read-only: HTTP GET a la Socrata Open
Data API de la CFTC. Opt-in OFF + soft-fail como todo lo nuevo: si esta apagado o algo
falla, el bot corre EXACTAMENTE igual.

Fuente: https://publicreporting.cftc.gov/resource/6dca-aqww.json (Legacy Futures-Only,
semanal, martes con release el viernes). Idempotente por (report_date, market_code)
UNIQUE; gateado por bot_state.cot_last_capture_iso (la data es semanal, alcanza con
chequear un par de veces al dia).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from app.config.settings import Settings
from app.utils.safe_http import safe_json


logger = logging.getLogger(__name__)


_COT_ENDPOINT = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# Mercados que el bot opera, mapeados al cftc_contract_market_code (identificador
# ESTABLE de la CFTC; mas robusto que matchear nombres de mercado que cambian de texto).
# code interno -> (label legible, cftc_contract_market_code)
_COT_MARKETS: dict[str, tuple[str, str]] = {
    "EUR": ("Euro FX", "099741"),
    "GBP": ("British Pound", "096742"),
    "JPY": ("Japanese Yen", "097741"),
    "AUD": ("Australian Dollar", "232741"),
    "CAD": ("Canadian Dollar", "090741"),
    "CHF": ("Swiss Franc", "092741"),
    "NZD": ("New Zealand Dollar", "112741"),
    "USD": ("US Dollar Index", "098662"),
    "GOLD": ("Gold", "088691"),
}

# Nombres de columna del dataset Socrata (6dca-aqww). Centralizados para ajustar facil
# si la CFTC los renombra; cualquier ausencia cae a None (soft-fail), no crashea.
_F_REPORT_DATE = "report_date_as_yyyy_mm_dd"
_F_NONCOMM_LONG = "noncomm_positions_long_all"
_F_NONCOMM_SHORT = "noncomm_positions_short_all"
_F_COMM_LONG = "comm_positions_long_all"
_F_COMM_SHORT = "comm_positions_short_all"
_F_OPEN_INTEREST = "open_interest_all"


def _to_int(value: Any) -> int | None:
    """Parsea un entero tolerando floats/strings de la API; None si no se puede."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def net_position(long: int | None, short: int | None) -> int | None:
    """Posicion neta = long - short. None si falta cualquiera de los dos lados."""
    if long is None or short is None:
        return None
    return long - short


def parse_cot_row(row: dict[str, Any], market_code: str, market_label: str) -> dict[str, Any] | None:
    """Convierte una fila cruda de la API en el snapshot que persistimos.

    Pura y testeable. Devuelve None si la fila no trae fecha de reporte (sin eso no
    hay clave de idempotencia util). Los conteos ausentes quedan en None.
    """
    report_date = str(row.get(_F_REPORT_DATE) or "").strip()
    if not report_date:
        return None
    # report_date llega como ISO completo (2026-06-10T00:00:00.000); normalizamos a YYYY-MM-DD
    report_date = report_date[:10]

    noncomm_long = _to_int(row.get(_F_NONCOMM_LONG))
    noncomm_short = _to_int(row.get(_F_NONCOMM_SHORT))
    comm_long = _to_int(row.get(_F_COMM_LONG))
    comm_short = _to_int(row.get(_F_COMM_SHORT))

    return {
        "report_date": report_date,
        "market_code": market_code,
        "market_label": market_label,
        "noncomm_long": noncomm_long,
        "noncomm_short": noncomm_short,
        "comm_long": comm_long,
        "comm_short": comm_short,
        "open_interest": _to_int(row.get(_F_OPEN_INTEREST)),
        "net_noncomm": net_position(noncomm_long, noncomm_short),
        "net_comm": net_position(comm_long, comm_short),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


class COTCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TradingAlertAI/3.9 (COT)"})

    def _fetch_market(self, cftc_code: str) -> dict[str, Any] | None:
        """Trae la ultima fila (report mas reciente) para un mercado. Soft-fail -> None."""
        params = {
            "cftc_contract_market_code": cftc_code,
            "$order": f"{_F_REPORT_DATE} DESC",
            "$limit": "1",
        }
        try:
            response = self.session.get(
                _COT_ENDPOINT, params=params, timeout=self.settings.request_timeout_seconds
            )
            response.raise_for_status()
            payload = safe_json(response, default=[])
        except (requests.RequestException, ValueError):
            logger.warning("COT fetch failed for market %s", cftc_code)
            return None
        if not isinstance(payload, list) or not payload:
            return None
        first = payload[0]
        return first if isinstance(first, dict) else None

    def collect(self) -> list[dict[str, Any]] | None:
        """Devuelve un snapshot por mercado del ultimo reporte COT, o None si esta OFF.
        Soft-fail por mercado: un mercado que falla se saltea, los demas siguen."""
        if not self.settings.enable_cot_collector:
            return None

        snapshots: list[dict[str, Any]] = []
        for code, (label, cftc_code) in _COT_MARKETS.items():
            row = self._fetch_market(cftc_code)
            if not row:
                continue
            snapshot = parse_cot_row(row, code, label)
            if snapshot:
                snapshots.append(snapshot)
        return snapshots

    def should_run(self, repository: Any) -> bool:
        """True si paso el intervalo desde el ultimo pull (la data es semanal)."""
        if not self.settings.enable_cot_collector:
            return False
        last = repository.get_state("cot_last_capture_iso") or ""
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        except ValueError:
            return True
        elapsed_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60.0
        return elapsed_min >= self.settings.cot_collector_interval_minutes
