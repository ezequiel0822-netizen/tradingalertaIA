"""MT5 demo order executor with manual-confirmation safety gates.

This module is intentionally separate from ``MT5Reader``.  ``MT5Reader`` stays
read-only; this class is the only place where Phase 5 may call ``order_send``.
It only allows demo accounts and keeps real-money trading blocked.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from app.brokers.mt5_reader import MT5Reader
from app.brokers.mt5_symbol_map import yahoo_to_mt5
from app.config.settings import Settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DemoOrderDraft:
    symbol: str
    direction: str
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_pct: float
    strategy_name: str | None
    reason: str
    request_summary: str


@dataclass(frozen=True)
class DemoValidationResult:
    ok: bool
    reason: str
    draft: DemoOrderDraft | None = None


@dataclass(frozen=True)
class DemoSendResult:
    ok: bool
    status: str
    reason: str
    retcode: int | None = None
    order_ticket: int | None = None
    deal_ticket: int | None = None
    price: float | None = None
    result_summary: str | None = None


@dataclass(frozen=True)
class DemoCloseResult:
    ok: bool
    ticket: int | None
    symbol: str
    volume: float | None
    reason: str
    retcode: int | None = None
    order_ticket: int | None = None
    deal_ticket: int | None = None
    price: float | None = None
    result_summary: str | None = None


class MT5DemoTrader:
    """Executes MT5 demo orders only after strict validation."""

    MAGIC = 250500
    # v3.13.0 — órdenes del agente IA (sandbox demo). Nada filtra posiciones por
    # magic: cierre, SL y reconciler trabajan por ticket. Sirve para separarlas en MT5.
    AGENT_MAGIC = 250501

    def __init__(self, settings: Settings, reader: MT5Reader | None = None) -> None:
        self.settings = settings
        self.reader = reader or MT5Reader(settings)
        self._owns_reader = reader is None

    def connect(self) -> bool:
        if not self.settings.enable_mt5_demo_trading:
            return False
        if not self.settings.enable_mt5_reader:
            return False
        if self.reader.is_connected():
            return True
        return self.reader.connect()

    def disconnect(self) -> None:
        if self._owns_reader:
            self.reader.disconnect()

    def prepare_from_paper_trade(
        self,
        paper_trade: dict[str, Any],
        open_demo_positions: int = 0,
        risk_cap_pct: float | None = None,
    ) -> DemoValidationResult:
        """Build a safe demo order draft from an open paper trade.

        v3.13.0: con `risk_cap_pct` (agente IA) el lote se ACHICA hasta que el riesgo
        quepa en min(risk_cap_pct, DEMO_RISK_PER_TRADE_PCT) en vez de rechazar; si
        ni el lote mínimo del broker cabe, rechaza. Sin el parámetro, idéntico a antes.
        """
        if not self.settings.enable_mt5_demo_trading:
            return DemoValidationResult(False, "ENABLE_MT5_DEMO_TRADING=false")
        if not self.settings.demo_order_require_confirmation:
            return DemoValidationResult(
                False, "DEMO_ORDER_REQUIRE_CONFIRMATION must stay true"
            )
        if open_demo_positions >= self.settings.demo_max_open_trades:
            return DemoValidationResult(False, "demo max open trades reached")
        if not self.connect():
            return DemoValidationResult(False, "MT5 demo trader not connected")

        account = self._account_dict()
        ok, reason = self._validate_demo_account(account)
        if not ok:
            return DemoValidationResult(False, reason)

        if str(paper_trade.get("status") or "") != "open":
            return DemoValidationResult(False, "paper trade is not open")
        category = str(paper_trade.get("category") or "").lower()
        if category not in {"forex", "gold"}:
            return DemoValidationResult(False, "only forex/gold paper trades allowed")

        symbol = self._resolve_symbol(str(paper_trade.get("symbol") or ""))
        if not symbol:
            return DemoValidationResult(False, "symbol not supported")
        if symbol.upper() not in self._allowed_symbols():
            return DemoValidationResult(False, f"symbol {symbol} not in allowed list")

        direction = self._normalize_direction(str(paper_trade.get("direction") or ""))
        if direction not in {"long", "short"}:
            return DemoValidationResult(False, "direction must be long or short")

        stop_loss = _to_float(paper_trade.get("stop_loss"))
        take_profit = _to_float(paper_trade.get("take_profit_1"))
        if stop_loss is None:
            return DemoValidationResult(False, "stop loss is mandatory")
        if take_profit is None:
            return DemoValidationResult(False, "take profit is mandatory")

        symbol_info = self._ensure_symbol(symbol)
        if symbol_info is None:
            return DemoValidationResult(False, f"symbol {symbol} not available in MT5")

        price = self._current_price(symbol, direction)
        if price is None:
            price = _to_float(paper_trade.get("entry_price"))
        if price is None or price <= 0:
            return DemoValidationResult(False, "entry/current price unavailable")

        ok, reason = self._validate_sl_tp(direction, price, stop_loss, take_profit)
        if not ok:
            return DemoValidationResult(False, reason)

        volume, reason = self._safe_volume(symbol_info)
        if volume is None:
            return DemoValidationResult(False, reason)

        risk_pct, reason = self._estimate_risk_pct(
            symbol_info=symbol_info,
            account=account,
            entry_price=price,
            stop_loss=stop_loss,
            volume=volume,
        )
        if risk_pct is None:
            return DemoValidationResult(False, reason)
        if risk_cap_pct is not None:
            cap = min(float(risk_cap_pct), float(self.settings.demo_risk_per_trade_pct))
            if risk_pct > cap:
                scaled = self._scale_volume_to_risk(symbol_info, volume, risk_pct, cap)
                if scaled is None:
                    return DemoValidationResult(
                        False, f"ni el lote mínimo cabe en {cap:.3f}% de riesgo"
                    )
                volume = scaled
                risk_pct, reason = self._estimate_risk_pct(
                    symbol_info=symbol_info,
                    account=account,
                    entry_price=price,
                    stop_loss=stop_loss,
                    volume=volume,
                )
                if risk_pct is None:
                    return DemoValidationResult(False, reason)
        if risk_pct > self.settings.demo_risk_per_trade_pct:
            return DemoValidationResult(
                False,
                (
                    f"demo risk {risk_pct:.3f}% exceeds "
                    f"{self.settings.demo_risk_per_trade_pct:.3f}%"
                ),
            )

        strategy = paper_trade.get("strategy_name")
        summary = (
            f"{direction.upper()} {symbol} {volume:g} lot @ {price:g} | "
            f"SL {stop_loss:g} | TP {take_profit:g} | risk {risk_pct:.3f}%"
        )
        return DemoValidationResult(
            True,
            "ready",
            DemoOrderDraft(
                symbol=symbol,
                direction=direction,
                volume=volume,
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_pct=risk_pct,
                strategy_name=str(strategy) if strategy else None,
                reason=str(paper_trade.get("thesis") or "paper trade candidate"),
                request_summary=summary,
            ),
        )

    def send_prepared_request(
        self,
        request_row: dict[str, Any],
        open_demo_positions: int = 0,
        magic: int | None = None,
        comment: str | None = None,
    ) -> DemoSendResult:
        """Revalidate and send one previously prepared demo order.

        v3.13.0: `magic`/`comment` opcionales (el agente IA usa AGENT_MAGIC); por
        defecto, los de siempre."""
        if not self.settings.enable_mt5_demo_trading:
            return DemoSendResult(False, "failed", "ENABLE_MT5_DEMO_TRADING=false")
        if open_demo_positions >= self.settings.demo_max_open_trades:
            return DemoSendResult(False, "failed", "demo max open trades reached")
        if not self.connect():
            return DemoSendResult(False, "failed", "MT5 demo trader not connected")

        account = self._account_dict()
        ok, reason = self._validate_demo_account(account)
        if not ok:
            return DemoSendResult(False, "failed", reason)

        symbol = str(request_row.get("symbol") or "").upper()
        direction = self._normalize_direction(str(request_row.get("direction") or ""))
        volume = _to_float(request_row.get("volume"))
        price = _to_float(request_row.get("entry_price"))
        stop_loss = _to_float(request_row.get("stop_loss"))
        take_profit = _to_float(request_row.get("take_profit"))
        if symbol not in self._allowed_symbols():
            return DemoSendResult(False, "failed", f"symbol {symbol} not allowed")
        if direction not in {"long", "short"}:
            return DemoSendResult(False, "failed", "invalid direction")
        if volume is None or volume <= 0:
            return DemoSendResult(False, "failed", "invalid volume")
        if price is None or price <= 0 or stop_loss is None or take_profit is None:
            return DemoSendResult(False, "failed", "price, SL and TP are mandatory")

        symbol_info = self._ensure_symbol(symbol)
        if symbol_info is None:
            return DemoSendResult(False, "failed", f"symbol {symbol} unavailable")
        current = self._current_price(symbol, direction)
        if current is not None:
            price = current
        ok, reason = self._validate_sl_tp(direction, price, stop_loss, take_profit)
        if not ok:
            return DemoSendResult(False, "failed", reason)

        risk_pct, reason = self._estimate_risk_pct(
            symbol_info=symbol_info,
            account=account,
            entry_price=price,
            stop_loss=stop_loss,
            volume=volume,
        )
        if risk_pct is None:
            return DemoSendResult(False, "failed", reason)
        if risk_pct > self.settings.demo_risk_per_trade_pct:
            return DemoSendResult(
                False,
                "failed",
                (
                    f"demo risk {risk_pct:.3f}% exceeds "
                    f"{self.settings.demo_risk_per_trade_pct:.3f}%"
                ),
            )

        mt5 = self._mt5()
        order_type = (
            getattr(mt5, "ORDER_TYPE_BUY", 0)
            if direction == "long"
            else getattr(mt5, "ORDER_TYPE_SELL", 1)
        )
        base_request = {
            "action": getattr(mt5, "TRADE_ACTION_DEAL", 1),
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": stop_loss,
            "tp": take_profit,
            "deviation": 20,
            "magic": int(magic) if magic is not None else self.MAGIC,
            "comment": comment or "TradingAlertAI demo",
            "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
        }
        return self._send_deal_request(base_request, symbol_info, price)

    def close_all_positions(self) -> list[DemoCloseResult]:
        """Close every open position on the connected MT5 demo account."""
        if not self.settings.enable_mt5_demo_trading:
            return [
                DemoCloseResult(
                    False, None, "", None, "ENABLE_MT5_DEMO_TRADING=false"
                )
            ]
        if not self.connect():
            return [DemoCloseResult(False, None, "", None, "MT5 demo trader not connected")]

        account = self._account_dict()
        ok, reason = self._validate_demo_account(account)
        if not ok:
            return [DemoCloseResult(False, None, "", None, reason)]

        positions = self.positions()
        if not positions:
            return []

        return [self._close_position(position) for position in positions]

    def close_position_by_ticket(self, ticket: int) -> DemoCloseResult:
        """v2.6.7: Cierra UNA posición específica por ticket. Usado por el reconciler.

        Previene huérfanas: cuando el paper_trade cerró (closed_by_time, force_exit,
        stopped_simulated por SL movido a breakeven post-TP1) pero la posición MT5
        sigue abierta con su SL original.
        """
        if not self.settings.enable_mt5_demo_trading:
            return DemoCloseResult(
                False, ticket, "", None, "ENABLE_MT5_DEMO_TRADING=false"
            )
        if not self.connect():
            return DemoCloseResult(
                False, ticket, "", None, "MT5 demo trader not connected"
            )
        account = self._account_dict()
        ok, reason = self._validate_demo_account(account)
        if not ok:
            return DemoCloseResult(False, ticket, "", None, reason)

        positions = self.positions()
        match = next(
            (p for p in positions if _optional_int(p.get("ticket")) == int(ticket)),
            None,
        )
        if match is None:
            return DemoCloseResult(
                False, ticket, "", None, f"position {ticket} not found in MT5"
            )
        return self._close_position(match)

    def update_position_sl(
        self, ticket: int, new_sl: float, new_tp: float | None = None
    ) -> DemoSendResult:
        """v2.6.7: Actualiza SL (y opcionalmente TP) de una posición abierta via TRADE_ACTION_SLTP.

        Necesario cuando el lifecycle del bot mueve el SL del paper_trade (trailing,
        breakeven post-TP1) — sin esto el SL real en MT5 queda en su valor original
        y la posición puede ir mucho más en contra antes de cerrar.

        Si new_tp es None, preserva el TP actual de la posición (TRADE_ACTION_SLTP
        de MT5 requiere ambos valores).
        """
        if not self.settings.enable_mt5_demo_trading:
            return DemoSendResult(False, "failed", "ENABLE_MT5_DEMO_TRADING=false")
        if not self.connect():
            return DemoSendResult(False, "failed", "MT5 demo trader not connected")
        account = self._account_dict()
        ok, reason = self._validate_demo_account(account)
        if not ok:
            return DemoSendResult(False, "failed", reason)

        positions = self.positions()
        match = next(
            (p for p in positions if _optional_int(p.get("ticket")) == int(ticket)),
            None,
        )
        if match is None:
            return DemoSendResult(False, "failed", f"position {ticket} not found in MT5")

        symbol = str(match.get("symbol") or "").upper()
        mt5 = self._mt5()
        request = {
            "action": getattr(mt5, "TRADE_ACTION_SLTP", 6),
            "position": int(ticket),
            "symbol": symbol,
            "sl": float(new_sl),
            "magic": self.MAGIC,
        }
        if new_tp is not None:
            request["tp"] = float(new_tp)
        else:
            existing_tp = _to_float(match.get("tp"))
            if existing_tp is not None and existing_tp > 0:
                request["tp"] = existing_tp

        try:
            result = mt5.order_send(request)
        except Exception as exc:
            logger.warning(
                "MT5 demo update_position_sl raised: %s", exc.__class__.__name__
            )
            return DemoSendResult(False, "failed", "order_send raised")
        if result is None:
            return DemoSendResult(False, "failed", "order_send returned None")

        result_dict = _asdict(result)
        retcode = _optional_int(result_dict.get("retcode"))
        comment = str(result_dict.get("comment") or "")
        success_codes = {
            getattr(mt5, "TRADE_RETCODE_DONE", 10009),
            getattr(mt5, "TRADE_RETCODE_PLACED", 10008),
        }
        ok = retcode in success_codes
        return DemoSendResult(
            ok=ok,
            status="sent" if ok else "failed",
            reason=(
                f"SL updated to {new_sl:g}" if ok else f"update_sl failed: {comment}"
            ),
            retcode=retcode,
            order_ticket=_optional_int(result_dict.get("order")),
            deal_ticket=_optional_int(result_dict.get("deal")),
            price=None,
            result_summary=(
                f"position={ticket} new_sl={new_sl:g} retcode={retcode}"
            ),
        )

    def _close_position(self, position: dict[str, Any]) -> DemoCloseResult:
        mt5 = self._mt5()
        ticket = _optional_int(position.get("ticket"))
        symbol = str(position.get("symbol") or "").upper()
        volume = _to_float(position.get("volume"))
        position_type = _optional_int(position.get("type"))
        buy_type = getattr(mt5, "ORDER_TYPE_BUY", 0)
        sell_type = getattr(mt5, "ORDER_TYPE_SELL", 1)

        if ticket is None:
            return DemoCloseResult(False, None, symbol, volume, "position ticket missing")
        if not symbol:
            return DemoCloseResult(False, ticket, symbol, volume, "position symbol missing")
        if volume is None or volume <= 0:
            return DemoCloseResult(False, ticket, symbol, volume, "position volume invalid")
        if position_type == buy_type:
            close_type = sell_type
            close_direction = "short"
        elif position_type == sell_type:
            close_type = buy_type
            close_direction = "long"
        else:
            return DemoCloseResult(
                False, ticket, symbol, volume, f"unsupported position type {position_type}"
            )

        symbol_info = self._ensure_symbol(symbol)
        if symbol_info is None:
            return DemoCloseResult(False, ticket, symbol, volume, "symbol unavailable")

        price = (
            self._current_price(symbol, close_direction)
            or _to_float(position.get("price_current"))
            or _to_float(position.get("price_open"))
        )
        if price is None or price <= 0:
            return DemoCloseResult(False, ticket, symbol, volume, "close price unavailable")

        result = self._send_deal_request(
            {
                "action": getattr(mt5, "TRADE_ACTION_DEAL", 1),
                "position": ticket,
                "symbol": symbol,
                "volume": volume,
                "type": close_type,
                "price": price,
                "deviation": 20,
                "magic": self.MAGIC,
                "comment": "TradingAlertAI close",
                "type_time": getattr(mt5, "ORDER_TIME_GTC", 0),
            },
            symbol_info,
            price,
        )
        return DemoCloseResult(
            ok=result.ok,
            ticket=ticket,
            symbol=symbol,
            volume=volume,
            reason=result.reason,
            retcode=result.retcode,
            order_ticket=result.order_ticket,
            deal_ticket=result.deal_ticket,
            price=result.price,
            result_summary=result.result_summary,
        )

    def _send_deal_request(
        self,
        base_request: dict[str, Any],
        symbol_info: Any,
        price: float,
    ) -> DemoSendResult:
        mt5 = self._mt5()
        success_codes = {
            getattr(mt5, "TRADE_RETCODE_DONE", 10009),
            getattr(mt5, "TRADE_RETCODE_PLACED", 10008),
        }
        invalid_fill = getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030)
        last_failure: DemoSendResult | None = None
        for filling_mode in self._filling_modes(symbol_info):
            request = {**base_request, "type_filling": filling_mode}
            try:
                result = mt5.order_send(request)
            except Exception as exc:
                logger.warning("MT5 demo order_send raised: %s", exc.__class__.__name__)
                return DemoSendResult(False, "failed", "order_send raised")
            if result is None:
                return DemoSendResult(False, "failed", "order_send returned None")

            result_dict = _asdict(result)
            retcode = _optional_int(result_dict.get("retcode"))
            order_ticket = _optional_int(result_dict.get("order"))
            deal_ticket = _optional_int(result_dict.get("deal"))
            executed_price = _to_float(result_dict.get("price")) or price
            comment = str(result_dict.get("comment") or "")
            ok = retcode in success_codes
            status = "sent" if ok else "failed"
            summary = (
                f"retcode={retcode}; order={order_ticket}; deal={deal_ticket}; "
                f"price={executed_price:g}; filling={filling_mode}; {comment}"
            ).strip()
            result_payload = DemoSendResult(
                ok=ok,
                status=status,
                reason="order_send accepted"
                if ok
                else f"order_send failed: {comment}",
                retcode=retcode,
                order_ticket=order_ticket,
                deal_ticket=deal_ticket,
                price=executed_price,
                result_summary=summary,
            )
            if ok:
                return result_payload
            last_failure = result_payload
            if retcode != invalid_fill:
                return result_payload

        return last_failure or DemoSendResult(
            False, "failed", "no MT5 filling mode available"
        )

    def compute_actual_notional_usd(
        self, symbol: str, volume: float, entry_price: float
    ) -> float | None:
        """v2.6.8: Computa el notional USD REAL de una posición MT5 demo.

        Existe el bug arquitectónico de que el position_sizer del bot usa
        `ACCOUNT_STARTING_BALANCE` (típicamente 1M teórico) para calcular
        `paper_trade.size_notional`. Pero MT5 ejecuta sólo `DEMO_MAX_LOT=0.1`,
        que son ~$10k de notional real, no $10M+. La discrepancia distorsiona
        `/aprendizaje`, `total_exposure_by_category`, y peor de todo
        `realized_pnl_today` (que disparó kill switch con -3.18% el 2026-05-28
        cuando el daño real era -0.13%).

        Este helper devuelve el notional USD verdadero basado en:
        - volume × trade_contract_size (si USD es BASE, ej. USDJPY → volume × 100k)
        - volume × trade_contract_size × entry_price (si USD es QUOTE,
          ej. EURUSD → 0.1 × 100k × 1.16 = $11,600; XAUUSD → 0.1 × 100 × 4400 = $44k)

        Para casos con base ni cuota USD (raros), aproxima con × entry_price.
        Devuelve None si symbol_info no está disponible — caller debe NO actualizar.
        """
        if not self.connect():
            return None
        info = self._ensure_symbol(symbol)
        if info is None:
            return None
        try:
            contract_size = _to_float(getattr(info, "trade_contract_size", 0))
            currency_base = str(getattr(info, "currency_base", "") or "")
        except (TypeError, ValueError, AttributeError):
            return None
        if contract_size is None or contract_size <= 0:
            return None
        if volume is None or volume <= 0 or entry_price is None or entry_price <= 0:
            return None
        if currency_base.upper() == "USD":
            return round(volume * contract_size, 2)
        return round(volume * contract_size * entry_price, 2)

    def actual_units(self, symbol: str, volume: float) -> float | None:
        """v2.6.8: Devuelve volumen × contract_size — unidades reales del activo.

        Para `paper_trade.size_units` consistente con `size_notional`.
        """
        if not self.connect():
            return None
        info = self._ensure_symbol(symbol)
        if info is None:
            return None
        try:
            contract_size = _to_float(getattr(info, "trade_contract_size", 0))
        except (TypeError, ValueError, AttributeError):
            return None
        if contract_size is None or contract_size <= 0:
            return None
        if volume is None or volume <= 0:
            return None
        return round(volume * contract_size, 4)

    def positions(self) -> list[dict[str, Any]]:
        if not self.connect():
            return []
        mt5 = self._mt5()
        try:
            raw_positions = mt5.positions_get()
        except Exception:
            return []
        if not raw_positions:
            return []
        positions: list[dict[str, Any]] = []
        for position in raw_positions:
            row = _asdict(position)
            positions.append(
                {
                    "ticket": row.get("ticket"),
                    "symbol": row.get("symbol"),
                    "volume": row.get("volume"),
                    "type": row.get("type"),
                    "price_open": row.get("price_open"),
                    "price_current": row.get("price_current"),
                    "sl": row.get("sl"),
                    "tp": row.get("tp"),
                    "profit": row.get("profit"),
                }
            )
        return positions

    def closed_position_outcome(
        self, position_ticket: int, stop_loss: float
    ) -> dict[str, Any] | None:
        """v3.14.0 — SOLO LECTURA: resultado real de una posición ya cerrada.

        Suma profit + swap + comisión + fee de todos sus deals
        (`history_deals_get(position=...)`, sin rango de fechas: así no depende de la
        hora del servidor) y lo divide por la pérdida que habría dado el SL con el
        volumen y el precio de apertura REALES (`order_calc_profit`). None si sigue
        abierta, si no hay deals o si MT5 no responde (el caller reintenta)."""
        if not position_ticket or not self.connect():
            return None
        mt5 = self._mt5()
        try:
            if mt5.positions_get(ticket=int(position_ticket)):
                return None                       # sigue abierta
            deals = mt5.history_deals_get(position=int(position_ticket))
        except Exception:
            return None
        rows = [_asdict(d) for d in (deals or ())]
        entry_in = getattr(mt5, "DEAL_ENTRY_IN", 0)
        exits = {getattr(mt5, "DEAL_ENTRY_OUT", 1), getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)}
        opens = [r for r in rows if r.get("entry") == entry_in]
        if not opens or not any(r.get("entry") in exits for r in rows):
            return None
        profit = sum(
            (_to_float(r.get(k)) or 0.0)
            for r in rows
            for k in ("profit", "swap", "commission", "fee")
        )
        first = opens[0]
        volume = sum(_to_float(r.get("volume")) or 0.0 for r in opens)
        price_open = _to_float(first.get("price"))
        is_buy = first.get("type") == getattr(mt5, "DEAL_TYPE_BUY", 0)
        order_type = getattr(mt5, "ORDER_TYPE_BUY", 0) if is_buy else getattr(
            mt5, "ORDER_TYPE_SELL", 1
        )
        risk_usd = None
        try:
            at_sl = mt5.order_calc_profit(
                order_type, str(first.get("symbol")), volume, price_open, float(stop_loss)
            )
            if at_sl is not None and float(at_sl) < 0:
                risk_usd = abs(float(at_sl))
        except Exception:
            risk_usd = None
        return {
            "profit_usd": round(profit, 2),
            "risk_usd": round(risk_usd, 2) if risk_usd else None,
            "r": round(profit / risk_usd, 4) if risk_usd else None,
            "symbol": first.get("symbol"),
            "volume": volume,
            "price_open": price_open,
        }

    def _mt5(self):
        mt5 = getattr(self.reader, "_mt5", None)
        if mt5 is None:
            raise RuntimeError("MT5 module unavailable")
        return mt5

    def _account_dict(self) -> dict[str, Any]:
        try:
            info = self._mt5().account_info()
        except Exception:
            return {}
        return _asdict(info) if info is not None else {}

    def _validate_demo_account(self, account: dict[str, Any]) -> tuple[bool, str]:
        if not account:
            return False, "account_info unavailable"
        if account.get("trade_allowed") is False:
            return False, "account trade_allowed=false"
        if account.get("trade_expert") is False:
            return False, "account trade_expert=false"
        if not self._is_demo_account(account):
            return False, "account is not demo; real trading is blocked"
        return True, "ok"

    def _is_demo_account(self, account: dict[str, Any]) -> bool:
        mt5 = self._mt5()
        trade_mode = account.get("trade_mode")
        demo_const = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
        if demo_const is not None and trade_mode == demo_const:
            return True
        text = " ".join(
            str(account.get(key) or "")
            for key in ("server", "company", "name")
        ).lower()
        return "demo" in text

    def _resolve_symbol(self, symbol: str) -> str | None:
        raw = symbol.strip().upper()
        if not raw:
            return None
        return yahoo_to_mt5(raw, self.settings.mt5_broker_profile) or raw

    def _allowed_symbols(self) -> set[str]:
        return {symbol.upper() for symbol in self.settings.demo_allowed_symbols}

    def _normalize_direction(self, direction: str) -> str:
        value = direction.strip().lower()
        if value in {"buy", "long"}:
            return "long"
        if value in {"sell", "short"}:
            return "short"
        return value

    def _ensure_symbol(self, symbol: str):
        mt5 = self._mt5()
        try:
            info = mt5.symbol_info(symbol)
        except Exception:
            return None
        if info is None:
            return None
        if not bool(getattr(info, "visible", True)):
            try:
                if not mt5.symbol_select(symbol, True):
                    return None
                info = mt5.symbol_info(symbol)
            except Exception:
                return None
        return info

    def _current_price(self, symbol: str, direction: str) -> float | None:
        tick = self.reader.get_tick(symbol)
        if not tick:
            return None
        if direction == "long":
            return _to_float(tick.get("ask")) or _to_float(tick.get("last"))
        return _to_float(tick.get("bid")) or _to_float(tick.get("last"))

    def _validate_sl_tp(
        self, direction: str, price: float, stop_loss: float, take_profit: float
    ) -> tuple[bool, str]:
        if direction == "long":
            if not stop_loss < price:
                return False, "long order requires SL below entry/current price"
            if not take_profit > price:
                return False, "long order requires TP above entry/current price"
        else:
            if not stop_loss > price:
                return False, "short order requires SL above entry/current price"
            if not take_profit < price:
                return False, "short order requires TP below entry/current price"
        return True, "ok"

    def _safe_volume(self, symbol_info: Any) -> tuple[float | None, str]:
        volume_min = _to_float(getattr(symbol_info, "volume_min", None)) or 0.01
        volume_step = _to_float(getattr(symbol_info, "volume_step", None)) or volume_min
        volume_max = _to_float(getattr(symbol_info, "volume_max", None)) or 100.0
        hard_cap = min(self.settings.demo_max_lot, volume_max)
        if hard_cap + 1e-12 < volume_min:
            return None, (
                f"DEMO_MAX_LOT {self.settings.demo_max_lot:g} below "
                f"broker min {volume_min:g}"
            )
        steps = math.floor((hard_cap - volume_min) / volume_step + 1e-12)
        volume = volume_min + max(0, steps) * volume_step
        volume = min(volume, hard_cap, volume_max)
        precision = _step_precision(volume_step)
        return round(volume, precision), "ok"

    def _scale_volume_to_risk(
        self, symbol_info: Any, volume: float, risk_pct: float, cap_pct: float
    ) -> float | None:
        """v3.13.0: lote más grande (múltiplo del step del broker) con riesgo <= cap.
        El riesgo es lineal en el volumen. None si ni volume_min cabe."""
        if risk_pct <= 0 or volume <= 0:
            return None
        volume_min = _to_float(getattr(symbol_info, "volume_min", None)) or 0.01
        volume_step = _to_float(getattr(symbol_info, "volume_step", None)) or volume_min
        # margen 1e-6: justo en el tope, el redondeo flotante del riesgo recalculado
        # podria quedar apenas encima y la orden se rechazaria.
        target = volume * cap_pct / risk_pct * (1.0 - 1e-6)
        if target < volume_min:
            return None
        steps = math.floor((target - volume_min) / volume_step + 1e-9)
        scaled = min(volume_min + max(0, steps) * volume_step, volume)
        return round(scaled, _step_precision(volume_step))

    def _estimate_risk_pct(
        self,
        symbol_info: Any,
        account: dict[str, Any],
        entry_price: float,
        stop_loss: float,
        volume: float,
    ) -> tuple[float | None, str]:
        equity = _to_float(account.get("equity")) or _to_float(account.get("balance"))
        tick_size = _to_float(getattr(symbol_info, "trade_tick_size", None))
        if tick_size is None or tick_size <= 0:
            tick_size = _to_float(getattr(symbol_info, "point", None))
        tick_value = _to_float(getattr(symbol_info, "trade_tick_value", None))
        if tick_value is None or tick_value <= 0:
            tick_value = _to_float(getattr(symbol_info, "trade_tick_value_profit", None))
        if tick_value is None or tick_value <= 0:
            tick_value = _to_float(getattr(symbol_info, "trade_tick_value_loss", None))
        if tick_value is None or tick_value <= 0:
            contract_size = _to_float(getattr(symbol_info, "trade_contract_size", None))
            if (
                contract_size is not None
                and contract_size > 0
                and tick_size is not None
                and tick_size > 0
            ):
                tick_value = tick_size * contract_size
        if equity is None or equity <= 0:
            return None, "account equity unavailable"
        if tick_size is None or tick_size <= 0 or tick_value is None or tick_value <= 0:
            return None, "symbol tick_size/tick_value unavailable"
        ticks_at_risk = abs(entry_price - stop_loss) / tick_size
        risk_amount = ticks_at_risk * tick_value * volume
        return round((risk_amount / equity) * 100.0, 6), "ok"

    def _filling_mode(self, symbol_info: Any) -> int:
        return self._filling_modes(symbol_info)[0]

    def _filling_modes(self, symbol_info: Any) -> list[int]:
        mt5 = self._mt5()
        mode = getattr(symbol_info, "filling_mode", None)
        order_fok = getattr(mt5, "ORDER_FILLING_FOK", 0)
        order_ioc = getattr(mt5, "ORDER_FILLING_IOC", 1)
        order_return = getattr(mt5, "ORDER_FILLING_RETURN", 2)
        symbol_fok = getattr(mt5, "SYMBOL_FILLING_FOK", 1)
        symbol_ioc = getattr(mt5, "SYMBOL_FILLING_IOC", 2)
        modes: list[int] = []

        if isinstance(mode, int):
            # MT5 exposes symbol_info.filling_mode as symbol capability flags,
            # while order_send expects an ORDER_FILLING_* enum value.
            if mode & symbol_ioc:
                modes.append(order_ioc)
            if mode & symbol_fok:
                modes.append(order_fok)
            # Some test doubles / brokers expose the order enum directly.
            if mode in {order_fok, order_ioc, order_return} and mode not in modes:
                modes.append(mode)
        for fallback in (order_ioc, order_fok, order_return):
            if fallback not in modes:
                modes.append(fallback)
        return modes


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _asdict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(vars(value))
    except TypeError:
        return {}


def _step_precision(step: float) -> int:
    text = f"{step:.10f}".rstrip("0")
    if "." not in text:
        return 0
    return min(8, len(text.split(".", 1)[1]))
