"""Tests para GeckoTerminal new_pools endpoint + filter por edad + caché/cooldown (v3.4.0)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import requests

from app.collectors.geckoterminal_collector import GeckoTerminalCollector
from tests.test_score import _settings


def _enable_early(base):
    return type(base)(
        **{
            **base.__dict__,
            "enable_early_memecoin_detection": True,
            "max_early_pool_age_hours": 6,
            "chains_to_monitor": ["solana"],
        }
    )


def _pool_payload(token_address: str, pool_age_hours: float) -> dict:
    """Genera un payload tipo GeckoTerminal /new_pools con 1 pool."""
    created_at = datetime.now(timezone.utc) - timedelta(hours=pool_age_hours)
    return {
        "data": [
            {
                "id": "solana_XYZ",
                "type": "pool",
                "attributes": {
                    "name": "TEST / SOL",
                    "address": "POOL_ADDR_123",
                    "pool_created_at": created_at.isoformat(),
                    "base_token_price_usd": "1.50",
                    "reserve_in_usd": "25000",
                    "volume_usd": {"m5": "500", "h1": "3000", "h24": "20000"},
                    "price_change_percentage": {"m5": "10", "h1": "30", "h24": "120"},
                    "transactions": {
                        "m5": {"buys": 12, "sells": 4},
                        "h1": {"buys": 60, "sells": 20},
                    },
                },
                "relationships": {
                    "base_token": {"data": {"id": token_address, "type": "token"}},
                    "dex": {"data": {"id": "raydium", "type": "dex"}},
                },
            }
        ],
        "included": [
            {
                "id": token_address,
                "type": "token",
                "attributes": {
                    "address": token_address,
                    "symbol": "TEST",
                    "name": "Test Token",
                },
            },
            {
                "id": "raydium",
                "type": "dex",
                "attributes": {"name": "Raydium"},
            },
        ],
    }


def test_new_pools_disabled_skips_endpoint() -> None:
    settings = _enable_early(_settings())
    settings = type(settings)(
        **{**settings.__dict__, "enable_early_memecoin_detection": False}
    )
    collector = GeckoTerminalCollector(settings)

    trending_response = MagicMock()
    trending_response.json.return_value = {"data": [], "included": []}
    trending_response.raise_for_status = MagicMock()

    with patch.object(collector.session, "get", return_value=trending_response) as mock_get:
        collector.collect()

    # Solo trending_pools fue llamado, NO new_pools
    urls = [c.args[0] for c in mock_get.call_args_list]
    assert any("trending_pools" in u for u in urls)
    assert not any("new_pools" in u for u in urls)


def test_new_pools_filters_old_by_age() -> None:
    settings = _enable_early(_settings())
    collector = GeckoTerminalCollector(settings)

    def fake_get(url, **kwargs):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if "new_pools" in url:
            # Pool muy viejo (24h) — debe filtrarse
            response.json.return_value = _pool_payload("solana_oldcoin", pool_age_hours=24)
        else:  # trending_pools
            response.json.return_value = {"data": [], "included": []}
        return response

    with patch.object(collector.session, "get", side_effect=fake_get):
        snapshots = collector.collect()

    # Pool > max_early_pool_age_hours (6h) → no debe aparecer
    addresses = [s.token_address for s in snapshots]
    assert "solana_oldcoin" not in addresses


def test_new_pools_includes_young_token_with_event_type() -> None:
    settings = _enable_early(_settings())
    collector = GeckoTerminalCollector(settings)

    def fake_get(url, **kwargs):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if "new_pools" in url:
            response.json.return_value = _pool_payload(
                "solana_younggem", pool_age_hours=2
            )
        else:
            response.json.return_value = {"data": [], "included": []}
        return response

    with patch.object(collector.session, "get", side_effect=fake_get):
        snapshots = collector.collect()

    young = [s for s in snapshots if s.token_address == "solana_younggem"]
    assert len(young) == 1
    assert young[0].event_type == "EARLY_MEMECOIN"
    assert young[0].is_new is True


def test_new_pools_dedup_with_trending() -> None:
    """Si un mismo token aparece en trending Y new_pools, no se duplica."""
    settings = _enable_early(_settings())
    collector = GeckoTerminalCollector(settings)

    def fake_get(url, **kwargs):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        # Mismo token en ambos endpoints
        response.json.return_value = _pool_payload("solana_dup", pool_age_hours=2)
        return response

    with patch.object(collector.session, "get", side_effect=fake_get):
        snapshots = collector.collect()

    matches = [s for s in snapshots if s.token_address == "solana_dup"]
    assert len(matches) == 1


# ----------------------- v3.4.0: caché + cooldown 429 --------------------- #
def test_list_cache_avoids_refetch_within_ttl() -> None:
    """El 2do collect() dentro del TTL sirve del caché y NO vuelve a pegarle a la API."""
    settings = _enable_early(_settings())
    collector = GeckoTerminalCollector(settings)

    def fake_get(url, **kwargs):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = _pool_payload("solana_cached", pool_age_hours=2)
        return r

    with patch.object(collector.session, "get", side_effect=fake_get) as mock_get:
        collector.collect()
        first = mock_get.call_count          # trending + new_pools (1 chain) = 2
        collector.collect()                  # dentro del TTL -> 0 llamadas nuevas
        second = mock_get.call_count
    assert first == 2
    assert second == first  # el 2do ciclo no pego a GeckoTerminal


def test_429_sets_cooldown_and_serves_stale_cache() -> None:
    """Un 429 NO devuelve [] si hay caché previo: sirve el ultimo conocido + arma cooldown."""
    settings = _enable_early(_settings())
    collector = GeckoTerminalCollector(settings)

    ok = MagicMock()
    ok.raise_for_status = MagicMock()
    ok.json.return_value = _pool_payload("solana_warm", pool_age_hours=2)
    with patch.object(collector.session, "get", return_value=ok):
        first = collector.collect()
    assert any(s.token_address == "solana_warm" for s in first)

    # Vencer el TTL para forzar que intente la red, y simular 429 en todas.
    collector._list_cache = {k: (0.0, v[1]) for k, v in collector._list_cache.items()}
    err = requests.HTTPError()
    err.response = MagicMock(status_code=429)
    bad = MagicMock()
    bad.raise_for_status = MagicMock(side_effect=err)
    with patch.object(collector.session, "get", return_value=bad):
        second = collector.collect()

    assert any(s.token_address == "solana_warm" for s in second)  # sirvio stale, no []
    assert collector._list_cooldown_until > 0  # quedo en cooldown
