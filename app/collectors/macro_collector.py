"""MacroCollector: pull diario de VIX, DXY, SPY via Yahoo Finance.

Calcula `regime` macro: risk_on / risk_off / neutral.
Persiste en `macro_snapshots` con UNIQUE captured_at.
Gateado por bot_state.macro_last_capture_iso (min interval entre pulls).

Read-only: solo HTTP GET a Yahoo Finance publico.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from app.config.settings import Settings


logger = logging.getLogger(__name__)


_MACRO_SYMBOLS = {
    "vix": "^VIX",
    "dxy": "DX-Y.NYB",
    "spy": "SPY",
}


def _fetch_price(session: requests.Session, symbol: str, timeout: int) -> tuple[float | None, float | None]:
    """Return (current_price, previous_close)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "5d", "interval": "1d"}
    try:
        response = session.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        from app.utils.safe_http import safe_json
        payload = safe_json(response, default={})
    except (requests.RequestException, ValueError):
        logger.warning("Macro fetch failed for %s", symbol)
        return None, None
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None, None
    meta = result.get("meta") or {}
    closes_raw = (((result.get("indicators") or {}).get("quote") or [{}])[0] or {}).get("close") or []
    closes = [c for c in closes_raw if c is not None]
    current = meta.get("regularMarketPrice")
    previous = closes[-2] if len(closes) >= 2 else None
    try:
        current_f = float(current) if current is not None else (float(closes[-1]) if closes else None)
    except (TypeError, ValueError):
        current_f = None
    try:
        previous_f = float(previous) if previous is not None else None
    except (TypeError, ValueError):
        previous_f = None
    return current_f, previous_f


def classify_regime(vix: float | None, dxy_change_pct: float | None) -> str:
    if vix is None:
        return "neutral"
    if vix >= 25.0:
        return "risk_off"
    if dxy_change_pct is not None and dxy_change_pct >= 0.5 and vix >= 20.0:
        return "risk_off"
    if vix < 18.0 and (dxy_change_pct is None or abs(dxy_change_pct) < 0.5):
        return "risk_on"
    return "neutral"


class MacroCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TradingAlertAI/2.4"})

    def collect(self) -> dict | None:
        if not self.settings.enable_macro_collector:
            return None

        vix, _ = _fetch_price(
            self.session, _MACRO_SYMBOLS["vix"], self.settings.request_timeout_seconds
        )
        dxy, dxy_prev = _fetch_price(
            self.session, _MACRO_SYMBOLS["dxy"], self.settings.request_timeout_seconds
        )
        spy, _ = _fetch_price(
            self.session, _MACRO_SYMBOLS["spy"], self.settings.request_timeout_seconds
        )

        dxy_change_pct: float | None = None
        if dxy is not None and dxy_prev not in (None, 0):
            dxy_change_pct = ((dxy - dxy_prev) / dxy_prev) * 100

        regime = classify_regime(vix, dxy_change_pct)

        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "vix_value": vix,
            "dxy_value": dxy,
            "spy_value": spy,
            "regime": regime,
        }

    def should_run(self, repository: Any) -> bool:
        """Check si paso el intervalo desde el ultimo pull."""
        if not self.settings.enable_macro_collector:
            return False
        last = repository.get_state("macro_last_capture_iso") or ""
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        except ValueError:
            return True
        elapsed_min = (
            datetime.now(timezone.utc) - last_dt
        ).total_seconds() / 60.0
        return elapsed_min >= self.settings.macro_collector_interval_minutes
