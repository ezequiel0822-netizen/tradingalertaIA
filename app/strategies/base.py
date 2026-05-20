"""Base de strategies: contratos de input/output y Protocol Strategy.

Cada strategy implementa `evaluate(ctx, settings) -> StrategySignal | None`.
StrategyContext agrega snapshot + candles + pattern + pro + news + macro
para que las strategies decidan con toda la info en mano.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config.settings import Settings
from app.database.models import TokenSnapshot


@dataclass
class StrategyContext:
    snapshot: TokenSnapshot
    candles: list[dict[str, float]]
    pattern: Any | None  # TechnicalPattern de analyzers/technical_patterns
    pro: Any | None      # ProfessionalAnalysis de analyzers/pro_intelligence
    news_label: str = "no_recent_news"
    news_score: int = 0
    macro: dict = field(default_factory=dict)


@dataclass
class StrategySignal:
    strategy_name: str
    direction: str            # "long" | "short"
    entry: float
    stop: float
    targets: list[float]      # [tp1, tp2]
    confidence: int           # 0-100
    reasoning: list[str]
    time_horizon_hours: int   # 1, 6, 24, 48, 168


class Strategy(Protocol):
    name: str
    enabled_setting_key: str

    def evaluate(
        self, ctx: StrategyContext, settings: Settings
    ) -> StrategySignal | None: ...
