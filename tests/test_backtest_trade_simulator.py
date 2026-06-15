"""Tests del trade_simulator (v3.6.0, ESPEC §6 / §14).

Numeros DORADOS calculados a mano sobre fixtures sinteticas. Long y short POR
SEPARADO (referencia: el bug de shorts corregido en v2.7.0): geometria SL/TP por
direccion, B3 (empate -> SL), B4 (gap_sl al open; TP con gap -> fill en TP exacto),
B5 (trailing solo al close, tighten-only), B6 (time exit), B9 (slippage), B8 (costos).

Base long:  entry=100, sl=98,  tp=104  -> risk=2, TP=+2R
Base short: entry=100, sl=102, tp=96   -> risk=2, TP=+2R
"""

import pytest

from app.backtest.trade_simulator import TradeSetup, net_r, simulate_trade
from tests.test_score import _settings

_DAY = 86_400


def _c(o: float, h: float, l: float, c: float, i: int = 0) -> dict:
    return {"open": o, "high": h, "low": l, "close": c, "time": i * _DAY}


def _long(tp: float | None = 104.0, k: int = 99) -> TradeSetup:
    return TradeSetup("long", 0, 100.0, 98.0, tp, k)


def _short(tp: float | None = 96.0, k: int = 99) -> TradeSetup:
    return TradeSetup("short", 0, 100.0, 102.0, tp, k)


# == LONG =================================================================


def test_long_take_profit() -> None:
    fwd = [_c(100, 101, 99.5, 100, 0), _c(100, 104.5, 100, 104, 1)]
    res = simulate_trade(_long(), fwd)
    assert res.exit_reason == "tp"
    assert res.exit_price == 104.0
    assert res.r_gross == pytest.approx(2.0)
    assert res.bars_held == 1
    assert res.mfe_r == pytest.approx(2.0)
    assert res.mae_r == pytest.approx(0.25)


def test_long_stop_loss() -> None:
    fwd = [_c(100, 100.5, 99.6, 100, 0), _c(100, 100.5, 97, 98, 1)]
    res = simulate_trade(_long(), fwd)
    assert res.exit_reason == "sl"
    assert res.exit_price == 98.0
    assert res.r_gross == pytest.approx(-1.0)
    assert res.bars_held == 1


def test_long_b3_tie_sl_wins_and_mfe_not_credited() -> None:
    # La barra toca SL (98) y TP (104) a la vez -> gana el SL (B3). Y el high 104
    # NO se acredita a la MFE (pesimismo: asumimos que el favorable vino despues).
    fwd = [_c(100, 100.5, 99.6, 100, 0), _c(100, 104, 98, 101, 1)]
    res = simulate_trade(_long(), fwd)
    assert res.exit_reason == "sl"
    assert res.exit_price == 98.0
    assert res.r_gross == pytest.approx(-1.0)
    assert res.mfe_r == pytest.approx(0.25)  # solo el high 100.5 de la barra 0


def test_long_gap_sl() -> None:
    # El open salta MAS ALLA del SL -> fill al open real (peor que el SL), gap_sl.
    fwd = [_c(100, 100.5, 99.6, 100, 0), _c(96, 97, 95, 95.5, 1)]
    res = simulate_trade(_long(), fwd)
    assert res.exit_reason == "gap_sl"
    assert res.exit_price == 96.0
    assert res.r_gross == pytest.approx(-2.0)


def test_long_gap_sl_with_slippage() -> None:
    fwd = [_c(100, 100.5, 99.6, 100, 0), _c(96, 97, 95, 95.5, 1)]
    res = simulate_trade(_long(), fwd, sl_slippage_price=0.5)
    assert res.exit_reason == "gap_sl"
    assert res.exit_price == 95.5
    assert res.r_gross == pytest.approx(-2.25)


def test_long_favorable_gap_caps_at_tp() -> None:
    # El open salta MAS ALLA del TP a favor -> fill al PRECIO del TP, el extra NO
    # se acredita (B4).
    fwd = [_c(100, 100.5, 99.6, 100, 0), _c(106, 107, 105, 106, 1)]
    res = simulate_trade(_long(), fwd)
    assert res.exit_reason == "tp"
    assert res.exit_price == 104.0
    assert res.r_gross == pytest.approx(2.0)


def test_long_sl_slippage() -> None:
    fwd = [_c(100, 100.5, 99.6, 100, 0), _c(100, 100.5, 97, 98, 1)]
    res = simulate_trade(_long(), fwd, sl_slippage_price=0.5)
    assert res.exit_reason == "sl"
    assert res.exit_price == 97.5
    assert res.r_gross == pytest.approx(-1.25)


def test_long_time_exit_at_open_of_bar_k() -> None:
    fwd = [
        _c(100, 100.5, 99.6, 100, 0),
        _c(100, 100.8, 99.7, 100.2, 1),
        _c(101, 101.5, 100.5, 101, 2),  # idx==K==2 -> time exit al OPEN (101)
    ]
    res = simulate_trade(_long(k=2), fwd)
    assert res.exit_reason == "time"
    assert res.exit_price == 101.0
    assert res.r_gross == pytest.approx(0.5)
    assert res.bars_held == 2


def test_long_trailing_exit_is_close_evaluated_and_tightens() -> None:
    # trail al close-1; arma en la barra 0 (stop 98 -> 100) y la barra 1 lo toca.
    fwd = [_c(100, 101, 99.5, 101, 0), _c(100.5, 100.8, 99.5, 100.6, 1)]
    res = simulate_trade(_long(tp=None), fwd,
                         trail_fn=lambda i, candle, stop: candle["close"] - 1.0)
    assert res.exit_reason == "trail"
    assert res.exit_price == 100.0
    assert res.r_gross == pytest.approx(0.0)
    assert res.trailed is True


def test_long_trailing_is_tighten_only() -> None:
    # Propone 99 (sube de 98) y luego 90 (IGNORADO por ser mas flojo). Si el
    # tighten-only fallara, la barra 2 (low 98.5) no saldria.
    proposals = {0: 99.0, 1: 90.0}
    fwd = [
        _c(100, 101, 99.5, 100, 0),
        _c(100, 101, 99.2, 100, 1),
        _c(100, 101, 98.5, 100, 2),
    ]
    res = simulate_trade(_long(tp=None), fwd,
                         trail_fn=lambda i, candle, stop: proposals.get(i))
    assert res.exit_reason == "trail"
    assert res.exit_price == 99.0
    assert res.r_gross == pytest.approx(-0.5)
    assert res.bars_held == 2


def test_long_data_exhaustion_forces_time_exit() -> None:
    fwd = [_c(100, 100.5, 99.6, 100, 0), _c(100, 100.6, 99.7, 100.3, 1)]
    res = simulate_trade(_long(), fwd)
    assert res.exit_reason == "time"
    assert res.exit_price == 100.3
    assert res.r_gross == pytest.approx(0.15)
    assert res.bars_held == 1


# == SHORT (geometria invertida, B7) =====================================


def test_short_stop_loss() -> None:
    fwd = [_c(100, 100.4, 99.5, 100, 0), _c(100, 103, 99.8, 102, 1)]
    res = simulate_trade(_short(), fwd)
    assert res.exit_reason == "sl"
    assert res.exit_price == 102.0
    assert res.r_gross == pytest.approx(-1.0)


def test_short_take_profit() -> None:
    fwd = [_c(100, 100.4, 99.5, 100, 0), _c(100, 100.2, 95.5, 96, 1)]
    res = simulate_trade(_short(), fwd)
    assert res.exit_reason == "tp"
    assert res.exit_price == 96.0
    assert res.r_gross == pytest.approx(2.0)


def test_short_b3_tie_sl_wins() -> None:
    fwd = [_c(100, 100.4, 99.5, 100, 0), _c(100, 103, 95, 98, 1)]
    res = simulate_trade(_short(), fwd)
    assert res.exit_reason == "sl"
    assert res.exit_price == 102.0
    assert res.r_gross == pytest.approx(-1.0)


def test_short_gap_sl() -> None:
    fwd = [_c(100, 100.4, 99.5, 100, 0), _c(104, 105, 103, 104, 1)]
    res = simulate_trade(_short(), fwd)
    assert res.exit_reason == "gap_sl"
    assert res.exit_price == 104.0
    assert res.r_gross == pytest.approx(-2.0)


def test_short_sl_slippage() -> None:
    fwd = [_c(100, 100.4, 99.5, 100, 0), _c(100, 103, 99.8, 102, 1)]
    res = simulate_trade(_short(), fwd, sl_slippage_price=0.5)
    assert res.exit_reason == "sl"
    assert res.exit_price == 102.5
    assert res.r_gross == pytest.approx(-1.25)


def test_short_favorable_gap_caps_at_tp() -> None:
    fwd = [_c(100, 100.4, 99.5, 100, 0), _c(95, 95.5, 94, 94.5, 1)]
    res = simulate_trade(_short(), fwd)
    assert res.exit_reason == "tp"
    assert res.exit_price == 96.0
    assert res.r_gross == pytest.approx(2.0)


# == guardas / determinismo / costos =====================================


def test_invalid_geometry_raises() -> None:
    fwd = [_c(100, 101, 99, 100, 0)]
    bad_setups = [
        TradeSetup("long", 0, 100.0, 101.0, 104.0, 99),   # sl arriba del entry
        TradeSetup("short", 0, 100.0, 99.0, 96.0, 99),    # sl abajo del entry
        TradeSetup("long", 0, 100.0, 100.0, 104.0, 99),   # risk 0
        TradeSetup("diagonal", 0, 100.0, 98.0, 104.0, 99),  # direccion invalida
    ]
    for setup in bad_setups:
        with pytest.raises(ValueError):
            simulate_trade(setup, fwd)


def test_empty_candles_raises() -> None:
    with pytest.raises(ValueError):
        simulate_trade(_long(), [])


def test_determinism_same_input_same_output() -> None:
    fwd = [_c(100, 100.5, 99.6, 100, 0), _c(100, 100.5, 97, 98, 1)]
    assert simulate_trade(_long(), fwd) == simulate_trade(_long(), fwd)


def test_net_r_applies_real_cost_map() -> None:
    s = _settings()  # forex 0.02% round-trip, mult 1.25, stress 1.5
    # cost_r = 0.02*1.25 / risk_pct(=2.0) = 0.0125
    cost_r, r_net = net_r(2.0, 100.0, 98.0, "forex", s)
    assert cost_r == pytest.approx(0.0125)
    assert r_net == pytest.approx(1.9875)
    # stress ×1.5 -> 0.03 / 2.0 = 0.015
    cost_r_s, r_net_s = net_r(2.0, 100.0, 98.0, "forex", s, stress=True)
    assert cost_r_s == pytest.approx(0.015)
    assert r_net_s == pytest.approx(1.985)
    # categoria sin costo conocido -> 0
    cost_r_u, r_net_u = net_r(2.0, 100.0, 98.0, "desconocida", s)
    assert cost_r_u == 0.0
    assert r_net_u == pytest.approx(2.0)


# == salida confirmada al close (Donchian §9, close_exit_fn) ==============


def test_close_exit_signals_and_exits_at_next_open() -> None:
    # close_exit_fn dispara en idx 1 -> ejecucion al OPEN de idx 2 (reason trail).
    fwd = [
        _c(100, 100.5, 99.6, 100, 0),
        _c(100, 100.8, 99.7, 100.2, 1),  # señal al close de esta barra
        _c(101, 101.5, 100.5, 101, 2),   # ejecuta al open (101)
    ]
    res = simulate_trade(_long(tp=None), fwd, close_exit_fn=lambda i, c: i == 1)
    assert res.exit_reason == "trail"
    assert res.exit_price == 101.0
    assert res.r_gross == pytest.approx(0.5)
    assert res.bars_held == 2


def test_hard_sl_gap_beats_pending_close_exit() -> None:
    # Señal Donchian en idx 1, pero idx 2 gapea BAJO el SL duro -> gana gap_sl
    # (el SL duro es lo unico intrabar y un gap a traves es peor).
    fwd = [
        _c(100, 100.5, 99.6, 100, 0),
        _c(100, 100.8, 99.7, 100.2, 1),
        _c(96, 97, 95, 95.5, 2),
    ]
    res = simulate_trade(_long(tp=None), fwd, close_exit_fn=lambda i, c: i == 1)
    assert res.exit_reason == "gap_sl"
    assert res.exit_price == 96.0
    assert res.r_gross == pytest.approx(-2.0)


def test_close_exit_fn_does_not_shadow_hard_sl() -> None:
    # Con close_exit_fn presente pero sin disparar, el SL duro intrabar sigue mandando.
    fwd = [_c(100, 100.5, 99.6, 100, 0), _c(100, 100.5, 97, 98, 1)]
    res = simulate_trade(_long(tp=None), fwd, close_exit_fn=lambda i, c: False)
    assert res.exit_reason == "sl"
    assert res.r_gross == pytest.approx(-1.0)
