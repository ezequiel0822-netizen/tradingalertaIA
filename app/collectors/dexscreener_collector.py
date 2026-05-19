import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import requests

from app.config.settings import Settings
from app.database.models import TokenSnapshot


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


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _pair_created_at_to_iso(value: Any) -> str | None:
    timestamp = _to_float(value)
    if timestamp is None:
        return None
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


class DexScreenerCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TradingAlertAI/0.1"})

    def collect(self) -> list[TokenSnapshot]:
        seeds: list[dict[str, Any]] = []
        seeds.extend(self._collect_profiles())
        seeds.extend(self._collect_boosts("/token-boosts/latest/v1"))
        seeds.extend(self._collect_boosts("/token-boosts/top/v1"))
        return self._enrich_seeds(seeds)

    def _get_json(self, path: str) -> Any:
        from app.utils.safe_http import safe_json
        url = f"{self.settings.dexscreener_base_url}{path}"
        response = self.session.get(url, timeout=self.settings.request_timeout_seconds)
        response.raise_for_status()
        return safe_json(response, default=None)

    def _collect_profiles(self) -> list[dict[str, Any]]:
        try:
            rows = _as_list(self._get_json("/token-profiles/latest/v1"))
        except requests.RequestException as exc:
            logger.warning("DEX Screener profiles failed: %s", exc)
            return []

        return [
            {
                "chain": str(row.get("chainId") or "").lower(),
                "token_address": str(row.get("tokenAddress") or ""),
                "event_type": "NEW_TOKEN",
                "source": "DEX Screener",
                "is_new": True,
                "raw": row,
            }
            for row in rows
            if self._allowed(row.get("chainId"), row.get("tokenAddress"))
        ]

    def _collect_boosts(self, path: str) -> list[dict[str, Any]]:
        try:
            rows = _as_list(self._get_json(path))
        except requests.RequestException as exc:
            logger.warning("DEX Screener boosts failed: %s", exc)
            return []

        return [
            {
                "chain": str(row.get("chainId") or "").lower(),
                "token_address": str(row.get("tokenAddress") or ""),
                "event_type": "BOOSTED_TOKEN",
                "source": "DEX Screener",
                "is_boosted": True,
                "raw": row,
            }
            for row in rows
            if self._allowed(row.get("chainId"), row.get("tokenAddress"))
        ]

    def _allowed(self, chain: Any, token_address: Any) -> bool:
        chain_value = str(chain or "").lower()
        token_value = str(token_address or "")
        return bool(token_value) and chain_value in self.settings.chains_to_monitor

    def _enrich_seeds(self, seeds: list[dict[str, Any]]) -> list[TokenSnapshot]:
        addresses_by_chain: dict[str, list[str]] = defaultdict(list)
        for seed in seeds:
            addresses_by_chain[seed["chain"]].append(seed["token_address"])

        pair_index: dict[tuple[str, str], dict[str, Any]] = {}
        for chain, addresses in addresses_by_chain.items():
            for batch in self._chunks(sorted(set(addresses)), 30):
                for pair in self._fetch_pairs(chain, batch):
                    token_address = self._token_address_from_pair(pair, batch)
                    if token_address:
                        key = (chain, token_address.lower())
                        current = pair_index.get(key)
                        if current is None or self._pair_rank(pair) > self._pair_rank(current):
                            pair_index[key] = pair

        snapshots: list[TokenSnapshot] = []
        for seed in seeds:
            pair = pair_index.get((seed["chain"], seed["token_address"].lower()))
            snapshots.append(self._snapshot_from_seed(seed, pair))
        return snapshots

    def _fetch_pairs(self, chain: str, addresses: list[str]) -> list[dict[str, Any]]:
        if not addresses:
            return []
        path = f"/tokens/v1/{chain}/{','.join(addresses)}"
        try:
            payload = self._get_json(path)
        except requests.RequestException as exc:
            logger.warning("DEX Screener token pairs failed for %s: %s", chain, exc)
            return []
        return _as_list(payload)

    def _snapshot_from_seed(
        self, seed: dict[str, Any], pair: dict[str, Any] | None
    ) -> TokenSnapshot:
        if not pair:
            raw = seed.get("raw", {})
            return TokenSnapshot(
                chain=seed["chain"],
                token_address=seed["token_address"],
                symbol=str(raw.get("symbol") or "unknown"),
                name=str(raw.get("description") or raw.get("name") or "unknown"),
                source=seed["source"],
                event_type=seed["event_type"],
                is_boosted=bool(seed.get("is_boosted")),
                is_new=bool(seed.get("is_new")),
                raw=raw,
            )

        base_token = pair.get("baseToken") or {}
        txns = pair.get("txns") or {}
        volume = pair.get("volume") or {}
        price_change = pair.get("priceChange") or {}
        liquidity = pair.get("liquidity") or {}
        boosts = pair.get("boosts") or {}

        return TokenSnapshot(
            chain=str(pair.get("chainId") or seed["chain"]).lower(),
            token_address=seed["token_address"],
            symbol=str(base_token.get("symbol") or "unknown"),
            name=str(base_token.get("name") or "unknown"),
            source=seed["source"],
            event_type=seed["event_type"],
            price=_to_float(pair.get("priceUsd")),
            liquidity_usd=_to_float(liquidity.get("usd")),
            volume_5m=_to_float(volume.get("m5")),
            volume_1h=_to_float(volume.get("h1")),
            volume_24h=_to_float(volume.get("h24")),
            price_change_5m=_to_float(price_change.get("m5")),
            price_change_1h=_to_float(price_change.get("h1")),
            price_change_24h=_to_float(price_change.get("h24")),
            pair_address=pair.get("pairAddress"),
            dex=pair.get("dexId"),
            pool_created_at=_pair_created_at_to_iso(pair.get("pairCreatedAt")),
            is_boosted=bool(seed.get("is_boosted") or boosts.get("active")),
            is_new=bool(seed.get("is_new")),
            buys_5m=_to_int((txns.get("m5") or {}).get("buys")),
            sells_5m=_to_int((txns.get("m5") or {}).get("sells")),
            buys_1h=_to_int((txns.get("h1") or {}).get("buys")),
            sells_1h=_to_int((txns.get("h1") or {}).get("sells")),
            raw=pair,
        )

    def _token_address_from_pair(
        self, pair: dict[str, Any], candidates: list[str]
    ) -> str | None:
        candidate_set = {address.lower(): address for address in candidates}
        for token_key in ("baseToken", "quoteToken"):
            token = pair.get(token_key) or {}
            address = str(token.get("address") or "").lower()
            if address in candidate_set:
                return candidate_set[address]
        return None

    def _pair_rank(self, pair: dict[str, Any]) -> float:
        liquidity = _to_float((pair.get("liquidity") or {}).get("usd")) or 0
        volume = _to_float((pair.get("volume") or {}).get("h24")) or 0
        return liquidity + (volume * 0.2)

    def _chunks(self, values: list[str], size: int) -> list[list[str]]:
        return [values[index : index + size] for index in range(0, len(values), size)]
