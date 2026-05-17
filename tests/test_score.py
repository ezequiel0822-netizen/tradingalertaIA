from pathlib import Path

from app.config.settings import Settings
from app.database.models import SecuritySummary, TokenSnapshot
from app.analyzers.token_score import score_token


def _settings() -> Settings:
    return Settings(
        app_version="v1.5",
        telegram_bot_token=None,
        telegram_chat_id=None,
        dexscreener_base_url="https://api.dexscreener.com",
        geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
        goplus_base_url="https://api.gopluslabs.io/api/v1",
        min_liquidity_usd=10000,
        min_volume_5m_usd=5000,
        min_volume_1h_usd=15000,
        alert_score_threshold=65,
        critical_risk_alerts=True,
        poll_interval_seconds=60,
        max_alerts_per_run=10,
        dedup_window_minutes=60,
        max_snapshots_per_run=80,
        max_security_checks_per_run=25,
        min_estimated_gain_pct=500,
        min_estimate_confidence=45,
        alert_critical_risks_without_gain=False,
        memecoin_max_alerts_per_24h=5,
        stock_max_alerts_per_24h=5,
        memecoin_max_alerts_per_run=2,
        stock_max_alerts_per_run=2,
        alert_cap_window_hours=24,
        enable_stock_alerts=True,
        stock_symbols=["aapl", "msft"],
        min_stock_estimated_gain_pct=8,
        min_stock_estimate_confidence=55,
        enable_telegram_assistant=True,
        telegram_assistant_max_updates=10,
        enable_advanced_market_intel=True,
        enable_news_intel=True,
        max_chart_analyses_per_run=6,
        max_news_per_symbol=5,
        enable_obsidian_memory=False,
        obsidian_vault_path=Path("obsidian/tradingbot v.1"),
        chains_to_monitor=["ethereum", "base", "bsc", "solana"],
        sqlite_path=Path(":memory:"),
        request_timeout_seconds=15,
    )


def test_score_marks_critical_security() -> None:
    snapshot = TokenSnapshot(
        chain="ethereum",
        token_address="0xabc",
        symbol="TEST",
        liquidity_usd=50000,
        volume_5m=10000,
        volume_1h=30000,
        is_trending=True,
    )
    security = SecuritySummary(
        honeypot_status="possible_honeypot",
        is_critical=True,
        contract_risk="risky",
    )

    result = score_token(snapshot, security, _settings())

    assert result.critical_risk is True
    assert result.risk_level == "critical"
    assert 0 <= result.score <= 100


def test_score_rewards_liquidity_volume_and_security() -> None:
    snapshot = TokenSnapshot(
        chain="base",
        token_address="0xdef",
        symbol="GOOD",
        liquidity_usd=300000,
        volume_5m=10000,
        volume_1h=40000,
        volume_24h=200000,
        is_trending=True,
        buys_1h=80,
        sells_1h=40,
    )
    security = SecuritySummary(
        honeypot_status="not_detected",
        owner_status="ok",
        mint_risk="ok",
        blacklist_risk="ok",
        contract_risk="ok",
        raw_summary='{"risks":["none_detected"]}',
    )

    result = score_token(snapshot, security, _settings())

    assert result.score >= 80
    assert result.risk_level in {"orange", "red"}
