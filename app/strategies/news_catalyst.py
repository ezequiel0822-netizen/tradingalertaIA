"""News catalyst strategy: noticia positiva + precio confirma + volumen."""

from app.config.settings import Settings
from app.strategies.base import StrategyContext, StrategySignal


class NewsCatalystStrategy:
    name = "news_catalyst"
    enabled_setting_key = "enable_strategy_news_catalyst"

    def evaluate(
        self, ctx: StrategyContext, settings: Settings
    ) -> StrategySignal | None:
        # Phase 3 v2.2.0: permitir tambien forex y gold (catalizadores macro)
        if ctx.snapshot.category not in {"stock", "forex", "gold"}:
            return None
        if ctx.news_score < 20:
            return None
        pattern = ctx.pattern
        if pattern is None:
            return None
        if getattr(pattern, "trend", None) != "bullish":
            return None
        rel_vol = getattr(pattern, "relative_volume", None)
        if rel_vol is None or rel_vol < 1.5:
            return None

        entry = ctx.snapshot.price
        if entry is None or entry <= 0:
            return None
        atr_pct = getattr(pattern, "atr_pct", None) or 2.5

        stop = entry * (1 - (atr_pct * 2.0) / 100.0)
        tp1 = entry * (1 + (atr_pct * 2.0) / 100.0)
        tp2 = entry * (1 + (atr_pct * 4.0) / 100.0)

        confidence = 60 + min(20, ctx.news_score // 2) + min(10, int(rel_vol * 3))
        reasoning = [
            f"News score {ctx.news_score} ({ctx.news_label})",
            f"Trend bullish con vol {rel_vol:.1f}x",
            f"ATR {atr_pct:.2f}%",
        ]
        return StrategySignal(
            strategy_name=self.name,
            direction="long",
            entry=round(entry, 8),
            stop=round(stop, 8),
            targets=[round(tp1, 8), round(tp2, 8)],
            confidence=min(confidence, 95),
            reasoning=reasoning,
            time_horizon_hours=24,
        )
