"""Simulador de la vida de un trade (ESPEC_BACKTEST_REPLAY_v1.md §6, B1-B13).

Recorre las velas FORWARD (desde la barra de entrada N+1 en adelante) y resuelve
la salida con PESIMISMO por diseño (R3):

  B3  empate intrabar (toca SL y TP en la misma barra) -> gana el SL.
  B4  gaps asimetricos: open mas alla del SL -> fill al open real (peor),
      exit_reason=gap_sl; open mas alla del TP a favor -> fill al PRECIO del TP
      (el extra NO se acredita).
  B5  trailing SOLO al close y solo APRIETA (tighten-only, igual que el reconciler).
  B6  time exit a los K bars: señal al close de K-1, ejecucion al OPEN de la barra K.
  B7  TODO direction-aware: para short, SL arriba / TP abajo y geometria invertida.
  B9  slippage de SL: los fills de stop (sl, gap_sl, trail) se empeoran en una
      cantidad de precio adicional (el harness la calcula como SLIPPAGE_ATR*ATR14).
  B10 determinista y offline: funcion pura de sus inputs, sin red ni aleatoriedad.

Mide en R (fraccion del riesgo inicial), el MISMO idioma que la medicion viva:
  risk_price = |entry - sl_initial|
  r_gross(long)  = (exit - entry) / risk_price
  r_gross(short) = (entry - exit) / risk_price

Convencion de mfe/mae (pesimista, coherente con B3): el recorrido adverso de cada
barra SIEMPRE cuenta para la MAE; el recorrido favorable de la barra de salida NO
se acredita a la MFE cuando la salida es por stop (sl/trail/gap_sl) — asumir que
el favorable vino despues de que ya nos sacaron. Los costos (B8) viven aparte en
`net_r`, reusando el cost map REAL de training_engine.
"""

from dataclasses import dataclass
from typing import Callable

from app.config.settings import Settings
from app.learning.training_engine import _cost_map_from_settings

EXIT_SL = "sl"
EXIT_TP = "tp"
EXIT_TRAIL = "trail"
EXIT_TIME = "time"
EXIT_GAP_SL = "gap_sl"

# trail_fn(idx, candle, current_stop) -> stop propuesto | None. El simulador SOLO
# lo llama al close de cada barra y SOLO aprieta el stop (B5).
TrailFn = Callable[[int, dict, float], "float | None"]

# close_exit_fn(idx, candle) -> True si la regla de salida CONFIRMADA AL CLOSE se
# dispara en esta barra. El simulador ejecuta al OPEN de la barra siguiente
# (mismo patron B2/B6 que el time exit), reason 'trail'. Es la salida trailing
# Donchian de trend_following_d1 (§9): close-confirmada, NO intrabar — el SL duro
# sigue siendo lo unico intrabar.
CloseExitFn = Callable[[int, dict], bool]


@dataclass(frozen=True)
class TradeSetup:
    direction: str            # 'long' | 'short'
    entry_utc: int
    entry_price: float        # open de N+1 (B2)
    sl_initial: float
    tp_initial: float | None  # None = sin TP fijo (dejar correr; trend following)
    time_exit_bars: int       # K: exit al open de la barra K si no salio antes (B6)


@dataclass(frozen=True)
class TradeResult:
    exit_utc: int
    exit_price: float
    exit_reason: str          # sl | tp | trail | time | gap_sl
    bars_held: int
    r_gross: float
    mfe_r: float
    mae_r: float
    trailed: bool


def simulate_trade(
    setup: TradeSetup,
    forward_candles: list[dict],
    *,
    sl_slippage_price: float = 0.0,
    trail_fn: TrailFn | None = None,
    close_exit_fn: CloseExitFn | None = None,
) -> TradeResult:
    """Simula el trade completo y devuelve su outcome. `forward_candles[0]` es la
    barra de entrada (N+1); la entrada ya ocurrio a su OPEN (B2)."""
    if not forward_candles:
        raise ValueError("simulate_trade requiere al menos la barra de entrada")
    if setup.direction not in ("long", "short"):
        raise ValueError(f"direction invalida: {setup.direction}")
    is_long = setup.direction == "long"

    entry = float(setup.entry_price)
    sl = float(setup.sl_initial)
    risk = abs(entry - sl)
    if risk <= 0:
        raise ValueError("risk_price (|entry - sl|) debe ser > 0")
    if is_long and sl >= entry:
        raise ValueError("long: sl_initial debe estar por debajo del entry (B7)")
    if (not is_long) and sl <= entry:
        raise ValueError("short: sl_initial debe estar por encima del entry (B7)")

    tp = setup.tp_initial
    if tp is not None:
        tp = float(tp)
        # TP del lado equivocado -> se ignora (queda sin TP), no se inventa nada.
        if (is_long and tp <= entry) or ((not is_long) and tp >= entry):
            tp = None

    slip = float(sl_slippage_price or 0.0)
    current_stop = sl
    trailed = False
    pending_close_exit = False  # salida confirmada al close de la barra previa (B6-like)
    mfe_r = 0.0
    mae_r = 0.0

    def r_of(price: float) -> float:
        return (price - entry) / risk if is_long else (entry - price) / risk

    n = len(forward_candles)
    for idx, candle in enumerate(forward_candles):
        o = float(candle.get("open"))
        h = float(candle.get("high", o))
        l = float(candle.get("low", o))
        t = int(candle.get("time") or 0)
        fav = h if is_long else l
        adv = l if is_long else h

        stop = current_stop
        on_stop_reason = EXIT_TRAIL if trailed else EXIT_SL
        slipped_stop = (stop - slip) if is_long else (stop + slip)

        # -- salidas al OPEN (solo en barras posteriores a la entrada) --------
        if idx > 0:
            gap_through_stop = (o <= stop) if is_long else (o >= stop)
            if gap_through_stop:  # B4: gap MAS ALLA del stop -> fill al open peor
                px = (o - slip) if is_long else (o + slip)
                return _result(t, px, EXIT_GAP_SL, idx, r_of(px),
                               mfe_r, max(mae_r, -r_of(px)), trailed)
            if tp is not None:
                gap_through_tp = (o >= tp) if is_long else (o <= tp)
                if gap_through_tp:  # B4: gap a favor MAS ALLA del TP -> fill en TP
                    return _result(t, tp, EXIT_TP, idx, r_of(tp),
                                   max(mfe_r, r_of(tp)), mae_r, trailed)
            if pending_close_exit:  # salida Donchian (§9): señal al close previo -> open
                return _result(t, o, EXIT_TRAIL, idx, r_of(o),
                               max(mfe_r, r_of(o)), max(mae_r, -r_of(o)), trailed)
            if idx == setup.time_exit_bars:  # B6: time exit al open de la barra K
                return _result(t, o, EXIT_TIME, idx, r_of(o),
                               max(mfe_r, r_of(o)), max(mae_r, -r_of(o)), trailed)

        # -- intrabar: B3 empate -> SL primero --------------------------------
        hits_sl = (l <= stop) if is_long else (h >= stop)
        hits_tp = tp is not None and ((h >= tp) if is_long else (l <= tp))
        if hits_sl:  # pesimista: no acreditamos el favorable de esta barra a la MFE
            px = slipped_stop
            return _result(t, px, on_stop_reason, idx, r_of(px),
                           mfe_r, max(mae_r, -r_of(px)), trailed)
        if hits_tp:
            return _result(t, tp, EXIT_TP, idx, r_of(tp),
                           max(mfe_r, r_of(tp)), max(mae_r, -r_of(adv)), trailed)

        # -- sobrevivio la barra entera: actualiza excursiones ----------------
        mfe_r = max(mfe_r, r_of(fav))
        mae_r = max(mae_r, -r_of(adv))

        # -- B5 trailing: SOLO al close, SOLO aprieta -------------------------
        if trail_fn is not None:
            proposed = trail_fn(idx, candle, current_stop)
            if proposed is not None:
                proposed = float(proposed)
                if is_long and proposed > current_stop:
                    current_stop, trailed = proposed, True
                elif (not is_long) and proposed < current_stop:
                    current_stop, trailed = proposed, True

        # -- salida confirmada al close (Donchian §9) -> ejecuta al open de N+1
        if close_exit_fn is not None and close_exit_fn(idx, candle):
            pending_close_exit = True

    # -- se acabo la data: cierre forzoso al ultimo close (reason time) -------
    last = forward_candles[-1]
    t = int(last.get("time") or 0)
    close = float(last.get("close", last.get("open")))
    return _result(t, close, EXIT_TIME, n - 1, r_of(close),
                   max(mfe_r, r_of(close)), max(mae_r, -r_of(close)), trailed)


def _result(exit_utc, exit_price, reason, bars_held, r_gross, mfe_r, mae_r, trailed):
    return TradeResult(
        exit_utc=exit_utc,
        exit_price=round(exit_price, 8),
        exit_reason=reason,
        bars_held=bars_held,
        r_gross=round(r_gross, 6),
        mfe_r=round(max(mfe_r, 0.0), 6),
        mae_r=round(max(mae_r, 0.0), 6),
        trailed=trailed,
    )


# -- categoria 'index' (H-M1, pre-registro research/HIPOTESIS_2026-07-09_multiasset.md) --
# Roundtrip spread+slippage % para indices CFD (survey MetaQuotes 2026-07-09:
# spreads medianos 1-3 bps + colchon pesimista). Constante harness-only: la
# categoria 'index' NO existe en el ciclo vivo ni en settings.
INDEX_ROUNDTRIP_PCT = 0.08
# Financiamiento CFD anual (% sobre nocional) por LADO y escenario. El demo
# esconde este costo (swaps deshabilitados/irrisorios); numeros del research
# 2026-07-09 con fuentes (benchmark + markup - dividendos). El escenario de
# stress trae su PROPIO nivel: el multiplicador x1.5 NO se aplica encima.
INDEX_FINANCING_ANNUAL_PCT = {
    False: {"long": 5.0, "short": 1.0},  # CENTRAL (decide el §11)
    True: {"long": 7.0, "short": 2.0},   # ESTRES
}


def net_r(
    r_gross: float,
    entry_price: float,
    sl_initial: float,
    category: str,
    settings: Settings,
    *,
    stress: bool = False,
    bars_held: int = 0,
    direction: str = "long",
) -> tuple[float, float]:
    """Aplica costos (B8/§7) y devuelve (cost_r, r_net). Reusa el cost map REAL de
    training_engine para que /expectancy y el backtest hablen el mismo idioma:

        cost_r = (cost_roundtrip_pct[cat] * multiplicador) / risk_pct
        risk_pct = |entry - sl| / entry * 100

    `stress=True` usa BACKTEST_STRESS_COST_MULTIPLIER (×1.5) en vez del ×1.25:
    un edge que no sobrevive costos pesimistas no es edge.

    v3.12 H-M1 — categoria 'index': roundtrip constante (INDEX_ROUNDTRIP_PCT) +
    FINANCIAMIENTO por dia de holding (annual% × bars_held/252; los swaps CFD
    cobran los 7 dias via triple-swap, por eso bars D1 / 252 equivale a
    dias_calendario/365). Para las demas categorias bars_held/direction son
    inertes: comportamiento identico al historico.
    """
    multiplier = float(
        settings.backtest_stress_cost_multiplier
        if stress
        else settings.backtest_cost_multiplier
    )
    if category == "index":
        cost_pct = INDEX_ROUNDTRIP_PCT * multiplier
    else:
        cost_map = _cost_map_from_settings(settings)
        cost_pct = float(cost_map.get(category, 0.0)) * multiplier
    risk_pct = (
        abs(entry_price - sl_initial) / entry_price * 100.0 if entry_price else 0.0
    )
    financing_pct = 0.0
    if category == "index" and bars_held > 0:
        side = "short" if str(direction) == "short" else "long"
        annual = INDEX_FINANCING_ANNUAL_PCT[bool(stress)][side]
        financing_pct = annual * (bars_held / 252.0)
    cost_r = (cost_pct + financing_pct) / risk_pct if risk_pct > 0 else 0.0
    return round(cost_r, 6), round(r_gross - cost_r, 6)
