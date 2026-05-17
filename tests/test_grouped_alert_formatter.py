from app.alerts.alert_formatter import format_grouped_telegram_alert
from app.database.models import AlertRecord, EstimateResult, SecuritySummary, TokenSnapshot


def _record(symbol: str, gain: float) -> AlertRecord:
    snapshot = TokenSnapshot(
        chain="base",
        token_address=f"0x{symbol.lower()}",
        category="memecoin",
        symbol=symbol,
        name=f"{symbol} Token",
        source="test",
        price=0.01,
        liquidity_usd=50_000,
        volume_1h=100_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=gain,
        estimated_loss_pct=45,
        confidence=70,
        label="high-conviction",
        reasons=["momentum"],
        eligible_for_gain_alert=True,
    )
    return AlertRecord(
        token_id=1,
        alert_type="TRENDING_POOL",
        snapshot=snapshot,
        app_version="v1.5",
        category="memecoin",
        score=82,
        risk_level="orange",
        reasons=["Candidato fuerte para revision manual."],
        security=SecuritySummary(raw_summary="unknown"),
        estimate=estimate,
    )


def test_grouped_alert_contains_multiple_candidates() -> None:
    message = format_grouped_telegram_alert(
        [_record("AAA", 650), _record("BBB", 540)],
        "memecoin",
        "v1.5",
    )

    assert "Trading Alert AI v1.5" in message
    assert "TOP MEMECOINS" in message
    assert "1. AAA" in message
    assert "2. BBB" in message
    assert message.count("No es recomendaci") == 1
