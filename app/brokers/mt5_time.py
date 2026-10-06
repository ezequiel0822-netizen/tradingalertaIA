"""v3.13.3 — hora del servidor MT5 -> UTC real (DST-aware, stdlib puro).

PROBLEMA (medido 2026-10-06 contra MetaQuotes-Demo, ver CHANGELOG v3.13.3): el
package MetaTrader5 devuelve los timestamps (velas de copy_rates_*, ticks, deals)
como epoch en HORA DEL SERVIDOR, no en UTC real. MetaQuotes-Demo usa EET con la
regla de horario de verano EUROPEA: UTC+2 en invierno, UTC+3 desde el ultimo
domingo de marzo hasta el ultimo domingo de octubre (cambio a las 01:00 UTC).
Una vela H1 que el servidor etiqueta 16:00 empezo a las 13:00 UTC en verano.

CONVENCION (MT5_SERVER_TZ):
- ""/"UTC"  -> sin conversion (default; comportamiento anterior a v3.13.3).
- "EET"     -> UTC+2 / UTC+3 con regla UE (MetaQuotes-Demo; medido).
- "NY+7"    -> UTC+2 / UTC+3 con regla de EE.UU. (brokers "NY close": 00:00 del
               servidor = 17:00 Nueva York todo el anio, p.ej. ICMarkets).
- "UTC+N" / "UTC-N" -> offset fijo en horas, sin DST.

QUE SE CONVIERTE: solo timeframes INTRADIA (< D1) y los ticks (son instantes).
D1/W1/MN1 NO se convierten: su epoch es las 00:00 de la FECHA de trading del
servidor (cierre NY), una etiqueta de fecha, no un instante. Convertirla la
correria a las 21:00/22:00 del dia ANTERIOR y romperia todo lo que usa la fecha
o el weekday de la barra D1 (gold_friday_hold, estudios de estacionalidad,
carry, COT, regime gate). Esa es la misma convencion con la que se evaluaron
esas familias.

Ambiguedad en el cambio de hora: la hora "repetida" (fin del verano) se resuelve
como horario de verano y la hora "salteada" (inicio) con el offset estandar.
Para FX/oro no importa: los dos cambios caen en domingo con el mercado cerrado.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

# Timeframes del package MetaTrader5 (constantes con bits de flag >= H1). Las
# APIs internas usan tambien MINUTOS (MT5Timeframe: H1=60, D1=1440). Intradia =
# cualquiera de las dos formas por debajo de D1.
_API_H1 = 0x4001
_API_H12 = 0x400C
_D1_MINUTES = 1440

TIME_BASIS_UTC = "utc"        # epochs = instantes en UTC real
TIME_BASIS_SERVER = "server"  # epochs = hora del servidor MT5 (legacy)

_FIXED_RE = re.compile(r"^UTC([+-])(\d{1,2})$")
_HOUR = 3600


def normalize_server_tz(value: Any) -> str:
    """Normaliza MT5_SERVER_TZ. Devuelve "" (sin conversion) si esta vacio,
    es "UTC"/"UTC+0" o no se reconoce (soft-fail: nunca inventa un offset)."""
    raw = str(value or "").strip().upper().replace(" ", "")
    if raw in ("", "UTC", "UTC+0", "UTC-0", "GMT"):
        return ""
    if raw in ("EET", "NY+7"):
        return raw
    match = _FIXED_RE.match(raw)
    if match and 0 < int(match.group(2)) <= 14:
        return f"UTC{match.group(1)}{int(match.group(2))}"
    return ""


def is_known_server_tz(value: Any) -> bool:
    """True si el valor es vacio/UTC o una zona soportada (para avisar typos)."""
    raw = str(value or "").strip().upper().replace(" ", "")
    return raw in ("", "UTC", "UTC+0", "UTC-0", "GMT") or bool(normalize_server_tz(raw))


def is_intraday_timeframe(timeframe: int) -> bool:
    """True para M1..H12 en minutos (1..720) o en constantes de la API MT5."""
    try:
        tf = int(timeframe)
    except (TypeError, ValueError):
        return False
    return 0 < tf < _D1_MINUTES or _API_H1 <= tf <= _API_H12


# -- reglas de DST ---------------------------------------------------------


def _last_sunday(year: int, month: int) -> date:
    last = (date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() + 1) % 7)


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    first_sunday = first + timedelta(days=(6 - first.weekday()) % 7)
    return first_sunday + timedelta(weeks=n - 1)


def _utc_ts(day: date, hour: int) -> float:
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc).timestamp()


def _eu_dst(utc_epoch: float) -> bool:
    """UE: verano desde el ultimo domingo de marzo 01:00 UTC hasta el ultimo
    domingo de octubre 01:00 UTC (regla vigente desde 1996)."""
    year = datetime.fromtimestamp(utc_epoch, tz=timezone.utc).year
    return _utc_ts(_last_sunday(year, 3), 1) <= utc_epoch < _utc_ts(_last_sunday(year, 10), 1)


def _us_dst(utc_epoch: float) -> bool:
    """EE.UU. (hora de Nueva York): 02:00 local. Desde 2007: 2do domingo de marzo
    (07:00 UTC) -> 1er domingo de noviembre (06:00 UTC). Antes: 1er domingo de
    abril -> ultimo domingo de octubre."""
    year = datetime.fromtimestamp(utc_epoch, tz=timezone.utc).year
    if year >= 2007:
        start, end = _nth_sunday(year, 3, 2), _nth_sunday(year, 11, 1)
    else:
        start, end = _nth_sunday(year, 4, 1), _last_sunday(year, 10)
    return _utc_ts(start, 7) <= utc_epoch < _utc_ts(end, 6)


def utc_offset_seconds(server_tz: str, utc_epoch: float) -> int:
    """Offset (s) de la hora del servidor respecto de UTC en ese instante UTC."""
    tz = normalize_server_tz(server_tz)
    if not tz:
        return 0
    if tz == "EET":
        return (3 if _eu_dst(utc_epoch) else 2) * _HOUR
    if tz == "NY+7":
        return (3 if _us_dst(utc_epoch) else 2) * _HOUR
    match = _FIXED_RE.match(tz)
    sign = 1 if match.group(1) == "+" else -1  # type: ignore[union-attr]
    return sign * int(match.group(2)) * _HOUR  # type: ignore[union-attr]


def server_epoch_to_utc(server_epoch: float, server_tz: str) -> int:
    """Epoch en hora del servidor -> epoch UTC real."""
    tz = normalize_server_tz(server_tz)
    epoch = int(server_epoch)
    if not tz:
        return epoch
    if tz not in ("EET", "NY+7"):
        return epoch - utc_offset_seconds(tz, epoch)
    # Probar el offset de verano primero: resuelve la hora repetida como verano.
    for offset in (3 * _HOUR, 2 * _HOUR):
        if utc_offset_seconds(tz, epoch - offset) == offset:
            return epoch - offset
    return epoch - 2 * _HOUR  # hora salteada (no existe en el servidor)


def utc_to_server_epoch(utc_epoch: float, server_tz: str) -> int:
    """Epoch UTC real -> epoch en hora del servidor (para pedir rangos a MT5)."""
    epoch = int(utc_epoch)
    return epoch + utc_offset_seconds(server_tz, epoch)


def convert_candles_to_utc(
    candles: list[dict], timeframe: int, server_tz: str
) -> list[dict]:
    """Convierte in-place la clave 'time' de velas INTRADIA a UTC real.
    D1+ o sin zona configurada: devuelve las velas sin tocar."""
    tz = normalize_server_tz(server_tz)
    if not tz or not is_intraday_timeframe(timeframe):
        return candles
    for candle in candles:
        if candle.get("time") is not None:
            candle["time"] = server_epoch_to_utc(candle["time"], tz)
    return candles


# -- base horaria del cache (mt5_historical_cache + mt5_cache_meta) ----------


def cache_time_basis(repository: Any, symbol: str, timeframe: int) -> str | None:
    """Base horaria de una serie INTRADIA del cache: 'utc', 'server' o None
    (serie vacia). Sin marca pero con filas = legacy = 'server'. D1+ -> None
    (etiqueta de fecha, no aplica)."""
    if not is_intraday_timeframe(timeframe):
        return None
    try:
        meta = repository.get_mt5_cache_time_basis(symbol, timeframe)
    except Exception:
        meta = None
    if meta and meta.get("time_basis"):
        return str(meta["time_basis"])
    try:
        bars = int((repository.fetch_mt5_cache_depth(symbol, timeframe) or {}).get("bars") or 0)
    except Exception:
        bars = 0
    return TIME_BASIS_SERVER if bars > 0 else None


def migrate_series_to_utc(
    repository: Any, symbol: str, timeframe: int, server_tz: str, *, apply: bool = True
) -> dict:
    """Pasa una serie intradia legacy (hora del servidor) a UTC real, en el
    lugar y en una transaccion, y la marca 'utc'. Idempotente: si ya esta en
    UTC no hace nada. apply=False = dry-run."""
    tz = normalize_server_tz(server_tz)
    if not tz:
        return {"applied": False, "reason": "MT5_SERVER_TZ vacio: nada que convertir"}
    if not is_intraday_timeframe(timeframe):
        return {"applied": False, "reason": "D1+ no se convierte (etiqueta de fecha)"}
    basis = cache_time_basis(repository, symbol, timeframe)
    if basis is None:
        return {"applied": False, "reason": "serie vacia"}
    if basis == TIME_BASIS_UTC:
        return {"applied": False, "reason": "ya esta en UTC"}
    result = repository.rewrite_mt5_cache_times(
        symbol,
        timeframe,
        lambda epoch: server_epoch_to_utc(epoch, tz),
        time_basis=TIME_BASIS_UTC,
        server_tz=tz,
        note="migrado desde hora del servidor (v3.13.3)",
        apply=apply,
    )
    if result.get("collisions"):
        result["reason"] = "colisiones al convertir: NO se toco la serie"
    return result


def ensure_cache_time_basis(
    repository: Any, symbol: str, timeframe: int, server_tz: str
) -> tuple[bool, str]:
    """Antes de ESCRIBIR velas intradia de MT5 en el cache: garantiza que la
    serie no mezcle bases horarias. Devuelve (se_puede_escribir, nota).

    - serie vacia o en la misma base que la escritura -> OK.
    - legacy 'server' y ahora se escribe en UTC -> migra en el lugar y OK.
    - serie en 'utc' y MT5_SERVER_TZ vacio -> NO escribir (mezclaria bases).
    Despues de escribir, el caller marca la base con mark_cache_time_basis."""
    if not is_intraday_timeframe(timeframe):
        return True, ""
    tz = normalize_server_tz(server_tz)
    target = TIME_BASIS_UTC if tz else TIME_BASIS_SERVER
    current = cache_time_basis(repository, symbol, timeframe)
    if current is None or current == target:
        return True, ""
    if current == TIME_BASIS_SERVER and target == TIME_BASIS_UTC:
        result = migrate_series_to_utc(repository, symbol, timeframe, tz)
        if result.get("applied"):
            return True, f"cache legacy migrado a UTC ({result.get('rows', 0)} barras)"
        return False, f"no se pudo migrar el cache a UTC: {result.get('reason', '?')}"
    return False, (
        "el cache de esta serie esta en UTC real y MT5_SERVER_TZ esta vacio: "
        "no se escribe para no mezclar bases (configurar MT5_SERVER_TZ)"
    )


def mark_cache_time_basis(
    repository: Any, symbol: str, timeframe: int, server_tz: str
) -> None:
    """Marca la base de una serie intradia recien escrita (soft-fail)."""
    if not is_intraday_timeframe(timeframe):
        return
    tz = normalize_server_tz(server_tz)
    try:
        repository.set_mt5_cache_time_basis(
            symbol,
            timeframe,
            TIME_BASIS_UTC if tz else TIME_BASIS_SERVER,
            tz or None,
        )
    except Exception:
        pass


# -- diagnostico: que regla de DST usa el servidor ---------------------------


def weekly_close_rule_votes(
    h1_server_epochs: list[int], candidates: tuple[str, ...] = ("EET", "NY+7")
) -> dict:
    """Vota la zona del servidor con la ULTIMA vela H1 de cada viernes.

    El FX cierra el viernes 17:00 de Nueva York (21:00 UTC con horario de verano
    de EE.UU., 22:00 UTC sin el). La ultima vela H1 empieza 1 h antes, y su hora
    en el servidor depende de la regla: con "NY+7" siempre es 23:00; con "EET"
    (regla UE) es 22:00 las semanas en que EE.UU. ya cambio de hora y Europa no.
    Se ignoran cierres tempranos (24 y 31 de diciembre, ultima vela < 22:00).
    Devuelve {"n": semanas, "<zona>": coincidencias, "mismatch": {zona: [...]}}."""
    epochs = sorted(int(e) for e in h1_server_epochs)
    votes: dict = {"n": 0, "mismatch": {tz: [] for tz in candidates}}
    for tz in candidates:
        votes[tz] = 0
    for current, nxt in zip(epochs, epochs[1:]):
        if nxt - current <= 36 * _HOUR:
            continue
        last_bar = datetime.fromtimestamp(current, tz=timezone.utc)
        if last_bar.weekday() != 4 or last_bar.hour < 22:
            continue
        if (last_bar.month, last_bar.day) in ((12, 24), (12, 31)):
            continue
        day = last_bar.date()
        close_utc = _utc_ts(day, 21) if _us_dst(_utc_ts(day, 21)) else _utc_ts(day, 22)
        votes["n"] += 1
        for tz in candidates:
            expected = datetime.fromtimestamp(
                close_utc + utc_offset_seconds(tz, close_utc) - _HOUR, tz=timezone.utc
            )
            if expected.hour == last_bar.hour:
                votes[tz] += 1
            else:
                votes["mismatch"][tz].append(last_bar.strftime("%Y-%m-%d %H:%M"))
    return votes
