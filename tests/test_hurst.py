"""Tests de app/indicators/hurst.py (v3.12.0).

Series canonicas: tendencia pura -> H~1 (persistent); alternancia con ruido ->
H bajo (antipersistent); random walk seeded -> H~0.5 (random). Honestidad: data
insuficiente/degenerada -> None, jamas un H inventado.
"""

import random

import pytest

from app.indicators.hurst import (
    MIN_WINDOW,
    HurstReading,
    classify_regime,
    hurst_exponent,
    hurst_features,
)


def _random_walk(n: int, seed: int = 42, sigma: float = 0.01) -> list[float]:
    rng = random.Random(seed)
    price = 100.0
    out = [price]
    for _ in range(n - 1):
        price *= 1.0 + rng.gauss(0.0, sigma)
        out.append(price)
    return out


def _trending(n: int, seed: int = 7) -> list[float]:
    # Drift fuerte + ruido chico: dominancia de tendencia -> H alto.
    rng = random.Random(seed)
    price = 100.0
    out = [price]
    for _ in range(n - 1):
        price *= 1.0 + 0.01 + rng.gauss(0.0, 0.0005)
        out.append(price)
    return out


def _mean_reverting(n: int, seed: int = 11) -> list[float]:
    # Retornos que alternan signo (con ruido): antipersistencia fuerte.
    rng = random.Random(seed)
    price = 100.0
    out = [price]
    sign = 1.0
    for _ in range(n - 1):
        price *= 1.0 + sign * 0.01 + rng.gauss(0.0, 0.001)
        sign = -sign
        out.append(price)
    return out


def test_trending_series_is_persistent():
    reading = hurst_exponent(_trending(300), window=200)
    assert reading.value is not None
    assert reading.value > 0.55
    assert reading.regime == "persistent"


def test_alternating_series_is_antipersistent():
    reading = hurst_exponent(_mean_reverting(300), window=200)
    assert reading.value is not None
    assert reading.value < 0.45
    assert reading.regime == "antipersistent"


def test_random_walk_is_near_half():
    # El estimador de escalado de varianza no tiene el sesgo alcista del R/S:
    # para un random walk H debe caer cerca de 0.5 (banda tolerante por ruido).
    reading = hurst_exponent(_random_walk(600), window=500)
    assert reading.value is not None
    assert 0.35 < reading.value < 0.65


def test_insufficient_data_returns_none():
    reading = hurst_exponent(_random_walk(30), window=100)
    assert reading.value is None
    assert reading.regime == "insufficient_data"
    assert hurst_exponent([], window=100).value is None


def test_min_window_boundary():
    closes = _random_walk(MIN_WINDOW)
    assert hurst_exponent(closes, window=MIN_WINDOW).value is not None
    assert hurst_exponent(closes[:-1], window=MIN_WINDOW).value is None


def test_flat_series_is_degenerate_not_invented():
    # Precios congelados: varianza 0 -> None (no un H=0 "antipersistente" falso).
    reading = hurst_exponent([100.0] * 300, window=200)
    assert reading.value is None
    assert reading.regime == "insufficient_data"


def test_non_positive_closes_filtered():
    closes = _random_walk(300)
    dirty = closes[:150] + [0.0, -5.0] + closes[150:]
    reading = hurst_exponent(dirty, window=200)
    assert reading.value is not None  # los invalidos se filtran, no revientan


def test_clamped_to_unit_interval():
    reading = hurst_exponent(_trending(600), window=500)
    assert 0.0 <= reading.value <= 1.0


def test_classify_regime_thresholds():
    assert classify_regime(0.60) == "persistent"
    assert classify_regime(0.50) == "random"
    assert classify_regime(0.40) == "antipersistent"
    assert classify_regime(None) == "insufficient_data"
    # thresholds configurables
    assert classify_regime(0.52, persistent_threshold=0.51) == "persistent"


def test_hurst_features_contract():
    feats = hurst_features(_random_walk(600))
    assert set(feats) == {
        "hurst_100", "hurst_200", "hurst_500",
        "hurst_best", "hurst_best_window", "hurst_regime",
    }
    # con 600 closes las 3 ventanas estiman y la mejor es la mas larga
    assert feats["hurst_500"] is not None
    assert feats["hurst_best_window"] == 500
    assert feats["hurst_regime"] in {"persistent", "antipersistent", "random"}


def test_hurst_features_prefers_longest_available():
    feats = hurst_features(_random_walk(250))  # alcanza 100 y 200, no 500
    assert feats["hurst_500"] is None
    assert feats["hurst_best_window"] == 200


def test_hurst_features_none_safe_on_short_data():
    feats = hurst_features(_random_walk(20))
    assert feats["hurst_best"] is None
    assert feats["hurst_regime"] == "insufficient_data"


def test_reading_dataclass_defaults():
    r = HurstReading(window=100, value=None, regime="insufficient_data")
    assert r.n_used == 0


def test_analyze_ohlcv_populates_hurst():
    # 120 velas con timestamps: alcanza hurst_100; el pattern lo expone.
    from app.analyzers.technical_patterns import analyze_ohlcv

    closes = _random_walk(120)
    candles = [
        {"timestamp": 1_700_000_000 + i * 900, "open": c, "high": c * 1.001,
         "low": c * 0.999, "close": c, "volume": 100.0}
        for i, c in enumerate(closes)
    ]
    pattern = analyze_ohlcv(candles)
    assert pattern.hurst is not None
    assert pattern.hurst_regime in {"persistent", "antipersistent", "random"}


def test_analyze_ohlcv_hurst_none_on_short_feed():
    from app.analyzers.technical_patterns import analyze_ohlcv

    closes = _random_walk(40)  # >=20 para el pattern, <100 para hurst
    candles = [
        {"timestamp": 1_700_000_000 + i * 900, "open": c, "high": c * 1.001,
         "low": c * 0.999, "close": c, "volume": 100.0}
        for i, c in enumerate(closes)
    ]
    pattern = analyze_ohlcv(candles)
    assert pattern.hurst is None
    assert pattern.hurst_regime == "insufficient_data"
    assert pattern.label  # el resto del analisis sigue vivo
