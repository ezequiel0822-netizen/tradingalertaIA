"""Scalping mean-reversion strategy — v2.6.6.

Estrategia counter-trend basada en Bollinger Bands + RSI extremos sobre M1.
Complementa scalping_breakout: cubre el escenario opuesto (extremos rangebound,
no momentum direccional). Diseñada para acumular outcomes scalping en
condiciones de mercado lateral, donde breakout fallaría.

Patrón:
1. Computa Bollinger Bands (período N, desviación K) sobre los closes.
2. Computa RSI SMA-based (período P) sobre los closes.
3. LONG si bid <= BB_lower AND RSI <= oversold → bounce a la media.
4. SHORT si ask >= BB_upper AND RSI >= overbought → reversal a la media.
5. SL/TP en pips fijos (reutiliza scalping_sl_pips/tp_pips para consistencia
   con breakout y permitir comparación honesta de win rates).
6. Cooldown post-signal evita reentry inmediato en el mismo símbolo.
7. Skip mercado plano: si bandwidth < 1 pip, no hay setup.

Defaults conservadores (BB 20, RSI 14, 70/30) para que los test fixtures
existentes del engine (11 velas) no disparen accidentalmente esta strategy
y rompan tests del breakout.

NO es financial advice.
"""

from __future__ import annotations

from typing import Any

from app.strategies.scalping_breakout import ScalpingContext, ScalpingSignal


class ScalpingMeanReversionStrategy:
    """BB + RSI extremes sobre M1.

    Reglas:
    - Necesita al menos max(bb_period, rsi_period+1) closes para evaluar.
    - LONG: bid <= bb_lower AND RSI <= rsi_oversold.
    - SHORT: ask >= bb_upper AND RSI >= rsi_overbought.
    - Entry: ask (long) o bid (short), igual que breakout.
    - SL = entry ± `sl_pips * pip_size`.
    - TP = entry ± `tp_pips * pip_size` (mismas distancias que breakout).
    - Cooldown: si `last_signal_ts` fue hace < 60s, no emite.
    - Skip flat market: si bb_upper - bb_lower < pip_size, no emite.
    """

    name = "scalping_mean_reversion"
    cooldown_seconds = 60

    def evaluate(
        self, ctx: ScalpingContext, settings: Any, now_ts: float | None = None
    ) -> ScalpingSignal | None:
        # Validaciones básicas
        if ctx.pip_size <= 0 or ctx.current_ask <= 0 or ctx.current_bid <= 0:
            return None

        # Cooldown
        if ctx.last_signal_ts is not None and now_ts is not None:
            if (now_ts - ctx.last_signal_ts) < self.cooldown_seconds:
                return None

        # Parámetros configurables
        bb_period = int(getattr(settings, "scalping_mr_bollinger_period", 20))
        bb_std_mult = float(getattr(settings, "scalping_mr_bollinger_std", 2.0))
        rsi_period = int(getattr(settings, "scalping_mr_rsi_period", 14))
        rsi_ob = int(getattr(settings, "scalping_mr_rsi_overbought", 70))
        rsi_os = int(getattr(settings, "scalping_mr_rsi_oversold", 30))

        if bb_period < 2 or rsi_period < 2 or bb_std_mult <= 0:
            return None
        if rsi_ob <= rsi_os or rsi_ob > 100 or rsi_os < 0:
            return None

        # Necesitamos suficientes closes para ambos indicadores
        needed = max(bb_period, rsi_period + 1)
        if not ctx.candles_m1 or len(ctx.candles_m1) < needed:
            return None

        # Extraer closes en orden cronológico
        closes: list[float] = []
        for c in ctx.candles_m1:
            v = self._to_float(c.get("close"))
            if v is None:
                return None
            closes.append(v)

        # Bollinger Bands
        bb = self._bollinger(closes, bb_period, bb_std_mult)
        if bb is None:
            return None
        bb_mean, bb_upper, bb_lower = bb

        # Skip flat market — bandwidth menor a 1 pip no da ventaja vs spread
        if (bb_upper - bb_lower) < ctx.pip_size:
            return None

        # RSI
        rsi = self._rsi(closes, rsi_period)
        if rsi is None:
            return None

        # SL/TP distances (reuso settings de breakout)
        sl_pips = int(getattr(settings, "scalping_sl_pips", 8))
        tp_pips = int(getattr(settings, "scalping_tp_pips", 12))
        if sl_pips <= 0 or tp_pips <= 0:
            return None
        sl_distance = sl_pips * ctx.pip_size
        tp_distance = tp_pips * ctx.pip_size

        # LONG: bid en o por debajo del BB_lower + RSI oversold
        if ctx.current_bid <= bb_lower and rsi <= rsi_os:
            entry = ctx.current_ask
            return ScalpingSignal(
                strategy_name=self.name,
                symbol=ctx.symbol,
                direction="long",
                entry=round(entry, 8),
                stop_loss=round(entry - sl_distance, 8),
                take_profit=round(entry + tp_distance, 8),
                reasoning=[
                    f"M1 mean-reversion LONG: bid {ctx.current_bid:g} <= BB_lower {bb_lower:g}",
                    f"RSI {rsi:.1f} <= oversold {rsi_os}",
                    f"BB({bb_period},{bb_std_mult:g}) mean={bb_mean:g}",
                    f"SL -{sl_pips}pips, TP +{tp_pips}pips",
                ],
            )

        # SHORT: ask en o por encima del BB_upper + RSI overbought
        if ctx.current_ask >= bb_upper and rsi >= rsi_ob:
            entry = ctx.current_bid
            return ScalpingSignal(
                strategy_name=self.name,
                symbol=ctx.symbol,
                direction="short",
                entry=round(entry, 8),
                stop_loss=round(entry + sl_distance, 8),
                take_profit=round(entry - tp_distance, 8),
                reasoning=[
                    f"M1 mean-reversion SHORT: ask {ctx.current_ask:g} >= BB_upper {bb_upper:g}",
                    f"RSI {rsi:.1f} >= overbought {rsi_ob}",
                    f"BB({bb_period},{bb_std_mult:g}) mean={bb_mean:g}",
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

    @staticmethod
    def _bollinger(
        closes: list[float], period: int, std_mult: float
    ) -> tuple[float, float, float] | None:
        """SMA + population stddev. Devuelve (mean, upper, lower) o None."""
        if len(closes) < period or period < 2:
            return None
        window = closes[-period:]
        mean = sum(window) / period
        variance = sum((v - mean) ** 2 for v in window) / period
        std = variance ** 0.5
        return mean, mean + std_mult * std, mean - std_mult * std

    @staticmethod
    def _rsi(closes: list[float], period: int) -> float | None:
        """SMA-based RSI (no Wilder smoothing). Devuelve 0-100 o None."""
        if len(closes) < period + 1 or period < 2:
            return None
        window = closes[-(period + 1) :]
        gains = 0.0
        losses = 0.0
        for i in range(1, len(window)):
            diff = window[i] - window[i - 1]
            if diff > 0:
                gains += diff
            elif diff < 0:
                losses += -diff
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
