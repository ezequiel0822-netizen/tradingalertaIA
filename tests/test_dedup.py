from app.database.models import TokenSnapshot
from app.utils.dedup import should_send_deduped_alert


def test_dedup_blocks_duplicate_alert_inside_window() -> None:
    latest = {
        "score": 70,
        "risk_level": "yellow",
        "liquidity_usd": 50000,
        "volume_1h": 20000,
    }
    snapshot = TokenSnapshot(
        chain="base",
        token_address="0xabc",
        liquidity_usd=51000,
        volume_1h=21000,
    )

    allowed, reason = should_send_deduped_alert(
        latest, "TRENDING_POOL", 72, "yellow", snapshot
    )

    assert allowed is False
    assert "duplicada" in reason


def test_dedup_allows_large_score_increase() -> None:
    latest = {
        "score": 45,
        "risk_level": "watch",
        "liquidity_usd": 50000,
        "volume_1h": 20000,
    }
    snapshot = TokenSnapshot(
        chain="base",
        token_address="0xabc",
        liquidity_usd=51000,
        volume_1h=21000,
    )

    allowed, reason = should_send_deduped_alert(
        latest, "TRENDING_POOL", 70, "yellow", snapshot
    )

    assert allowed is True
    assert "20 puntos" in reason
