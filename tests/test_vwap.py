"""Tests de app/indicators/vwap.py (v3.12.0).

Cubre: correccion aritmetica (hlc3, cuadra a mano), reset diario por bar-time
(NO datetime.now — leccion A1/v3.10.0), soft-fail sin volumen (Yahoo forex),
dualidad de claves 'timestamp' (Yahoo) / 'time' (cache MT5 del harness),
anchors week/month, y el contrato de vwap_features.
"""

from datetime import datetime, timezone

import pytest

from app.indicators.vwap import (
    ANCHOR_MONTH,
    ANCHOR_SESSION,
    ANCHOR_WEEK,
    VwapReading,
    anchor_start_epoch,
    anchored_vwap,
    bar_timestamp,
    monthly_vwap,
    session_vwap,
    vwap_features,
    weekly_vwap,
)


def _epoch(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp()


def _candle(ts, high, low, close, volume, key="timestamp"):
    return {key: ts, "open": close, "high": high, "low": low, "close": close, "volume": volume}


# --- correccion aritmetica -------------------------------------------------


def test_session_vwap_matches_hand_calculation():
    # Miercoles 2026-06-17, dos velas de 15m con volumen conocido.
    # hlc3: (102+98+100)/3=100 ; (108+102+106)/3 = 105.333...
    # VWAP = (100*200 + 105.3333*400) / 600 = 103.5555...
    candles = [
        _candle(_epoch(2026, 6, 17, 14, 30), 102, 98, 100, 200),
        _candle(_epoch(2026, 6, 17, 14, 45), 108, 102, 106, 400),
    ]
    reading = session_vwap(candles)
    expected = (100.0 * 200 + (108 + 102 + 106) / 3 * 400) / 600
    assert reading.vwap == pytest.approx(expected)
    assert reading.bars_used == 2
    assert reading.position == "above"  # close 106 > vwap ~103.56
    assert reading.distance_pct == pytest.approx((106 - expected) / expected * 100)


def test_daily_reset_excludes_yesterday():
    # Velas de AYER con precios absurdos: no deben contaminar el VWAP de hoy.
    candles = [
        _candle(_epoch(2026, 6, 16, 15, 0), 1000, 900, 950, 99999),
        _candle(_epoch(2026, 6, 17, 14, 30), 102, 98, 100, 200),
    ]
    reading = session_vwap(candles)
    assert reading.vwap == pytest.approx(100.0)  # solo la vela de hoy (hlc3=100)
    assert reading.bars_used == 1


def test_position_below_when_price_under_vwap():
    candles = [
        _candle(_epoch(2026, 6, 17, 14, 30), 110, 100, 108, 500),
        _candle(_epoch(2026, 6, 17, 14, 45), 104, 96, 98, 100),
    ]
    reading = session_vwap(candles)
    assert reading.position == "below"
    assert reading.distance_pct < 0


# --- soft-fail sin volumen (caso Yahoo forex) --------------------------------


def test_zero_volume_returns_none_not_invented():
    # Yahoo devuelve volumen 0 para forex: el VWAP debe ser None, jamas inventado.
    candles = [
        _candle(_epoch(2026, 6, 17, 14, 30), 1.09, 1.08, 1.085, 0),
        _candle(_epoch(2026, 6, 17, 14, 45), 1.10, 1.09, 1.095, 0),
    ]
    reading = session_vwap(candles)
    assert reading.vwap is None
    assert reading.distance_pct is None
    assert reading.position == "unknown"
    assert reading.bars_used == 2  # las velas existen, el volumen no


def test_zero_volume_bars_weigh_nothing():
    # Una vela sin volumen entre velas con volumen: pesa 0, no distorsiona.
    candles = [
        _candle(_epoch(2026, 6, 17, 14, 30), 102, 98, 100, 300),
        _candle(_epoch(2026, 6, 17, 14, 45), 500, 400, 450, 0),  # sin volumen
    ]
    reading = session_vwap(candles)
    assert reading.vwap == pytest.approx(100.0)
    # distance se mide contra el ULTIMO close (450), aunque esa vela no pese.
    assert reading.position == "above"


def test_empty_and_timestampless_candles():
    assert session_vwap([]).vwap is None
    assert session_vwap([{"close": 100.0, "volume": 10}]).vwap is None
    assert session_vwap([]).position == "unknown"


# --- dualidad timestamp/time (Yahoo vivo vs cache MT5 del harness) ----------


def test_mt5_time_key_supported():
    # El cache MT5 / harness usa 'time' (epoch) y tick_volume como 'volume'.
    candles = [
        _candle(_epoch(2026, 6, 17, 0, 0), 102, 98, 100, 1500, key="time"),
        _candle(_epoch(2026, 6, 17, 1, 0), 108, 102, 106, 500, key="time"),
    ]
    reading = session_vwap(candles)
    assert reading.vwap is not None
    assert reading.bars_used == 2


def test_bar_timestamp_prefers_timestamp_then_time():
    assert bar_timestamp({"timestamp": 100.0, "time": 200.0}) == 100.0
    assert bar_timestamp({"time": 200.0}) == 200.0
    assert bar_timestamp({}) is None
    assert bar_timestamp({"timestamp": "garbage"}) is None


# --- anchors week / month ----------------------------------------------------


def test_anchor_start_epoch_week_is_monday_utc():
    # 2026-06-17 es miercoles; el lunes de esa semana es 2026-06-15.
    assert anchor_start_epoch(_epoch(2026, 6, 17, 15, 0), ANCHOR_WEEK) == _epoch(2026, 6, 15)
    assert anchor_start_epoch(_epoch(2026, 6, 17, 15, 0), ANCHOR_MONTH) == _epoch(2026, 6, 1)
    assert anchor_start_epoch(_epoch(2026, 6, 17, 15, 0), ANCHOR_SESSION) == _epoch(2026, 6, 17)


def test_weekly_vwap_excludes_previous_week():
    candles = [
        _candle(_epoch(2026, 6, 12), 1000, 900, 950, 99999),  # viernes semana pasada
        _candle(_epoch(2026, 6, 15), 102, 98, 100, 200),      # lunes
        _candle(_epoch(2026, 6, 17), 108, 102, 106, 400),     # miercoles (ultima)
    ]
    reading = weekly_vwap(candles)
    expected = (100.0 * 200 + (108 + 102 + 106) / 3 * 400) / 600
    assert reading.vwap == pytest.approx(expected)
    assert reading.bars_used == 2


def test_monthly_vwap_excludes_previous_month():
    candles = [
        _candle(_epoch(2026, 5, 29), 1000, 900, 950, 99999),  # mayo: fuera
        _candle(_epoch(2026, 6, 1), 102, 98, 100, 200),
        _candle(_epoch(2026, 6, 17), 108, 102, 106, 400),
    ]
    reading = monthly_vwap(candles)
    assert reading.bars_used == 2
    assert reading.vwap == pytest.approx(
        (100.0 * 200 + (108 + 102 + 106) / 3 * 400) / 600
    )


def test_invalid_anchor_raises():
    with pytest.raises(ValueError):
        anchored_vwap([_candle(_epoch(2026, 6, 17), 1, 1, 1, 1)], "quarter")
    with pytest.raises(ValueError):
        anchor_start_epoch(_epoch(2026, 6, 17), "quarter")


def test_future_bars_beyond_last_are_ignored():
    # Defensivo: si una vela viniera DESPUES de la ultima (feed desordenado),
    # no debe entrar — el "ahora" es la ULTIMA vela de la lista (bar-time).
    candles = [
        _candle(_epoch(2026, 6, 17, 15, 0), 1000, 900, 950, 99999),  # "futura"
        _candle(_epoch(2026, 6, 17, 14, 30), 102, 98, 100, 200),     # ultima = ahora
    ]
    reading = session_vwap(candles)
    assert reading.vwap == pytest.approx(100.0)
    assert reading.bars_used == 1


# --- contrato de vwap_features ----------------------------------------------


def test_vwap_features_contract_with_volume():
    candles = [
        _candle(_epoch(2026, 6, 15), 102, 98, 100, 200),
        _candle(_epoch(2026, 6, 17), 108, 102, 106, 400),
    ]
    feats = vwap_features(candles)
    assert set(feats) == {
        "vwap_session", "vwap_session_dist_pct", "vwap_session_position",
        "vwap_week", "vwap_week_dist_pct", "vwap_week_position",
    }
    # sesion = solo la vela del 17; semana = ambas.
    assert feats["vwap_session"] == pytest.approx((108 + 102 + 106) / 3)
    assert feats["vwap_week"] == pytest.approx(
        (100.0 * 200 + (108 + 102 + 106) / 3 * 400) / 600
    )
    assert feats["vwap_week_position"] in {"above", "below", "at"}


def test_vwap_features_none_safe_without_volume():
    candles = [_candle(_epoch(2026, 6, 17), 1.09, 1.08, 1.085, 0)]
    feats = vwap_features(candles)
    assert feats["vwap_session"] is None
    assert feats["vwap_session_dist_pct"] is None
    assert feats["vwap_session_position"] == "unknown"
    assert feats["vwap_week"] is None


def test_reading_dataclass_defaults():
    reading = VwapReading(anchor=ANCHOR_SESSION, vwap=None, distance_pct=None, position="unknown")
    assert reading.bars_used == 0


# --- integracion: analyze_ohlcv / IA Pro / feature_extractor -----------------


def _session_candles(n=30, volume=1000.0, base=100.0):
    """n velas de 15m del MISMO dia UTC (2026-06-17), con volumen."""
    return [
        _candle(
            _epoch(2026, 6, 17, 10 + (i * 15) // 60, (i * 15) % 60),
            base + i * 0.2 + 0.5,
            base + i * 0.2 - 0.5,
            base + i * 0.2,
            volume,
        )
        for i in range(n)
    ]


def test_analyze_ohlcv_populates_vwap_fields():
    from app.analyzers.technical_patterns import analyze_ohlcv

    pattern = analyze_ohlcv(_session_candles())
    assert pattern.vwap is not None
    assert pattern.vwap_dist_pct is not None
    assert pattern.vwap_position in {"above", "below", "at"}
    assert pattern.vwap_week_dist_pct is not None


def test_analyze_ohlcv_vwap_soft_fail_without_volume():
    # Caso forex-Yahoo: velas sin volumen -> VWAP None, el resto del pattern vive.
    from app.analyzers.technical_patterns import analyze_ohlcv

    pattern = analyze_ohlcv(_session_candles(volume=0.0))
    assert pattern.vwap is None
    assert pattern.vwap_dist_pct is None
    assert pattern.vwap_position == "unknown"
    assert pattern.label  # el analisis tecnico sigue funcionando igual
    assert pattern.rsi is not None


def test_vwap_stays_out_of_pattern_reasons_and_score_path():
    # El VWAP es INFORMATIVO dentro de analyze_ohlcv: no aparece en reasons
    # (el feature_extractor parsea ese texto) ni suma/resta al score. La
    # unica via de exposicion son los campos vwap_* del dataclass.
    from app.analyzers.technical_patterns import analyze_ohlcv

    pattern = analyze_ohlcv(_session_candles())
    assert not any("vwap" in reason.lower() for reason in pattern.reasons)


def test_pro_checklist_and_setup_include_vwap():
    from app.analyzers.pro_intelligence import analyze_professional_setup
    from app.analyzers.technical_patterns import analyze_ohlcv
    from app.database.models import SecuritySummary, TokenSnapshot

    pattern = analyze_ohlcv(_session_candles())
    snapshot = TokenSnapshot(chain="stock", token_address="NVDA", category="stock", symbol="NVDA")
    pro = analyze_professional_setup(snapshot, SecuritySummary(), pattern)
    assert any("VWAP" in item for item in pro.checklist)
    assert "vwap_above" in pro.setup or "vwap_below" in pro.setup


def test_pro_score_unaffected_by_vwap_fields():
    # Mismo pattern con los campos VWAP vaciados a mano: el score de IA Pro
    # debe ser IDENTICO (VWAP no toca score/confidence, solo checklist/setup).
    from app.analyzers.pro_intelligence import analyze_professional_setup
    from app.analyzers.technical_patterns import analyze_ohlcv
    from app.database.models import SecuritySummary, TokenSnapshot

    snapshot = TokenSnapshot(chain="stock", token_address="NVDA", category="stock", symbol="NVDA")
    pattern = analyze_ohlcv(_session_candles())
    with_vwap = analyze_professional_setup(snapshot, SecuritySummary(), pattern)
    pattern.vwap = None
    pattern.vwap_dist_pct = None
    pattern.vwap_position = "unknown"
    pattern.vwap_week_dist_pct = None
    without_vwap = analyze_professional_setup(snapshot, SecuritySummary(), pattern)
    assert with_vwap.score == without_vwap.score
    assert with_vwap.confidence == without_vwap.confidence
    assert with_vwap.bias == without_vwap.bias


def test_vwap_reason_line_does_not_shift_feature_extractor():
    # REGRESION: la linea VWAP que jobs.py agrega a reasons NO debe activar
    # ningun needle del feature_extractor (una fila ML nueva no puede cambiar
    # de one-hots porque agregamos texto VWAP).
    import json

    from app.learning.feature_extractor import extract_features

    base_reasons = [
        "Patron grafico: bullish_watch (bullish, score 20).",
        "Setup: stock + bullish_watch.",
    ]
    vwap_reasons = [
        "Patron grafico: bullish_watch (bullish, score 20).",
        "Setup: stock + bullish_watch + vwap_above.",  # pieza de pro.setup
        "VWAP sesion: precio 0.42% sobre VWAP.",       # linea de jobs.py
        "Velas: strong_bull | engulfing_bull.",        # v3.12.0 footprint
        "Hurst 0.62 (persistent).",                    # v3.12.0 hurst
    ]
    alert = {
        "alert_type": "STOCK_BREAKOUT",
        "risk_level": "medium",
        "category": "stock",
        "score": 70,
        "reasons": json.dumps(base_reasons),
    }
    with_vwap = dict(alert, reasons=json.dumps(vwap_reasons))
    assert extract_features(alert) == extract_features(with_vwap)
