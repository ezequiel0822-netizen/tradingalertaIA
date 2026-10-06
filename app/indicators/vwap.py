"""v3.12.0 — VWAP (Volume-Weighted Average Price) como indicador puro.

Calcula VWAP intradia (reset diario) y VWAP anclado (semana / mes) sobre la
convencion de velas del proyecto: list[dict] con open/high/low/close/volume y
el tiempo en epoch seconds UTC bajo la clave 'timestamp' (feed vivo Yahoo) o
'time' (cache MT5 / backtest harness) — la misma dualidad que resolvio v3.10.0
para forex_session_breakout.

Reglas de diseno (INAMOVIBLES):
- BAR-TIME como reloj (leccion del bug A1 / v3.10.0): el "hoy" y los anchors se
  derivan del timestamp de la ULTIMA vela de la lista, JAMAS de datetime.now().
  El mismo codigo es replayable en el harness sin look-ahead: la ventana la
  controla el caller y solo se usan velas <= la ultima.
- SOFT-FAIL honesto sin volumen: Yahoo devuelve volumen 0 para forex -> el
  VWAP es None y position="unknown". NUNCA se inventa un VWAP sin volumen
  real. (Para forex, el VWAP anclado sale del cache D1 de MT5, que persiste
  tick_volume como 'volume' — mismo input que usa el regime gate.)
- Precio tipico = (high + low + close) / 3 (hlc3), la convencion default de
  TradingView para su VWAP: los valores deben cuadrar contra el chart.
- Velas con volumen <= 0 pesan 0 (no aportan ni distorsionan).

Limites honestos del anchor "session" (= dia UTC del bar-time):
- Sobre velas D1 la "sesion" es 1 sola barra -> el VWAP de sesion degenera al
  precio tipico del dia. Sobre D1 lo util son los anchors week/month.
- Las velas de MT5 traen bar-time en hora del SERVIDOR (tipicamente EET,
  UTC+2/3): agrupar por "dia UTC" sobre intradia MT5 corre el corte ~2-3h.
  Para Yahoo (UTC real) el corte es exacto. Aproximacion aceptada y documentada;
  si algun dia el VWAP de sesion se calcula sobre intradia MT5, revisar esto.
  (v3.13.3: con MT5_SERVER_TZ configurado el intradia de MT5 llega en UTC real;
  el D1 sigue siendo la fecha de trading del servidor, que es lo que usan los
  anchors week/month.)

Sin numpy/pandas: stdlib puro, mismo estilo que technical_patterns.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# Anchors soportados. "session" = dia UTC de la ultima vela (reset diario).
ANCHOR_SESSION = "session"
ANCHOR_WEEK = "week"    # lunes 00:00 UTC de la semana de la ultima vela
ANCHOR_MONTH = "month"  # dia 1 00:00 UTC del mes de la ultima vela

VALID_ANCHORS = (ANCHOR_SESSION, ANCHOR_WEEK, ANCHOR_MONTH)


@dataclass
class VwapReading:
    """Lectura de VWAP para un anchor. vwap=None => sin volumen/data (soft-fail)."""

    anchor: str
    vwap: float | None
    distance_pct: float | None  # (close - vwap) / vwap * 100; >0 = precio arriba
    position: str               # "above" | "below" | "at" | "unknown"
    bars_used: int = 0


def bar_timestamp(candle: dict[str, Any]) -> float | None:
    """Epoch seconds UTC de la vela; soporta 'timestamp' (Yahoo) y 'time' (MT5)."""
    for key in ("timestamp", "time"):
        value = candle.get(key)
        if value is None:
            continue
        try:
            ts = float(value)
        except (TypeError, ValueError):
            continue
        if ts > 0:
            return ts
    return None


def _typical_price(candle: dict[str, Any]) -> float | None:
    close = candle.get("close")
    if close is None:
        return None
    try:
        c = float(close)
        h = float(candle.get("high") or c)
        low = float(candle.get("low") or c)
    except (TypeError, ValueError):
        return None
    if c <= 0:
        return None
    return (h + low + c) / 3


def _volume(candle: dict[str, Any]) -> float:
    try:
        volume = float(candle.get("volume") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return volume if volume > 0 else 0.0


def anchor_start_epoch(last_ts: float, anchor: str) -> float:
    """Epoch del inicio del periodo del anchor que contiene a last_ts (UTC)."""
    if anchor not in VALID_ANCHORS:
        raise ValueError(f"anchor invalido: {anchor!r} (validos: {VALID_ANCHORS})")
    dt = datetime.fromtimestamp(float(last_ts), tz=timezone.utc)
    day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if anchor == ANCHOR_SESSION:
        return day.timestamp()
    if anchor == ANCHOR_WEEK:
        return (day - timedelta(days=day.weekday())).timestamp()
    return day.replace(day=1).timestamp()


def anchored_vwap(
    candles: list[dict[str, Any]],
    anchor: str = ANCHOR_SESSION,
) -> VwapReading:
    """VWAP acumulado desde el inicio del periodo del anchor hasta la ultima vela.

    El "ahora" es el bar-time de la ULTIMA vela de la lista con timestamp valido
    (convencion v3.10.0) — nunca el reloj de pared. Velas fuera de
    [anchor_start, ahora] se ignoran; velas sin timestamp o sin close tambien.
    Sin volumen total > 0 el VWAP es None (caso Yahoo-forex): soft-fail honesto.
    """
    empty = VwapReading(anchor=anchor, vwap=None, distance_pct=None, position="unknown")
    if anchor not in VALID_ANCHORS:
        raise ValueError(f"anchor invalido: {anchor!r} (validos: {VALID_ANCHORS})")
    if not candles:
        return empty

    last_ts: float | None = None
    for candle in reversed(candles):
        last_ts = bar_timestamp(candle)
        if last_ts is not None:
            break
    if last_ts is None:
        return empty
    start_ts = anchor_start_epoch(last_ts, anchor)

    pv_sum = 0.0
    volume_sum = 0.0
    bars_used = 0
    last_close: float | None = None
    for candle in candles:
        ts = bar_timestamp(candle)
        if ts is None or ts < start_ts or ts > last_ts:
            continue
        typical = _typical_price(candle)
        if typical is None:
            continue
        bars_used += 1
        last_close = float(candle["close"])
        volume = _volume(candle)
        if volume > 0:
            pv_sum += typical * volume
            volume_sum += volume

    if volume_sum <= 0 or last_close is None:
        # Sin volumen real (Yahoo forex = 0) o sin closes: no hay VWAP.
        return VwapReading(
            anchor=anchor, vwap=None, distance_pct=None,
            position="unknown", bars_used=bars_used,
        )

    vwap = pv_sum / volume_sum
    distance_pct = ((last_close - vwap) / vwap) * 100 if vwap else None
    if distance_pct is None:
        position = "unknown"
    elif distance_pct > 0:
        position = "above"
    elif distance_pct < 0:
        position = "below"
    else:
        position = "at"
    return VwapReading(
        anchor=anchor,
        vwap=vwap,
        distance_pct=distance_pct,
        position=position,
        bars_used=bars_used,
    )


def session_vwap(candles: list[dict[str, Any]]) -> VwapReading:
    """VWAP intradia con reset diario (dia UTC de la ultima vela)."""
    return anchored_vwap(candles, ANCHOR_SESSION)


def weekly_vwap(candles: list[dict[str, Any]]) -> VwapReading:
    """VWAP anclado al lunes 00:00 UTC de la semana de la ultima vela."""
    return anchored_vwap(candles, ANCHOR_WEEK)


def monthly_vwap(candles: list[dict[str, Any]]) -> VwapReading:
    """VWAP anclado al dia 1 del mes de la ultima vela."""
    return anchored_vwap(candles, ANCHOR_MONTH)


def vwap_features(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Features planas de VWAP para el analyzer / ML dataset / display.

    Todas None-safe: sin volumen (Yahoo forex) todo queda None/"unknown" y el
    caller decide que mostrar. Los nombres son estables: son columnas del
    dataset ML a futuro.
    """
    session = session_vwap(candles)
    week = weekly_vwap(candles)
    return {
        "vwap_session": session.vwap,
        "vwap_session_dist_pct": session.distance_pct,
        "vwap_session_position": session.position,
        "vwap_week": week.vwap,
        "vwap_week_dist_pct": week.distance_pct,
        "vwap_week_position": week.position,
    }
