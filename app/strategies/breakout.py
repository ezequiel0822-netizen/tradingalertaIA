"""Breakout strategy: precio rompe maximo reciente con volumen y ATR moderado."""

from app.config.settings import Settings
from app.strategies.base import StrategyContext, StrategySignal


class BreakoutStrategy:
    name = "breakout"
    enabled_setting_key = "enable_strategy_breakout"

    def evaluate(
        self, ctx: StrategyContext, settings: Settings
    ) -> StrategySignal | None:
        pattern = ctx.pattern
        if pattern is None:
            return None
        if pattern.label not in {"bullish_breakout", "trend_continuation_bullish"}:
            return None
        rel_vol = getattr(pattern, "relative_volume", None)
        if rel_vol is None or rel_vol < 2.0:
            return None
        atr_pct = getattr(pattern, "atr_pct", None)
        if atr_pct is None or atr_pct < 1.5 or atr_pct > 6.0:
            return None
        if getattr(pattern, "trend", None) != "bullish":
            return None
        rsi = getattr(pattern, "rsi", None)
        if rsi is not None and rsi > 78:
            return None

        entry = ctx.snapshot.price
        if entry is None or entry <= 0:
            return None

        stop = entry * (1 - (atr_pct * 2.0) / 100.0)
        tp1 = entry * (1 + (atr_pct * 2.0) / 100.0)
        tp2 = entry * (1 + (atr_pct * 4.0) / 100.0)

        confidence = min(95, 60 + int(rel_vol * 5) + int(pattern.score / 4))
        reasoning = [
            f"Breakout pattern ({pattern.label})",
            f"Relative volume {rel_vol:.1f}x",
            f"ATR {atr_pct:.2f}%",
        ]
        if rsi is not None:
            reasoning.append(f"RSI {rsi:.1f}")

        return StrategySignal(
            strategy_name=self.name,
            direction="long",
            entry=round(entry, 8),
            stop=round(stop, 8),
            targets=[round(tp1, 8), round(tp2, 8)],
            confidence=confidence,
            reasoning=reasoning,
            time_horizon_hours=24,
        )
