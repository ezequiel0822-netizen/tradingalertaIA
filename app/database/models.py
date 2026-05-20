from dataclasses import dataclass, field


ALERT_TYPES = {
    "NEW_TOKEN",
    "BOOSTED_TOKEN",
    "TRENDING_POOL",
    "VOLUME_SPIKE",
    "LIQUIDITY_SPIKE",
    "PRICE_SPIKE",
    "SECURITY_RISK",
    "POSSIBLE_HONEYPOT",
    "WATCHLIST_MOVEMENT",
    "STOCK_MOVEMENT",
    "STOCK_BREAKOUT",
    "STOCK_DROP_RISK",
}


@dataclass
class TokenSnapshot:
    chain: str
    token_address: str
    category: str = "memecoin"
    symbol: str = "unknown"
    name: str = "unknown"
    source: str = "unknown"
    event_type: str = "WATCHLIST_MOVEMENT"
    price: float | None = None
    liquidity_usd: float | None = None
    volume_5m: float | None = None
    volume_1h: float | None = None
    volume_24h: float | None = None
    price_change_5m: float | None = None
    price_change_1h: float | None = None
    price_change_24h: float | None = None
    pair_address: str | None = None
    dex: str | None = None
    pool_created_at: str | None = None
    is_boosted: bool = False
    is_trending: bool = False
    is_new: bool = False
    buys_5m: int | None = None
    sells_5m: int | None = None
    buys_1h: int | None = None
    sells_1h: int | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class SecuritySummary:
    honeypot_status: str = "unknown"
    buy_tax: float | None = None
    sell_tax: float | None = None
    owner_status: str = "unknown"
    mint_risk: str = "unknown"
    blacklist_risk: str = "unknown"
    contract_risk: str = "unknown"
    is_critical: bool = False
    raw_summary: str = "unknown"


@dataclass
class ScoreResult:
    score: int
    risk_level: str
    reasons: list[str]
    critical_risk: bool = False


@dataclass
class EstimateResult:
    estimated_gain_pct: float
    estimated_loss_pct: float
    confidence: int
    label: str
    reasons: list[str]
    eligible_for_gain_alert: bool = False


@dataclass
class IntelligenceSummary:
    pattern_label: str = "unknown"
    pattern_score: int = 0
    news_label: str = "unknown"
    news_score: int = 0
    reasons: list[str] = field(default_factory=list)


@dataclass
class AlertRecord:
    token_id: int
    alert_type: str
    snapshot: TokenSnapshot
    app_version: str
    category: str
    score: int
    risk_level: str
    reasons: list[str]
    security: SecuritySummary
    estimate: EstimateResult
    intel_rank_bonus: float = 0.0
    sent_to_telegram: bool = False
    # Phase 3 v2.2.0: nombre de la strategy que generó la alerta (si aplica)
    strategy_name: str | None = None
    # Phase 3.5 v2.2.0: razonamiento de Claude (opcional)
    ai_reasoning: list[str] = field(default_factory=list)
