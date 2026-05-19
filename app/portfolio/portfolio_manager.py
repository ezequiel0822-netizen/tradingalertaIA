"""Portfolio Manager: posiciones abiertas, exposicion, P&L, equity curve.

Read-only: solo consulta SQLite y opcionalmente MT5 (account_info).
No abre, modifica ni cierra trades.
"""

from datetime import timedelta
from typing import Any

from app.config.settings import Settings
from app.database.repository import Repository
from app.utils.time_utils import utc_now


class PortfolioManager:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        mt5_reader=None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.mt5_reader = mt5_reader

    def get_open_positions(self) -> list[dict[str, Any]]:
        return self.repository.fetch_open_positions_full()

    def count_open_by_category(self) -> dict[str, int]:
        return self.repository.count_open_trades_by_category()

    def total_exposure_by_category(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for pos in self.get_open_positions():
            cat = str(pos.get("category") or "unknown")
            notional = _to_float(pos.get("size_notional")) or 0.0
            result[cat] = result.get(cat, 0.0) + notional
        return result

    def total_risk_pct(self, account_balance: float | None = None) -> float:
        if account_balance is None:
            account_balance = self.account_balance()
        if account_balance <= 0:
            return 0.0
        total = 0.0
        for pos in self.get_open_positions():
            entry = _to_float(pos.get("entry_price"))
            stop = _to_float(pos.get("stop_loss"))
            size_notional = _to_float(pos.get("size_notional")) or 0.0
            direction = str(pos.get("direction") or "long")
            if entry is None or stop is None or entry <= 0:
                continue
            if direction == "long":
                per_unit = entry - stop
            else:
                per_unit = stop - entry
            if per_unit <= 0:
                continue
            risk_amount = (per_unit / entry) * size_notional
            total += risk_amount
        return round((total / account_balance) * 100.0, 4)

    def unrealized_pnl_pct(self) -> float:
        positions = self.get_open_positions()
        if not positions:
            return 0.0
        total = sum(_to_float(p.get("unrealized_return_pct")) or 0.0 for p in positions)
        return round(total / len(positions), 4)

    def realized_pnl_today(self) -> float:
        """Suma de return_pct de trades cerrados HOY (UTC)."""
        today = utc_now().date()
        start_iso = f"{today.isoformat()}T00:00:00+00:00"
        closed = self.repository.fetch_closed_trades_since(start_iso)
        if not closed:
            return 0.0
        return round(
            sum(_to_float(t.get("unrealized_return_pct")) or 0.0 for t in closed), 4
        )

    def equity_curve(self, days: int = 14) -> list[tuple[str, float]]:
        rows = self.repository.fetch_daily_pnl_log(days=days)
        curve: list[tuple[str, float]] = []
        equity = 1.0
        for row in reversed(rows):
            pct = _to_float(row.get("realized_pnl_pct")) or 0.0
            equity *= 1.0 + (pct / 100.0)
            curve.append((str(row.get("date")), round(equity, 6)))
        return curve

    def account_balance(self) -> float:
        # prioridad: MT5 live → bot_state → starting_balance
        if self.mt5_reader is not None and getattr(self.mt5_reader, "is_connected", lambda: False)():
            try:
                info = self.mt5_reader.get_account_info()
                if info and info.get("equity"):
                    return float(info["equity"])
            except Exception:
                pass
        stored = self.repository.get_state("account_balance")
        if stored:
            try:
                return float(stored)
            except ValueError:
                pass
        return float(self.settings.account_starting_balance)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
