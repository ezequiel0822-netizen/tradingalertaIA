"""Scalping breakout strategy — Phase 5.5 Bloque B v2.6.0.

Estrategia simple basada en breakout del rango M1 últimas N velas.

Patrón:
1. Computa range_high / range_low de las últimas N velas M1 (no incluye actual).
2. Si current_ask > range_high con buffer pequeño → LONG signal.
3. Si current_bid < range_low con buffer pequeño → SHORT signal.
4. SL fijo en pips desde entry, TP fijo en pips (R:R configurable).
5. Cooldown post-signal evita reentry inmediato.

NO es financial advice. Es un punto de arranque para acumular data scalping.
Strategies adicionales (mean_reversion_scalping, etc.) vienen en v2.6.x.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScalpingContext:
    """Contexto que el engine pasa a la strategy.

    Attributes:
        symbol: Símbolo MT5 (ej. "EURUSD").
        candles_m1: Últimas N velas M1, cada una con keys high/low/close/time.
        current_ask: Precio ask actual del tick.
        current_bid: Precio bid actual del tick.
        pip_size: Tamaño de 1 pip en unidades de precio (ej. 0.0001 EURUSD).
        last_signal_ts: Unix ts del último signal emitido para este símbolo
            (None si nunca). Permite implementar cooldown.
    """

    symbol: str
    candles_m1: list[dict[str, Any]]
    current_ask: float
    current_bid: float
    pip_size: float
    last_signal_ts: float | None = None


@dataclass(frozen=True)
class ScalpingSignal:
    """Output de la strategy. El engine la convierte en orden demo via mt5_demo_trader."""

    strategy_name: str
    symbol: str
    direction: str  # "long" o "short"
    entry: float
    stop_loss: float
    take_profit: float
    reasoning: list[str] = field(default_factory=list)


# Buffer multiplicativo para evitar falsos breakouts justo en el borde del rango.
# 1.00005 = 0.005% (0.5 pips en EURUSD aprox). Suficiente para descartar ruido.
_BREAKOUT_BUFFER = 1.00005


class ScalpingBreakoutStrategy:
    """Range breakout sobre M1 candles.

    Reglas:
    - Requiere al menos `range_lookback_bars + 1` velas (extra es la actual).
    - Computa high/low del rango sobre las últimas N velas (sin la actual).
    - Breakout LONG: ask actual > range_high * 1.00005.
    - Breakout SHORT: bid actual < range_low * 0.99995.
    - SL = entry ± `sl_pips * pip_size`.
    - TP = entry ± `tp_pips * pip_size`.
    - Cooldown: si `last_signal_ts` fue hace < 60s, no emite.
    """

    name = "scalping_breakout"
    cooldown_seconds = 60

    def evaluate(
        self, ctx: ScalpingContext, settings: Any, now_ts: float | None = None
    ) -> ScalpingSignal | None:
        """Devuelve ScalpingSignal o None si no hay setup válido."""
        # Validaciones de input
        lookback = int(getattr(settings, "scalping_range_lookback_bars", 10))
        if lookback < 2:
            return None
        if not ctx.candles_m1 or len(ctx.candles_m1) < lookback + 1:
            return None
        if ctx.pip_size <= 0 or ctx.current_ask <= 0 or ctx.current_bid <= 0:
            return None

        # Cooldown
        if ctx.last_signal_ts is not None and now_ts is not None:
            if (now_ts - ctx.last_signal_ts) < self.cooldown_seconds:
                return None

        # Rango sobre las ultimas N velas sin contar la actual (-1 = actual).
        range_candles = ctx.candles_m1[-(lookback + 1) : -1]
        highs = [self._to_float(c.get("high")) for c in range_candles]
        lows = [self._to_float(c.get("low")) for c in range_candles]
        if any(h is None for h in highs) or any(l is None for l in lows):
            return None
        range_high = max(highs)  # type: ignore[arg-type]
        range_low = min(lows)  # type: ignore[arg-type]

        # Pip distances
        sl_pips = int(getattr(settings, "scalping_sl_pips", 8))
        tp_pips = int(getattr(settings, "scalping_tp_pips", 12))
        if sl_pips <= 0 or tp_pips <= 0:
            return None
        sl_distance = sl_pips * ctx.pip_size
        tp_distance = tp_pips * ctx.pip_size

        # LONG breakout: precio rompe arriba del rango
        if ctx.current_ask > range_high * _BREAKOUT_BUFFER:
            entry = ctx.current_ask
            return ScalpingSignal(
                strategy_name=self.name,
                symbol=ctx.symbol,
                direction="long",
                entry=round(entry, 8),
                stop_loss=round(entry - sl_distance, 8),
                take_profit=round(entry + tp_distance, 8),
                reasoning=[
                    f"M1 breakout LONG sobre rango {range_low:g}-{range_high:g}",
                    f"Entry {entry:g} > range_high {range_high:g}",
                    f"SL -{sl_pips}pips, TP +{tp_pips}pips",
                ],
            )

        # SHORT breakout: precio rompe abajo del rango
        if ctx.current_bid < range_low * (2 - _BREAKOUT_BUFFER):
            entry = ctx.current_bid
            return ScalpingSignal(
                strategy_name=self.name,
                symbol=ctx.symbol,
                direction="short",
                entry=round(entry, 8),
                stop_loss=round(entry + sl_distance, 8),
                take_profit=round(entry - tp_distance, 8),
                reasoning=[
                    f"M1 breakout SHORT bajo rango {range_low:g}-{range_high:g}",
                    f"Entry {entry:g} < range_low {range_low:g}",
                    f"SL +{sl_pips}pips, TP -{tp_pips}pips",
                ],
            )

        return None

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
