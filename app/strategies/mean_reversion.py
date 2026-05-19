"""Mean reversion: RSI extremo + ATR moderado."""

from app.config.settings import Settings
from app.strategies.base import StrategyContext, StrategySignal


class MeanReversionStrategy:
    name = "mean_reversion"
    enabled_setting_key = "enable_strategy_mean_reversion"

    def evaluate(
        self, ctx: StrategyContext, settings: Settings
    ) -> StrategySignal | None:
        pattern = ctx.pattern
        if pattern is None:
            return None
        rsi = getattr(pattern, "rsi", None)
        if rsi is None:
            return None
        atr_pct = getattr(pattern, "atr_pct", None)
        if atr_pct is None or atr_pct >= 5.0:
            return None
        if getattr(pattern, "label", "") in {
            "bullish_breakout",
            "bearish_breakdown",
        }:
            return None

        entry = ctx.snapshot.price
        if entry is None or entry <= 0:
            return None

        if rsi < 28:
            direction = "long"
            stop = entry * (1 - (atr_pct * 1.5) / 100.0)
            tp1 = entry * (1 + (atr_pct * 1.5) / 100.0)
            tp2 = entry * (1 + (atr_pct * 3.0) / 100.0)
        elif rsi > 72:
            direction = "short"
            stop = entry * (1 + (atr_pct * 1.5) / 100.0)
            tp1 = entry * (1 - (atr_pct * 1.5) / 100.0)
            tp2 = entry * (1 - (atr_pct * 3.0) / 100.0)
        else:
            return None

        confidence = 60 + min(25, int(abs(rsi - 50) * 0.7))
        reasoning = [
            f"RSI extremo ({rsi:.1f})",
            f"ATR {atr_pct:.2f}%",
            "Sin trend fuerte que pelear",
        ]
        return StrategySignal(
            strategy_name=self.name,
            direction=direction,
            entry=round(entry, 8),
            stop=round(stop, 8),
            targets=[round(tp1, 8), round(tp2, 8)],
            confidence=confidence,
            reasoning=reasoning,
            time_horizon_hours=6,
        )
