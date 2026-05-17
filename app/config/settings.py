import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
    max_chart_analyses_per_run: int
    max_news_per_symbol: int
    enable_obsidian_memory: bool
    obsidian_vault_path: Path
    chains_to_monitor: list[str]
    sqlite_path: Path
    request_timeout_seconds: int

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

    obsidian_value = os.getenv("OBSIDIAN_VAULT_PATH", "obsidian/tradingbot v.1")
    obsidian_vault_path = Path(obsidian_value)
    if not obsidian_vault_path.is_absolute():
        obsidian_vault_path = PROJECT_ROOT / obsidian_vault_path

    return Settings(
        app_version=os.getenv("APP_VERSION", "v1.5"),
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
        max_chart_analyses_per_run=_get_int("MAX_CHART_ANALYSES_PER_RUN", 6),
        max_news_per_symbol=_get_int("MAX_NEWS_PER_SYMBOL", 5),
        enable_obsidian_memory=_get_bool("ENABLE_OBSIDIAN_MEMORY", True),
        obsidian_vault_path=obsidian_vault_path,
        chains_to_monitor=_get_list(
            "CHAINS_TO_MONITOR", ["solana", "ethereum", "base", "bsc"]
        ),
        sqlite_path=sqlite_path,
        request_timeout_seconds=_get_int("REQUEST_TIMEOUT_SECONDS", 15),
    )
