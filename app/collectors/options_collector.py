"""v3.16.0 — OptionsFlowCollector: foto diaria de las cadenas de opciones (Yahoo, gratis).

Por qué: el "options flow" (volumen y open interest de calls/puts, actividad inusual,
volatilidad implícita) no tiene historia gratis. La única forma honesta de probarlo es
GUARDARLO desde hoy y evaluarlo más adelante con un pre-registro
(research/OPCIONES_COLECTA_2026-10-07.md). Igual que el COT collector:

- NO genera señal ni gate y NO muestra los valores (solo cuántos días se guardaron), para
  no "mirar" la ventana antes del pre-registro.
- Opt-in OFF + soft-fail: apagado o con error, el bot corre EXACTAMENTE igual.
- Read-only: HTTP GET a Yahoo (cookie A3 + crumb, como el sitio). Sin órdenes.

Cuándo: después del cierre de EE.UU. (desde OPTIONS_COLLECTOR_HOUR_UTC, por defecto
22:00 UTC, hasta las 08:00 UTC del día siguiente), días hábiles. Incremental: unos pocos
símbolos por ciclo (OPTIONS_COLLECTOR_SYMBOLS_PER_CYCLE) para no frenar el ciclo del bot.
La fecha de sesión sale de la cotización (`regularMarketTime`): un feriado no se guarda.

Qué guarda:
- `options_snapshots` (DB): un resumen por (sesión, símbolo) — volumen y OI de calls y
  puts, prima negociada, actividad inusual (volumen > OI), IV ATM y skew 95/105.
- Opcional (`OPTIONS_COLLECTOR_SAVE_RAW`): la cadena compacta en
  `<carpeta de la DB>/options_raw/<sesión>/<SÍMBOLO>.json.gz`, para poder definir otras
  medidas en el pre-registro sin perder historia.
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

YAHOO_OPTIONS_URL = "https://query2.finance.yahoo.com/v7/finance/options/{symbol}"
YAHOO_COOKIE_URL = "https://fc.yahoo.com"
YAHOO_CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
# Gotcha del proyecto: con un UA de navegador Yahoo no devuelve 429 tan seguido.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
DEFAULT_ETFS = ("SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "UUP", "FXE")
CATCHUP_UNTIL_HOUR_UTC = 8          # se puede completar la sesión hasta las 08:00 UTC
MAX_ATTEMPTS = 3                    # reintentos por símbolo y sesión
RATE_LIMIT_COOLDOWN_SECONDS = 900.0
REQUEST_PAUSE_SECONDS = 0.4
UNUSUAL_MIN_VOLUME = 100            # "inusual" = volumen > OI y volumen ≥ 100 contratos
REF_EXPIRY_MIN_DAYS = 7             # vencimiento de referencia para IV ATM y skew
IV_SEARCH_REL = 0.03                # si el strike justo no tiene IV, vecino dentro de ±3 %
CONTRACT_FIELDS = ("strike", "lastPrice", "bid", "ask", "volume", "openInterest",
                   "impliedVolatility", "lastTradeDate", "inTheMoney")
QUOTE_FIELDS = ("regularMarketPrice", "regularMarketTime", "regularMarketVolume",
                "regularMarketPreviousClose", "currency")


class RateLimited(Exception):
    """Yahoo devolvió 429: cortar por un rato."""


# ------------------------------------------------------------ funciones puras
def _num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def target_session_date(now: datetime, hour_from: int = 22,
                        until_hour: int = CATCHUP_UNTIL_HOUR_UTC) -> date | None:
    """Sesión de EE.UU. que toca capturar ahora, o None. Desde `hour_from` UTC del día
    D hasta `until_hour` UTC de D+1; D tiene que ser día hábil."""
    now = now.astimezone(timezone.utc)
    if now.hour >= hour_from:
        d = now.date()
    elif now.hour < until_hour:
        d = now.date() - timedelta(days=1)
    else:
        return None
    return d if d.weekday() < 5 else None


def collector_symbols(settings) -> list[str]:
    """OPTIONS_COLLECTOR_SYMBOLS (o los ETF por defecto) + las acciones del bot, sin
    repetir y en mayúsculas."""
    base = list(getattr(settings, "options_collector_symbols", None) or DEFAULT_ETFS)
    extra = list(getattr(settings, "stock_symbols", None) or [])
    out: list[str] = []
    for s in base + extra:
        s = str(s or "").strip().upper()
        if s and s not in out and "=" not in s:
            out.append(s)
    return out


def _iv(c: dict | None) -> float | None:
    v = _num((c or {}).get("impliedVolatility"))
    return v if v is not None and v > 0.001 else None    # Yahoo usa ~1e-5 para "sin dato"


def _iv_near(contracts: list[dict], target: float, max_rel: float = IV_SEARCH_REL) -> float | None:
    """IV válida del strike más cercano a `target`; si ese no tiene dato (fuera de
    horario Yahoo suele dar ~1e-5), el vecino más cercano con dato dentro de ±max_rel."""
    ranked = sorted((c for c in contracts if _num(c.get("strike")) is not None),
                    key=lambda c: abs(float(c["strike"]) - target))
    for c in ranked:
        if abs(float(c["strike"]) - target) > max_rel * target:
            break
        v = _iv(c)
        if v is not None:
            return v
    return None


def session_date_of(quote: dict) -> date | None:
    t = _num(quote.get("regularMarketTime"))
    return datetime.fromtimestamp(t, tz=timezone.utc).date() if t else None


def summarize_chain(symbol: str, chain: dict, captured_at: datetime) -> dict:
    """Resumen de la cadena (todas las expiraciones guardadas) para la DB."""
    quote = chain.get("quote") or {}
    spot = _num(quote.get("regularMarketPrice"))
    expiries = chain.get("options") or []
    agg = {"call": {"vol": 0.0, "oi": 0.0, "prem": 0.0, "u_n": 0, "u_prem": 0.0},
           "put": {"vol": 0.0, "oi": 0.0, "prem": 0.0, "u_n": 0, "u_prem": 0.0}}
    n_contracts = 0
    for ex in expiries:
        for side, key in (("call", "calls"), ("put", "puts")):
            for c in ex.get(key) or []:
                n_contracts += 1
                vol = _num(c.get("volume")) or 0.0
                oi = _num(c.get("openInterest")) or 0.0
                px = _num(c.get("lastPrice")) or 0.0
                prem = vol * px * 100.0
                a = agg[side]
                a["vol"] += vol
                a["oi"] += oi
                a["prem"] += prem
                if vol >= UNUSUAL_MIN_VOLUME and vol > oi:
                    a["u_n"] += 1
                    a["u_prem"] += prem
    atm_iv = skew = ref_days = None
    sess = session_date_of(quote)
    if spot and expiries:
        t_ref = _num(quote.get("regularMarketTime")) or captured_at.timestamp()
        ref = None
        for ex in expiries:
            days = ((_num(ex.get("expirationDate")) or 0) - t_ref) / 86400.0
            if days >= REF_EXPIRY_MIN_DAYS:
                ref, ref_days = ex, days
                break
        if ref is None:
            ref = expiries[0]
            ref_days = ((_num(ref.get("expirationDate")) or 0) - t_ref) / 86400.0
        calls, puts = ref.get("calls") or [], ref.get("puts") or []
        ivs = [v for v in (_iv_near(calls, spot), _iv_near(puts, spot)) if v]
        atm_iv = sum(ivs) / len(ivs) if ivs else None
        put_iv, call_iv = _iv_near(puts, 0.95 * spot), _iv_near(calls, 1.05 * spot)
        skew = (put_iv - call_iv) if (put_iv and call_iv) else None
    c, p = agg["call"], agg["put"]
    return {
        "session_date": sess.isoformat() if sess else None,
        "symbol": symbol,
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "underlying_price": spot,
        "n_expiries": len(expiries),
        "n_contracts": n_contracts,
        "call_volume": c["vol"], "put_volume": p["vol"],
        "call_oi": c["oi"], "put_oi": p["oi"],
        "call_premium": round(c["prem"], 2), "put_premium": round(p["prem"], 2),
        "unusual_call_count": c["u_n"], "unusual_put_count": p["u_n"],
        "unusual_call_premium": round(c["u_prem"], 2),
        "unusual_put_premium": round(p["u_prem"], 2),
        "atm_iv": atm_iv, "skew_iv": skew,
        "ref_expiry_days": round(ref_days, 2) if ref_days is not None else None,
        "source": "yahoo",
    }


def compact_chain(symbol: str, chain: dict, captured_at: datetime) -> dict:
    """Versión compacta para el archivo crudo (solo los campos que importan)."""
    quote = chain.get("quote") or {}
    return {
        "symbol": symbol,
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "quote": {k: quote.get(k) for k in QUOTE_FIELDS},
        "options": [
            {"expiration": ex.get("expirationDate"),
             "calls": [{k: c.get(k) for k in CONTRACT_FIELDS} for c in ex.get("calls") or []],
             "puts": [{k: c.get(k) for k in CONTRACT_FIELDS} for c in ex.get("puts") or []]}
            for ex in chain.get("options") or []
        ],
    }


# ------------------------------------------------------------------ colector
class OptionsFlowCollector:
    STATE_KEY = "options_capture_state"

    def __init__(self, settings, session: requests.Session | None = None,
                 pause_seconds: float = REQUEST_PAUSE_SECONDS) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": BROWSER_UA})
        self.pause_seconds = pause_seconds
        self._crumb: str | None = None
        self._cooldown_until = 0.0

    # --------------------------------------------------------------- HTTP
    def _refresh_crumb(self) -> None:
        timeout = getattr(self.settings, "request_timeout_seconds", 15)
        try:
            self.session.get(YAHOO_COOKIE_URL, timeout=timeout)   # setea la cookie A3 (404 ok)
        except requests.RequestException:
            pass
        r = self.session.get(YAHOO_CRUMB_URL, timeout=timeout)
        if r.status_code == 429:
            raise RateLimited()
        r.raise_for_status()
        crumb = (r.text or "").strip()
        if not crumb or "<" in crumb:
            raise RuntimeError("Yahoo no devolvió crumb")
        self._crumb = crumb

    def _get(self, symbol: str, expiry: int | None = None) -> dict:
        timeout = getattr(self.settings, "request_timeout_seconds", 15)
        for attempt in (1, 2):
            if not self._crumb:
                self._refresh_crumb()
            params: dict[str, Any] = {"crumb": self._crumb}
            if expiry is not None:
                params["date"] = int(expiry)
            r = self.session.get(YAHOO_OPTIONS_URL.format(symbol=symbol), params=params,
                                 timeout=timeout)
            if r.status_code == 429:
                raise RateLimited()
            if r.status_code == 401 and attempt == 1:
                self._crumb = None                     # crumb vencido: uno nuevo y reintenta
                continue
            r.raise_for_status()
            if self.pause_seconds:
                time.sleep(self.pause_seconds)
            return r.json()
        raise RuntimeError("Yahoo rechazó el crumb dos veces")

    def fetch_chain(self, symbol: str) -> dict:
        """Cotización + hasta OPTIONS_COLLECTOR_MAX_EXPIRIES vencimientos dentro de
        OPTIONS_COLLECTOR_MAX_DAYS días."""
        max_exp = int(getattr(self.settings, "options_collector_max_expiries", 6))
        max_days = float(getattr(self.settings, "options_collector_max_days", 60))
        res = ((self._get(symbol).get("optionChain") or {}).get("result") or [None])[0]
        if not res:
            raise RuntimeError(f"cadena vacía para {symbol}")
        quote = res.get("quote") or {}
        t0 = _num(quote.get("regularMarketTime")) or time.time()
        keep = [int(e) for e in res.get("expirationDates") or []
                if (int(e) - t0) / 86400.0 <= max_days][:max_exp]
        got = {int(o.get("expirationDate")): o for o in res.get("options") or []
               if o.get("expirationDate") is not None}
        for e in keep:
            if e in got:
                continue
            r2 = ((self._get(symbol, e).get("optionChain") or {}).get("result") or [None])[0]
            for o in (r2 or {}).get("options") or []:
                if o.get("expirationDate") is not None:
                    got[int(o["expirationDate"])] = o
        return {"quote": quote, "options": [got[e] for e in keep if e in got]}

    # ------------------------------------------------------------ captura
    def _raw_dir(self) -> Path:
        return raw_dir(self.settings)

    def _load_state(self, repository, session_day: str) -> dict:
        try:
            st = json.loads(repository.get_state(self.STATE_KEY) or "{}")
        except (TypeError, ValueError):
            st = {}
        if st.get("session") != session_day:
            st = {"session": session_day, "done": [], "attempts": {}}
        return st

    def step(self, repository, now: datetime | None = None) -> int:
        """Un paso incremental. Devuelve cuántos resúmenes guardó en este ciclo."""
        if not getattr(self.settings, "enable_options_collector", False):
            return 0
        now = now or datetime.now(timezone.utc)
        target = target_session_date(
            now, int(getattr(self.settings, "options_collector_hour_utc", 22)))
        if target is None or time.monotonic() < self._cooldown_until:
            return 0
        day = target.isoformat()
        st = self._load_state(repository, day)
        pending = [s for s in collector_symbols(self.settings)
                   if s not in st["done"] and int(st["attempts"].get(s, 0)) < MAX_ATTEMPTS]
        per_cycle = max(1, int(getattr(self.settings, "options_collector_symbols_per_cycle", 4)))
        saved = 0
        for sym in pending[:per_cycle]:
            try:
                chain = self.fetch_chain(sym)
                snap = summarize_chain(sym, chain, datetime.now(timezone.utc))
                if snap["session_date"] != day:
                    st["done"].append(sym)              # feriado / sin sesión: nada que guardar
                    continue
                if getattr(self.settings, "options_collector_save_raw", True):
                    self._save_raw(day, sym, compact_chain(sym, chain, now))
                if repository.insert_options_snapshot(snap):
                    saved += 1
                st["done"].append(sym)
            except RateLimited:
                self._cooldown_until = time.monotonic() + RATE_LIMIT_COOLDOWN_SECONDS
                logger.warning("Yahoo 429 (opciones): pausa de %ss",
                               int(RATE_LIMIT_COOLDOWN_SECONDS))
                break
            except Exception as exc:  # soft-fail por símbolo
                st["attempts"][sym] = int(st["attempts"].get(sym, 0)) + 1
                logger.warning("Opciones de %s fallaron (intento %s): %s",
                               sym, st["attempts"][sym], exc)
        repository.set_state(self.STATE_KEY, json.dumps(st))
        return saved

    def _save_raw(self, day: str, symbol: str, payload: dict) -> None:
        folder = self._raw_dir() / day
        folder.mkdir(parents=True, exist_ok=True)
        with gzip.open(folder / f"{symbol}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))

    def raw_size_mb(self) -> float:
        return raw_size_mb(self.settings)


def raw_dir(settings) -> Path:
    return Path(settings.sqlite_path).parent / "options_raw"


def raw_size_mb(settings) -> float:
    """Tamaño de los archivos crudos guardados (MB)."""
    root = raw_dir(settings)
    if not root.exists():
        return 0.0
    return sum(p.stat().st_size for p in root.rglob("*.json.gz")) / 1e6
