"""Lifecycle manager: gestiona posiciones abiertas vivas.

- Refresca latest_price (MT5 si disponible, sino token.latest_price del repo).
- Actualiza MFE/MAE + trailing (reusa logica de _update_paper_trades).
- Time exit: si paso el horizon, cierra closed_by_time.
- Partial close: si llega a TP1 y no esta partial_closed, marca y mueve stop a entry.
- (Invalidacion strategy: stub - se activa solo si hay candles fresh; Fase 3 lo completa.)

Read-only: no envia ordenes; solo actualiza paper_trades en SQLite.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.brokers.mt5_symbol_map import yahoo_to_mt5
from app.config.settings import Settings
from app.database.repository import Repository
from app.utils.time_utils import utc_now, utc_now_iso


logger = logging.getLogger(__name__)


def manage_open_positions(
    settings: Settings,
    repository: Repository,
    mt5_reader=None,
) -> dict[str, int]:
    summary = {
        "managed": 0,
        "time_closed": 0,
        "partial_closed": 0,
        "stopped": 0,
        "targets_hit": 0,
    }
    open_trades = repository.fetch_open_positions_full()
    if not open_trades:
        return summary

    broker_profile = getattr(settings, "mt5_broker_profile", "icmarkets")
    for trade in open_trades:
        summary["managed"] += 1
        latest = _fresh_price(trade, repository, mt5_reader, broker_profile)
        entry = _to_float(trade.get("entry_price"))
        if latest is None or entry is None or entry <= 0:
            continue

        direction = str(trade.get("direction") or "long")
        if direction == "long":
            current_return = ((latest - entry) / entry) * 100.0
        else:
            current_return = ((entry - latest) / entry) * 100.0

        prior_mfe = _to_float(trade.get("mfe_pct")) or 0.0
        prior_mae = _to_float(trade.get("mae_pct")) or 0.0
        new_mfe = max(prior_mfe, current_return)
        new_mae = min(prior_mae, current_return)

        updates: dict[str, Any] = {
            "latest_price": latest,
            "unrealized_return_pct": round(current_return, 4),
            "mfe_pct": round(new_mfe, 4),
            "mae_pct": round(new_mae, 4),
            "updated_at": utc_now_iso(),
        }

        stop = _to_float(trade.get("stop_loss"))
        tp1 = _to_float(trade.get("take_profit_1"))
        tp2 = _to_float(trade.get("take_profit_2"))

        # Trailing stop (reusa logica simplificada)
        if settings.enable_trailing_stop:
            category = str(trade.get("category") or "memecoin")
            if category == "stock":
                activation = settings.trailing_activation_pct_stock
                distance = settings.trailing_distance_pct_stock
            else:
                activation = settings.trailing_activation_pct_memecoin
                distance = settings.trailing_distance_pct_memecoin
            trailing_active = int(trade.get("trailing_active") or 0)
            if not trailing_active and current_return >= activation:
                trailing_active = 1
                updates["trailing_active"] = 1
            if trailing_active and direction == "long":
                new_stop = latest * (1 - distance / 100.0)
                if stop is None or new_stop > stop:
                    stop = new_stop
                    updates["stop_loss"] = round(new_stop, 8)

        # Partial close en TP1
        partial_closed = int(trade.get("partial_closed") or 0)
        if (
            settings.enable_partial_close_at_tp1
            and not partial_closed
            and tp1 is not None
        ):
            hit_tp1 = (direction == "long" and latest >= tp1) or (
                direction == "short" and latest <= tp1
            )
            if hit_tp1:
                size_notional = _to_float(trade.get("size_notional"))
                if size_notional is not None:
                    updates["size_notional"] = round(
                        size_notional * (1 - settings.partial_close_fraction), 4
                    )
                updates["partial_closed"] = 1
                # Mover stop a breakeven (entry)
                updates["stop_loss"] = round(entry, 8)
                stop = entry
                summary["partial_closed"] += 1
                logger.info(
                    "Partial close TP1: trade_id=%s symbol=%s",
                    trade.get("id"),
                    trade.get("symbol"),
                )

        # Time-based exit
        status = "open"
        closed_at = None
        if settings.enable_time_based_exit:
            horizon = _to_float(trade.get("time_horizon_hours"))
            if horizon is None or horizon <= 0:
                horizon = float(settings.default_time_horizon_hours)
            opened_at = _parse_iso(trade.get("opened_at"))
            if opened_at is not None:
                age_hours = (utc_now() - opened_at).total_seconds() / 3600.0
                if age_hours >= horizon:
                    status = "closed_by_time"
                    closed_at = utc_now_iso()
                    summary["time_closed"] += 1
                    logger.info(
                        "Time exit: trade_id=%s age=%.1fh horizon=%.1fh",
                        trade.get("id"),
                        age_hours,
                        horizon,
                    )

        # Stop / target hit (despues de trailing y partial)
        if status == "open":
            if direction == "long":
                if stop is not None and latest <= stop:
                    status = "stopped_simulated"
                    closed_at = utc_now_iso()
                    summary["stopped"] += 1
                elif tp2 is not None and latest >= tp2:
                    status = "target_2_simulated"
                    closed_at = utc_now_iso()
                    summary["targets_hit"] += 1
            else:  # short
                if stop is not None and latest >= stop:
                    status = "stopped_simulated"
                    closed_at = utc_now_iso()
                    summary["stopped"] += 1
                elif tp2 is not None and latest <= tp2:
                    status = "target_2_simulated"
                    closed_at = utc_now_iso()
                    summary["targets_hit"] += 1

        updates["status"] = status
        updates["closed_at"] = closed_at
        repository.update_paper_trade(int(trade["id"]), updates)

    return summary


def _fresh_price(
    trade: dict, repository: Repository, mt5_reader=None, broker_profile: str = "icmarkets"
) -> float | None:
    # 1. MT5 si conectado y aplica
    if mt5_reader is not None and getattr(mt5_reader, "is_connected", lambda: False)():
        raw_symbol = trade.get("token_address") or trade.get("symbol")
        if raw_symbol:
            # v2.7.0: mapear Yahoo→MT5 (ej. 'USDCHF=X'→'USDCHF', 'GC=F'→'XAUUSD').
            # Antes se pasaba el símbolo Yahoo crudo a get_tick → siempre fallaba
            # para forex/gold y caía al fallback de precio stale (token.latest_price
            # ≈ entry). Por eso los paper_trades forex/gold tenían precio congelado.
            mt5_symbol = yahoo_to_mt5(str(raw_symbol), broker_profile) or str(raw_symbol)
            try:
                tick = mt5_reader.get_tick(mt5_symbol)
                if tick and tick.get("bid"):
                    return float(tick["bid"])
            except Exception:
                pass
    # 2. token.latest_price del repo
    token = repository.get_token(
        str(trade.get("chain")), str(trade.get("token_address"))
    )
    if token:
        latest = token.get("latest_price")
        if latest is not None:
            try:
                return float(latest)
            except (TypeError, ValueError):
                return None
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
