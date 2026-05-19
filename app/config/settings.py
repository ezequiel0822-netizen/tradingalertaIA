import logging
import os
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]

_logger = logging.getLogger(__name__)

# Campos que jamas deben aparecer en repr/log.
_SECRET_FIELDS = frozenset({
    "telegram_bot_token",
    "telegram_chat_id",
    "mt5_login",
    "mt5_password",
    "mt5_server",
    "anthropic_api_key",
})

# Campos con paths que solo se muestran como nombre de archivo (no path absoluto).
_PATH_FIELDS = frozenset({
    "sqlite_path",
    "obsidian_vault_path",
    "mt5_path",
})


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _get_optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    app_version: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    dexscreener_base_url: str
    geckoterminal_base_url: str
    goplus_base_url: str
    min_liquidity_usd: float
    min_volume_5m_usd: float
    min_volume_1h_usd: float
    alert_score_threshold: int
    critical_risk_alerts: bool
    poll_interval_seconds: int
    max_alerts_per_run: int
    dedup_window_minutes: int
    max_snapshots_per_run: int
    max_security_checks_per_run: int
    min_estimated_gain_pct: float
    min_estimate_confidence: int
    alert_critical_risks_without_gain: bool
    memecoin_max_alerts_per_24h: int
    stock_max_alerts_per_24h: int
    memecoin_max_alerts_per_run: int
    stock_max_alerts_per_run: int
    alert_cap_window_hours: int
    enable_stock_alerts: bool
    stock_symbols: list[str]
    min_stock_estimated_gain_pct: float
    min_stock_estimate_confidence: int
    enable_telegram_assistant: bool
    telegram_assistant_max_updates: int
    enable_advanced_market_intel: bool
    enable_news_intel: bool
    enable_pro_intelligence: bool
    enable_sec_filings_intel: bool
    max_chart_analyses_per_run: int
    max_news_per_symbol: int
    max_sec_filings_per_run: int
    max_sec_filings_per_symbol: int
    sec_recent_days: int
    sec_user_agent: str
    enable_obsidian_memory: bool
    obsidian_vault_path: Path
    enable_learning_engine: bool
    learning_min_alert_age_minutes: int
    learning_max_alerts_per_run: int
    enable_paper_trading: bool
    paper_trade_max_active: int
    readiness_min_score: int
    readiness_min_confidence: int
    outcome_win_return_memecoin_pct: float
    outcome_win_return_stock_pct: float
    outcome_loss_return_memecoin_pct: float
    outcome_loss_return_stock_pct: float
    chains_to_monitor: list[str]
    sqlite_path: Path
    request_timeout_seconds: int
    enable_price_snapshots: bool
    snapshot_retention_days: int
    horizon_min_snapshots: int
    enable_horizon_evaluator: bool
    backtest_min_samples: int
    backtest_default_horizon_hours: int
    enable_weekly_obsidian_report: bool
    enable_atr_based_sltp: bool
    atr_stop_multiplier: float
    atr_tp1_multiplier: float
    atr_tp2_multiplier: float
    enable_trailing_stop: bool
    trailing_activation_pct_stock: float
    trailing_activation_pct_memecoin: float
    trailing_distance_pct_stock: float
    trailing_distance_pct_memecoin: float
    enable_learned_weights: bool
    learned_weights_min_samples: int
    learned_weights_min_confidence: int
    learned_weights_per_feature_max: float
    learned_weights_max_adjustment: float
    enable_learning_gate: bool
    learning_gate_min_win_rate: float
    learning_gate_min_samples: int
    learning_gate_horizon_hours: int
    learning_gate_since_days: int
    enable_forex_collector: bool
    forex_symbols: list[str]
    # Fase 2.5 v2.0.0 - trader engine + MT5 reader
    account_starting_balance: float
    max_open_trades_total: int
    max_open_trades_stock: int
    max_open_trades_forex: int
    max_open_trades_gold: int
    risk_per_trade_pct: float
    max_total_risk_pct: float
    max_daily_drawdown_pct: float
    kill_switch_cooldown_hours: int
    enable_kill_switch_auto: bool
    enable_strategy_router: bool
    strategy_min_confidence: int
    enable_strategy_breakout: bool
    enable_strategy_mean_reversion: bool
    enable_strategy_momentum: bool
    enable_strategy_news_catalyst: bool
    enable_partial_close_at_tp1: bool
    partial_close_fraction: float
    enable_time_based_exit: bool
    default_time_horizon_hours: int
    enable_invalidation_exit: bool
    lifecycle_reeval_every_n_cycles: int
    enable_memecoin_telegram: bool
    enable_mt5_reader: bool
    mt5_path: str | None
    mt5_login: int | None
    mt5_password: str | None
    mt5_server: str | None
    mt5_connection_timeout_ms: int
    enable_macro_context: bool
    enable_trade_action_reports: bool
    # Phase 3 + 3.5 v2.2.0 — forex price-action + LLM integration
    enable_macro_collector: bool
    macro_collector_interval_minutes: int
    enable_economic_calendar: bool
    calendar_buffer_minutes: int
    calendar_refresh_hours: int
    enable_strategy_forex_session_breakout: bool
    enable_forex_alerts: bool
    enable_gold_alerts: bool
    max_forex_alerts_per_24h: int
    max_gold_alerts_per_24h: int
    max_forex_alerts_per_run: int
    max_gold_alerts_per_run: int
    anthropic_api_key: str | None
    enable_claude_integration: bool
    claude_model: str
    claude_max_tokens: int
    claude_calls_per_cycle_cap: int
    claude_cache_ttl_seconds: int
    claude_max_cost_per_day_usd: float

    def __repr__(self) -> str:
        parts: list[str] = []
        for f in fields(self):
            val = getattr(self, f.name)
            if f.name in _SECRET_FIELDS:
                shown = "<redacted>" if val not in (None, "") else "<unset>"
            elif f.name in _PATH_FIELDS:
                # Mostrar solo el basename para evitar filesystem leak
                if val is None:
                    shown = "None"
                else:
                    try:
                        shown = repr(Path(val).name)
                    except (TypeError, ValueError):
                        shown = "<path>"
            else:
                shown = repr(val)
            parts.append(f"{f.name}={shown}")
        return f"Settings({', '.join(parts)})"

    @property
    def geckoterminal_networks(self) -> dict[str, str]:
        return {
            "ethereum": "eth",
            "eth": "eth",
            "base": "base",
            "bsc": "bsc",
            "binance": "bsc",
            "solana": "solana",
        }

    @property
    def goplus_chain_ids(self) -> dict[str, str]:
        return {
            "ethereum": "1",
            "eth": "1",
            "bsc": "56",
            "binance": "56",
            "base": "8453",
        }


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    sqlite_value = os.getenv("SQLITE_PATH", "trading_alert_ai.db")
    sqlite_path = Path(sqlite_value)
    if not sqlite_path.is_absolute():
        sqlite_path = PROJECT_ROOT / sqlite_path

    # Import local para evitar ciclo en startup
    from app.utils.safe_path import safe_optional_file, safe_resolve_within

    obsidian_value = os.getenv("OBSIDIAN_VAULT_PATH", "obsidian/tradingbot v.1")
    obsidian_vault_path = Path(obsidian_value)
    if not obsidian_vault_path.is_absolute():
        obsidian_vault_path = PROJECT_ROOT / obsidian_vault_path
    # Bloquear path traversal (../../...) — fallback al default si OBSIDIAN_VAULT_PATH escapa PROJECT_ROOT
    safe_obsidian = safe_resolve_within(obsidian_vault_path, PROJECT_ROOT)
    if safe_obsidian is None:
        _logger.warning(
            "OBSIDIAN_VAULT_PATH escapa PROJECT_ROOT; usando default."
        )
        obsidian_vault_path = PROJECT_ROOT / "obsidian" / "tradingbot v.1"
    else:
        obsidian_vault_path = safe_obsidian

    return Settings(
        app_version=os.getenv("APP_VERSION", "v2.2.0"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        dexscreener_base_url=os.getenv(
            "DEXSCREENER_BASE_URL", "https://api.dexscreener.com"
        ).rstrip("/"),
        geckoterminal_base_url=os.getenv(
            "GECKOTERMINAL_BASE_URL", "https://api.geckoterminal.com/api/v2"
        ).rstrip("/"),
        goplus_base_url=os.getenv(
            "GOPLUS_BASE_URL", "https://api.gopluslabs.io/api/v1"
        ).rstrip("/"),
        min_liquidity_usd=_get_float("MIN_LIQUIDITY_USD", 10000),
        min_volume_5m_usd=_get_float("MIN_VOLUME_5M_USD", 5000),
        min_volume_1h_usd=_get_float("MIN_VOLUME_1H_USD", 15000),
        alert_score_threshold=_get_int("ALERT_SCORE_THRESHOLD", 65),
        critical_risk_alerts=_get_bool("CRITICAL_RISK_ALERTS", True),
        poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 60),
        max_alerts_per_run=_get_int("MAX_ALERTS_PER_RUN", 10),
        dedup_window_minutes=_get_int("DEDUP_WINDOW_MINUTES", 360),
        max_snapshots_per_run=_get_int("MAX_SNAPSHOTS_PER_RUN", 80),
        max_security_checks_per_run=_get_int("MAX_SECURITY_CHECKS_PER_RUN", 25),
        min_estimated_gain_pct=_get_float("MIN_ESTIMATED_GAIN_PCT", 500),
        min_estimate_confidence=_get_int("MIN_ESTIMATE_CONFIDENCE", 45),
        alert_critical_risks_without_gain=_get_bool(
            "ALERT_CRITICAL_RISKS_WITHOUT_GAIN", False
        ),
        memecoin_max_alerts_per_24h=_get_int("MEMECOIN_MAX_ALERTS_PER_24H", 5),
        stock_max_alerts_per_24h=_get_int("STOCK_MAX_ALERTS_PER_24H", 5),
        memecoin_max_alerts_per_run=_get_int("MEMECOIN_MAX_ALERTS_PER_RUN", 2),
        stock_max_alerts_per_run=_get_int("STOCK_MAX_ALERTS_PER_RUN", 2),
        alert_cap_window_hours=_get_int("ALERT_CAP_WINDOW_HOURS", 24),
        enable_stock_alerts=_get_bool("ENABLE_STOCK_ALERTS", True),
        stock_symbols=_get_list(
            "STOCK_SYMBOLS",
            [
                "aapl",
                "msft",
                "nvda",
                "tsla",
                "amd",
                "meta",
                "amzn",
                "googl",
                "spy",
                "qqq",
                "coin",
                "mstr",
                "pltr",
                "smci",
            ],
        ),
        min_stock_estimated_gain_pct=_get_float("MIN_STOCK_ESTIMATED_GAIN_PCT", 8),
        min_stock_estimate_confidence=_get_int("MIN_STOCK_ESTIMATE_CONFIDENCE", 55),
        enable_telegram_assistant=_get_bool("ENABLE_TELEGRAM_ASSISTANT", True),
        telegram_assistant_max_updates=_get_int("TELEGRAM_ASSISTANT_MAX_UPDATES", 10),
        enable_advanced_market_intel=_get_bool("ENABLE_ADVANCED_MARKET_INTEL", True),
        enable_news_intel=_get_bool("ENABLE_NEWS_INTEL", True),
        enable_pro_intelligence=_get_bool("ENABLE_PRO_INTELLIGENCE", True),
        enable_sec_filings_intel=_get_bool("ENABLE_SEC_FILINGS_INTEL", True),
        max_chart_analyses_per_run=_get_int("MAX_CHART_ANALYSES_PER_RUN", 6),
        max_news_per_symbol=_get_int("MAX_NEWS_PER_SYMBOL", 5),
        max_sec_filings_per_run=_get_int("MAX_SEC_FILINGS_PER_RUN", 6),
        max_sec_filings_per_symbol=_get_int("MAX_SEC_FILINGS_PER_SYMBOL", 5),
        sec_recent_days=_get_int("SEC_RECENT_DAYS", 14),
        sec_user_agent=os.getenv(
            "SEC_USER_AGENT",
            "TradingAlertAI/1.5.1 local-read-only contact@example.com",
        ),
        enable_obsidian_memory=_get_bool("ENABLE_OBSIDIAN_MEMORY", True),
        obsidian_vault_path=obsidian_vault_path,
        enable_learning_engine=_get_bool("ENABLE_LEARNING_ENGINE", True),
        learning_min_alert_age_minutes=_get_int("LEARNING_MIN_ALERT_AGE_MINUTES", 60),
        learning_max_alerts_per_run=_get_int("LEARNING_MAX_ALERTS_PER_RUN", 300),
        enable_paper_trading=_get_bool("ENABLE_PAPER_TRADING", True),
        paper_trade_max_active=_get_int("PAPER_TRADE_MAX_ACTIVE", 20),
        readiness_min_score=_get_int("READINESS_MIN_SCORE", 75),
        readiness_min_confidence=_get_int("READINESS_MIN_CONFIDENCE", 65),
        outcome_win_return_memecoin_pct=_get_float("OUTCOME_WIN_RETURN_MEMECOIN_PCT", 100),
        outcome_win_return_stock_pct=_get_float("OUTCOME_WIN_RETURN_STOCK_PCT", 5),
        outcome_loss_return_memecoin_pct=_get_float("OUTCOME_LOSS_RETURN_MEMECOIN_PCT", -40),
        outcome_loss_return_stock_pct=_get_float("OUTCOME_LOSS_RETURN_STOCK_PCT", -3),
        chains_to_monitor=_get_list(
            "CHAINS_TO_MONITOR", ["solana", "ethereum", "base", "bsc"]
        ),
        sqlite_path=sqlite_path,
        request_timeout_seconds=_get_int("REQUEST_TIMEOUT_SECONDS", 15),
        enable_price_snapshots=_get_bool("ENABLE_PRICE_SNAPSHOTS", True),
        snapshot_retention_days=_get_int("SNAPSHOT_RETENTION_DAYS", 30),
        horizon_min_snapshots=_get_int("HORIZON_MIN_SNAPSHOTS", 2),
        enable_horizon_evaluator=_get_bool("ENABLE_HORIZON_EVALUATOR", True),
        backtest_min_samples=_get_int("BACKTEST_MIN_SAMPLES", 5),
        backtest_default_horizon_hours=_get_int(
            "BACKTEST_DEFAULT_HORIZON_HOURS", 24
        ),
        enable_weekly_obsidian_report=_get_bool(
            "ENABLE_WEEKLY_OBSIDIAN_REPORT", True
        ),
        enable_atr_based_sltp=_get_bool("ENABLE_ATR_BASED_SLTP", True),
        atr_stop_multiplier=_get_float("ATR_STOP_MULTIPLIER", 2.0),
        atr_tp1_multiplier=_get_float("ATR_TP1_MULTIPLIER", 2.0),
        atr_tp2_multiplier=_get_float("ATR_TP2_MULTIPLIER", 4.0),
        enable_trailing_stop=_get_bool("ENABLE_TRAILING_STOP", True),
        trailing_activation_pct_stock=_get_float(
            "TRAILING_ACTIVATION_PCT_STOCK", 5.0
        ),
        trailing_activation_pct_memecoin=_get_float(
            "TRAILING_ACTIVATION_PCT_MEMECOIN", 50.0
        ),
        trailing_distance_pct_stock=_get_float("TRAILING_DISTANCE_PCT_STOCK", 3.0),
        trailing_distance_pct_memecoin=_get_float(
            "TRAILING_DISTANCE_PCT_MEMECOIN", 25.0
        ),
        enable_learned_weights=_get_bool("ENABLE_LEARNED_WEIGHTS", False),
        learned_weights_min_samples=_get_int("LEARNED_WEIGHTS_MIN_SAMPLES", 5),
        learned_weights_min_confidence=_get_int(
            "LEARNED_WEIGHTS_MIN_CONFIDENCE", 40
        ),
        learned_weights_per_feature_max=_get_float(
            "LEARNED_WEIGHTS_PER_FEATURE_MAX", 3.0
        ),
        learned_weights_max_adjustment=_get_float(
            "LEARNED_WEIGHTS_MAX_ADJUSTMENT", 10.0
        ),
        enable_learning_gate=_get_bool("ENABLE_LEARNING_GATE", False),
        learning_gate_min_win_rate=_get_float("LEARNING_GATE_MIN_WIN_RATE", 0.45),
        learning_gate_min_samples=_get_int("LEARNING_GATE_MIN_SAMPLES", 10),
        learning_gate_horizon_hours=_get_int("LEARNING_GATE_HORIZON_HOURS", 24),
        learning_gate_since_days=_get_int("LEARNING_GATE_SINCE_DAYS", 30),
        enable_forex_collector=_get_bool("ENABLE_FOREX_COLLECTOR", True),
        forex_symbols=_get_list(
            "FOREX_SYMBOLS",
            [
                "EURUSD=X",
                "GBPUSD=X",
                "USDJPY=X",
                "USDCHF=X",
                "AUDUSD=X",
                "USDCAD=X",
                "NZDUSD=X",
                "GC=F",
            ],
        ),
        # Fase 2.5 v2.0.0 - trader engine + MT5 reader
        account_starting_balance=_get_float("ACCOUNT_STARTING_BALANCE", 10000.0),
        max_open_trades_total=_get_int("MAX_OPEN_TRADES_TOTAL", 5),
        max_open_trades_stock=_get_int("MAX_OPEN_TRADES_STOCK", 3),
        max_open_trades_forex=_get_int("MAX_OPEN_TRADES_FOREX", 4),
        max_open_trades_gold=_get_int("MAX_OPEN_TRADES_GOLD", 2),
        risk_per_trade_pct=_get_float("RISK_PER_TRADE_PCT", 1.0),
        max_total_risk_pct=_get_float("MAX_TOTAL_RISK_PCT", 6.0),
        max_daily_drawdown_pct=_get_float("MAX_DAILY_DRAWDOWN_PCT", 3.0),
        kill_switch_cooldown_hours=_get_int("KILL_SWITCH_COOLDOWN_HOURS", 24),
        enable_kill_switch_auto=_get_bool("ENABLE_KILL_SWITCH_AUTO", True),
        enable_strategy_router=_get_bool("ENABLE_STRATEGY_ROUTER", True),
        strategy_min_confidence=_get_int("STRATEGY_MIN_CONFIDENCE", 60),
        enable_strategy_breakout=_get_bool("ENABLE_STRATEGY_BREAKOUT", True),
        enable_strategy_mean_reversion=_get_bool(
            "ENABLE_STRATEGY_MEAN_REVERSION", True
        ),
        enable_strategy_momentum=_get_bool("ENABLE_STRATEGY_MOMENTUM", True),
        enable_strategy_news_catalyst=_get_bool(
            "ENABLE_STRATEGY_NEWS_CATALYST", True
        ),
        enable_partial_close_at_tp1=_get_bool("ENABLE_PARTIAL_CLOSE_AT_TP1", True),
        partial_close_fraction=_get_float("PARTIAL_CLOSE_FRACTION", 0.5),
        enable_time_based_exit=_get_bool("ENABLE_TIME_BASED_EXIT", True),
        default_time_horizon_hours=_get_int("DEFAULT_TIME_HORIZON_HOURS", 48),
        enable_invalidation_exit=_get_bool("ENABLE_INVALIDATION_EXIT", True),
        lifecycle_reeval_every_n_cycles=_get_int(
            "LIFECYCLE_REEVAL_EVERY_N_CYCLES", 5
        ),
        enable_memecoin_telegram=_get_bool("ENABLE_MEMECOIN_TELEGRAM", False),
        enable_mt5_reader=_get_bool("ENABLE_MT5_READER", False),
        # mt5_path validado: solo paths absolutos a archivo existente (None si invalido)
        mt5_path=str(safe_optional_file(os.getenv("MT5_PATH"))) if safe_optional_file(os.getenv("MT5_PATH")) else None,
        mt5_login=_get_optional_int("MT5_LOGIN"),
        mt5_password=os.getenv("MT5_PASSWORD") or None,
        mt5_server=os.getenv("MT5_SERVER") or None,
        mt5_connection_timeout_ms=_get_int("MT5_CONNECTION_TIMEOUT_MS", 5000),
        enable_macro_context=_get_bool("ENABLE_MACRO_CONTEXT", True),
        enable_trade_action_reports=_get_bool("ENABLE_TRADE_ACTION_REPORTS", True),
        # Phase 3 + 3.5 v2.2.0
        enable_macro_collector=_get_bool("ENABLE_MACRO_COLLECTOR", True),
        macro_collector_interval_minutes=_get_int(
            "MACRO_COLLECTOR_INTERVAL_MINUTES", 60
        ),
        enable_economic_calendar=_get_bool("ENABLE_ECONOMIC_CALENDAR", True),
        calendar_buffer_minutes=_get_int("CALENDAR_BUFFER_MINUTES", 30),
        calendar_refresh_hours=_get_int("CALENDAR_REFRESH_HOURS", 12),
        enable_strategy_forex_session_breakout=_get_bool(
            "ENABLE_STRATEGY_FOREX_SESSION_BREAKOUT", True
        ),
        enable_forex_alerts=_get_bool("ENABLE_FOREX_ALERTS", True),
        enable_gold_alerts=_get_bool("ENABLE_GOLD_ALERTS", True),
        max_forex_alerts_per_24h=_get_int("MAX_FOREX_ALERTS_PER_24H", 3),
        max_gold_alerts_per_24h=_get_int("MAX_GOLD_ALERTS_PER_24H", 2),
        max_forex_alerts_per_run=_get_int("MAX_FOREX_ALERTS_PER_RUN", 1),
        max_gold_alerts_per_run=_get_int("MAX_GOLD_ALERTS_PER_RUN", 1),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        enable_claude_integration=_get_bool("ENABLE_CLAUDE_INTEGRATION", False),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5"),
        claude_max_tokens=_get_int("CLAUDE_MAX_TOKENS", 1024),
        claude_calls_per_cycle_cap=_get_int("CLAUDE_CALLS_PER_CYCLE_CAP", 6),
        claude_cache_ttl_seconds=_get_int("CLAUDE_CACHE_TTL_SECONDS", 3600),
        claude_max_cost_per_day_usd=_get_float("CLAUDE_MAX_COST_PER_DAY_USD", 2.0),
    )
