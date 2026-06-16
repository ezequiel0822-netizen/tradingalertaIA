"""Tests del gate ENABLE_MEMECOIN_ENGINE (v3.7.0).

Apagado, el ciclo ni siquiera COLECTA memecoins (DEX/Gecko) -> el presupuesto
del ciclo queda para la bolsa (acciones/forex/oro). Encendido (default), corre
todo como siempre. Se usa el patron _StubJob: bindea solo _collect_snapshots a
un stub con los 4 collectors mockeados (sin construir el TradingAlertJob completo).
"""

from dataclasses import replace
from unittest.mock import MagicMock

from app.scheduler.jobs import TradingAlertJob
from tests.test_score import _settings


class _StubJob:
    def __init__(self, settings, dex, gecko, stocks, forex) -> None:
        self.settings = settings
        self.dexscreener = dex
        self.geckoterminal = gecko
        self.stocks = stocks
        self.forex = forex

    _collect_snapshots = TradingAlertJob._collect_snapshots


def _collectors():
    dex, gecko, stocks, forex = (MagicMock() for _ in range(4))
    for m in (dex, gecko, stocks, forex):
        m.collect.return_value = []
    return dex, gecko, stocks, forex


def test_memecoin_engine_off_skips_meme_collectors() -> None:
    settings = replace(_settings(), enable_memecoin_engine=False)
    dex, gecko, stocks, forex = _collectors()
    _StubJob(settings, dex, gecko, stocks, forex)._collect_snapshots()

    dex.collect.assert_not_called()
    gecko.collect.assert_not_called()
    stocks.collect.assert_called_once()   # la bolsa sigue corriendo
    forex.collect.assert_called_once()


def test_memecoin_engine_on_runs_all_collectors() -> None:
    settings = replace(_settings(), enable_memecoin_engine=True)
    dex, gecko, stocks, forex = _collectors()
    _StubJob(settings, dex, gecko, stocks, forex)._collect_snapshots()

    dex.collect.assert_called_once()
    gecko.collect.assert_called_once()
    stocks.collect.assert_called_once()
    forex.collect.assert_called_once()


def test_default_is_on_backward_compat() -> None:
    # El default es True para no cambiarle el comportamiento a nadie.
    assert _settings().enable_memecoin_engine is True
