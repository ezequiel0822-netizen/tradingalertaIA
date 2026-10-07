"""Trade reporter: mensajes Telegram cuando el bot abre / cierra paper trades.

Solo formatea, no envia. El caller (jobs.py / lifecycle_manager.py) usa
TelegramNotifier para mandar si settings.enable_trade_action_reports.
"""

from typing import Any

from app.database.models import TokenSnapshot
from app.risk.position_sizer import PositionSizing
from app.strategies.base import StrategySignal


CLOSE_REASON_EMOJI = {
    "stopped_simulated": "🔴",
    "target_2_simulated": "🟢",
    "closed_by_time": "🟡",
    "closed_by_invalidation": "🟠",
    "closed_by_strategy_exit": "🟠",
    "closed_by_kill_switch": "⛔",
    "partial_tp1": "🟢",
}


def format_trade_opened(
    snapshot: TokenSnapshot,
    signal: StrategySignal,
    sizing: PositionSizing,
    price_note: str | None = None,
) -> str:
    """v3.14.1: `price_note` aclara de dónde salen los niveles cuando se trasladaron
    al precio de MT5 (PAPER_PRICE_FROM_MT5)."""
    direction_emoji = "🟢" if signal.direction == "long" else "🔴"
    targets_str = ", ".join(f"TP{i+1} {t:g}" for i, t in enumerate(signal.targets))
    reasons_str = "; ".join(signal.reasoning[:3]) or "n/a"
    note = f" ({price_note})" if price_note else ""
    return (
        f"{direction_emoji} Abri {signal.direction} {snapshot.symbol} "
        f"({signal.strategy_name}, conf {signal.confidence}/100).\n"
        f"Entry {signal.entry:g}, SL {signal.stop:g}, {targets_str}{note}.\n"
        f"Size {sizing.size_notional:,.0f} USD (risk {sizing.risk_pct_actual:.2f}%).\n"
        f"Horizon {signal.time_horizon_hours}h. Razones: {reasons_str}.\n"
        f"Simulado, no orden real."
    )


def format_trade_closed(
    trade_row: dict[str, Any],
    reason_status: str,
    pnl_pct: float,
) -> str:
    emoji = CLOSE_REASON_EMOJI.get(reason_status, "⚪")
    symbol = trade_row.get("symbol") or trade_row.get("token_address") or "?"
    direction = trade_row.get("direction") or "long"
    strategy = trade_row.get("strategy_name") or "n/a"
    mfe = trade_row.get("mfe_pct") or 0
    mae = trade_row.get("mae_pct") or 0
    return (
        f"{emoji} Cerre {direction} {symbol} ({reason_status}).\n"
        f"Strategy {strategy}, P&L {pnl_pct:+.2f}%. "
        f"MFE {mfe:+.2f}% / MAE {mae:+.2f}%.\n"
        f"Simulado, no orden real."
    )
