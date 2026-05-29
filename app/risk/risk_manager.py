"""Risk Manager de cuenta.

Aplica gates duros antes de abrir trades:
- Kill-switch (manual o automatico por drawdown).
- Max trades concurrentes total y por categoria.
- Max riesgo agregado de cuenta.
- Max drawdown diario (activa kill-switch automatico).

Read-only: solo decide si permitir / bloquear / forzar cierre. No envia ordenes.
"""

import logging
from datetime import timedelta
from typing import Any

from app.config.settings import Settings
from app.database.repository import Repository
from app.portfolio.portfolio_manager import PortfolioManager
from app.utils.time_utils import utc_now, utc_now_iso


logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        portfolio_manager: PortfolioManager,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.portfolio_manager = portfolio_manager

    def is_kill_switch_active(self) -> tuple[bool, str | None]:
        raw = self.repository.get_state("kill_switch_active_until")
        if not raw:
            return False, None
        try:
            from datetime import datetime
            until = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False, None
        if until <= utc_now():
            return False, None
        reason = self.repository.get_state("kill_switch_reason") or "manual"
        return True, f"{reason} (hasta {until.isoformat()})"

    def check_can_open_trade(
        self,
        category: str,
        proposed_risk_pct: float,
        symbol: str | None = None,
    ) -> tuple[bool, str]:
        active, reason = self.is_kill_switch_active()
        if active:
            return False, f"kill switch active: {reason}"

        # v2.6.9 — per-symbol cooldown anti-feedback-loop.
        # Bug del 28-may: bot abrió 159 USDCHF orders en 20 min (~8/min) porque
        # forex_session_breakout re-detectaba el mismo setup tras cada SL hit.
        # Dedup global (DEDUP_WINDOW_MINUTES=360) protege alertas Telegram pero
        # NO los trades. Este check rechaza si hay paper_trade del mismo símbolo
        # opened en los últimos N minutos.
        cooldown_min = int(getattr(self.settings, "strategy_symbol_cooldown_minutes", 0))
        if symbol and cooldown_min > 0:
            cutoff = utc_now() - timedelta(minutes=cooldown_min)
            if self.repository.has_recent_paper_trade_for_symbol(
                symbol, cutoff.isoformat()
            ):
                return (
                    False,
                    f"symbol_cooldown_active ({symbol}, last trade <{cooldown_min}min ago)",
                )

        counts = self.portfolio_manager.count_open_by_category()
        total_open = sum(counts.values())
        if total_open >= self.settings.max_open_trades_total:
            return (
                False,
                f"max_open_trades_total reached ({total_open}/{self.settings.max_open_trades_total})",
            )

        per_cat_limits = {
            "stock": self.settings.max_open_trades_stock,
            "forex": self.settings.max_open_trades_forex,
            "gold": self.settings.max_open_trades_gold,
        }
        cat_limit = per_cat_limits.get(category)
        if cat_limit is not None:
            open_in_cat = counts.get(category, 0)
            if open_in_cat >= cat_limit:
                return (
                    False,
                    f"max_open_trades_{category} reached ({open_in_cat}/{cat_limit})",
                )

        current_risk = self.portfolio_manager.total_risk_pct()
        # v2.5.5: cap separado para forex/gold cuando demo trading está activo.
        # Sin esto, stocks paper acumulan riesgo y bloquean signals forex/oro que
        # SÍ tienen pretensión de ejecutar a MT5 demo via auto-confirm.
        applicable_cap = self.settings.max_total_risk_pct
        cap_name = "max_total_risk_pct"
        if (
            category in {"forex", "gold"}
            and self.settings.enable_mt5_demo_trading
        ):
            applicable_cap = self.settings.demo_max_total_risk_pct
            cap_name = "demo_max_total_risk_pct"
        if current_risk + proposed_risk_pct > applicable_cap:
            return (
                False,
                f"{cap_name} exceeded ({current_risk:.2f}+{proposed_risk_pct:.2f}>{applicable_cap})",
            )

        if self.settings.enable_kill_switch_auto:
            daily_pnl = self.portfolio_manager.realized_pnl_today()
            if daily_pnl < -self.settings.max_daily_drawdown_pct:
                self.trigger_kill_switch(
                    reason=f"daily drawdown {daily_pnl:.2f}% < -{self.settings.max_daily_drawdown_pct}%",
                    hours=self.settings.kill_switch_cooldown_hours,
                )
                return (
                    False,
                    f"daily drawdown breach ({daily_pnl:.2f}%); kill switch activated",
                )

        return True, "ok"

    def trigger_kill_switch(self, reason: str, hours: int) -> None:
        until = utc_now() + timedelta(hours=hours)
        self.repository.set_state("kill_switch_active_until", until.isoformat())
        self.repository.set_state("kill_switch_reason", reason)
        logger.warning("Kill switch triggered: %s (until %s)", reason, until.isoformat())

    def release_kill_switch(self) -> None:
        self.repository.set_state("kill_switch_active_until", "")
        self.repository.set_state("kill_switch_reason", "")
        logger.info("Kill switch released")

    def force_close_all_open(self, reason: str) -> int:
        closed = 0
        for pos in self.portfolio_manager.get_open_positions():
            self.repository.update_paper_trade(
                int(pos["id"]),
                {
                    "status": "closed_by_kill_switch",
                    "closed_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                },
            )
            closed += 1
        logger.warning("Force-closed %s open trades: %s", closed, reason)
        return closed
