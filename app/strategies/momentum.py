"""Momentum strategy: MACD alcista + medias alineadas + RSI mid-range."""

from app.config.settings import Settings
from app.strategies.base import StrategyContext, StrategySignal


class MomentumStrategy:
    name = "momentum"
    enabled_setting_key = "enable_strategy_momentum"

    def evaluate(
        self, ctx: StrategyContext, settings: Settings
    ) -> StrategySignal | None:
        pattern = ctx.pattern
        if pattern is None:
            return None
        macd = getattr(pattern, "macd", None)
        macd_signal = getattr(pattern, "macd_signal", None)
        if macd is None or macd_signal is None:
            return None
        if not (macd > macd_signal and macd > 0):
            return None
        if getattr(pattern, "trend", None) != "bullish":
            return None
        rsi = getattr(pattern, "rsi", None)
        if rsi is None or not (50 <= rsi <= 70):
            return None
        atr_pct = getattr(pattern, "atr_pct", None)
        if atr_pct is None or atr_pct > 8.0:
            return None

        # confirma con pro analysis si esta presente
        pro = ctx.pro
        if pro is not None:
            bias = getattr(pro, "bias", "")
            if bias and bias not in {"bullish", "neutral_bullish"}:
                return None

        entry = ctx.snapshot.price
        if entry is None or entry <= 0:
            return None

        atr_effective = atr_pct if atr_pct > 0 else 2.0
        stop = entry * (1 - (atr_effective * 2.0) / 100.0)
        tp1 = entry * (1 + (atr_effective * 2.0) / 100.0)
        tp2 = entry * (1 + (atr_effective * 4.0) / 100.0)

        confidence = 60 + min(25, int(pattern.score / 4)) + (5 if pro else 0)
        # Phase 3 v2.2.0: bonus risk_on
        macro = ctx.macro or {}
        if macro.get("regime") == "risk_on":
            confidence = min(95, confidence + 10)
        reasoning = [
            f"MACD alcista ({macd:.4f} > {macd_signal:.4f})",
            f"RSI {rsi:.1f} (mid-range)",
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
            time_horizon_hours=48,
        )
