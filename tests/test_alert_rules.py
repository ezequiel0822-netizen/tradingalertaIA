from pathlib import Path

from app.analyzers.alert_decision_engine import (
    candidate_for_security_check,
    should_send_alert,
)
from app.config.settings import Settings
from app.database.models import EstimateResult, TokenSnapshot


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


def test_alert_threshold_rules() -> None:
    settings = _settings()
    watch_only = EstimateResult(
        estimated_gain_pct=499,
        estimated_loss_pct=40,
        confidence=80,
        label="watch-only",
        reasons=[],
        eligible_for_gain_alert=False,
    )
    high_conviction = EstimateResult(
        estimated_gain_pct=500,
        estimated_loss_pct=40,
        confidence=80,
        label="high-conviction",
        reasons=[],
        eligible_for_gain_alert=True,
    )

    assert should_send_alert(90, False, watch_only, settings, "memecoin") is False
    assert should_send_alert(65, False, high_conviction, settings, "memecoin") is True
    assert should_send_alert(20, True, watch_only, settings, "memecoin") is False


def test_security_check_candidates_include_trending_and_volume() -> None:
    settings = _settings()

    trending = TokenSnapshot(
        chain="base",
        token_address="0xabc",
        event_type="TRENDING_POOL",
    )
    volume = TokenSnapshot(
        chain="base",
        token_address="0xdef",
        event_type="WATCHLIST_MOVEMENT",
        volume_1h=20000,
    )

    assert candidate_for_security_check(trending, settings) is True
    assert candidate_for_security_check(volume, settings) is True
