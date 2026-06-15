"""Clasificador de regimen de mercado (ESPEC_BACKTEST_REPLAY_v1.md §8).

Funcion PURA sobre un array de velas (cada una dict con high/low/close): sin
estado oculto, sin red, sin aleatoriedad. Misma entrada -> misma salida. Hoy
solo la usa el backtest harness, pero queda en app/intelligence/ a proposito:
es importable por el bot vivo a futuro sin arrastrar nada del paquete backtest.

Doble uso (ESPEC §8):
  1. Gate de `trend_following_d1` (S5): solo opera alineada al regimen.
  2. Dimension de slicing para TODAS las estrategias en el reporte: ahi se
     responde si el +R de forex_session_breakout era regimen o era edge.

regime_trend (up|down|flat|unknown):
  - up   si close(N) > SMA200(N)  y  SMA200(N) > SMA200(N-20)
  - down espejo (close(N) < SMA200(N)  y  SMA200(N) < SMA200(N-20))
  - flat cualquier otro caso con datos suficientes
  - unknown si no hay barras para computar SMA200(N) y SMA200(N-20)
    (la honestidad de B11: no se inventa 'flat' cuando no se puede medir)

regime_vol (low|mid|high|unknown):
  - tercil del ATR14(N) contra la distribucion de los 252 ATR14 previos
  - unknown si no hay 252 ATR14 previos computables

Todo con datos <= N (B1): la funcion solo ve lo que el caller le pasa y trata
el ULTIMO elemento del array como la barra N. El harness siempre corta en N+1
antes de llamar (canario anti-look-ahead de §14).
"""

from dataclasses import dataclass

SMA_TREND_PERIOD = 200
TREND_SLOPE_LOOKBACK = 20
ATR_PERIOD = 14
VOL_LOOKBACK = 252

UNKNOWN = "unknown"


@dataclass(frozen=True)
class RegimeTags:
    """Etiquetas de regimen en la barra N. Frozen: una vez clasificado no muta."""

    regime_trend: str  # up | down | flat | unknown
    regime_vol: str    # low | mid | high | unknown


def classify(candles: list[dict]) -> RegimeTags:
    """Clasifica el regimen en la ultima barra del array (la barra N).

    `candles` debe estar ordenado ascendente por tiempo y contener solo barras
    <= N (responsabilidad del caller; la funcion no mira mas alla del array).
    """
    closes = [_f(c.get("close")) for c in candles]
    highs = [_f(c.get("high"), fallback=closes[i]) for i, c in enumerate(candles)]
    lows = [_f(c.get("low"), fallback=closes[i]) for i, c in enumerate(candles)]
    return RegimeTags(
        regime_trend=_trend(closes),
        regime_vol=_vol(highs, lows, closes),
    )


def _trend(closes: list[float]) -> str:
    need = SMA_TREND_PERIOD + TREND_SLOPE_LOOKBACK
    if len(closes) < need:
        return UNKNOWN
    sma_now = _mean(closes[-SMA_TREND_PERIOD:])
    # SMA200 terminada 20 barras atras = media de las 200 closes que terminan en N-20.
    sma_prev = _mean(closes[-(SMA_TREND_PERIOD + TREND_SLOPE_LOOKBACK):-TREND_SLOPE_LOOKBACK])
    close_now = closes[-1]
    if close_now > sma_now and sma_now > sma_prev:
        return "up"
    if close_now < sma_now and sma_now < sma_prev:
        return "down"
    return "flat"


def _vol(highs: list[float], lows: list[float], closes: list[float]) -> str:
    atr = _atr_series(highs, lows, closes, ATR_PERIOD)
    n = len(closes) - 1
    if n < 0:
        return UNKNOWN
    atr_now = atr[n]
    if atr_now is None or n - VOL_LOOKBACK < 0:
        return UNKNOWN
    prev = atr[n - VOL_LOOKBACK:n]
    if len(prev) < VOL_LOOKBACK or any(v is None for v in prev):
        return UNKNOWN
    below = sum(1 for v in prev if v < atr_now)
    pct = below / len(prev)
    if pct < 1 / 3:
        return "low"
    if pct < 2 / 3:
        return "mid"
    return "high"


def _atr_series(
    highs: list[float], lows: list[float], closes: list[float], period: int
) -> list[float | None]:
    """ATR simple (media movil de True Range de `period` barras) alineado al
    indice de la vela. atr[i] = None hasta que hay `period` true ranges; el
    primer TR vive en i=1 (necesita el close previo)."""
    n = len(closes)
    trs: list[float | None] = [None] * n
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs[i] = tr
    atr: list[float | None] = [None] * n
    for i in range(period, n):
        window = trs[i - period + 1:i + 1]
        if any(v is None for v in window):
            continue
        atr[i] = sum(window) / period  # type: ignore[arg-type]
    return atr


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _f(value, fallback: float = 0.0) -> float:
    try:
        if value is None:
            return float(fallback)
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)
