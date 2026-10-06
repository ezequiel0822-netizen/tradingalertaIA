"""v3.13.0 — arranque en caliente (OPCIONAL) del agente IA con la experiencia del bot.

Alimenta el modelo del agente con los paper trades forex/gold YA CERRADOS (sin
artifacts), como si los hubiera visto practicando. Sin esto, el agente arranca sin
experiencia y explora más (ejecuta ~la mitad de los candidatos al principio). Con
esto, arranca sabiendo lo que el bot ya midió (hoy: breakout y mean_reversion con R
negativo) y ejecuta menos.

v3.14.0 — `--version 2`: modelo v2 (24 features) con las features calculadas AS-OF
la apertura de cada trade (calendario, COT con lag de 4 días, racha de la estrategia
con trades cerrados ANTES, régimen/VWAP D1 con velas de días anteriores). Con
`--mt5-d1` lee las velas D1 de MT5 en solo lectura (`initialize()` sin credenciales);
si no, usa el cache D1 de la DB (con el mismo guard de frescura de 10 días del bot).

No envía órdenes ni toca el ciclo vivo. Solo escribe el estado del modelo en
`bot_state` si se pasa --apply (sin --apply, solo muestra qué aprendería).
No lee el .env: usa la DB por ruta. Correrlo con el bot APAGADO.

  python scripts/ai_agent_warmstart.py                              # vista previa v1
  python scripts/ai_agent_warmstart.py --version 2 --mt5-d1         # vista previa v2
  python scripts/ai_agent_warmstart.py --version 2 --mt5-d1 --apply # guarda el modelo v2
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai_agent.agent import MODEL_STATE_KEYS  # noqa: E402
from app.ai_agent.features import (  # noqa: E402
    DIM,
    EVENT_WINDOW_MIN,
    FEATURE_NAMES,
    FEATURE_NAMES_V2,
    build_features,
    build_features_v2,
    cot_index_signed,
    cot_market_for,
    event_proximity,
    feature_names_for,
    parse_utc,
    recent_strategy_r,
)
from app.ai_agent.model import LinearThompson  # noqa: E402
from app.database.repository import Repository  # noqa: E402
from app.learning.trade_outcomes import is_artifact, r_multiple  # noqa: E402

D1_MAX_AGE_DAYS = 10     # = guard de frescura de jobs._d1_candles_for_regime


def _mt5_symbol(symbol: str) -> str:
    s = str(symbol or "").upper()
    if s in {"GC=F", "XAUUSD=X"}:
        return "XAUUSD"
    return s.replace("=X", "")


def load_d1(repo: Repository, symbols: set[str], use_mt5: bool) -> dict[str, list[dict]]:
    """Velas D1 por símbolo MT5: de MT5 (solo lectura) si se pide y responde; si no,
    del cache de la DB."""
    out: dict[str, list[dict]] = {}
    mt5 = None
    if use_mt5:
        try:
            import MetaTrader5 as mt5  # type: ignore[import-not-found]

            if not mt5.initialize():          # SIN credenciales: se engancha a la terminal
                print(f"MT5 no inicializó ({mt5.last_error()}); uso el cache D1")
                mt5 = None
        except Exception as exc:  # pragma: no cover - depende de la máquina
            print(f"MT5 no disponible ({type(exc).__name__}); uso el cache D1")
            mt5 = None
    try:
        for sym in sorted(symbols):
            bars: list[dict] = []
            if mt5 is not None:
                try:
                    mt5.symbol_select(sym, True)
                    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 2000)
                    bars = [{"time": int(r["time"]), "open": float(r["open"]),
                             "high": float(r["high"]), "low": float(r["low"]),
                             "close": float(r["close"]), "volume": float(r["tick_volume"])}
                            for r in (rates if rates is not None else [])]
                except Exception:
                    bars = []
            if not bars:
                bars = repo.fetch_mt5_cache_window(sym, 1440, 0, 9_999_999_999)
            out[sym] = sorted(bars, key=lambda c: int(c["time"]))
    finally:
        if mt5 is not None:
            mt5.shutdown()                    # cierra SOLO la conexión de este proceso
    return out


def d1_context(bars: list[dict], opened: datetime) -> tuple[str | None, float | None]:
    """Régimen y VWAP semanal con las velas D1 de días ANTERIORES a la apertura."""
    from app.indicators.vwap import weekly_vwap
    from app.intelligence.regime_filter import SMA_TREND_PERIOD, TREND_SLOPE_LOOKBACK, classify

    day0 = int(datetime(opened.year, opened.month, opened.day, tzinfo=timezone.utc).timestamp())
    prior = [c for c in bars if int(c["time"]) < day0][-400:]
    if not prior or (day0 - int(prior[-1]["time"])) > D1_MAX_AGE_DAYS * 86400:
        return None, None
    regime = None
    if len(prior) >= SMA_TREND_PERIOD + TREND_SLOPE_LOOKBACK:
        regime = classify(prior).regime_trend
    vwap = None
    reading = weekly_vwap(prior)
    if reading.distance_pct is not None and reading.bars_used >= 2:
        vwap = float(reading.distance_pct)
    return regime, vwap


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=ROOT / "trading_data" / "trading_alert_ai.db")
    ap.add_argument("--version", type=int, choices=(1, 2), default=1, help="= AI_AGENT_VERSION")
    ap.add_argument("--prior-var", type=float, default=0.25, help="= AI_AGENT_PRIOR_VAR")
    ap.add_argument("--noise-var", type=float, default=1.0, help="= AI_AGENT_NOISE_VAR")
    ap.add_argument("--mt5-d1", action="store_true",
                    help="v2: velas D1 de MT5 en solo lectura (si no, cache de la DB)")
    ap.add_argument("--apply", action="store_true", help="guardar el modelo en bot_state")
    ap.add_argument("--force", action="store_true", help="pisar un modelo que ya aprendió")
    args = ap.parse_args()

    repo = Repository(args.db)
    names = feature_names_for(args.version)
    key = MODEL_STATE_KEYS[args.version]
    current = LinearThompson.from_json(repo.get_state(key), names,
                                       args.prior_var, args.noise_var)
    if current.n and args.apply and not args.force:
        print(f"El agente v{args.version} ya aprendió de {current.n} trades. "
              "Usá --force para reemplazarlo.")
        return 1

    trades = sorted(repo.fetch_paper_trades(limit=100000), key=lambda r: int(r["id"]))
    fxg = [t for t in trades if str(t.get("category") or "").lower() in {"forex", "gold"}]
    closed_all = [t for t in fxg if str(t.get("status") or "") != "open" and t.get("closed_at")]

    d1: dict[str, list[dict]] = {}
    cot: dict[str, list[dict]] = {}
    if args.version == 2:
        d1 = load_d1(repo, {_mt5_symbol(t.get("symbol")) for t in fxg}, args.mt5_d1)
        for mk in {m[0] for m in (cot_market_for(t.get("symbol")) for t in fxg) if m}:
            cot[mk] = repo.fetch_cot_history(mk, limit=5000)

    model = LinearThompson(feature_names=names, prior_var=args.prior_var,
                           noise_var=args.noise_var)
    used = skipped = with_regime = with_event = 0
    seen: list[tuple[str, list[float]]] = []
    for t in fxg:
        if str(t.get("status") or "") == "open" or is_artifact(t):
            continue
        r = r_multiple(t)
        if r is None:
            skipped += 1
            continue
        if args.version == 1:
            x = build_features(t)   # sin régimen D1 histórico -> 0 (como v3.13.0)
        else:
            opened = parse_utc(t.get("opened_at"))
            if opened is None:
                skipped += 1
                continue
            regime, vwap = d1_context(d1.get(_mt5_symbol(t.get("symbol")), []), opened)
            from app.intelligence.calendar_filter import currencies_for_symbol

            win = timedelta(minutes=EVENT_WINDOW_MIN)
            events = repo.fetch_economic_events_window(
                (opened - win).isoformat(), (opened + win).isoformat(),
                countries=sorted(currencies_for_symbol(str(t.get("symbol") or ""))),
                impact="high")
            mk = cot_market_for(t.get("symbol"))
            extras = {
                "event_near": event_proximity(opened, events),
                "cot_signed": cot_index_signed(str(t.get("symbol")), str(t.get("direction")),
                                               opened, cot.get(mk[0], [])) if mk else 0.0,
                "strat_recent_r": recent_strategy_r(str(t.get("strategy_name") or ""),
                                                    opened, closed_all),
            }
            x = build_features_v2(t, regime, vwap, extras)
            with_regime += regime is not None
            with_event += extras["event_near"] > 0
        model.update(x, r)
        seen.append((str(t.get("strategy_name") or ""), x))
        used += 1

    print(f"Agente v{args.version}: trades forex/gold cerrados usados: {used} "
          f"(sin R utilizable: {skipped})")
    if args.version == 2:
        print(f"  con régimen D1 as-of: {with_regime} | con evento high a ±2 h: {with_event}")
    print("Lo que el agente creería (R esperado en el contexto MEDIO de cada estrategia):")
    for name in ("forex_session_breakout", "mean_reversion", "momentum"):
        xs = [x for n, x in seen if n == name]
        if not xs:
            continue
        avg = [sum(col) / len(xs) for col in zip(*xs)]
        mu, sd = model.predict(avg)
        print(f"  {name:23} {mu:+.2f}R ± {sd:.2f}  (n={len(xs)})")
    if seen:
        thr = 0.05
        explo = sum(1 for _, x in seen if model.predict(x)[0] > thr)
        print(f"Dentro de muestra (optimista): en estos {len(seen)} trades el modelo "
              f"explotaría {explo} ({explo / len(seen):.0%}) con media > {thr}R")
    if args.version == 2:
        coef = model.mean()
        print("Pesos aprendidos de las features nuevas (R por unidad):")
        for i, n in enumerate(FEATURE_NAMES_V2):
            if i >= DIM:
                print(f"  {n:15} {coef[i]:+.3f}")
    if args.apply:
        repo.set_state(key, model.to_json())
        print(f"Modelo v{args.version} guardado en bot_state['{key}'] ({model.n} observaciones).")
    else:
        print("Vista previa: no se guardó nada (usá --apply).")
    assert FEATURE_NAMES == names[:DIM]
    return 0


if __name__ == "__main__":
    sys.exit(main())
