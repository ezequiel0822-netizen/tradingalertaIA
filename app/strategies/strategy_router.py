"""Strategy router: pregunta a cada strategy habilitada, devuelve signals validas."""

import logging

from app.config.settings import Settings
from app.strategies.base import Strategy, StrategyContext, StrategySignal
from app.strategies.breakout import BreakoutStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.momentum import MomentumStrategy
from app.strategies.news_catalyst import NewsCatalystStrategy


logger = logging.getLogger(__name__)


class StrategyRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.strategies: list[Strategy] = []
        all_strategies: list[Strategy] = [
            BreakoutStrategy(),
            MeanReversionStrategy(),
            MomentumStrategy(),
            NewsCatalystStrategy(),
        ]
        for s in all_strategies:
            if getattr(settings, s.enabled_setting_key, False):
                self.strategies.append(s)

    def route(
        self, ctx: StrategyContext, settings: Settings | None = None
    ) -> list[StrategySignal]:
        st = settings or self.settings
        signals: list[StrategySignal] = []
        for s in self.strategies:
            try:
                sig = s.evaluate(ctx, st)
            except Exception:
                logger.exception("Strategy %s raised; skipping signal", s.name)
                continue
            if sig is None:
                continue
            if sig.confidence < st.strategy_min_confidence:
                continue
            signals.append(sig)
        return signals
