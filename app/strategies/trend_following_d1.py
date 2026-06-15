"""Trend following Donchian D1 — hipotesis CONGELADA (ESPEC §9).

Deliberadamente aburrida: trend-following tipo Donchian, la familia con MAS
evidencia academica multi-activo y multi-decada. La hipotesis se fijo ANTES de
mirar la data (anti data-dredging): si ni esto muestra señal en la historia, es
informacion valiosisima.

Hoy NO corre en vivo: su enabled_setting_key no existe en Settings -> el router
la deja OFF. El backtest la MIDE; la integracion viva (al ciclo D1) es v3.7
(MAPA §8), y aun ahi entra por el pipeline normal (paper -> demo -> gates).

Reglas (Modo A, params congelados):
  Long:  regime_trend == up   y close(N) > max(high de los 55 bars previos)
  Short: regime_trend == down y close(N) < min(low  de los 55 bars previos)
  SL inicial: 2.0 x ATR14 desde el entry. SIN TP fijo (dejar correr al ganador).
  Salida trailing Donchian (close-confirmada, ejecucion al open siguiente):
    long sale cuando close(M) < min(low de los 20 bars previos); short espejo.
    El SL duro sigue activo intrabar todo el tiempo.
  Time exit: 120 barras. Confianza: 70 constante (paridad STRATEGY_MIN_CONFIDENCE).
"""

from typing import Callable

from app.analyzers.technical_patterns import atr_pct_from_candles
from app.config.settings import Settings
from app.intelligence.regime_filter import classify
from app.strategies.base import StrategyContext, StrategySignal

ENTRY_LOOKBACK = 55   # canal Donchian de entrada
EXIT_LOOKBACK = 20    # canal Donchian de salida
ATR_MULT = 2.0
ATR_PERIOD = 14
TIME_EXIT_BARS = 120
CONFIDENCE = 70
# El harness convierte time_horizon_hours -> barras con ceil(h*60/tf_min). Para D1
# (1440 min/barra), 120 barras = 120*24 horas. Calibrado para D1 (es D1-only).
TIME_HORIZON_HOURS = TIME_EXIT_BARS * 24


class TrendFollowingD1Strategy:
    name = "trend_following_d1"
    enabled_setting_key = "enable_strategy_trend_following_d1"  # inexistente -> OFF en vivo

    def evaluate(
        self, ctx: StrategyContext, settings: Settings
    ) -> StrategySignal | None:
        candles = ctx.candles or []
        if len(candles) < ENTRY_LOOKBACK + 2:
            return None
        regime = classify(candles).regime_trend
        if regime not in ("up", "down"):
            return None  # solo opera alineada al regimen (gate)

        close_n = _f(candles[-1].get("close"))
        if close_n is None or close_n <= 0:
            return None
        atr_pct = atr_pct_from_candles(candles, ATR_PERIOD)
        if not atr_pct or atr_pct <= 0:
            return None
        atr_price = atr_pct / 100.0 * close_n

        prev = candles[-(ENTRY_LOOKBACK + 1):-1]  # los 55 bars PREVIOS a N
        if regime == "up" and close_n > max(_f(c.get("high"), c.get("close")) for c in prev):
            direction, stop = "long", close_n - ATR_MULT * atr_price
        elif regime == "down" and close_n < min(_f(c.get("low"), c.get("close")) for c in prev):
            direction, stop = "short", close_n + ATR_MULT * atr_price
        else:
            return None

        return StrategySignal(
            strategy_name=self.name,
            direction=direction,
            entry=round(close_n, 8),
            stop=round(stop, 8),
            targets=[],  # sin TP fijo: la salida es Donchian/SL/time
            confidence=CONFIDENCE,
            reasoning=[
                f"Donchian {ENTRY_LOOKBACK} breakout alineado al regimen {regime}",
                f"SL {ATR_MULT}xATR14 ({atr_pct:.2f}% del precio)",
            ],
            time_horizon_hours=TIME_HORIZON_HOURS,
        )

    def backtest_close_exit(
        self, candles: list[dict], entry_idx: int, direction: str, settings: Settings
    ) -> Callable[[int, dict], bool]:
        """Hook para el harness: la salida trailing Donchian (close-confirmada).
        `entry_idx` es el indice ABSOLUTO de la barra de entrada (N+1); `idx` es
        relativo al forward (0 = barra de entrada). Usa SOLO barras < M (sin
        look-ahead)."""
        is_long = direction == "long"

        def _should_exit(idx: int, candle: dict) -> bool:
            m = entry_idx + idx
            lo = m - EXIT_LOOKBACK
            if lo < 0:
                return False
            window = candles[lo:m]  # los 20 bars previos a M (todos < M)
            if not window:
                return False
            close_m = _f(candle.get("close"))
            if close_m is None:
                return False
            if is_long:
                return close_m < min(_f(c.get("low"), c.get("close")) for c in window)
            return close_m > max(_f(c.get("high"), c.get("close")) for c in window)

        return _should_exit


def _f(value, fallback=None):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback
