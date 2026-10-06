"""Loader historico del Backtest Replay Harness (v3.6.0, ESPEC §4).

Extiende mt5_historical: trae la profundidad MAXIMA disponible de D1 (y H1 si
hay) por simbolo desde MT5, la cachea en SQLite (mt5_historical_cache, la misma
tabla/patron de MT5HistoricalFetcher) y reporta el rango REAL por simbolo.
Nunca asume profundidad: se mide y se imprime.

Read-only contra MT5 (solo copy_rates via MT5Reader; jamas order_send) y
offline-first: si MT5 no esta conectado, sirve lo que haya en cache y lo dice.
Soft-fail por simbolo: uno que falla no tumba el resto.

CLI (S1 gate): python -m app.backtest.historical_loader
Requiere ENABLE_BACKTEST_HARNESS=true (opt-in explicito; el default false
garantiza que nada de esto corra por accidente).

Convencion de timeframe: el cache y la API interna usan MINUTOS por barra
(MT5Timeframe: D1=1440, H1=60). El package MetaTrader5 usa constantes con bits
de flag para >=H1 (TIMEFRAME_H1=16385, TIMEFRAME_D1=16408) — coinciden con los
minutos SOLO hasta M30. _api_timeframe() traduce en el borde; sin esa
traduccion, pedir D1 con 1440 devuelve silenciosamente None.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.brokers.mt5_reader import MT5Reader, MT5Timeframe
from app.brokers.mt5_time import (
    cache_time_basis,
    ensure_cache_time_basis,
    mark_cache_time_basis,
)
from app.config.settings import Settings


logger = logging.getLogger(__name__)

# Minutos -> constante TIMEFRAME_* del package MetaTrader5.
_MT5_API_TIMEFRAME_BY_MINUTES = {
    MT5Timeframe.M1: 1,
    MT5Timeframe.M5: 5,
    MT5Timeframe.M15: 15,
    MT5Timeframe.M30: 30,
    MT5Timeframe.H1: 0x4001,    # 16385
    MT5Timeframe.H4: 0x4004,    # 16388
    MT5Timeframe.D1: 0x4018,    # 16408
    MT5Timeframe.W1: 0x8001,    # 32769
}

_TIMEFRAME_MINUTES_BY_LABEL = {
    "M1": MT5Timeframe.M1,
    "M5": MT5Timeframe.M5,
    "M15": MT5Timeframe.M15,
    "M30": MT5Timeframe.M30,
    "H1": MT5Timeframe.H1,
    "H4": MT5Timeframe.H4,
    "D1": MT5Timeframe.D1,
    "W1": MT5Timeframe.W1,
}

# Probe descendente para "profundidad maxima": MT5 puede devolver None si el
# count pedido excede lo que el terminal banca (Max bars). Se intenta de mayor
# a menor y gana el primer resultado no vacio.
_PROBE_COUNTS = (200_000, 100_000, 50_000, 20_000, 10_000, 5_000, 2_000, 500)

# Umbral de sospecha de truncamiento (bars). D1: ~10 anos de un major son
# ~2.600 barras; H1: ~1 ano son ~6.200. Menos que esto en un simbolo que SI
# devolvio data sugiere que el terminal tiene "Max bars" corto (S1 gate:
# avisar al user que lo suba a Unlimited y re-descargue).
_TRUNCATION_SUSPECT_BARS = {
    MT5Timeframe.D1: 2_500,
    MT5Timeframe.H1: 6_000,
}


def _api_timeframe(timeframe_minutes: int) -> int | None:
    return _MT5_API_TIMEFRAME_BY_MINUTES.get(timeframe_minutes)


def timeframe_minutes_from_label(label: str) -> int | None:
    return _TIMEFRAME_MINUTES_BY_LABEL.get((label or "").strip().upper())


def _epoch_to_iso(epoch: int | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


@dataclass
class SymbolDepth:
    """Profundidad REAL disponible de un (symbol, timeframe) tras el load."""

    symbol: str
    timeframe_label: str
    timeframe_minutes: int
    bars: int = 0
    first_utc: str | None = None
    last_utc: str | None = None
    fetched_from_mt5: bool = False
    truncation_suspect: bool = False
    note: str = ""
    # v3.13.3: base horaria de la serie intradia ('utc' | 'server' | None=D1+/vacia)
    time_basis: str | None = None


@dataclass
class LoadSummary:
    depths: list[SymbolDepth] = field(default_factory=list)
    mt5_connected: bool = False


class BacktestHistoricalLoader:
    """Carga y mide la historia disponible por simbolo para el harness."""

    def __init__(
        self,
        settings: Settings,
        repository,
        mt5_reader: MT5Reader | None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.mt5_reader = mt5_reader

    def load_symbol(self, symbol: str, timeframe_minutes: int) -> SymbolDepth:
        """Trae la profundidad maxima de un simbolo, cachea y mide.

        Soft-fail total: ante cualquier error devuelve lo que haya en cache,
        con la nota explicando que paso.
        """
        symbol = (symbol or "").strip().upper()
        label = self._label_for(timeframe_minutes)
        depth = SymbolDepth(
            symbol=symbol,
            timeframe_label=label,
            timeframe_minutes=timeframe_minutes,
        )

        if self._reader_connected():
            candles = self._fetch_max_depth(symbol, timeframe_minutes)
            # v3.13.3: el reader ya entrega UTC real si MT5_SERVER_TZ esta
            # configurado; la serie del cache no puede mezclar bases horarias.
            server_tz = getattr(self.settings, "mt5_server_tz", "")
            can_write, basis_note = (
                ensure_cache_time_basis(
                    self.repository, symbol, timeframe_minutes, server_tz
                )
                if candles
                else (True, "")
            )
            if candles and can_write:
                written = self.repository.upsert_mt5_cache_candles(
                    symbol, timeframe_minutes, candles
                )
                depth.fetched_from_mt5 = written > 0
                if written > 0:
                    mark_cache_time_basis(
                        self.repository, symbol, timeframe_minutes, server_tz
                    )
                    depth.note = basis_note
                else:
                    depth.note = "MT5 devolvio data pero el cache no escribio (soft-fail)"
            elif candles:
                depth.note = basis_note
            else:
                depth.note = "MT5 conectado pero sin data para este simbolo/timeframe"
        else:
            depth.note = "MT5 no conectado: solo cache local"

        self._measure_from_cache(depth)
        return depth

    def load_all(self, include_h1: bool = True) -> LoadSummary:
        """Carga D1 (timeframe de settings) para todos los simbolos del
        harness, y H1 si hay (ESPEC: 'D1 y H1 si hay')."""
        summary = LoadSummary(mt5_connected=self._reader_connected())
        base_minutes = (
            timeframe_minutes_from_label(self.settings.backtest_timeframe)
            or MT5Timeframe.D1
        )
        timeframes = [base_minutes]
        if include_h1 and MT5Timeframe.H1 not in timeframes:
            timeframes.append(MT5Timeframe.H1)

        for raw_symbol in self.settings.backtest_symbols:
            for timeframe_minutes in timeframes:
                try:
                    depth = self.load_symbol(raw_symbol, timeframe_minutes)
                except Exception:
                    logger.exception(
                        "Loader soft-fail en %s %s",
                        raw_symbol,
                        self._label_for(timeframe_minutes),
                    )
                    depth = SymbolDepth(
                        symbol=(raw_symbol or "").strip().upper(),
                        timeframe_label=self._label_for(timeframe_minutes),
                        timeframe_minutes=timeframe_minutes,
                        note="error inesperado (soft-fail); ver logs",
                    )
                summary.depths.append(depth)
        return summary

    # -- internos ---------------------------------------------------------

    def _reader_connected(self) -> bool:
        try:
            return bool(self.mt5_reader and self.mt5_reader.is_connected())
        except Exception:
            return False

    def _fetch_max_depth(
        self, symbol: str, timeframe_minutes: int
    ) -> list[dict]:
        api_timeframe = _api_timeframe(timeframe_minutes)
        if api_timeframe is None:
            return []
        for count in _PROBE_COUNTS:
            try:
                candles = self.mt5_reader.get_rates(symbol, api_timeframe, count)
            except Exception:
                candles = None
            if candles:
                return candles
        return []

    def _measure_from_cache(self, depth: SymbolDepth) -> None:
        try:
            info = self.repository.fetch_mt5_cache_depth(
                depth.symbol, depth.timeframe_minutes
            )
        except Exception:
            depth.note = (depth.note + "; cache ilegible (soft-fail)").strip("; ")
            return
        depth.bars = int(info.get("bars") or 0)
        depth.first_utc = _epoch_to_iso(info.get("first_epoch"))
        depth.last_utc = _epoch_to_iso(info.get("last_epoch"))
        depth.time_basis = cache_time_basis(
            self.repository, depth.symbol, depth.timeframe_minutes
        )
        if depth.time_basis == "server":
            depth.note = (
                depth.note + "; epochs en HORA DEL SERVIDOR (legacy, ver "
                "scripts/mt5_cache_tz_migrate.py)"
            ).strip("; ")
        suspect_under = _TRUNCATION_SUSPECT_BARS.get(depth.timeframe_minutes)
        if suspect_under and 0 < depth.bars < suspect_under:
            depth.truncation_suspect = True
        if depth.bars == 0 and not depth.note:
            depth.note = "sin data en cache"

    @staticmethod
    def _label_for(timeframe_minutes: int) -> str:
        for label, minutes in _TIMEFRAME_MINUTES_BY_LABEL.items():
            if minutes == timeframe_minutes:
                return label
        return f"{timeframe_minutes}m"


def depth_report(summary: LoadSummary) -> str:
    """Reporte ASCII de profundidad real por simbolo (consola PS 5.1 es
    cp1252: nada de acentos ni unicode aca)."""
    lines: list[str] = []
    lines.append("== Profundidad historica REAL por simbolo (cache SQLite) ==")
    lines.append(
        "MT5: " + ("conectado" if summary.mt5_connected else "NO conectado (solo cache)")
    )
    lines.append("")
    header = f"{'symbol':<10} {'tf':<4} {'bars':>8}  {'desde':<17} {'hasta':<17} nota"
    lines.append(header)
    lines.append("-" * len(header))
    suspects: list[SymbolDepth] = []
    for d in sorted(summary.depths, key=lambda x: (x.timeframe_label, x.symbol)):
        note = d.note
        if d.bars == 0 and not note:
            note = "SIN DATA"
        if d.truncation_suspect:
            suspects.append(d)
            note = (note + " [posible truncamiento]").strip()
        lines.append(
            f"{d.symbol:<10} {d.timeframe_label:<4} {d.bars:>8}  "
            f"{d.first_utc or '-':<17} {d.last_utc or '-':<17} {note}"
        )
    if suspects:
        lines.append("")
        lines.append(
            "AVISO: profundidad sospechosamente corta en: "
            + ", ".join(f"{d.symbol} {d.timeframe_label}" for d in suspects)
        )
        lines.append(
            "Si parece truncada: en MT5 -> Herramientas -> Opciones -> Graficos,"
        )
        lines.append(
            "subir 'Max. barras en graficos' a Unlimited y volver a correr este loader."
        )
    return "\n".join(lines)


def main() -> int:
    """CLI del S1 gate. No toca el bot vivo: lee MT5 (read-only) y escribe
    SOLO en mt5_historical_cache."""
    import sys

    from app.config.settings import load_settings
    from app.database.db import init_db
    from app.database.repository import Repository

    logging.basicConfig(level=logging.WARNING)
    settings = load_settings()
    if not settings.enable_backtest_harness:
        print(
            "ENABLE_BACKTEST_HARNESS=false (default). Este loader es opt-in:\n"
            "  PowerShell:  $env:ENABLE_BACKTEST_HARNESS='true'; "
            "python -m app.backtest.historical_loader\n"
            "El flag NO afecta al bot vivo: solo habilita este tooling offline."
        )
        return 1

    init_db(settings.sqlite_path)
    repository = Repository(settings.sqlite_path)
    reader = MT5Reader(settings)
    connected = reader.connect()
    if not connected:
        print(
            "MT5 no conectado (package faltante, terminal cerrado o "
            "ENABLE_MT5_READER=false): se reporta solo el cache local.\n"
        )
    try:
        loader = BacktestHistoricalLoader(settings, repository, reader)
        summary = loader.load_all()
        print(depth_report(summary))
    finally:
        reader.disconnect()
    return 0 if any(d.bars > 0 for d in summary.depths) else 2


if __name__ == "__main__":
    raise SystemExit(main())
