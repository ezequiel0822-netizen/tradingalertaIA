import logging
from typing import Any

import requests

from app.analyzers.technical_patterns import candles_from_yahoo
from app.config.settings import Settings
from app.database.models import TokenSnapshot


logger = logging.getLogger(__name__)


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return ((current - previous) / previous) * 100


class StockCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TradingAlertAI/2.4"})

    def collect(self) -> list[TokenSnapshot]:
        if not self.settings.enable_stock_alerts:
            return []

        snapshots: list[TokenSnapshot] = []
        for symbol in self.settings.stock_symbols:
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
            logger.warning("Stock data failed for %s: %s", symbol, exc)
            return None

        result = ((payload.get("chart") or {}).get("result") or [None])[0]
        if not result:
            return None
        candles = candles_from_yahoo(result)

        meta = result.get("meta") or {}
        quote = (((result.get("indicators") or {}).get("quote") or [{}])[0]) or {}
        closes = [value for value in quote.get("close") or [] if value is not None]
        volumes = quote.get("volume") or []
        if len(closes) < 2:
            return None

        current_price = float(meta.get("regularMarketPrice") or closes[-1])
        previous_15m = closes[-2] if len(closes) >= 2 else None
        previous_1h = closes[-5] if len(closes) >= 5 else None
        previous_24h = closes[-27] if len(closes) >= 27 else closes[0]

        dollar_volumes = self._dollar_volumes(closes, volumes)
        volume_latest = dollar_volumes[-1] if dollar_volumes else None
        volume_1h = sum(dollar_volumes[-4:]) if dollar_volumes else None
        volume_24h = sum(dollar_volumes[-26:]) if dollar_volumes else None

        event_type = "STOCK_MOVEMENT"
        change_1h = _pct_change(current_price, previous_1h)
        change_24h = _pct_change(current_price, previous_24h)
        if change_1h is not None and change_1h >= 3:
            event_type = "STOCK_BREAKOUT"
        elif change_24h is not None and change_24h <= -5:
            event_type = "STOCK_DROP_RISK"

        return TokenSnapshot(
            chain="stock",
            token_address=symbol,
            category="stock",
            symbol=symbol,
            name=str(meta.get("longName") or meta.get("shortName") or symbol),
            source="Yahoo Finance",
            event_type=event_type,
            price=current_price,
            liquidity_usd=volume_24h,
            volume_5m=volume_latest,
            volume_1h=volume_1h,
            volume_24h=volume_24h,
            price_change_5m=_pct_change(current_price, previous_15m),
            price_change_1h=change_1h,
            price_change_24h=change_24h,
            raw={"meta": meta, "candles": candles},
        )

    def _dollar_volumes(
        self,
        closes: list[float],
        volumes: list[Any],
    ) -> list[float]:
        output: list[float] = []
        for close, volume in zip(closes, volumes):
            if volume is None:
                continue
            try:
                output.append(float(close) * float(volume))
            except (TypeError, ValueError):
                continue
        return output
