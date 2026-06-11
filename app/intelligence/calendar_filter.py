"""Calendar filter: bloquea trades en ventanas alrededor de eventos high-impact.

`is_safe_window(symbol, now_utc, repository, buffer_min)` consulta los eventos
guardados y retorna (True, "ok") o (False, "razon") si hay un evento high-impact
para la moneda del symbol dentro del buffer.

Read-only: solo lee economic_events.
"""

from datetime import datetime, timedelta, timezone


# Mapeo simbolo → monedas afectadas (eventos de cualquiera bloquean)
_SYMBOL_CURRENCIES = {
    "EURUSD=X": {"USD", "EUR"},
    "GBPUSD=X": {"USD", "GBP"},
    "USDJPY=X": {"USD", "JPY"},
    "USDCHF=X": {"USD", "CHF"},
    "AUDUSD=X": {"USD", "AUD"},
    "USDCAD=X": {"USD", "CAD"},
    "NZDUSD=X": {"USD", "NZD"},
    "GC=F": {"USD"},        # Oro (US gold futures)
    "XAUUSD=X": {"USD"},    # Oro spot
}


def currencies_for_symbol(symbol: str) -> set[str]:
    if symbol in _SYMBOL_CURRENCIES:
        return _SYMBOL_CURRENCIES[symbol]
    upper = str(symbol or "").upper().strip()
    if upper in _SYMBOL_CURRENCIES:
        return _SYMBOL_CURRENCIES[upper]
    # v3.5.0: parsear pares genericos — 'EURUSD' (formato MT5 del scalping) o
    # 'EURUSD=X' (Yahoo) -> {EUR, USD}. Antes el formato MT5 caia al default y
    # perdia los eventos de la moneda no-USD (p.ej. un rate decision del BCE).
    if upper.endswith("=X"):
        upper = upper[:-2]
    if len(upper) == 6 and upper.isalpha():
        return {upper[:3], upper[3:]}
    # Default conservador: bloquear con eventos USD si no se reconoce
    return {"USD"}


def is_safe_window(
    symbol: str,
    now_utc: datetime,
    repository,
    buffer_min: int = 30,
) -> tuple[bool, str]:
    countries = currencies_for_symbol(symbol)
    if not countries:
        return True, "no currency map"

    start = (now_utc - timedelta(minutes=buffer_min)).isoformat()
    end = (now_utc + timedelta(minutes=buffer_min)).isoformat()

    try:
        events = repository.fetch_economic_events_window(
            start_iso=start,
            end_iso=end,
            countries=list(countries),
            impact="high",
        )
    except Exception:
        return True, "calendar query failed; allow"

    if not events:
        return True, "no high-impact events"

    # Usa el primer evento mas cercano
    upcoming = events[0]
    try:
        event_dt = datetime.fromisoformat(
            str(upcoming.get("event_time")).replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return True, "event_time parse failed; allow"

    delta_min = int(abs((event_dt - now_utc).total_seconds()) / 60)
    title = str(upcoming.get("title") or "evento")
    country = str(upcoming.get("country") or "?")
    return False, f"{title} ({country}) en {delta_min}min"
