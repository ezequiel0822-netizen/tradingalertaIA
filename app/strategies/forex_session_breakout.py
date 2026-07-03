"""Forex Session Breakout strategy.

Solo activa durante London/NY overlap (UTC 13-17). Calcula Asian range
high/low (00:00-08:00 UTC) y abre long si rompe el high, short si rompe el low.

Solo aplica a category forex y gold.

v3.10.0 — REPLAYABILIDAD: "ahora" es el timestamp de la ULTIMA vela del contexto,
no el reloj de pared, y el overlap London/NY se deriva de ese bar-time (antes
dependia de macro['active_sessions'], que el harness no puede poblar — B11 — y de
datetime.now(), que hacia la estrategia irreplayable). En vivo ambos relojes
coinciden (feed fresco); en el harness permite reproducir ~8 anios de H1. La
proteccion anti-A1 (velas stale) se conserva con un guard de frescura SOLO-vivo:
si la ultima vela tiene mas de 2h respecto del reloj de pared, no se opera
(en replay, ctx.snapshot.raw['backtest']=True lo desactiva).
"""

from datetime import datetime, timezone

from app.config.settings import Settings
from app.strategies.base import StrategyContext, StrategySignal

# Frescura maxima del feed en vivo: sin vela de menos de 2h, no se opera contra
# niveles potencialmente viejos (la leccion del bug A1).
_MAX_LIVE_STALENESS_SECONDS = 2 * 3600

# London/NY overlap en UTC (mismas franjas que macro_context).
_OVERLAP_START_HOUR = 13
_OVERLAP_END_HOUR = 17


def _candle_epoch(candle: dict) -> float | None:
    """Epoch (s) de una vela: 'timestamp' (feed vivo Yahoo) o 'time' (cache MT5
    del harness). None si no hay ninguna."""
    for key in ("timestamp", "time"):
        value = candle.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


class ForexSessionBreakoutStrategy:
    name = "forex_session_breakout"
    enabled_setting_key = "enable_strategy_forex_session_breakout"

    def evaluate(
        self, ctx: StrategyContext, settings: Settings
    ) -> StrategySignal | None:
        if ctx.snapshot.category not in {"forex", "gold"}:
            return None

        candles = ctx.candles or []
        if len(candles) < 30:
            return None

        # v3.10.0: bar-time = reloj de la estrategia (replayable).
        last_epoch = _candle_epoch(candles[-1])
        if last_epoch is None:
            return None

        # Guard de frescura SOLO-vivo (anti-A1): en replay el harness marca
        # raw['backtest']=True y el guard no aplica (bar-time ES el reloj).
        is_replay = bool((ctx.snapshot.raw or {}).get("backtest"))
        if not is_replay:
            age = datetime.now(timezone.utc).timestamp() - last_epoch
            if age > _MAX_LIVE_STALENESS_SECONDS:
                return None

        bar_now = datetime.fromtimestamp(last_epoch, tz=timezone.utc)

        # Solo durante London/NY overlap (13-17 UTC), derivado del bar-time.
        if not (_OVERLAP_START_HOUR <= bar_now.hour < _OVERLAP_END_HOUR):
            return None

        # Asian range REAL: velas de la sesion 00:00-08:00 UTC del DIA de la barra,
        # filtradas por timestamp (fix del bug A1: nada de posiciones).
        day_start = (
            bar_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        )
        asian_end = day_start + 8 * 3600
        asian_slice = []
        for candle in candles:
            epoch = _candle_epoch(candle)
            if epoch is not None and day_start <= epoch < asian_end:
                asian_slice.append(candle)
        if len(asian_slice) < 4:
            return None
        highs = [c.get("high") for c in asian_slice if c.get("high") is not None]
        lows = [c.get("low") for c in asian_slice if c.get("low") is not None]
        if not highs or not lows:
            return None
        asian_high = max(highs)
        asian_low = min(lows)
        if asian_high <= 0 or asian_low <= 0:
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
