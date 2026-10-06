"""MT5 historical fetcher con cache local en SQLite.

Para walk-forward backtester evitamos pedir el mismo bar dos veces al broker.
Se persiste en `mt5_historical_cache` con UNIQUE(symbol, timeframe, time).
"""

import logging
from datetime import datetime, timezone
from typing import Any

from app.brokers.mt5_reader import MT5Reader
from app.brokers.mt5_time import ensure_cache_time_basis, mark_cache_time_basis
from app.config.settings import Settings


logger = logging.getLogger(__name__)


class MT5HistoricalFetcher:
    def __init__(
        self,
        settings: Settings,
        repository: Any,
        mt5_reader: MT5Reader,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.mt5_reader = mt5_reader

    def fetch_window(
        self,
        symbol: str,
        timeframe_minutes: int,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[dict]:
        """Devuelve candles en la ventana. Combina cache + fetch live.

        Si MT5 no conectado, devuelve solo lo que hay en cache.
        """
        start_epoch = int(start_utc.replace(tzinfo=timezone.utc).timestamp())
        end_epoch = int(end_utc.replace(tzinfo=timezone.utc).timestamp())

        cached = self._read_cache(symbol, timeframe_minutes, start_epoch, end_epoch)

        # Si tenemos cache "completo" (suficiente cobertura), retornar
        if self._is_window_complete(cached, start_epoch, end_epoch, timeframe_minutes):
            return cached

        # Sino fetch fresh y persistir
        if self.mt5_reader and self.mt5_reader.is_connected():
            try:
                fresh = self.mt5_reader.get_historical_range(
                    symbol, timeframe_minutes, start_utc, end_utc
                )
            except Exception:
                fresh = None

            if fresh:
                self._persist(symbol, timeframe_minutes, fresh)
                # Re-leer cache con los nuevos datos
                cached = self._read_cache(
                    symbol, timeframe_minutes, start_epoch, end_epoch
                )

        return cached

    def _read_cache(
        self, symbol: str, timeframe: int, start_epoch: int, end_epoch: int
    ) -> list[dict]:
        try:
            return self.repository.fetch_mt5_cache_window(
                symbol, timeframe, start_epoch, end_epoch
            )
        except AttributeError:
            return []

    def _persist(self, symbol: str, timeframe: int, candles: list[dict]) -> int:
        if not hasattr(self.repository, "upsert_mt5_cache_candle"):
            return 0
        # v3.13.3: no mezclar hora del servidor y UTC real en la misma serie.
        server_tz = getattr(self.settings, "mt5_server_tz", "")
        try:
            can_write, note = ensure_cache_time_basis(
                self.repository, symbol, timeframe, server_tz
            )
        except Exception:
            can_write, note = False, "chequeo de base horaria fallo (soft-fail)"
        if not can_write:
            logger.warning("MT5 cache %s tf=%s sin escribir: %s", symbol, timeframe, note)
            return 0
        n = 0
        for c in candles:
            try:
                if self.repository.upsert_mt5_cache_candle(symbol, timeframe, c):
                    n += 1
            except Exception:
                continue
        if n:
            mark_cache_time_basis(self.repository, symbol, timeframe, server_tz)
        return n

    @staticmethod
    def _is_window_complete(
        candles: list[dict],
        start_epoch: int,
        end_epoch: int,
        timeframe_minutes: int,
    ) -> bool:
        """Heuristica: si la cantidad de barras cubre al menos 80% de la ventana
        esperada (asumiendo continuidad ideal), tratamos el cache como completo."""
        if not candles:
            return False
        bar_seconds = timeframe_minutes * 60
        expected_bars = max(1, (end_epoch - start_epoch) // bar_seconds)
        # Mercado FX cierra weekend → 5/7 dias activos
        expected_with_gaps = expected_bars * 5 / 7
        return len(candles) >= int(expected_with_gaps * 0.8)
