from app.analyzers.move_estimator import estimate_move
from app.database.models import SecuritySummary, TokenSnapshot
from tests.test_score import _settings


def test_estimator_marks_high_conviction_above_500_percent() -> None:
    settings = _settings()
    snapshot = TokenSnapshot(
        chain="base",
        token_address="0xabc",
        symbol="MOON",
        liquidity_usd=100000,
        volume_5m=25000,
        volume_1h=160000,
        volume_24h=500000,
        price_change_5m=18,
        price_change_1h=35,
        is_trending=True,
        buys_1h=90,
        sells_1h=45,
    )
    security = SecuritySummary(
        honeypot_status="not_detected",
        owner_status="ok",
        mint_risk="ok",
        blacklist_risk="ok",
        contract_risk="ok",
        raw_summary='{"risks":["none_detected"]}',
    )

    estimate = estimate_move(snapshot, security, score=85, settings=settings)

    assert estimate.estimated_gain_pct >= 500
    assert estimate.eligible_for_gain_alert is True


def test_estimator_blocks_critical_risk_even_with_momentum() -> None:
    settings = _settings()
    snapshot = TokenSnapshot(
        chain="ethereum",
        token_address="0xabc",
        liquidity_usd=100000,
        volume_5m=25000,
        volume_1h=160000,
        price_change_1h=50,
        is_trending=True,
    )
    security = SecuritySummary(
        honeypot_status="possible_honeypot",
        contract_risk="risky",
        is_critical=True,
    )

    estimate = estimate_move(snapshot, security, score=70, settings=settings)

    assert estimate.eligible_for_gain_alert is False
    assert estimate.estimated_loss_pct >= 90


def test_stock_estimator_uses_stock_threshold() -> None:
    settings = _settings()
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        liquidity_usd=800_000_000,
        volume_5m=20_000_000,
        volume_1h=120_000_000,
        volume_24h=1_500_000_000,
        price_change_5m=1.5,
        price_change_1h=3.5,
        price_change_24h=5.5,
    )
    security = SecuritySummary(raw_summary="unknown")

    estimate = estimate_move(snapshot, security, score=78, settings=settings)

    assert estimate.estimated_gain_pct >= settings.min_stock_estimated_gain_pct
    assert estimate.eligible_for_gain_alert is True


def test_estimator_penalizes_hype_with_low_liquidity() -> None:
    settings = _settings()
    snapshot = TokenSnapshot(
        chain="base",
        token_address="0xhype",
        symbol="HYPE",
        liquidity_usd=5_000,
        volume_5m=25_000,
        volume_1h=60_000,
        volume_24h=200_000,
        price_change_1h=140,
        price_change_24h=350,
        is_boosted=True,
        is_trending=True,
    )
    security = SecuritySummary(raw_summary="unknown")

    estimate = estimate_move(snapshot, security, score=85, settings=settings)

    assert estimate.eligible_for_gain_alert is False
    assert estimate.confidence < settings.min_estimate_confidence
    assert any("anti-hype" in reason for reason in estimate.reasons)
