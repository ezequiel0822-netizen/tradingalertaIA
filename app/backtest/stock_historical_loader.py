"""Loader historico de ACCIONES para el backtest (ESPEC_BACKTEST_STOCKS_v1 §4, S1).

Baja D1 de Yahoo (range=max, interval=1d) por simbolo, lo AJUSTA por splits y
dividendos (adjusted close), y lo cachea en mt5_historical_cache (timeframe=1440;
los tickers de acciones no chocan con los pares de forex). Reporta el rango REAL.

Defensa #1 de honestidad (ESPEC §3): se usa SIEMPRE el adjusted close. Yahoo
devuelve OHLC CRUDO + adjclose; aca se back-ajusta el OHLC por el factor
(adjclose/close) de cada barra, asi un split 4:1 NO fabrica un gap_sl espurio.

OFFLINE / opt-in: nada de esto corre en el ciclo vivo. Soft-fail por simbolo.
ADVERTENCIA: el universo actual son SOBREVIVIENTES (survivorship bias) — el
backtest de acciones solo sirve para DESCARTAR, nunca para confirmar (ESPEC §2).

CLI: python -m app.backtest.stock_historical_loader (requiere ENABLE_BACKTEST_HARNESS=true)
"""

import logging
import time

import requests

from app.backtest.historical_loader import LoadSummary, SymbolDepth, _epoch_to_iso
from app.config.settings import Settings

logger = logging.getLogger(__name__)

_D1_MINUTES = 1440
_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# D1 de acciones: ~252 barras/año. Menos que esto en un nombre con historia larga
# sugiere data corta (no es truncamiento del broker como en forex, pero se marca).
_TRUNCATION_SUSPECT_BARS = 300


# Backoff (segundos) ante 429 de Yahoo. Yahoo throttlea rafagas de requests.
_RETRY_BACKOFF = (3, 6, 12)


def fetch_yahoo_daily(symbol: str, session, timeout: int) -> list[dict]:
    """Trae D1 ajustado de Yahoo. Cada vela: time(epoch), open/high/low/close
    AJUSTADOS, volume. Devuelve [] ante cualquier problema (soft-fail). Reintenta
    con backoff ante 429 (Too Many Requests)."""
    url = _YAHOO_CHART.format(symbol=symbol)
    # OJO: range=max DEGRADA la granularidad a mensual/semanal. Para D1 REAL hay
    # que pasar period1/period2 explicitos (epoch). period1=0 -> desde el IPO.
    params = {"period1": 0, "period2": int(time.time()), "interval": "1d",
              "events": "div,splits"}
    payload = None
    for attempt in range(len(_RETRY_BACKOFF) + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            logger.warning("Yahoo daily failed for %s: %s", symbol, exc)
            return []
        if getattr(resp, "status_code", None) == 429 and attempt < len(_RETRY_BACKOFF):
            time.sleep(_RETRY_BACKOFF[attempt])  # throttle de Yahoo -> backoff
            continue
        try:
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Yahoo daily failed for %s: %s", symbol, exc)
            return []
        break
    if payload is None:
        return []

    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return []
    timestamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0]) or {}
    adj_block = (((result.get("indicators") or {}).get("adjclose") or [{}])[0]) or {}
    adjclose = adj_block.get("adjclose") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    candles: list[dict] = []
    for i, ts in enumerate(timestamps):
        o, h, l, c = _at(opens, i), _at(highs, i), _at(lows, i), _at(closes, i)
        a = _at(adjclose, i)
        if None in (o, h, l, c, a) or c == 0:
            continue
        factor = a / c  # back-ajuste por splits + dividendos
        candles.append({
            "time": int(ts),
            "open": o * factor,
            "high": h * factor,
            "low": l * factor,
            "close": a,
            "volume": _at(volumes, i) or 0,
        })
    return candles


class StockHistoricalLoader:
    """Carga y mide la historia D1 ajustada de acciones desde Yahoo."""

    def __init__(self, settings: Settings, repository, session=None,
                 request_delay_seconds: float = 2.0) -> None:
        self.settings = settings
        self.repository = repository
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "TradingAlertAI/3.8 backtest")
        # Pacing entre simbolos para no comerse un 429 de Yahoo (rafagas throttlean).
        self.request_delay_seconds = request_delay_seconds

    def load_symbol(self, symbol: str) -> SymbolDepth:
        symbol = (symbol or "").strip().upper()
        depth = SymbolDepth(symbol=symbol, timeframe_label="D1",
                            timeframe_minutes=_D1_MINUTES)
        candles = fetch_yahoo_daily(symbol, self.session,
                                    self.settings.request_timeout_seconds)
        if candles:
            written = self.repository.upsert_mt5_cache_candles(
                symbol, _D1_MINUTES, candles)
            depth.fetched_from_mt5 = written > 0
            if written == 0:
                depth.note = "Yahoo devolvio data pero el cache no escribio (soft-fail)"
        else:
            depth.note = "Yahoo sin data para este simbolo"
        self._measure(depth)
        return depth

    def load_all(self) -> LoadSummary:
        summary = LoadSummary(mt5_connected=True)  # 'conectado' = Yahoo alcanzable
        symbols = getattr(self.settings, "stock_backtest_symbols", None) \
            or self.settings.stock_symbols
        for i, raw in enumerate(symbols):
            if i > 0 and self.request_delay_seconds > 0:
                time.sleep(self.request_delay_seconds)  # pacing anti-429
            try:
                summary.depths.append(self.load_symbol(raw))
            except Exception:
                logger.exception("Stock loader soft-fail en %s", raw)
                summary.depths.append(SymbolDepth(
                    symbol=(raw or "").strip().upper(), timeframe_label="D1",
                    timeframe_minutes=_D1_MINUTES,
                    note="error inesperado (soft-fail); ver logs"))
        return summary

    def _measure(self, depth: SymbolDepth) -> None:
        try:
            info = self.repository.fetch_mt5_cache_depth(depth.symbol, _D1_MINUTES)
        except Exception:
            depth.note = (depth.note + "; cache ilegible").strip("; ")
            return
        depth.bars = int(info.get("bars") or 0)
        depth.first_utc = _epoch_to_iso(info.get("first_epoch"))
        depth.last_utc = _epoch_to_iso(info.get("last_epoch"))
        if 0 < depth.bars < _TRUNCATION_SUSPECT_BARS:
            depth.truncation_suspect = True
        if depth.bars == 0 and not depth.note:
            depth.note = "sin data en cache"


def _at(seq, i):
    return seq[i] if i < len(seq) else None


def main() -> int:
    from app.backtest.historical_loader import depth_report
    from app.config.settings import load_settings
    from app.database.db import init_db
    from app.database.repository import Repository

    logging.basicConfig(level=logging.WARNING)
    settings = load_settings()
    if not settings.enable_backtest_harness:
        print("ENABLE_BACKTEST_HARNESS=false (default). Opt-in:\n"
              "  $env:ENABLE_BACKTEST_HARNESS='true'; "
              "python -m app.backtest.stock_historical_loader")
        return 1
    init_db(settings.sqlite_path)
    repository = Repository(settings.sqlite_path)
    loader = StockHistoricalLoader(settings, repository)
    summary = loader.load_all()
    print(depth_report(summary))
    print("\nADVERTENCIA: universo de SOBREVIVIENTES (survivorship bias). El backtest "
          "de acciones solo sirve para DESCARTAR, nunca para confirmar (ESPEC §2).")
    return 0 if any(d.bars > 0 for d in summary.depths) else 2


if __name__ == "__main__":
    raise SystemExit(main())
