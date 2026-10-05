"""B4b — colector hacia adelante (short Hyperliquid / long Binance, BTC + ETH).

Pre-registro: research/HIPOTESIS_2026-10-04_B4b_forward.md (commit 8febc1a, ANTES de
bajar datos). Ventana decisoria T0 = 2026-10-06 00:00 UTC -> T1 = 2027-04-06 00:00 UTC.

Qué hace (idempotente; una corrida semanal alcanza y sobra):
  - baja el funding horario de Hyperliquid, las velas 1 h de Hyperliquid (la API solo
    guarda las 5000 más recientes ~ 208 días: por eso hay que juntarlas mientras existen),
    el funding y las velas 1 h del perp de Binance (REST; al evaluar se prefieren los
    archivos oficiales de data.binance.vision) y el `meta` de Hyperliquid (apalancamiento
    máximo -> margen de mantenimiento);
  - guarda cada respuesta cruda comprimida y su sha256 en `manifest.csv`;
  - fusiona en CSVs con los valores TAL CUAL los da la API (texto) y registra en
    `conflicts.csv` cualquier valor que cambie entre corridas (nunca pisa en silencio);
  - rellena huecos solo: cada corrida arranca desde el hueco más viejo (o 48 h antes del
    último dato), dentro de lo que la API todavía tenga;
  - imprime SOLO salud de datos: filas, primera/última marca y huecos. NUNCA calcula ni
    muestra funding medio, spread ni PnL (pre-registro §8: anti-espiar).

Research-only: no importa `app`, no toca el bot, ni MT5, ni el .env.

Uso:  python scripts/b4b_forward_collector.py [--out trading_data/b4b_forward]
Salida != 0 si alguna serie falló (lo ve el Programador de tareas).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "trading_data" / "b4b_forward"
HL_INFO = "https://api.hyperliquid.xyz/info"
BN_FAPI = "https://fapi.binance.com/fapi/v1"
UA = {"User-Agent": "Mozilla/5.0 (research)"}

H_MS = 3_600_000
T0_MS = int(datetime(2026, 10, 6, tzinfo=timezone.utc).timestamp() * 1000)
T1_MS = T0_MS + 182 * 24 * H_MS
COLLECT_FROM_MS = T0_MS - 48 * H_MS            # colchón de alineación (no entra en métricas)
COLLECT_UNTIL_MS = T1_MS + 7 * 24 * H_MS
OVERLAP_MS = 48 * H_MS
HL_CANDLE_HORIZON_MS = 4990 * H_MS             # la API guarda las 5000 velas más recientes
COINS = (("BTC", "BTCUSDT"), ("ETH", "ETHUSDT"))

# serie -> (columna clave, columnas)
SCHEMAS = {
    "hl_funding": ("time_ms", ["time_ms", "fundingRate", "premium"]),
    "hl_candles_1h": ("t_ms", ["t_ms", "T_ms", "o", "h", "l", "c", "v", "n"]),
    "bn_funding": ("time_ms", ["time_ms", "fundingRate", "markPrice"]),
    "bn_klines_1h": ("open_time_ms", ["open_time_ms", "o", "h", "l", "c", "v", "close_time_ms"]),
}

_session = requests.Session()
_session.headers.update(UA)
_log_file: Path | None = None


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    if _log_file is not None:
        with _log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def iso(ms: int | None) -> str:
    if ms is None:
        return "-"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def request(method: str, url: str, **kw) -> bytes:
    last: Exception | None = None
    for attempt in range(6):
        try:
            r = _session.request(method, url, timeout=60, **kw)
            if r.status_code in (418, 429) or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{method} {url} falló: {last}")


class Run:
    """Una corrida: guarda crudos + manifest."""

    def __init__(self, out: Path):
        self.out = out
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.raw_dir = out / "raw" / self.run_id
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.manifest: list[dict] = []

    def save(self, name: str, page: int, req: dict, raw: bytes, n: int) -> None:
        fn = self.raw_dir / f"{name}_{page:03d}.json.gz"
        with gzip.open(fn, "wb") as f:
            f.write(raw)
        self.manifest.append({
            "run_id": self.run_id, "series": name, "page": page,
            "request": json.dumps(req, sort_keys=True), "file": fn.relative_to(self.out).as_posix(),
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "records": n,
        })


# ================================ FUENTES ==========================================
def hl_funding(run: Run, coin: str, start: int, end: int) -> list[dict]:
    rows, t, page = [], start, 0
    while t <= end:
        body = {"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": end}
        raw = request("POST", HL_INFO, json=body)
        d = json.loads(raw)
        if not isinstance(d, list):
            raise RuntimeError(f"respuesta inesperada: {str(d)[:200]}")
        run.save(f"hl_funding_{coin}", page, body, raw, len(d))
        if not d:
            break
        rows += [{"time_ms": str(int(x["time"])), "fundingRate": str(x["fundingRate"]),
                  "premium": str(x.get("premium", ""))} for x in d]
        last = max(int(x["time"]) for x in d)
        if last < t:
            break
        t, page = last + 1, page + 1
        time.sleep(0.5)
    return [r for r in rows if start <= int(r["time_ms"]) <= end]


def hl_candles(run: Run, coin: str, start: int, end: int, now: int) -> list[dict]:
    rows, t, page = [], start, 0
    while t < end:
        body = {"type": "candleSnapshot",
                "req": {"coin": coin, "interval": "1h", "startTime": t, "endTime": end}}
        raw = request("POST", HL_INFO, json=body)
        d = json.loads(raw)
        if not isinstance(d, list):
            raise RuntimeError(f"respuesta inesperada: {str(d)[:200]}")
        run.save(f"hl_candles_1h_{coin}", page, body, raw, len(d))
        if not d:
            break
        rows += [{"t_ms": str(int(x["t"])), "T_ms": str(int(x["T"])), "o": str(x["o"]),
                  "h": str(x["h"]), "l": str(x["l"]), "c": str(x["c"]), "v": str(x["v"]),
                  "n": str(x["n"])} for x in d]
        last = max(int(x["t"]) for x in d)
        if last < t:
            break
        t, page = last + H_MS, page + 1
        time.sleep(0.5)
    # solo velas CERRADAS y dentro del rango pedido
    return [r for r in rows if int(r["t_ms"]) + H_MS <= now and start <= int(r["t_ms"]) < end]


def bn_funding(run: Run, sym: str, start: int, end: int) -> list[dict]:
    rows, t, page = [], start, 0
    while t <= end:
        params = {"symbol": sym, "startTime": t, "endTime": end, "limit": 1000}
        raw = request("GET", f"{BN_FAPI}/fundingRate", params=params)
        d = json.loads(raw)
        if not isinstance(d, list):
            raise RuntimeError(f"respuesta inesperada: {str(d)[:200]}")
        run.save(f"bn_funding_{sym}", page, params, raw, len(d))
        if not d:
            break
        rows += [{"time_ms": str(int(x["fundingTime"])), "fundingRate": str(x["fundingRate"]),
                  "markPrice": str(x.get("markPrice", ""))} for x in d]
        last = max(int(x["fundingTime"]) for x in d)
        if last < t:
            break
        t, page = last + 1, page + 1
        time.sleep(0.3)
    return [r for r in rows if start <= int(r["time_ms"]) <= end]


def bn_klines(run: Run, sym: str, start: int, end: int, now: int) -> list[dict]:
    rows, t, page = [], start, 0
    while t < end:
        params = {"symbol": sym, "interval": "1h", "startTime": t, "endTime": end, "limit": 1500}
        raw = request("GET", f"{BN_FAPI}/klines", params=params)
        d = json.loads(raw)
        if not isinstance(d, list):
            raise RuntimeError(f"respuesta inesperada: {str(d)[:200]}")
        run.save(f"bn_klines_1h_{sym}", page, params, raw, len(d))
        if not d:
            break
        rows += [{"open_time_ms": str(int(x[0])), "o": str(x[1]), "h": str(x[2]), "l": str(x[3]),
                  "c": str(x[4]), "v": str(x[5]), "close_time_ms": str(int(x[6]))} for x in d]
        last = max(int(x[0]) for x in d)
        if last < t:
            break
        t, page = last + H_MS, page + 1
        time.sleep(0.3)
    return [r for r in rows if int(r["close_time_ms"]) < now and start <= int(r["open_time_ms"]) < end]


def hl_meta(run: Run) -> dict[str, str]:
    body = {"type": "meta"}
    raw = request("POST", HL_INFO, json=body)
    d = json.loads(raw)
    run.save("hl_meta", 0, body, raw, len(d.get("universe", [])))
    lev = {u.get("name"): str(u.get("maxLeverage")) for u in d.get("universe", [])}
    return {c: lev.get(c, "?") for c, _ in COINS}


# ================================ ALMACÉN ==========================================
def read_store(path: Path, key: str) -> dict[int, dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {int(r[key]): r for r in csv.DictReader(f)}


def merge(out: Path, series: str, rows: list[dict], run_id: str) -> tuple[int, int]:
    base = series.rsplit("_", 1)[0]
    key, cols = SCHEMAS[base]
    path = out / "data" / f"{series}.csv"
    store = read_store(path, key)
    added = changed = 0
    conflicts = []
    for r in rows:
        k = int(r[key])
        old = store.get(k)
        if old is None:
            added += 1
        elif any(old.get(c) != r[c] for c in cols):
            changed += 1
            conflicts.append({"run_id": run_id, "series": series, "key": k,
                              "old": json.dumps(old, sort_keys=True),
                              "new": json.dumps(r, sort_keys=True)})
        else:
            continue
        store[k] = {c: r[c] for c in cols}          # la versión más nueva queda en data/
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for k in sorted(store):
            w.writerow(store[k])
    tmp.replace(path)
    if conflicts:
        append_csv(out / "conflicts.csv", conflicts)
    return added, changed


def append_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new:
            w.writeheader()
        w.writerows(rows)


def expected_hours(lo: int, hi: int) -> range:
    """Marcas horarias [lo, hi] alineadas a la hora."""
    first = -(-lo // H_MS) * H_MS
    return range(first, hi + 1, H_MS)


def health(series: str, store: dict[int, dict], now: int) -> dict:
    """Solo conteos y huecos. Ningún valor de funding ni de precio."""
    base = series.rsplit("_", 1)[0]
    keys = sorted(store)
    hi = min(now, COLLECT_UNTIL_MS)
    if base == "hl_funding":
        have = {k // H_MS * H_MS for k in keys}
        exp = expected_hours(COLLECT_FROM_MS + H_MS, (hi // H_MS) * H_MS)
    elif base == "bn_funding":
        have = {k // H_MS * H_MS for k in keys}
        exp = range(-(-COLLECT_FROM_MS // (8 * H_MS)) * 8 * H_MS, (hi // H_MS) * H_MS + 1, 8 * H_MS)
    else:                                            # velas: marca = apertura
        have = set(keys)
        exp = expected_hours(COLLECT_FROM_MS, (hi // H_MS) * H_MS - H_MS)
    missing = [e for e in exp if e not in have]
    fwd_exp = [e for e in exp if e >= T0_MS]
    fwd_missing = [e for e in missing if e >= T0_MS]
    return {"series": series, "rows": len(keys), "first": iso(keys[0]) if keys else "-",
            "last": iso(keys[-1]) if keys else "-", "expected": len(exp), "missing": len(missing),
            "fwd_expected": len(fwd_exp), "fwd_missing": len(fwd_missing),
            "oldest_missing_ms": missing[0] if missing else None}


def start_for(series: str, store: dict[int, dict], now: int) -> int:
    floor = COLLECT_FROM_MS
    if series.startswith("hl_candles"):
        floor = max(floor, now - HL_CANDLE_HORIZON_MS)
    if not store:
        return floor
    h = health(series, store, now)
    start = max(store) - OVERLAP_MS
    if h["oldest_missing_ms"] is not None:
        start = min(start, h["oldest_missing_ms"])
    return max(start, floor)


# ================================ MAIN =============================================
def main() -> int:
    global _log_file
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consola cp1252
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    _log_file = out / "collector.log"

    now = int(time.time() * 1000)
    end = min(now, COLLECT_UNTIL_MS)
    run = Run(out)
    elapsed = max(0.0, (now - T0_MS) / (24 * H_MS))
    log(f"B4b colector run {run.run_id} | T0 {iso(T0_MS)} UTC -> T1 {iso(T1_MS)} UTC | "
        f"día {min(elapsed, 182):.1f} de 182")
    if now < COLLECT_FROM_MS:
        log("todavía no empezó el colchón de colección; nada que hacer")
        return 0

    status: dict[str, str] = {}
    added_tot: dict[str, int] = {}
    jobs = []
    for coin, sym in COINS:
        jobs += [
            (f"hl_funding_{coin}", lambda s, c=coin: hl_funding(run, c, s, end)),
            (f"hl_candles_1h_{coin}", lambda s, c=coin: hl_candles(run, c, s, end, now)),
            (f"bn_funding_{sym}", lambda s, y=sym: bn_funding(run, y, s, end)),
            (f"bn_klines_1h_{sym}", lambda s, y=sym: bn_klines(run, y, s, end, now)),
        ]
    healths = []
    for series, fn in jobs:
        path = out / "data" / f"{series}.csv"
        key = SCHEMAS[series.rsplit("_", 1)[0]][0]
        try:
            store = read_store(path, key)
            start = start_for(series, store, now)
            rows = fn(start)
            added, changed = merge(out, series, rows, run.run_id)
            status[series] = "ok" if not changed else f"ok ({changed} valores CAMBIARON -> conflicts.csv)"
            added_tot[series] = added
        except Exception as e:  # soft-fail por serie
            status[series] = f"FALLO: {e}"
            added_tot[series] = 0
        healths.append(health(series, read_store(path, key), now))

    try:
        lev = hl_meta(run)
        status["hl_meta"] = "ok"
        log("Hyperliquid maxLeverage (pre-registro: BTC 40x -> MM 1.25 %, ETH 25x -> MM 2 %): "
            + ", ".join(f"{c} {v}x" for c, v in lev.items()))
    except Exception as e:
        status["hl_meta"] = f"FALLO: {e}"
        lev = {}

    append_csv(out / "manifest.csv", run.manifest)
    log("salud de datos (solo conteos; huecos 'fwd' = dentro de T0 -> ahora):")
    for h in healths:
        log(f"  {h['series']:<22} filas {h['rows']:>6}  {h['first']} -> {h['last']}  "
            f"huecos {h['missing']}/{h['expected']}  fwd {h['fwd_missing']}/{h['fwd_expected']}  "
            f"+{added_tot.get(h['series'], 0)}  [{status[h['series']]}]")
    append_csv(out / "runs.csv", [{
        "run_id": run.run_id, "now_utc": iso(now), "files": len(run.manifest),
        "status": json.dumps(status, ensure_ascii=False),
        "fwd_missing": json.dumps({h["series"]: h["fwd_missing"] for h in healths}),
        "hl_max_leverage": json.dumps(lev),
    }])
    if now > COLLECT_UNTIL_MS:
        log("ventana completa (T1 + 7 días): la tarea programada ya se puede borrar")
    failed = [s for s, v in status.items() if v.startswith("FALLO")]
    if failed:
        log(f"series con FALLO: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
