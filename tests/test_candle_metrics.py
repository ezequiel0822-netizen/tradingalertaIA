"""Tests de app/indicators/candles.py (v3.12.0, footprint lite).

Velas construidas a mano con aritmetica verificable. Cubre anatomia (body/wick/
clv), fuerza normalizada por ATR, secuencias 1-3 velas con escala ATR, anomalia
de volumen y None-safety integral.
"""

from app.indicators.candles import (
    CandleAnatomy,
    atr_absolute,
    candle_anatomy,
    candle_strength,
    detect_sequences,
    footprint_features,
    volume_anomaly,
)


def _c(o, h, low, c, v=1000.0):
    return {"open": o, "high": h, "low": low, "close": c, "volume": v}


def _base(n=20, price=100.0, rng=1.0):
    """n velas neutras (rango `rng`) para dar contexto de ATR estable."""
    half = rng / 2
    return [_c(price, price + half, price - half, price + 0.1) for _ in range(n)]


# --- anatomia -----------------------------------------------------------------


def test_anatomy_hand_math():
    # open 100, high 110, low 98, close 108: rango 12, cuerpo 8 (0.6667),
    # upper wick 2 (0.1667), lower wick 2 (0.1667), clv (108-98)/12 = 0.8333.
    a = candle_anatomy(_c(100, 110, 98, 108))
    assert a.direction == "bull"
    assert abs(a.body_ratio - 8 / 12) < 1e-4
    assert abs(a.upper_wick_ratio - 2 / 12) < 1e-4
    assert abs(a.lower_wick_ratio - 2 / 12) < 1e-4
    assert abs(a.clv - 10 / 12) < 1e-4


def test_anatomy_doji_and_flat():
    assert candle_anatomy(_c(100, 101, 99, 100.05)).direction == "doji"  # cuerpo 2.5%
    flat = candle_anatomy(_c(100, 100, 100, 100))
    assert flat.direction == "doji" and flat.clv == 0.5


def test_anatomy_invalid_returns_none():
    assert candle_anatomy({"open": None, "high": 1, "low": 0, "close": 1}) is None
    assert candle_anatomy({}) is None


# --- fuerza -------------------------------------------------------------------


def test_strong_bull_requires_atr_scale():
    # Contexto: ATR ~1. Ultima vela: cuerpo 2.4 (2.4xATR), clv alto -> strong_bull.
    candles = _base() + [_c(100, 102.5, 100, 102.4)]
    assert candle_strength(candles) == "strong_bull"


def test_small_body_is_not_strong():
    # Vela alcista pero de rango ~igual al ATR y cuerpo mediano -> bull, no strong.
    candles = _base() + [_c(100, 100.9, 100.1, 100.75)]
    assert candle_strength(candles) == "bull"


def test_strong_bear_symmetry():
    candles = _base() + [_c(102.4, 102.4, 100, 100.1)]
    assert candle_strength(candles) == "strong_bear"


def test_empty_and_doji_neutral():
    assert candle_strength([]) == "neutral"
    assert candle_strength(_base() + [_c(100, 101, 99, 100.02)]) == "neutral"


# --- secuencias ---------------------------------------------------------------


def test_engulfing_bull():
    candles = _base() + [_c(101, 101.5, 99.8, 100), _c(99.9, 102.2, 99.9, 102)]
    assert "engulfing_bull" in detect_sequences(candles)


def test_engulfing_bear():
    candles = _base() + [_c(100, 102.2, 99.9, 102), _c(102.1, 102.2, 99.5, 99.8)]
    assert "engulfing_bear" in detect_sequences(candles)


def test_inside_bar():
    candles = _base() + [_c(100, 103, 97, 102), _c(101, 102, 99, 100)]
    assert "inside_bar" in detect_sequences(candles)


def test_hammer_needs_atr_scale():
    # Martillo real: mecha inferior larga, cierre arriba, rango >= 0.8xATR.
    candles = _base() + [_c(100.8, 101, 99.5, 100.95)]
    assert "hammer" in detect_sequences(candles)
    # El mismo shape en miniatura (rango 0.15 << ATR ~1) NO califica.
    tiny = _base() + [_c(100.08, 100.10, 99.95, 100.095)]
    assert "hammer" not in detect_sequences(tiny)


def test_shooting_star():
    candles = _base() + [_c(100.05, 101.5, 99.95, 100.1)]
    assert "shooting_star" in detect_sequences(candles)


def test_three_soldiers_and_crows():
    up = _base() + [
        _c(100, 100.8, 99.9, 100.7),
        _c(100.7, 101.5, 100.6, 101.4),
        _c(101.4, 102.2, 101.3, 102.1),
    ]
    assert "three_soldiers" in detect_sequences(up)
    down = _base() + [
        _c(102.1, 102.2, 101.3, 101.4),
        _c(101.4, 101.5, 100.6, 100.7),
        _c(100.7, 100.8, 99.9, 100.0),
    ]
    assert "three_crows" in detect_sequences(down)


def test_sequences_need_two_candles():
    assert detect_sequences([_c(100, 101, 99, 100.5)]) == []
    assert detect_sequences([]) == []


# --- volumen ------------------------------------------------------------------


def test_volume_anomaly_hand_math():
    candles = _base(20) + [_c(100, 101, 99, 100.5, v=3000.0)]
    # promedio previo 1000, actual 3000 -> 3.0x
    assert volume_anomaly(candles) == 3.0


def test_volume_anomaly_none_without_volume():
    candles = [_c(100, 101, 99, 100.5, v=0.0) for _ in range(25)]
    assert volume_anomaly(candles) is None
    assert volume_anomaly(_base(5)) is None  # data insuficiente


# --- contrato features --------------------------------------------------------


def test_footprint_features_contract():
    candles = _base() + [_c(100, 102.5, 100, 102.4, v=5000.0)]
    feats = footprint_features(candles)
    assert feats["candle_strength"] == "strong_bull"
    assert feats["candle_direction"] == "bull"
    assert feats["candle_clv"] is not None
    assert isinstance(feats["candle_patterns"], str)
    assert feats["volume_anomaly"] == 5.0


def test_footprint_features_empty_safe():
    feats = footprint_features([])
    assert feats["candle_strength"] == "neutral"
    assert feats["candle_clv"] is None
    assert feats["candle_patterns"] == ""


def test_atr_absolute_basic():
    assert atr_absolute(_base(20)) is not None
    assert atr_absolute(_base(5)) is None  # <= period


def test_anatomy_dataclass():
    a = CandleAnatomy("bull", 0.5, 0.2, 0.3, 0.7, 1.1)
    assert a.direction == "bull"


def test_analyze_ohlcv_populates_footprint():
    from app.analyzers.technical_patterns import analyze_ohlcv

    candles = [dict(c, timestamp=1_700_000_000 + i * 900)
               for i, c in enumerate(_base(25) + [_c(100, 102.5, 100, 102.4)])]
    pattern = analyze_ohlcv(candles)
    assert pattern.candle_strength == "strong_bull"
    assert pattern.candle_clv is not None
    assert isinstance(pattern.candle_patterns, str)
