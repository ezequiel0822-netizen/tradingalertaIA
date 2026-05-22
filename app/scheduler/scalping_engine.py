"""Scalping Engine — Phase 5.5 Bloque B v2.6.0.

Thread dedicado que opera scalping en paralelo con el swing engine del main loop.
Polea MT5 cada `scalping_poll_interval_seconds` (default 5s), evalúa la strategy
`scalping_breakout` sobre M1 candles, y auto-ejecuta a MT5 demo via el mismo
`mt5_demo_trader.send_prepared_request` que usa el swing engine.

Real-money trading sigue 100% bloqueado por las validaciones internas de
`mt5_demo_trader` (cuenta demo + trade_allowed + ENABLE_REAL_TRADING=false).

Coordinación con swing:
- Caps independientes (`SCALPING_*` separados de `MAX_*`).
- Kill-switch global (`kill_switch_active_until`) bloquea ambos engines.
- Kill-switch propio (`bot_state.scalping_halted`) solo bloquea scalping.
- DB compartida via flag `is_scalping=1` para diferenciar trades.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config.settings import Settings
from app.database.repository import Repository
from app.strategies.scalping_breakout import (
    ScalpingBreakoutStrategy,
    ScalpingContext,
    ScalpingSignal,
)
from app.utils.scalping_state import is_scalping_halted
from app.utils.time_utils import utc_now, utc_now_iso


logger = logging.getLogger(__name__)


@dataclass
class ScalpingCycleResult:
    cycle_count: int
    signals_evaluated: int
    trades_opened: int
    trades_force_exited: int
    cap_blocks: int
    errors: int


class ScalpingEngine:
    """Engine de scalping en thread dedicado.

    Lifecycle:
        engine = ScalpingEngine(settings, repository, notifier, mt5_reader, mt5_demo_trader)
        engine.start()  # arranca thread
        ...
        engine.stop()   # graceful shutdown (espera fin del ciclo actual)
    """

    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        notifier: Any,
        mt5_reader: Any = None,
        mt5_demo_trader: Any = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.notifier = notifier
        self.mt5_reader = mt5_reader
        self.trader = mt5_demo_trader  # se acepta inyectado o se crea lazy
        self.strategy = ScalpingBreakoutStrategy()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_signal_ts: dict[str, float] = {}
        self._trades_since_heartbeat = 0
        self._cycle_count = 0

    # ---------------- Lifecycle ----------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.warning("ScalpingEngine.start() called but thread already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ScalpingEngine",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "ScalpingEngine thread started (interval=%ss, symbols=%s)",
            self.settings.scalping_poll_interval_seconds,
            self.settings.scalping_allowed_symbols,
        )

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("ScalpingEngine thread stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---------------- Main loop ----------------

    def _run_loop(self) -> None:
        interval = max(1, int(self.settings.scalping_poll_interval_seconds))
        while not self._stop_event.is_set():
            try:
                self._run_one_cycle()
            except Exception:
                logger.exception("ScalpingEngine cycle failed; continuing next cycle")
            # Sleep tolerante a stop_event mid-sleep
            self._stop_event.wait(timeout=interval)

    def _run_one_cycle(self) -> ScalpingCycleResult:
        """Un ciclo completo: lifecycle (force-exit) + signal eval + execute."""
        self._cycle_count += 1
        result = ScalpingCycleResult(
            cycle_count=self._cycle_count,
            signals_evaluated=0,
            trades_opened=0,
            trades_force_exited=0,
            cap_blocks=0,
            errors=0,
        )

        # 1. Kill-switches (orden: global > scalping propio)
        if self._is_global_kill_active() or is_scalping_halted(self.repository):
            return result

        # 2. Force-exits primero (libera slots de cap antes de evaluar nuevas)
        result.trades_force_exited = self._check_force_exits()

        # 3. Caps (check global, sino skip signal eval)
        ok, reason = self._check_caps()
        if not ok:
            result.cap_blocks += 1
            logger.debug("Scalping cap block: %s", reason)
            return result

        # 4. Para cada símbolo permitido: evaluar signal + execute
        for symbol in self.settings.scalping_allowed_symbols:
            symbol = symbol.upper().strip()
            if not symbol:
                continue
            try:
                signal = self._evaluate_signal_for_symbol(symbol)
                result.signals_evaluated += 1
                if signal is None:
                    continue
                opened = self._open_scalping_trade(signal)
                if opened:
                    result.trades_opened += 1
                    self._last_signal_ts[symbol] = time.time()
                    self._trades_since_heartbeat += 1
                    self._send_heartbeat_if_due()
                    # Después de abrir, re-check caps para no abrir 2 en un ciclo
                    ok, _ = self._check_caps()
                    if not ok:
                        break
            except Exception:
                logger.exception("Scalping cycle error for %s", symbol)
                result.errors += 1

        return result

    # ---------------- Force exits ----------------

    def _check_force_exits(self) -> int:
        """Cierra paper_trades scalping abiertos cuyo tiempo excede el límite."""
        force_exit_minutes = int(self.settings.scalping_force_exit_minutes)
        if force_exit_minutes <= 0:
            return 0
        now = utc_now()
        cutoff = now - timedelta(minutes=force_exit_minutes)
        closed = 0
        for trade in self._fetch_open_scalping_trades():
            opened_at = self._parse_iso(trade.get("opened_at"))
            if opened_at is None:
                continue
            if opened_at <= cutoff:
                self._close_scalping_trade(int(trade["id"]), reason="force_exit_timeout")
                closed += 1
        if closed:
            logger.info("Scalping force-exited %s trades (timeout=%smin)", closed, force_exit_minutes)
        return closed

    def _close_scalping_trade(self, trade_id: int, reason: str) -> None:
        """Marca paper_trade scalping como cerrado. NO toca MT5 position aún (v2.6.x)."""
        try:
            self.repository.update_paper_trade(
                trade_id,
                {
                    "status": f"closed_{reason}",
                    "closed_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                },
            )
        except Exception:
            logger.exception("Failed to close scalping trade %s", trade_id)

    # ---------------- Signal evaluation ----------------

    def _evaluate_signal_for_symbol(self, symbol: str) -> ScalpingSignal | None:
        """Construye ScalpingContext y evalúa la strategy."""
        if self.mt5_reader is None or not getattr(self.mt5_reader, "is_connected", lambda: False)():
            return None
        # M1 candles
        lookback = int(self.settings.scalping_range_lookback_bars) + 5
        candles = self._fetch_m1_candles(symbol, lookback)
        if not candles:
            return None
        # Tick actual
        tick = self.mt5_reader.get_tick(symbol)
        if not tick:
            return None
        ask = float(tick.get("ask") or 0)
        bid = float(tick.get("bid") or 0)
        if ask <= 0 or bid <= 0:
            return None
        # Pip size desde symbol_info
        pip_size = self._compute_pip_size(symbol)
        if pip_size <= 0:
            return None
        ctx = ScalpingContext(
            symbol=symbol,
            candles_m1=candles,
            current_ask=ask,
            current_bid=bid,
            pip_size=pip_size,
            last_signal_ts=self._last_signal_ts.get(symbol),
        )
        return self.strategy.evaluate(ctx, self.settings, now_ts=time.time())

    def _fetch_m1_candles(self, symbol: str, count: int) -> list[dict]:
        try:
            return self.mt5_reader.get_rates(symbol, timeframe="M1", count=count) or []
        except Exception:
            logger.exception("Failed to fetch M1 candles for %s", symbol)
            return []

    def _compute_pip_size(self, symbol: str) -> float:
        """pip_size = point*10 si broker quotea 5-digit (forex moderno); point si 4-digit."""
        try:
            info = self.mt5_reader.symbol_info(symbol) or {}
            point = float(info.get("point") or 0)
            digits = int(info.get("digits") or 0)
            if point <= 0:
                return 0.0
            if digits in (5, 3):
                return point * 10
            return point
        except Exception:
            return 0.0

    # ---------------- Order execution ----------------

    def _open_scalping_trade(self, signal: ScalpingSignal) -> bool:
        """Crea paper_trade is_scalping=1 + ejecuta a MT5 demo si demo trading on."""
        trader = self._ensure_trader()
        if trader is None:
            logger.warning("Scalping: mt5_demo_trader no disponible, signal descartado")
            return False

        # Determinar categoría del símbolo (forex vs gold)
        category = self._category_for_symbol(signal.symbol)

        # 1. Crear paper_trade con is_scalping=1
        now_iso = utc_now_iso()
        paper_trade = {
            "alert_id": 0,
            "token_id": 0,
            "category": category,
            "chain": category,
            "token_address": signal.symbol,
            "symbol": signal.symbol,
            "thesis": " | ".join(signal.reasoning),
            "readiness_grade": "scalping",
            "entry_price": signal.entry,
            "latest_price": signal.entry,
            "stop_loss": signal.stop_loss,
            "take_profit_1": signal.take_profit,
            "take_profit_2": signal.take_profit,
            "invalidation": "scalping force-exit at timeout or SL/TP",
            "status": "open",
            "unrealized_return_pct": 0,
            "opened_at": now_iso,
            "updated_at": now_iso,
            "closed_at": None,
            "mfe_pct": 0,
            "mae_pct": 0,
            "original_stop_loss": signal.stop_loss,
            "trailing_active": 0,
            "strategy_name": signal.strategy_name,
            "direction": signal.direction,
            "time_horizon_hours": 1,  # placeholder, scalping no usa horas
            "size_notional": 0,
            "size_units": 0,
            "risk_pct": float(self.settings.scalping_risk_per_trade_pct),
            "partial_closed": 0,
            "is_scalping": 1,
        }
        try:
            created = self.repository.create_paper_trade(paper_trade)
            if not created:
                return False
        except Exception:
            logger.exception("Scalping: failed to create paper_trade")
            return False

        # 2. Si demo trading no esta on, terminamos acá (solo paper trade simulado).
        if not self.settings.enable_mt5_demo_trading:
            logger.info("Scalping paper_trade abierto (sin MT5: demo off): %s %s", signal.direction, signal.symbol)
            return True

        # 3. Ejecutar a MT5 demo via trader. Construye request directo.
        paper_id = self._fetch_latest_scalping_trade_id(signal.symbol)
        if paper_id is None:
            logger.error("Scalping: no se pudo recuperar paper_trade recién creado")
            return False

        try:
            open_positions = len(trader.positions())
        except Exception:
            open_positions = 0
        request_dict = {
            "paper_trade_id": paper_id,
            "symbol": signal.symbol,
            "direction": signal.direction,
            "volume": float(self.settings.demo_max_lot),  # MVP: usa demo_max_lot, refinar en v2.6.x
            "entry_price": signal.entry,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
        }
        try:
            send_result = trader.send_prepared_request(request_dict, open_positions)
        except Exception:
            logger.exception("Scalping: send_prepared_request raised")
            return True  # paper trade ya creado

        # 4. Persistir resultado en demo_orders (con is_scalping=1)
        now_iso2 = utc_now_iso()
        try:
            self.repository.create_demo_order(
                {
                    "demo_request_id": 0,  # scalping no usa requests intermedios
                    "paper_trade_id": paper_id,
                    "symbol": signal.symbol,
                    "direction": signal.direction,
                    "volume": request_dict["volume"],
                    "price": send_result.price,
                    "stop_loss": signal.stop_loss,
                    "take_profit": signal.take_profit,
                    "retcode": send_result.retcode,
                    "order_ticket": send_result.order_ticket,
                    "deal_ticket": send_result.deal_ticket,
                    "status": send_result.status,
                    "strategy_name": signal.strategy_name,
                    "result_summary": (send_result.result_summary or send_result.reason),
                    "sent_at": now_iso2,
                    "is_scalping": 1,
                }
            )
        except Exception:
            logger.exception("Scalping: failed to persist demo_order")

        if send_result.ok:
            logger.info(
                "Scalping AUTO-ORDER ENVIADA #paper=%s %s %s ticket=%s retcode=%s",
                paper_id, signal.direction, signal.symbol,
                send_result.order_ticket, send_result.retcode,
            )
            return True
        else:
            logger.warning(
                "Scalping AUTO-ORDER FALLIDA #paper=%s %s: %s",
                paper_id, signal.symbol, send_result.reason,
            )
            return False

    # ---------------- Caps ----------------

    def _check_caps(self) -> tuple[bool, str]:
        """Verifica caps de scalping: max_open, max_per_day, daily_loss."""
        # Max open scalping trades
        open_count = self._count_open_scalping_trades()
        if open_count >= self.settings.scalping_max_open_trades:
            return False, f"scalping_max_open_trades ({open_count}/{self.settings.scalping_max_open_trades})"

        # Max trades per day
        today_count = self._count_scalping_orders_today()
        if today_count >= self.settings.scalping_max_trades_per_day:
            return False, f"scalping_max_trades_per_day ({today_count}/{self.settings.scalping_max_trades_per_day})"

        # Daily loss cap (futuro: cuando _calculate_daily_pnl esté disponible)
        # Para v2.6.0 MVP, lo dejamos pasivo. v2.6.x implementará.

        return True, "ok"

    # ---------------- Heartbeat ----------------

    def _send_heartbeat_if_due(self) -> None:
        every_n = int(self.settings.scalping_heartbeat_every_n_trades)
        if every_n <= 0:
            return
        if self._trades_since_heartbeat < every_n:
            return
        self._trades_since_heartbeat = 0
        try:
            open_count = self._count_open_scalping_trades()
            today_count = self._count_scalping_orders_today()
            msg = (
                f"Scalping heartbeat\n"
                f"Trades hoy: {today_count}/{self.settings.scalping_max_trades_per_day}\n"
                f"Abiertos: {open_count}/{self.settings.scalping_max_open_trades}\n"
                f"Símbolos: {','.join(self.settings.scalping_allowed_symbols)}"
            )
            self.notifier.send_message(msg)
        except Exception:
            logger.exception("Scalping heartbeat notification failed")

    # ---------------- Helpers ----------------

    def _ensure_trader(self):
        if self.trader is not None:
            return self.trader
        try:
            from app.brokers.mt5_demo_trader import MT5DemoTrader
            self.trader = MT5DemoTrader(self.settings, self.mt5_reader)
        except Exception:
            logger.exception("Could not instantiate MT5DemoTrader for scalping")
            self.trader = None
        return self.trader

    def _is_global_kill_active(self) -> bool:
        raw = self.repository.get_state("kill_switch_active_until") or ""
        if not raw:
            return False
        try:
            until = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        return until > utc_now()

    def _fetch_open_scalping_trades(self) -> list[dict]:
        try:
            return self.repository.fetch_open_scalping_trades()
        except AttributeError:
            # Fallback: filtrar todos los open trades por is_scalping=1
            all_open = self.repository.fetch_open_positions_full() or []
            return [t for t in all_open if int(t.get("is_scalping") or 0) == 1]

    def _count_open_scalping_trades(self) -> int:
        return len(self._fetch_open_scalping_trades())

    def _count_scalping_orders_today(self) -> int:
        try:
            orders = self.repository.fetch_demo_orders(limit=200)
        except Exception:
            return 0
        today_str = utc_now().date().isoformat()
        count = 0
        for o in orders:
            if int(o.get("is_scalping") or 0) != 1:
                continue
            sent_at = str(o.get("sent_at") or "")
            if sent_at.startswith(today_str):
                count += 1
        return count

    def _fetch_latest_scalping_trade_id(self, symbol: str) -> int | None:
        try:
            trades = self._fetch_open_scalping_trades()
            for t in trades:
                if str(t.get("symbol") or "").upper() == symbol.upper():
                    return int(t["id"])
        except Exception:
            return None
        return None

    @staticmethod
    def _category_for_symbol(symbol: str) -> str:
        upper = symbol.upper()
        if "XAU" in upper or "GOLD" in upper:
            return "gold"
        return "forex"

    @staticmethod
    def _parse_iso(raw: Any) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
