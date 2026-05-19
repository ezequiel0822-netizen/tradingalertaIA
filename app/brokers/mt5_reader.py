"""MT5 reader adapter (read-only, soft-fail).

Lee precios y datos de cuenta de MetaTrader 5 sin mandar ordenes.
Si el package MetaTrader5 no esta instalado o initialize() falla, el adapter
queda en estado "disabled" y todos los metodos retornan None sin lanzar
excepciones, asi el bot sigue corriendo degradado con yfinance.

Read-only: NUNCA llama order_send, position_modify, ni close.
Logs no incluyen password, server completo ni login.
"""

import logging
from typing import Any

from app.config.settings import Settings


logger = logging.getLogger(__name__)


class MT5Reader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._mt5 = None
        self._connected = False

    def connect(self) -> bool:
        if not self.settings.enable_mt5_reader:
            return False
        try:
            import MetaTrader5 as mt5  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "MetaTrader5 package not installed; running without MT5 reader"
            )
            return False

        kwargs: dict[str, Any] = {}
        if self.settings.mt5_path:
            kwargs["path"] = self.settings.mt5_path
        if self.settings.mt5_login is not None:
            kwargs["login"] = self.settings.mt5_login
        if self.settings.mt5_password:
            kwargs["password"] = self.settings.mt5_password
        if self.settings.mt5_server:
            kwargs["server"] = self.settings.mt5_server
        kwargs["timeout"] = self.settings.mt5_connection_timeout_ms

        try:
            ok = mt5.initialize(**kwargs)
        except Exception:
            logger.warning("MT5 initialize raised; running without MT5 reader")
            return False

        if not ok:
            try:
                error_code = mt5.last_error()[0]
            except Exception:
                error_code = "unknown"
            logger.warning("MT5 initialize failed (code=%s); running degraded", error_code)
            return False

        self._mt5 = mt5
        self._connected = True
        logger.info("MT5 reader connected (read-only)")
        return True

    def disconnect(self) -> None:
        if self._mt5 is not None:
            try:
                self._mt5.shutdown()
            except Exception:
                pass
        self._mt5 = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self._mt5 is not None

    def get_tick(self, symbol: str) -> dict | None:
        if not self.is_connected():
            return None
        try:
            tick = self._mt5.symbol_info_tick(symbol)  # type: ignore[union-attr]
        except Exception:
            return None
        if tick is None:
            return None
        return {
            "bid": float(getattr(tick, "bid", 0)),
            "ask": float(getattr(tick, "ask", 0)),
            "last": float(getattr(tick, "last", 0)) or None,
            "time": int(getattr(tick, "time", 0)),
        }

    def get_rates(
        self, symbol: str, timeframe: int, count: int
    ) -> list[dict] | None:
        if not self.is_connected():
            return None
        try:
            rates = self._mt5.copy_rates_from_pos(symbol, timeframe, 0, count)  # type: ignore[union-attr]
        except Exception:
            return None
        if rates is None:
            return None
        candles: list[dict] = []
        for r in rates:
            candles.append(
                {
                    "time": int(r["time"]),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r.get("tick_volume", 0) or 0),
                }
            )
        return candles

    def get_account_info(self) -> dict | None:
        if not self.is_connected():
            return None
        try:
            info = self._mt5.account_info()  # type: ignore[union-attr]
        except Exception:
            return None
        if info is None:
            return None
        return {
            "balance": float(getattr(info, "balance", 0)),
            "equity": float(getattr(info, "equity", 0)),
            "currency": str(getattr(info, "currency", "USD")),
            "leverage": int(getattr(info, "leverage", 1)),
        }
