"""MT5 reader adapter (read-only, soft-fail).

Lee precios y datos de cuenta de MetaTrader 5 sin mandar ordenes.
Si el package MetaTrader5 no esta instalado o initialize() falla, el adapter
queda en estado "disabled" y todos los metodos retornan None sin lanzar
excepciones, asi el bot sigue corriendo degradado con yfinance.

Read-only: NUNCA llama order_send, position_modify, ni close.
Logs no incluyen password, server completo ni login.
"""

import logging
from datetime import datetime
from typing import Any

from app.config.settings import Settings


logger = logging.getLogger(__name__)


class MT5Timeframe:
    """Constants de timeframes para MT5 (minutos por barra).

    Estos son los mismos valores que MetaTrader5 expone como TIMEFRAME_*,
    pero hardcoded aqui asi tests sin MT5 instalado tambien pueden usarlos.
    """
    M1 = 1
    M5 = 5
    M15 = 15
    M30 = 30
    H1 = 60
    H4 = 240
    D1 = 1440
    W1 = 10080


def _safe_tick_volume(r: Any) -> float:
    """Extrae tick_volume de un registro de copy_rates_from_pos.

    v2.6.4: copy_rates_from_pos devuelve numpy structured array; cada elemento
    es numpy.void que soporta bracket access r["tick_volume"] pero NO r.get().
    Tests pueden pasar dict (que soporta ambos) — esta función maneja ambos.
    """
    try:
        value = r["tick_volume"]
    except (ValueError, IndexError, KeyError, TypeError):
        return 0.0
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


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
        # v2.6.5: ensure symbol is selected in Market Watch before fetching rates.
        # MT5 copy_rates_from_pos devuelve None silenciosamente para símbolos no
        # seleccionados. Llamar symbol_select(symbol, True) auto-agrega el
        # símbolo al Market Watch si no estaba. Previene el bug "0 velas M1"
        # cuando el usuario agrega símbolos a SCALPING_ALLOWED_SYMBOLS sin
        # tenerlos visibles en MT5 desktop.
        try:
            self._mt5.symbol_select(symbol, True)  # type: ignore[union-attr]
        except Exception:
            # No bloqueamos por error en symbol_select — algunos brokers pueden
            # rechazar pero copy_rates_from_pos podría funcionar igual.
            pass
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
                    "volume": _safe_tick_volume(r),
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
            "server": str(getattr(info, "server", "")),
            "login": int(getattr(info, "login", 0)),
            "name": str(getattr(info, "name", "")),
        }

    # Phase 4 v2.3.0 — extensiones para validacion y position sizing real
    def validate_symbol(self, symbol: str) -> bool:
        """True si el broker reconoce el simbolo."""
        if not self.is_connected():
            return False
        try:
            info = self._mt5.symbol_info(symbol)  # type: ignore[union-attr]
            return info is not None
        except Exception:
            return False

    def symbol_info(self, symbol: str) -> dict | None:
        """Devuelve info del simbolo: spread, point, digits, contract size,
        volume min/step, tick value, currency_profit."""
        if not self.is_connected():
            return None
        try:
            info = self._mt5.symbol_info(symbol)  # type: ignore[union-attr]
        except Exception:
            return None
        if info is None:
            return None
        return {
            "name": str(getattr(info, "name", symbol)),
            "spread": float(getattr(info, "spread", 0)),
            "point": float(getattr(info, "point", 0)),
            "digits": int(getattr(info, "digits", 0)),
            "trade_contract_size": float(getattr(info, "trade_contract_size", 0)),
            "volume_min": float(getattr(info, "volume_min", 0)),
            "volume_step": float(getattr(info, "volume_step", 0)),
            "tick_value": float(getattr(info, "trade_tick_value", 0)),
            "tick_size": float(getattr(info, "trade_tick_size", 0)),
            "currency_profit": str(getattr(info, "currency_profit", "USD")),
        }

    def compute_pip_value(
        self, symbol: str, lot_size: float = 1.0
    ) -> float | None:
        """Pip value en moneda de cuenta para 1 lote del simbolo.

        Aproximacion: tick_value * (point * 10 / tick_size) * lot_size.
        Para FX majors / pares ICMarkets resulta en USD/pip realista.
        """
        info = self.symbol_info(symbol)
        if not info:
            return None
        tick_value = info.get("tick_value") or 0
        tick_size = info.get("tick_size") or 0
        point = info.get("point") or 0
        if tick_size <= 0 or point <= 0:
            return None
        # 1 pip = 10 points para pares 5-digit, 1 point para 3-digit (JPY)
        digits = info.get("digits") or 0
        pip_in_points = 10 if digits in (3, 5) else 1
        pip_value_per_lot = tick_value * (pip_in_points * point / tick_size)
        return round(pip_value_per_lot * lot_size, 6)

    def get_historical_range(
        self,
        symbol: str,
        timeframe: int,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[dict] | None:
        """Wrapper sobre mt5.copy_rates_range para fetch historico arbitrario."""
        if not self.is_connected():
            return None
        try:
            rates = self._mt5.copy_rates_range(  # type: ignore[union-attr]
                symbol, timeframe, start_utc, end_utc
            )
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
                    "volume": _safe_tick_volume(r),
                }
            )
        return candles
