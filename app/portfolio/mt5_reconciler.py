"""MT5 Position Reconciler — v2.6.7.

Tapa el bug de posiciones MT5 demo huérfanas detectado el 2026-05-27.

Problema: cuando el bot abre una orden a MT5 demo, crea un paper_trade vinculado.
Si después el paper_trade cierra por una razón distinta a SL/TP de MT5 (time exit,
force_exit_timeout scalping, stopped_simulated por SL movido a breakeven post-TP1,
etc), la posición MT5 sigue abierta con su SL original. El bot la "olvida" y sigue
perdiendo dinero hasta que MT5 mismo hit SL (por bid/ask real) o intervención manual.

El 2026-05-27 esto le costó al usuario ~$9,600 de gap entre el paper PnL trackeado
(-$2,162) y la pérdida real del balance MT5 (-$12,106).

Solución: cada ciclo, después del lifecycle, este reconciler:
1. Obtiene todas las posiciones MT5 abiertas via trader.positions().
2. Matchea cada una con su paper_trade via demo_orders.order_ticket.
3. Si el paper_trade está CERRADO → cierra la posición MT5 (huérfana).
4. Si el paper_trade está ABIERTO pero su SL difiere de MT5.sl → actualiza MT5.sl
   (solo TIGHTENING — nunca relaja el SL existente para no empeorar el risk).

Soft-fail: cualquier error en una posición no afecta el resto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class ReconcileSummary:
    positions_checked: int = 0
    orphans_closed: int = 0
    orphans_close_failed: int = 0
    sls_synced: int = 0
    sls_sync_failed: int = 0
    unmatched: int = 0  # Posiciones MT5 sin demo_order matching (ej. abierta manual)
    errors: int = 0


class MT5Reconciler:
    """Reconcilia posiciones MT5 demo con paper_trades del bot.

    Pensado para correr cada ciclo del main loop (POLL_INTERVAL_SECONDS=60),
    después del lifecycle. Costo: 1 llamada `positions_get()` MT5 + 1 query SQLite
    bulk por tickets. Despreciable.
    """

    # Si la diferencia entre paper_trade.SL y MT5 position.sl es menor a
    # SL_SYNC_TOLERANCE_PIPS * pip_size, no sincronizamos (evita spam de updates
    # por ruido de floating-point o pequeños movimientos de trailing).
    SL_SYNC_TOLERANCE_PIPS = 0.5

    def __init__(
        self,
        settings: Any,
        repository: Any,
        trader: Any,
        mt5_reader: Any = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.trader = trader
        self.mt5_reader = mt5_reader

    def reconcile(self) -> ReconcileSummary:
        """Entry point. Devuelve summary con counts por categoría de acción."""
        summary = ReconcileSummary()
        if not getattr(self.settings, "enable_mt5_demo_trading", False):
            return summary
        if self.trader is None:
            return summary

        # 1. Obtener posiciones MT5 actuales
        try:
            positions = self.trader.positions()
        except Exception:
            logger.exception("MT5Reconciler: trader.positions() failed")
            summary.errors += 1
            return summary

        summary.positions_checked = len(positions)
        if not positions:
            return summary

        # 2. Bulk lookup de demo_orders por order_ticket
        tickets = [
            int(p["ticket"])
            for p in positions
            if p.get("ticket") is not None
        ]
        try:
            orders_by_ticket = self.repository.fetch_demo_orders_by_tickets(tickets)
        except Exception:
            logger.exception(
                "MT5Reconciler: fetch_demo_orders_by_tickets failed"
            )
            summary.errors += 1
            return summary

        # 3. Procesar cada posición individualmente (soft-fail por una no afecta el resto)
        for position in positions:
            try:
                self._reconcile_one(position, orders_by_ticket, summary)
            except Exception:
                logger.exception(
                    "MT5Reconciler: error reconciling position ticket=%s",
                    position.get("ticket"),
                )
                summary.errors += 1

        # 4. Log resumen si hubo cualquier acción (silenciar si nada cambió)
        if (
            summary.orphans_closed
            or summary.sls_synced
            or summary.orphans_close_failed
            or summary.sls_sync_failed
            or summary.errors
        ):
            logger.info(
                "MT5Reconciler: checked=%d closed=%d sl_synced=%d "
                "close_failed=%d sl_sync_failed=%d unmatched=%d errors=%d",
                summary.positions_checked,
                summary.orphans_closed,
                summary.sls_synced,
                summary.orphans_close_failed,
                summary.sls_sync_failed,
                summary.unmatched,
                summary.errors,
            )
        return summary

    def _reconcile_one(
        self,
        position: dict[str, Any],
        orders_by_ticket: dict[int, dict[str, Any]],
        summary: ReconcileSummary,
    ) -> None:
        ticket = position.get("ticket")
        if ticket is None:
            summary.errors += 1
            return
        try:
            ticket_int = int(ticket)
        except (TypeError, ValueError):
            summary.errors += 1
            return

        order = orders_by_ticket.get(ticket_int)
        if order is None:
            # Posición MT5 sin demo_order matching (puede ser abierta manualmente
            # por el usuario, o pre-bot). NO la tocamos.
            summary.unmatched += 1
            logger.debug(
                "MT5Reconciler: position ticket=%s sin demo_order match — ignorada",
                ticket_int,
            )
            return

        paper_trade_id = order.get("paper_trade_id")
        if paper_trade_id is None:
            summary.unmatched += 1
            return

        paper_trade = self.repository.fetch_paper_trade_by_id(int(paper_trade_id))
        if paper_trade is None:
            # demo_order existe pero paper_trade fue borrado — caso raro
            summary.unmatched += 1
            logger.debug(
                "MT5Reconciler: ticket=%s paper_trade=%s not found",
                ticket_int,
                paper_trade_id,
            )
            return

        paper_status = str(paper_trade.get("status") or "")

        # CASO 1: paper_trade está CERRADO → la MT5 position es huérfana
        if paper_status != "open":
            result = self.trader.close_position_by_ticket(ticket_int)
            if result.ok:
                summary.orphans_closed += 1
                logger.info(
                    "MT5Reconciler closed orphan: ticket=%s symbol=%s "
                    "paper_trade=%s paper_status=%s",
                    ticket_int,
                    position.get("symbol"),
                    paper_trade_id,
                    paper_status,
                )
            else:
                summary.orphans_close_failed += 1
                logger.warning(
                    "MT5Reconciler FAILED close orphan ticket=%s paper_trade=%s: %s",
                    ticket_int,
                    paper_trade_id,
                    result.reason,
                )
            return

        # CASO 2: paper_trade abierto + SL difiere → sincronizar
        paper_sl = _to_float(paper_trade.get("stop_loss"))
        mt5_sl = _to_float(position.get("sl"))
        if paper_sl is None or mt5_sl is None or paper_sl <= 0 or mt5_sl <= 0:
            return

        pip_size = self._estimate_pip_size(position.get("symbol"))
        tolerance = (
            self.SL_SYNC_TOLERANCE_PIPS * pip_size if pip_size > 0 else 0.0
        )
        if abs(paper_sl - mt5_sl) <= tolerance:
            return

        # Reglas de seguridad: solo tightening, nunca loosening
        direction = self._direction_from_position_type(position.get("type"))
        if direction == "long" and paper_sl < mt5_sl:
            # No relajar SL hacia abajo en long
            return
        if direction == "short" and paper_sl > mt5_sl:
            # No relajar SL hacia arriba en short
            return

        mt5_tp = _to_float(position.get("tp"))
        result = self.trader.update_position_sl(ticket_int, paper_sl, mt5_tp)
        if result.ok:
            summary.sls_synced += 1
            logger.info(
                "MT5Reconciler synced SL: ticket=%s symbol=%s old_sl=%g -> new_sl=%g",
                ticket_int,
                position.get("symbol"),
                mt5_sl,
                paper_sl,
            )
        else:
            summary.sls_sync_failed += 1
            logger.warning(
                "MT5Reconciler FAILED sync SL ticket=%s: %s",
                ticket_int,
                result.reason,
            )

    def _estimate_pip_size(self, symbol: Any) -> float:
        """Usa mt5_reader.symbol_info si disponible, sino asume 0.0001 (forex 4-digit)."""
        if not symbol or self.mt5_reader is None:
            return 0.0001
        try:
            info = self.mt5_reader.symbol_info(str(symbol)) or {}
            point = float(info.get("point") or 0)
            digits = int(info.get("digits") or 0)
            if point <= 0:
                return 0.0001
            return point * 10 if digits in (5, 3) else point
        except Exception:
            return 0.0001

    @staticmethod
    def _direction_from_position_type(pos_type: Any) -> str:
        """MT5: type 0 = BUY (long), 1 = SELL (short)."""
        try:
            t = int(pos_type)
        except (TypeError, ValueError):
            return "unknown"
        if t == 0:
            return "long"
        if t == 1:
            return "short"
        return "unknown"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
