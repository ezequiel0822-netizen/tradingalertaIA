"""H-M1 (pre-registro 2026-07-09) — tests del financiamiento CFD en el cost model.

Categoria 'index' harness-only: roundtrip constante + financiamiento por dia de
holding (annual% x bars_held/252), asimetrico por lado (long 5%/1% short central;
7%/2% estres — el estres NO multiplica encima, trae su propio nivel). Las
categorias existentes quedan BIT-A-BIT iguales (bars_held/direction inertes).
"""

from dataclasses import replace

import pytest

from app.backtest.trade_simulator import (
    INDEX_FINANCING_ANNUAL_PCT,
    INDEX_ROUNDTRIP_PCT,
    net_r,
)
from tests.test_score import _settings


def _s():
    # cost model ON con los multiplicadores default de la casa (x1.25 / x1.5)
    return replace(
        _settings(),
        enable_cost_model=True,
        backtest_cost_multiplier=1.25,
        backtest_stress_cost_multiplier=1.5,
    )


# entry 100, sl 98 -> risk_pct = 2.0 (aritmetica facil de verificar a mano)
ENTRY, SL = 100.0, 98.0


def test_index_roundtrip_without_holding():
    # bars_held=0: solo roundtrip 0.08% x1.25 = 0.10% / 2% riesgo = 0.05R
    cost_r, r_net = net_r(1.0, ENTRY, SL, "index", _s())
    assert cost_r == pytest.approx(0.05)
    assert r_net == pytest.approx(0.95)


def test_index_financing_long_half_year():
    # 126 barras D1 = medio anio: financiamiento long central = 5% * 126/252 = 2.5%
    # cost_r = (0.10 + 2.5) / 2 = 1.30R  <- el drag que el demo esconde
    cost_r, _ = net_r(1.0, ENTRY, SL, "index", _s(), bars_held=126, direction="long")
    assert cost_r == pytest.approx(1.30)


def test_index_financing_short_is_cheaper():
    # short central = 1%/anio -> 126 barras = 0.5% -> (0.10+0.5)/2 = 0.30R
    cost_r, _ = net_r(1.0, ENTRY, SL, "index", _s(), bars_held=126, direction="short")
    assert cost_r == pytest.approx(0.30)


def test_index_stress_uses_its_own_level_not_multiplied():
    # estres: roundtrip 0.08x1.5=0.12; financiamiento long 7% * 126/252 = 3.5%
    # cost_r = (0.12 + 3.5)/2 = 1.81R (el 7 NO se multiplica por 1.5)
    cost_r, _ = net_r(1.0, ENTRY, SL, "index", _s(), stress=True,
                      bars_held=126, direction="long")
    assert cost_r == pytest.approx(1.81)


def test_short_holding_long_trade_small_drag():
    # 10 barras long: 5% * 10/252 = 0.1984% -> (0.10+0.1984)/2 = 0.1492R
    cost_r, _ = net_r(0.5, ENTRY, SL, "index", _s(), bars_held=10, direction="long")
    assert cost_r == pytest.approx((0.10 + 5.0 * 10 / 252) / 2.0, abs=1e-6)


def test_existing_categories_unchanged_by_new_params():
    # forex/gold/stock: bars_held/direction INERTES -> mismo resultado que antes.
    s = _s()
    for cat in ("forex", "gold", "stock", "memecoin"):
        old = net_r(1.0, ENTRY, SL, cat, s)
        new = net_r(1.0, ENTRY, SL, cat, s, bars_held=500, direction="short")
        assert old == new, f"categoria {cat} cambio con bars_held (prohibido)"


def test_financing_table_matches_preregistration():
    # Los numeros congelados del pre-registro H-M1 (no tocar sin re-registro).
    assert INDEX_FINANCING_ANNUAL_PCT[False] == {"long": 5.0, "short": 1.0}
    assert INDEX_FINANCING_ANNUAL_PCT[True] == {"long": 7.0, "short": 2.0}
    assert INDEX_ROUNDTRIP_PCT == 0.08
