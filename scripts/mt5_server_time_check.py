"""Mide la hora del servidor MT5 contra UTC real y la regla de horario de verano.

v3.13.3. SOLO LECTURAS y SIN pelear el login con el bot vivo:
`mt5.initialize()` SIN login/password/server se engancha a la sesion ya abierta
del terminal; no re-loguea, no toca el .env, no manda ordenes. `mt5.shutdown()`
cierra solo la conexion de ESTE proceso.

Que mide:
1. Desfase actual: time_msc de los ticks de varios simbolos vs time.time().
   Requiere mercado abierto (con el mercado cerrado el tick es viejo).
2. Regla de DST: ultima vela H1 de cada viernes de EURUSD (toda la historia que
   el terminal tenga) contra lo que predice cada zona candidata (EET regla UE vs
   NY+7 regla de EE.UU.). Ver app/brokers/mt5_time.weekly_close_rule_votes.

Uso (desde la raiz del repo, con el terminal MT5 abierto):
    python scripts/mt5_server_time_check.py
Salida ASCII (consola PS 5.1 cp1252).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.brokers.mt5_time import (  # noqa: E402
    utc_offset_seconds,
    weekly_close_rule_votes,
)

_TICK_SYMBOLS = ("EURUSD", "USDCAD", "GBPUSD", "USDJPY", "XAUUSD")
_H1 = 0x4001  # mt5.TIMEFRAME_H1


def main() -> int:
    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except ImportError:
        print("Package MetaTrader5 no instalado en este Python.")
        return 2
    if not mt5.initialize():  # SIN credenciales: se engancha a la sesion abierta
        print(f"mt5.initialize() fallo: {mt5.last_error()} (terminal cerrado?)")
        return 2
    try:
        account = mt5.account_info()
        server = getattr(account, "server", "?") if account else "?"
        print(f"Servidor: {server}")
        print("")
        print("== 1. Desfase actual (tick time_msc - reloj local) ==")
        diffs: list[float] = []
        for symbol in _TICK_SYMBOLS:
            mt5.symbol_select(symbol, True)
            tick = mt5.symbol_info_tick(symbol)
            now = time.time()
            if tick is None or not getattr(tick, "time_msc", 0):
                print(f"  {symbol:<8} sin tick")
                continue
            diff = tick.time_msc / 1000.0 - now
            diffs.append(diff)
            print(f"  {symbol:<8} {diff:+10.1f} s  ({diff / 3600:+.3f} h)")
        if diffs:
            hours = round(sorted(diffs)[len(diffs) // 2] / 3600)
            print(f"  -> servidor = UTC{hours:+d} ahora "
                  "(si no es una hora entera, el mercado esta cerrado)")
        print("")
        print("== 2. Regla de horario de verano (ultima vela H1 de cada viernes) ==")
        rates = None
        for count in (100_000, 60_000, 30_000, 10_000):
            rates = mt5.copy_rates_from_pos("EURUSD", _H1, 0, count)
            if rates is not None and len(rates):
                break
        if rates is None or not len(rates):
            print("  sin velas H1 de EURUSD")
            return 1
        votes = weekly_close_rule_votes([int(r["time"]) for r in rates])
        n = votes["n"]
        print(f"  semanas evaluadas: {n}")
        for tz in ("EET", "NY+7"):
            print(f"  {tz:<5} coincide en {votes[tz]}/{n}  "
                  f"(no coincide: {', '.join(votes['mismatch'][tz][:6]) or '-'}"
                  f"{' ...' if len(votes['mismatch'][tz]) > 6 else ''})")
        best = max(("EET", "NY+7"), key=lambda tz: votes[tz])
        now_offset = utc_offset_seconds(best, time.time()) // 3600
        print("")
        print(f"Recomendado: MT5_SERVER_TZ={best} (hoy UTC{now_offset:+d}).")
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
