"""Collector de forex y oro via Yahoo Finance (HTTP).

Acumula snapshots OHLCV para `price_snapshots` y `alert_outcome_horizons`.
Alertas a Telegram: solo con ENABLE_FOREX_ALERTS / ENABLE_GOLD_ALERTS y un movimiento
notable (v3.13.2, alert_decision_engine + move_estimator._estimate_fx_move).

Provisional hasta que se conecte una fuente MT5 directa en Fase 4.
"""

import logging
import time
from typing import Any

import requests

from app.analyzers.technical_patterns import candles_from_yahoo
from app.config.settings import Settings
from app.database.models import TokenSnapshot


logger = logging.getLogger(__name__)

# v3.10.1 (M2): tras un 429 de Yahoo, pausa TODO el collector este rato en vez
# de seguir golpeando a full rate simbolo por simbolo, ciclo tras ciclo.
YAHOO_429_COOLDOWN_SECONDS = 600.0


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return ((current - previous) / previous) * 100


def _classify(symbol: str) -> tuple[str, str, str]:
    """Returns (category, chain, event_type) for a Yahoo symbol."""
    upper = symbol.upper()
    if upper.endswith("=F") or "XAU" in upper:
        return "gold", "commodity", "GOLD_MOVEMENT"
    return "forex", "forex", "FOREX_MOVEMENT"


class ForexCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TradingAlertAI/2.4"})
        self._cooldown_until = 0.0

    def collect(self) -> list[TokenSnapshot]:
        if not self.settings.enable_forex_collector:
            return []
        if time.monotonic() < self._cooldown_until:
            return []

        snapshots: list[TokenSnapshot] = []
        for symbol in self.settings.forex_symbols:
            if time.monotonic() < self._cooldown_until:
                break  # un 429 a mitad de la lista corta el resto del batch
            snapshot = self._fetch_symbol(symbol.upper())
            if snapshot:
                snapshots.append(snapshot)
        return snapshots

    def _fetch_symbol(self, symbol: str) -> TokenSnapshot | None:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"range": "5d", "interval": "15m", "includePrePost": "false"}
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429:
                self._cooldown_until = time.monotonic() + YAHOO_429_COOLDOWN_SECONDS
                logger.warning(
                    "Yahoo 429 (forex): cooldown de %ss", int(YAHOO_429_COOLDOWN_SECONDS)
                )
            logger.warning("Forex data failed for %s: %s", symbol, exc)
            return None

        result = ((payload.get("chart") or {}).get("result") or [None])[0]
        if not result:
            return None
        candles = candles_from_yahoo(result)

        meta = result.get("meta") or {}
        quote = (((result.get("indicators") or {}).get("quote") or [{}])[0]) or {}
        closes = [value for value in quote.get("close") or [] if value is not None]
        if len(closes) < 2:
            return None

        current_price = float(meta.get("regularMarketPrice") or closes[-1])
        previous_15m = closes[-2] if len(closes) >= 2 else None
        previous_1h = closes[-5] if len(closes) >= 5 else None  # 4 velas de 15m = 1h
        # M2 fix: 24h = 96 velas de 15m (antes usaba -27 = ~6.5h, mal etiquetado)
        previous_24h = closes[-97] if len(closes) >= 97 else closes[0]

        category, chain, event_type = _classify(symbol)

        return TokenSnapshot(
            chain=chain,
            token_address=symbol,
            category=category,
            symbol=symbol,
            name=str(meta.get("longName") or meta.get("shortName") or symbol),
            source="Yahoo Finance",
            event_type=event_type,
            price=current_price,
            liquidity_usd=None,
            volume_5m=None,
            volume_1h=None,
            volume_24h=None,
            price_change_5m=_pct_change(current_price, previous_15m),
            price_change_1h=_pct_change(current_price, previous_1h),
            price_change_24h=_pct_change(current_price, previous_24h),
            raw={"meta": meta, "candles": candles},
        )
