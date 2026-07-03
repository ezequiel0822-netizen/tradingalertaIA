"""gold_friday_hold — regla CONGELADA para el gate §11 del "viernes del oro".

Hipótesis H-B2 (research/HIPOTESIS_2026-07-02.md): el retorno diario del oro los
viernes es positivo (+10 bps/día bruto, 22 años, pasó la exploración pre-registrada).
Este es su ÚNICO tiro al gate §11 — la regla está congelada, prohibido ajustarla.

Regla ejecutable (pre-registrada 2026-07-03, ANTES de correr):
  - Señal al CLOSE de la barra D1 de XAUUSD cuyo bar-time UTC sea JUEVES
    (weekday==3, la MISMA convención que usó seasonality_study.py).
  - El harness entra al open de la barra siguiente (el "viernes" del estudio) y
    sale al open de la siguiente (time exit 1 barra: viernes→lunes open).
  - Long only. Stop = entry × (1 − 2.0×ATR%/100) — 2.0 congelado (default de la
    casa). Sin TP (targets=[]; la salida es por tiempo).

SOLO HARNESS: esta estrategia se registra únicamente en default_strategy_registry
del replay_harness — NO está en el router vivo, no tiene flag, no puede abrir
paper trades ni órdenes en vivo. Si algún día pasa §11, promoverla a paper es un
cambio deliberado aparte (con flag opt-in OFF + gates, como todo).
"""

from datetime import datetime, timezone

from app.config.settings import Settings
from app.strategies.base import StrategyContext, StrategySignal
from app.strategies.forex_session_breakout import _candle_epoch

# Congelados (pre-registro 2026-07-03). NO leer de settings: congelado es congelado.
_ATR_STOP_MULT = 2.0
_DEFAULT_ATR_PCT = 1.0  # fallback si el pattern no trae ATR (oro D1 ~1-1.5%)
_THURSDAY = 3           # weekday() UTC de la barra de señal


class GoldFridayHoldStrategy:
    name = "gold_friday_hold"
    # Sin enabled_setting_key: no existe en el router vivo (harness-only).

    def evaluate(
        self, ctx: StrategyContext, settings: Settings
    ) -> StrategySignal | None:
        if ctx.snapshot.category != "gold":
            return None

        candles = ctx.candles or []
        if not candles:
            return None
        last_epoch = _candle_epoch(candles[-1])
        if last_epoch is None:
            return None
        bar_now = datetime.fromtimestamp(last_epoch, tz=timezone.utc)
        if bar_now.weekday() != _THURSDAY:
            return None

        entry = ctx.snapshot.price
        if entry is None or entry <= 0:
            return None

        pattern = ctx.pattern
        atr_pct = getattr(pattern, "atr_pct", None) if pattern else None
        if atr_pct is None or atr_pct <= 0:
            atr_pct = _DEFAULT_ATR_PCT

        stop = entry * (1 - (_ATR_STOP_MULT * atr_pct) / 100.0)
        return StrategySignal(
            strategy_name=self.name,
            direction="long",
            entry=round(float(entry), 8),
            stop=round(stop, 8),
            targets=[],  # sin TP: salida por tiempo (1 barra D1)
            confidence=65,
            reasoning=[
                "Regla congelada gate §11: long viernes del oro (señal jueves)",
                f"ATR {atr_pct:.2f}%, stop 2.0x",
            ],
            time_horizon_hours=24,  # D1 -> time_exit_bars=1 (sale al open siguiente)
        )
