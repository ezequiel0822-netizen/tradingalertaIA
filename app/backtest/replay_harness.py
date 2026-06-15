"""Orquestador del Backtest Replay Harness (ESPEC §4 / §10, Modo A).

Recorre la historia de cada simbolo barra por barra, le pregunta a las
estrategias REALES (via context_builder) que habrian hecho, simula cada trade
con trade_simulator (pesimismo B1-B13), clasifica el regimen (regime_filter) y
escribe SOLO en las tablas backtest_* (R5). No toca el ciclo vivo: ni importa
mt5_demo_trader/reconciler/jobs, ni escribe en paper_trades ni en
strategy_performance.

Paridad con vivo: aplica el MISMO STRATEGY_MIN_CONFIDENCE que el router, para
que "señal" signifique lo mismo en backtest y en produccion. B12: una sola
posicion por (simbolo, estrategia) a la vez (sin piramidacion en v1).

CLI: python -m app.backtest.replay_harness --config <run.json>
Requiere ENABLE_BACKTEST_HARNESS=true (opt-in; default false no corre nada).
"""

import json
import logging
import math
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.analyzers.technical_patterns import atr_pct_from_candles
from app.backtest.context_builder import build_context
from app.backtest.historical_loader import timeframe_minutes_from_label
from app.backtest.trade_simulator import TradeSetup, net_r, simulate_trade
from app.config.settings import Settings
from app.intelligence.regime_filter import (
    ATR_PERIOD,
    SMA_TREND_PERIOD,
    TREND_SLOPE_LOOKBACK,
    VOL_LOOKBACK,
    classify,
)
from app.learning.trade_outcomes import session_of
from app.utils.time_utils import utc_now_iso

logger = logging.getLogger(__name__)

# Warmup: arrancar el replay donde el regimen es computable (SMA200 + pendiente y
# 252 ATR previos), para que ningun trade quede con regimen 'unknown' por falta
# de historia. Con D1 de decadas se pierden ~266 barras: despreciable.
WARMUP_BARS = max(SMA_TREND_PERIOD + TREND_SLOPE_LOOKBACK, VOL_LOOKBACK + ATR_PERIOD)

# El regimen solo mira la cola (SMA200+pendiente y 252 ATR previos). Pasarle SOLO
# esa ventana da un resultado IDENTICO a pasarle toda la historia, pero convierte
# el replay de O(n^2) a O(n) — clave con D1 de decadas (~14k barras por simbolo).
REGIME_WINDOW = WARMUP_BARS + 2

DEFAULT_LOOKBACK = 250


@dataclass
class RunConfig:
    mode: str = "A"
    timeframe: str = "D1"
    symbols: list[str] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)
    cost_multiplier: float | None = None
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "RunConfig":
        return cls(
            mode=str(data.get("mode", "A")),
            timeframe=str(data.get("timeframe", "D1")),
            symbols=[str(s).strip().upper() for s in data.get("symbols", [])],
            strategies=[str(s).strip() for s in data.get("strategies", [])],
            cost_multiplier=data.get("cost_multiplier"),
            notes=str(data.get("notes", "")),
        )


def default_strategy_registry() -> dict:
    """Las 4 estrategias backtesteables con honestidad en v1 (ESPEC §3). Se
    instancian DIRECTO, sin filtrar por su enabled_setting_key: el backtest mide
    aunque la estrategia este apagada en vivo (caso de `momentum`)."""
    from app.strategies.breakout import BreakoutStrategy
    from app.strategies.forex_session_breakout import ForexSessionBreakoutStrategy
    from app.strategies.mean_reversion import MeanReversionStrategy
    from app.strategies.momentum import MomentumStrategy

    instances = [
        BreakoutStrategy(),
        MeanReversionStrategy(),
        MomentumStrategy(),
        ForexSessionBreakoutStrategy(),
    ]
    return {s.name: s for s in instances}


def category_for(symbol: str) -> str:
    return "gold" if "XAU" in (symbol or "").upper() else "forex"


def horizon_to_bars(hours: int, timeframe_minutes: int) -> int:
    if not hours or hours <= 0 or timeframe_minutes <= 0:
        return 1
    return max(1, math.ceil(hours * 60 / timeframe_minutes))


def _epoch_dt(epoch) -> datetime:
    return datetime.fromtimestamp(int(epoch or 0), tz=timezone.utc)


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


class ReplayHarness:
    """Corre un backtest Modo A y persiste run + trades en tablas backtest_*."""

    def __init__(self, settings: Settings, repository) -> None:
        self.settings = settings
        self.repository = repository

    def run(
        self,
        config: RunConfig,
        *,
        strategies: dict | None = None,
        lookback: int = DEFAULT_LOOKBACK,
    ) -> int:
        registry = strategies if strategies is not None else default_strategy_registry()
        selected = {
            name: registry[name] for name in config.strategies if name in registry
        }
        if not selected:
            logger.warning("Ninguna estrategia valida en el config: %s", config.strategies)

        tf_minutes = timeframe_minutes_from_label(config.timeframe) or 1440
        all_trades: list[dict] = []
        data_ranges: dict[str, dict] = {}

        for symbol in config.symbols:
            candles = self.repository.fetch_mt5_cache_window(
                symbol, tf_minutes, 0, 9_999_999_999
            )
            if len(candles) <= WARMUP_BARS + 2:
                data_ranges[symbol] = {
                    "bars": len(candles),
                    "note": "sin profundidad suficiente para el warmup",
                }
                continue
            data_ranges[symbol] = {
                "bars": len(candles),
                "first": candles[0].get("time"),
                "last": candles[-1].get("time"),
            }
            self._replay_symbol(
                symbol, candles, selected, tf_minutes, lookback, all_trades
            )

        run_id = self.repository.insert_backtest_run(
            {
                "created_at_utc": utc_now_iso(),
                "git_commit": _git_commit(),
                "mode": config.mode,
                "timeframe": config.timeframe,
                "symbols": ",".join(config.symbols),
                "strategies": ",".join(selected.keys()),
                "data_ranges_json": json.dumps(data_ranges),
                "config_json": json.dumps(
                    {
                        "mode": config.mode,
                        "timeframe": config.timeframe,
                        "strategies": list(selected.keys()),
                        "params": "defaults hardcoded por estrategia (v1)",
                        "min_confidence": self.settings.strategy_min_confidence,
                        "lookback": lookback,
                    }
                ),
                "cost_multiplier": (
                    config.cost_multiplier
                    if config.cost_multiplier is not None
                    else self.settings.backtest_cost_multiplier
                ),
                "n_configs_tested": 1,  # Modo A: 1 config por estrategia
                "notes": config.notes,
            }
        )
        self.repository.insert_backtest_trades(run_id, all_trades)
        logger.info("Backtest run %s: %s trades simulados", run_id, len(all_trades))
        return run_id

    def _replay_symbol(
        self, symbol, candles, selected, tf_minutes, lookback, all_trades
    ) -> None:
        category = category_for(symbol)
        next_free = {name: WARMUP_BARS for name in selected}
        last_decision = len(candles) - 1  # necesitamos la barra N+1 para entrar

        for n in range(WARMUP_BARS, last_decision):
            built = False
            ctx = None
            regime = None
            for name, strat in selected.items():
                if n < next_free[name]:
                    continue
                if not built:  # construir contexto/regimen una vez por barra
                    ctx = build_context(
                        candles, n, symbol=symbol, category=category, lookback=lookback
                    )
                    regime = classify(candles[max(0, n + 1 - REGIME_WINDOW): n + 1])
                    built = True
                try:
                    sig = strat.evaluate(ctx, self.settings)
                except Exception:
                    logger.exception("Estrategia %s rompio en %s@%s", name, symbol, n)
                    continue
                if sig is None:
                    continue
                if sig.confidence < self.settings.strategy_min_confidence:
                    continue

                trade = self._open_and_simulate(
                    name, symbol, category, candles, n, sig, tf_minutes, lookback, regime
                )
                if trade is None:
                    continue
                all_trades.append(trade)
                exit_idx = (n + 1) + int(trade["bars_held"])
                next_free[name] = exit_idx  # B12: libre recien al cerrar

    def _open_and_simulate(
        self, name, symbol, category, candles, n, sig, tf_minutes, lookback, regime
    ) -> dict | None:
        entry_bar = candles[n + 1]
        entry_price = float(entry_bar.get("open") or 0.0)
        if entry_price <= 0:
            return None
        tp = sig.targets[0] if getattr(sig, "targets", None) else None
        setup = TradeSetup(
            direction=sig.direction,
            entry_utc=int(entry_bar.get("time") or 0),
            entry_price=entry_price,
            sl_initial=float(sig.stop),
            tp_initial=float(tp) if tp else None,
            time_exit_bars=horizon_to_bars(sig.time_horizon_hours, tf_minutes),
        )
        window = candles[max(0, n - lookback + 1): n + 1]
        atr_pct = atr_pct_from_candles(window) or 0.0
        slippage_price = (
            float(self.settings.backtest_sl_slippage_atr) * (atr_pct / 100.0) * entry_price
        )
        try:
            res = simulate_trade(setup, candles[n + 1:], sl_slippage_price=slippage_price)
        except ValueError:
            return None  # geometria invalida (p.ej. sl del lado equivocado) -> skip soft

        cost_r, r_net = net_r(res.r_gross, entry_price, float(sig.stop), category, self.settings)
        edt = _epoch_dt(entry_bar.get("time"))
        return {
            "config_id": 0,
            "strategy": name,
            "symbol": symbol,
            "category": category,
            "direction": sig.direction,
            "signal_bar_utc": int(candles[n].get("time") or 0),
            "entry_utc": setup.entry_utc,
            "entry_price": round(entry_price, 8),
            "sl_initial": round(float(sig.stop), 8),
            "tp_initial": round(float(tp), 8) if tp else None,
            "exit_utc": res.exit_utc,
            "exit_price": res.exit_price,
            "exit_reason": res.exit_reason,
            "bars_held": res.bars_held,
            "r_gross": res.r_gross,
            "cost_r": cost_r,
            "r_net": r_net,
            "mfe_r": res.mfe_r,
            "mae_r": res.mae_r,
            "session": session_of(edt.isoformat()),
            "regime_trend": regime.regime_trend if regime else "unknown",
            "regime_vol": regime.regime_vol if regime else "unknown",
            "year": edt.year,
        }


def main() -> int:
    import argparse

    from app.config.settings import load_settings
    from app.database.db import init_db
    from app.database.repository import Repository

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Backtest Replay Harness (Modo A)")
    parser.add_argument("--config", required=True, help="ruta al JSON del run")
    parser.add_argument("--report", action="store_true", help="generar reporte tras el run")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.enable_backtest_harness:
        print(
            "ENABLE_BACKTEST_HARNESS=false (default). Opt-in:\n"
            "  $env:ENABLE_BACKTEST_HARNESS='true'; "
            "python -m app.backtest.replay_harness --config run.json --report"
        )
        return 1

    with open(args.config, encoding="utf-8") as fh:
        config = RunConfig.from_dict(json.load(fh))

    init_db(settings.sqlite_path)
    repository = Repository(settings.sqlite_path)
    harness = ReplayHarness(settings, repository)
    run_id = harness.run(config)
    print(f"Run {run_id}: {config.mode} / {config.timeframe} / {len(config.symbols)} simbolos")

    if args.report:
        from app.backtest.report import generate_report

        paths = generate_report(repository, run_id, settings)
        print("Reporte:", paths.get("report_md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
