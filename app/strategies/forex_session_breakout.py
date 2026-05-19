"""Forex Session Breakout strategy.

Solo activa durante London/NY overlap (UTC 13-17). Calcula Asian range
high/low (00:00-08:00 UTC) y abre long si rompe el high, short si rompe el low.

Solo aplica a category forex y gold.
"""

from app.config.settings import Settings
from app.strategies.base import StrategyContext, StrategySignal


class ForexSessionBreakoutStrategy:
    name = "forex_session_breakout"
    enabled_setting_key = "enable_strategy_forex_session_breakout"

    def evaluate(
        self, ctx: StrategyContext, settings: Settings
    ) -> StrategySignal | None:
        if ctx.snapshot.category not in {"forex", "gold"}:
            return None
        macro = ctx.macro or {}
        # Solo durante London/NY overlap
        active = set(macro.get("active_sessions", []))
        if not ({"london", "ny"}.issubset(active)):
            return None

        candles = ctx.candles or []
        if len(candles) < 30:
            return None

        # Calcular Asian range (primeras ~32 velas si interval=15m → 8h)
        # Si los candles son del dia, asumimos que las primeras son sesion asiatica.
        asian_slice = candles[: min(32, len(candles) // 2)]
        asian_high = max((c.get("high") or c.get("close") or 0) for c in asian_slice)
        asian_low = min(
            (c.get("low") or c.get("close") or 1e9)
            for c in asian_slice if c.get("low") is not None
        )
        if asian_high <= 0 or asian_low >= 1e9:
            return None

        entry = ctx.snapshot.price
        if entry is None or entry <= 0:
            return None

        pattern = ctx.pattern
        atr_pct = getattr(pattern, "atr_pct", None) if pattern else None
        if atr_pct is None or atr_pct <= 0:
            atr_pct = 0.5  # default forex moderado

        # Long si precio rompe asian high con margen 0.05%
        if entry >= asian_high * 1.0005:
            stop = entry * (1 - (atr_pct * 1.5) / 100.0)
            tp1 = entry + (entry - asian_low) * 0.5
            tp2 = entry + (entry - asian_low)
            return StrategySignal(
                strategy_name=self.name,
                direction="long",
                entry=round(entry, 8),
                stop=round(stop, 8),
                targets=[round(tp1, 8), round(tp2, 8)],
                confidence=65,
                reasoning=[
                    f"Asian range high {asian_high:g} roto en sesion London/NY",
                    f"ATR {atr_pct:.2f}%",
                ],
                time_horizon_hours=8,
            )
        # Short si rompe asian low
        if entry <= asian_low * 0.9995:
            stop = entry * (1 + (atr_pct * 1.5) / 100.0)
            tp1 = entry - (asian_high - entry) * 0.5
            tp2 = entry - (asian_high - entry)
            return StrategySignal(
                strategy_name=self.name,
                direction="short",
                entry=round(entry, 8),
                stop=round(stop, 8),
                targets=[round(tp1, 8), round(tp2, 8)],
                confidence=65,
                reasoning=[
                    f"Asian range low {asian_low:g} roto en sesion London/NY",
                    f"ATR {atr_pct:.2f}%",
                ],
                time_horizon_hours=8,
            )

        return None
