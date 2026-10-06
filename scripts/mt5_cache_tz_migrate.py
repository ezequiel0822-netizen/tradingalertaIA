"""Migra las series INTRADIA del cache MT5 de hora del servidor a UTC real.

v3.13.3. Las velas de MT5 se cachearon (mt5_historical_cache) con el epoch en
HORA DEL SERVIDOR (MetaQuotes-Demo: EET, UTC+2/+3). El harness las lee como UTC
-> forex_session_breakout H1 replayo con las sesiones corridas 2-3 h.

Que hace:
- Lista cada serie del cache con su base horaria (mt5_cache_meta).
- DRY-RUN por defecto: muestra cuantas barras se moverian y el primer/ultimo
  epoch antes/despues. No escribe nada.
- Con --apply: por serie intradia legacy, re-expresa TODOS los epochs a UTC real
  en UNA transaccion (todo o nada) y la marca 'utc'. Si dos barras cayeran en el
  mismo epoch, esa serie NO se toca. Idempotente: una serie ya 'utc' se saltea.
- D1/W1 NO se tocan: su epoch es la fecha de trading (etiqueta), con esa
  convencion se evaluaron gold_friday_hold, estacionalidad, carry y COT; y el
  regime gate del bot vivo lee D1 -> el ciclo vivo no se entera de esta migracion.
- Las filas de Yahoo (acciones/indices) son todas D1: tampoco se tocan.

Uso (desde la raiz del repo):
    python scripts/mt5_cache_tz_migrate.py --server-tz EET            # dry-run
    python scripts/mt5_cache_tz_migrate.py --server-tz EET --apply
Opcional: --db <ruta a una COPIA de la DB> para probar sobre una copia.
Despues de migrar, configurar MT5_SERVER_TZ=EET para que el loader siga
escribiendo en UTC (sin el, el loader se niega a escribir sobre series 'utc').
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.brokers.mt5_time import (  # noqa: E402
    TIME_BASIS_SERVER,
    is_intraday_timeframe,
    is_known_server_tz,
    migrate_series_to_utc,
    normalize_server_tz,
)
from app.database.db import init_db  # noqa: E402
from app.database.repository import Repository  # noqa: E402


def _fmt(epoch) -> str:
    if epoch is None:
        return "-"
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server-tz", default=None,
                        help="EET | NY+7 | UTC+N (default: MT5_SERVER_TZ del .env)")
    parser.add_argument("--apply", action="store_true",
                        help="escribir (sin esto es dry-run)")
    parser.add_argument("--db", default=None, help="ruta de la DB (default: SQLITE_PATH)")
    args = parser.parse_args(argv)

    if args.db:
        db_path = Path(args.db)
        raw_tz = args.server_tz or ""
    else:
        from app.config.settings import load_settings

        settings = load_settings()
        db_path = settings.sqlite_path
        raw_tz = args.server_tz if args.server_tz is not None else settings.mt5_server_tz
    server_tz = normalize_server_tz(raw_tz)
    if not server_tz:
        hint = "" if is_known_server_tz(raw_tz) else f" ({raw_tz!r} no reconocido)"
        print(f"Falta la zona del servidor{hint}: --server-tz EET (MetaQuotes-Demo).")
        return 2

    init_db(db_path)  # solo crea tablas faltantes (mt5_cache_meta); no toca datos
    repo = Repository(db_path)
    mode = "APPLY" if args.apply else "DRY-RUN (no escribe)"
    print(f"== Migracion del cache MT5 a UTC real | zona {server_tz} | {mode} ==")
    print(f"DB: {db_path.name}")
    print("")
    header = (f"{'symbol':<10} {'tf':>5} {'bars':>7}  {'base':<7} "
              f"{'primero antes -> despues':<36} accion")
    print(header)
    print("-" * len(header))
    touched = errors = 0
    for serie in repo.list_mt5_cache_series():
        symbol, tf, bars = serie["symbol"], int(serie["timeframe"]), int(serie["bars"])
        basis = serie.get("time_basis") or TIME_BASIS_SERVER
        if not is_intraday_timeframe(tf):
            print(f"{symbol:<10} {tf:>5} {bars:>7}  {'-':<7} {'-':<36} D1+: no se toca")
            continue
        result = migrate_series_to_utc(repo, symbol, tf, server_tz, apply=args.apply)
        moved = (f"{_fmt(result.get('first_old'))} -> {_fmt(result.get('first_new'))}"
                 if result.get("rows") else "-")
        if result.get("collisions"):
            action = f"ERROR: {result['collisions']} colisiones, NO se toco"
            errors += 1
        elif result.get("applied"):
            action = f"migrada ({result['rows']} barras)"
            touched += 1
        elif result.get("rows") and not args.apply:
            action = f"se migraria ({result['rows']} barras)"
        else:
            action = result.get("reason", "-")
        print(f"{symbol:<10} {tf:>5} {bars:>7}  {basis:<7} {moved:<36} {action}")
    print("")
    if args.apply:
        print(f"Series migradas: {touched}. Errores: {errors}.")
    else:
        print("Dry-run: nada escrito. Repetir con --apply para migrar.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
