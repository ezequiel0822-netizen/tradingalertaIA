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
        """v2.6.5: % real del portfolio basado en USD perdido/ganado HOY (UTC).

        ANTES (broken hasta v2.6.4): sumaba `unrealized_return_pct` per-trade
        directamente. Causaba falsos drawdowns enormes cuando un trade chico
        se rugged (ej. memecoin -82% sobre $1k notional = $820 loss real, no
        -82% del portfolio de $100k). Disparaba el kill switch incorrectamente.

        Ahora: convierte cada trade a USD usando `size_notional`, suma USD
        ganados/perdidos, divide por balance actual. Trades sin
        `size_notional` válido (ej. paper trades memecoin que no se ejecutan
        a MT5) se ignoran porque no afectan el balance demo real.
        """
        today = utc_now().date()
        start_iso = f"{today.isoformat()}T00:00:00+00:00"
        closed = self.repository.fetch_closed_trades_since(start_iso)
        if not closed:
            return 0.0

        balance = self.account_balance()
        if balance <= 0:
            return 0.0

        total_usd_pnl = 0.0
        for t in closed:
            return_pct = _to_float(t.get("unrealized_return_pct"))
            notional = _to_float(t.get("size_notional"))
            if return_pct is None or notional is None or notional <= 0:
                continue
            usd_pnl = notional * (return_pct / 100.0)
            total_usd_pnl += usd_pnl

        return round((total_usd_pnl / balance) * 100.0, 4)

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
        """v2.6.5: prioridad MT5 live (con retry reconnect) → bot_state → starting_balance.

        ANTES (broken hasta v2.6.4): si MT5 estaba "conectado" pero
        get_account_info devolvía None (timeout silencioso después de horas),
        caía al starting_balance del .env. Resultado: /health reportaba 1M
        cuando el balance MT5 real era 100k.

        AHORA: si get_account_info devuelve None pero is_connected=True,
        intentamos un reconnect explícito antes de fallback. También
        persistimos el equity fresco en bot_state.account_balance para
        que el próximo arranque tenga un valor más realista que el starting.
        """
        if self.mt5_reader is not None and getattr(self.mt5_reader, "is_connected", lambda: False)():
            equity = self._fetch_mt5_equity()
            if equity is not None and equity > 0:
                # Persistir para que el próximo arranque tenga valor real, no starting.
                try:
                    self.repository.set_state("account_balance", str(equity))
                except Exception:
                    pass
                return equity
        stored = self.repository.get_state("account_balance")
        if stored:
            try:
                return float(stored)
            except ValueError:
                pass
        return float(self.settings.account_starting_balance)

    def _fetch_mt5_equity(self) -> float | None:
        """v2.6.5 helper: intenta leer equity con retry reconnect si la primera
        llamada devuelve None.

        El MT5 Python library a veces devuelve None silencioso cuando la sesión
        está "stale" (sin error explícito). Un reconnect refresca el state.
        """
        try:
            info = self.mt5_reader.get_account_info()
            if info and info.get("equity"):
                return float(info["equity"])
        except Exception:
            pass

        # Primera llamada falló — intentar reconnect 1 vez antes de fallback.
        try:
            disconnect = getattr(self.mt5_reader, "disconnect", None)
            if disconnect:
                disconnect()
            connect = getattr(self.mt5_reader, "connect", None)
            if connect and connect():
                info = self.mt5_reader.get_account_info()
                if info and info.get("equity"):
                    return float(info["equity"])
        except Exception:
            pass
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
