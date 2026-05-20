import logging
import time
from typing import Any

import requests

from app.config.settings import Settings
from app.database.models import TokenSnapshot
from app.utils.rate_limiter import RateLimiter


logger = logging.getLogger(__name__)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class GeckoTerminalCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.rate_limiter = RateLimiter(max_calls=10, period_seconds=60)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TradingAlertAI/2.3"})
        self.ohlcv_cooldown_until = 0.0

    def collect(self) -> list[TokenSnapshot]:
        snapshots: list[TokenSnapshot] = []
        for chain in self.settings.chains_to_monitor:
            network = self.settings.geckoterminal_networks.get(chain)
            if not network:
                logger.info("GeckoTerminal network not mapped for chain=%s", chain)
                continue
            snapshots.extend(self._collect_trending_for_network(chain, network))
        return snapshots

    def _collect_trending_for_network(
        self, chain: str, network: str
    ) -> list[TokenSnapshot]:
        self.rate_limiter.wait()
        url = f"{self.settings.geckoterminal_base_url}/networks/{network}/trending_pools"
        params = {"include": "base_token,quote_token,dex"}
        try:
            response = self.session.get(
                url, params=params, timeout=self.settings.request_timeout_seconds
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            logger.warning("GeckoTerminal trending failed for %s: %s", network, exc)
            return []

        included = self._included_index(payload.get("included") or [])
        snapshots = []
        for pool in payload.get("data") or []:
            snapshot = self._pool_to_snapshot(chain, pool, included)
            if snapshot:
                snapshots.append(snapshot)
        return snapshots

    def fetch_pool_ohlcv(
        self,
        chain: str,
        pool_address: str,
        timeframe: str = "minute",
        aggregate: int = 5,
        limit: int = 60,
    ) -> dict[str, Any] | None:
        network = self.settings.geckoterminal_networks.get(chain)
        if not network or not pool_address:
            return None
        if time.monotonic() < self.ohlcv_cooldown_until:
            return None
        self.rate_limiter.wait()
        url = (
            f"{self.settings.geckoterminal_base_url}/networks/"
            f"{network}/pools/{pool_address}/ohlcv/{timeframe}"
        )
        params = {"aggregate": aggregate, "limit": limit, "currency": "usd"}
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            from app.utils.safe_http import safe_json
            return safe_json(response, default=None)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 429:
                self.ohlcv_cooldown_until = time.monotonic() + 90
                logger.warning("GeckoTerminal OHLCV rate limited; cooling down for 90 seconds")
            else:
                logger.warning("GeckoTerminal OHLCV failed for %s:%s: %s", chain, pool_address, exc)
            return None
        except (requests.RequestException, ValueError) as exc:
            logger.warning("GeckoTerminal OHLCV failed for %s:%s: %s", chain, pool_address, exc)
            return None

    def _included_index(self, included: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
        index: dict[tuple[str, str], dict[str, Any]] = {}
        for item in included:
            item_type = str(item.get("type") or "")
            item_id = str(item.get("id") or "")
            if item_type and item_id:
                index[(item_type, item_id)] = item
        return index

    def _pool_to_snapshot(
        self,
        chain: str,
        pool: dict[str, Any],
        included: dict[tuple[str, str], dict[str, Any]],
    ) -> TokenSnapshot | None:
        attributes = pool.get("attributes") or {}
        relationships = pool.get("relationships") or {}
        base_ref = (relationships.get("base_token") or {}).get("data") or {}
        dex_ref = (relationships.get("dex") or {}).get("data") or {}
        base_token = included.get((str(base_ref.get("type") or ""), str(base_ref.get("id") or "")), {})
        dex = included.get((str(dex_ref.get("type") or ""), str(dex_ref.get("id") or "")), {})
        base_attributes = base_token.get("attributes") or {}
        dex_attributes = dex.get("attributes") or {}

        token_address = str(base_attributes.get("address") or "")
        if not token_address:
            token_address = self._address_from_gecko_id(str(base_ref.get("id") or ""))
        if not token_address:
            return None

        volume = attributes.get("volume_usd") or {}
        price_change = attributes.get("price_change_percentage") or {}
        transactions = attributes.get("transactions") or {}

        return TokenSnapshot(
            chain=chain,
            token_address=token_address,
            symbol=str(base_attributes.get("symbol") or "unknown"),
            name=str(base_attributes.get("name") or attributes.get("name") or "unknown"),
            source="GeckoTerminal",
            event_type="TRENDING_POOL",
            price=_to_float(attributes.get("base_token_price_usd")),
            liquidity_usd=_to_float(attributes.get("reserve_in_usd")),
            volume_5m=_to_float(volume.get("m5")),
            volume_1h=_to_float(volume.get("h1")),
            volume_24h=_to_float(volume.get("h24")),
            price_change_5m=_to_float(price_change.get("m5")),
            price_change_1h=_to_float(price_change.get("h1")),
            price_change_24h=_to_float(price_change.get("h24")),
            pair_address=str(attributes.get("address") or ""),
            dex=str(dex_attributes.get("name") or dex_ref.get("id") or "unknown"),
            pool_created_at=attributes.get("pool_created_at"),
            is_trending=True,
            buys_5m=_to_int((transactions.get("m5") or {}).get("buys")),
            sells_5m=_to_int((transactions.get("m5") or {}).get("sells")),
            buys_1h=_to_int((transactions.get("h1") or {}).get("buys")),
            sells_1h=_to_int((transactions.get("h1") or {}).get("sells")),
            raw=pool,
        )

    def _address_from_gecko_id(self, value: str) -> str:
        if "_" in value:
            return value.split("_", 1)[1]
        return value
