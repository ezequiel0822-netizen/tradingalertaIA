from pathlib import Path

from app.config.settings import Settings
from app.database.models import SecuritySummary, TokenSnapshot
from app.analyzers.token_score import score_token


def _settings() -> Settings:
    return Settings(
        app_version="v1.5.1",
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
        enable_pro_intelligence=True,
        enable_sec_filings_intel=True,
        max_chart_analyses_per_run=6,
        max_news_per_symbol=5,
        max_sec_filings_per_run=6,
        max_sec_filings_per_symbol=5,
        sec_recent_days=14,
        sec_user_agent="TradingAlertAI tests",
        enable_obsidian_memory=False,
        obsidian_vault_path=Path("obsidian/tradingbot v.1"),
        enable_learning_engine=True,
        learning_min_alert_age_minutes=60,
        learning_max_alerts_per_run=300,
        enable_paper_trading=True,
        paper_trade_max_active=20,
        readiness_min_score=75,
        readiness_min_confidence=65,
        outcome_win_return_memecoin_pct=100,
        outcome_win_return_stock_pct=5,
        outcome_loss_return_memecoin_pct=-40,
        outcome_loss_return_stock_pct=-3,
        chains_to_monitor=["ethereum", "base", "bsc", "solana"],
        sqlite_path=Path(":memory:"),
        request_timeout_seconds=15,
        enable_price_snapshots=True,
        snapshot_retention_days=30,
        horizon_min_snapshots=2,
        enable_horizon_evaluator=True,
        backtest_min_samples=5,
        backtest_default_horizon_hours=24,
        enable_weekly_obsidian_report=False,
        enable_atr_based_sltp=True,
        atr_stop_multiplier=2.0,
        atr_tp1_multiplier=2.0,
        atr_tp2_multiplier=4.0,
        enable_trailing_stop=True,
        trailing_activation_pct_stock=5.0,
        trailing_activation_pct_memecoin=50.0,
        trailing_distance_pct_stock=3.0,
        trailing_distance_pct_memecoin=25.0,
        enable_learned_weights=False,
        learned_weights_min_samples=5,
        learned_weights_min_confidence=40,
        learned_weights_per_feature_max=3.0,
        learned_weights_max_adjustment=10.0,
        enable_learning_gate=False,
        learning_gate_min_win_rate=0.45,
        learning_gate_min_samples=10,
        learning_gate_horizon_hours=24,
        learning_gate_since_days=30,
        enable_forex_collector=False,
        forex_symbols=["eurusd=x", "gc=f"],
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
