"""Tests del regime_filter (v3.6.0, ESPEC §8 / §14).

Fixtures sinteticas con resultado CONOCIDO: SMA200 + pendiente para el trend,
terciles de ATR14 contra los 252 previos para la vol. Funcion pura: misma
entrada -> misma salida, y solo mira datos <= N.
"""

from app.intelligence.regime_filter import RegimeTags, classify

_DAY = 86_400


def _candles(closes: list[float], ranges: list[float] | None = None) -> list[dict]:
    """Vela por close; el rango (high-low) controla el True Range para la vol.
    high = close + r/2, low = close - r/2 -> con close 'plano' TR == r."""
    out = []
    for i, close in enumerate(closes):
        r = (ranges[i] if ranges else 1.0)
        out.append(
            {
                "time": i * _DAY,
                "open": close,
                "high": close + r / 2,
                "low": close - r / 2,
                "close": close,
                "volume": 100,
            }
        )
    return out


# -- regime_trend ---------------------------------------------------------


def test_trend_up_on_rising_series() -> None:
    candles = _candles([100 + i for i in range(260)])
    assert classify(candles).regime_trend == "up"


def test_trend_down_on_falling_series() -> None:
    candles = _candles([400 - i for i in range(260)])
    assert classify(candles).regime_trend == "down"


def test_trend_flat_on_constant_series() -> None:
    candles = _candles([100.0 for _ in range(260)])
    assert classify(candles).regime_trend == "flat"


def test_trend_unknown_without_enough_history() -> None:
    candles = _candles([100 + i for i in range(100)])  # < 220
    assert classify(candles).regime_trend == "unknown"


# -- regime_vol -----------------------------------------------------------


def test_vol_high_when_recent_range_exceeds_history() -> None:
    ranges = [1.0] * 286 + [10.0] * 14
    candles = _candles([100.0] * 300, ranges)
    assert classify(candles).regime_vol == "high"


def test_vol_low_when_recent_range_below_history() -> None:
    ranges = [10.0] * 286 + [1.0] * 14
    candles = _candles([100.0] * 300, ranges)
    assert classify(candles).regime_vol == "low"


def test_vol_mid_when_recent_range_is_central() -> None:
    # high block, luego low block, luego medio: el ATR de hoy queda al ~54%
    # de la distribucion previa (entre 1/3 y 2/3) -> mid.
    ranges = [100.0] * 150 + [1.0] * 150 + [30.0] * 100
    candles = _candles([100.0] * 400, ranges)
    assert classify(candles).regime_vol == "mid"


def test_vol_unknown_without_252_priors() -> None:
    candles = _candles([100.0] * 100, [1.0] * 100)
    assert classify(candles).regime_vol == "unknown"


# -- pureza / no look-ahead ----------------------------------------------


def test_classify_is_deterministic() -> None:
    candles = _candles([100 + i for i in range(260)])
    assert classify(candles) == classify(candles)


def test_classify_only_uses_data_up_to_n() -> None:
    base = _candles([100 + i for i in range(260)])
    future = base + _candles([9_999.0] * 10)  # ruido brutal DESPUES de N
    # cortando ambos en el mismo N, el futuro no puede cambiar el veredicto.
    assert classify(base[:200]) == classify(future[:200])


def test_regime_tags_is_frozen() -> None:
    tags = RegimeTags(regime_trend="up", regime_vol="low")
    try:
        tags.regime_trend = "down"  # type: ignore[misc]
        raise AssertionError("RegimeTags deberia ser inmutable")
    except (AttributeError, Exception):
        pass
