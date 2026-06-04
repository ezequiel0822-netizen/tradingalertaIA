"""v2.9.0 — tests del MLPredictor (XGBoost hibrido, soft-fail, degradado).

Requiere xgboost+scikit-learn; si no estan, los tests se SKIPEAN (no fallan).
El test de soft-fail SIN libs no se puede simular aca, pero el de "modelo no
entrenado -> 0.5" cubre el camino degradado que es el critico para no romper nada.
"""

from __future__ import annotations

import random

import pandas as pd
import pytest

pytest.importorskip("xgboost")
pytest.importorskip("sklearn")

from app.learning.ml_predictor import (
    MLPredictor,
    NEUTRAL_CONFIDENCE,
    ml_gate_decision,
    should_consult_ml,
)


def _synthetic_df(n: int = 300, seed: int = 7) -> pd.DataFrame:
    """Dataset sintetico con SEÑAL aprendible: win mas probable si session=ny y
    vix bajo. Permite que el modelo entrene y el AUC sea computable y < 1."""
    rng = random.Random(seed)
    rows = []
    base = pd.Timestamp("2026-01-01")
    for i in range(n):
        sess = rng.choice(["asian", "london", "ny", "off"])
        vix = rng.uniform(10.0, 40.0)
        p_win = 0.72 if (sess == "ny" and vix < 25) else 0.30
        win = 1 if rng.random() < p_win else 0
        rows.append({
            "vix_level": vix,
            "dxy_level": rng.uniform(95.0, 110.0),
            "time_of_day_hour": rng.randint(0, 23),
            "day_of_week": rng.randint(0, 6),
            "rsi_entry": float("nan"),
            "atr_value": float("nan"),
            "session": sess,
            "strategy_name": rng.choice(["breakout", "momentum"]),
            "category": "forex",
            "macd_state": rng.choice(["bullish", "bearish", "neutral"]),
            "direction": rng.choice(["long", "short"]),
            "feat_ia_pro": rng.randint(0, 1),
            "feat_volume_strength": rng.randint(0, 1),
            "realized_return": 1.0 if win else -1.0,
            "r_multiple": 1.0 if win else -1.0,
            "win_loss": win,
            "opened_dt": base + pd.Timedelta(hours=i),
        })
    return pd.DataFrame(rows)


def _feat_row() -> dict:
    return {
        "vix_level": 18.0, "dxy_level": 103.0, "time_of_day_hour": 14,
        "day_of_week": 1, "rsi_entry": float("nan"), "atr_value": float("nan"),
        "session": "ny", "strategy_name": "breakout", "category": "forex",
        "macd_state": "bullish", "direction": "long", "feat_ia_pro": 1,
        "feat_volume_strength": 1,
    }


def test_small_dataset_returns_degraded(tmp_path) -> None:
    pred = MLPredictor(model_path=tmp_path / "m.pkl", min_train_samples=100)
    status = pred.train(_synthetic_df(n=50))
    assert status["trained"] is False
    assert status["degraded"] is True
    assert pred.predict(_feat_row()) == NEUTRAL_CONFIDENCE


def test_sufficient_dataset_trains_with_valid_auc(tmp_path) -> None:
    pred = MLPredictor(model_path=tmp_path / "m.pkl", min_train_samples=100)
    status = pred.train(_synthetic_df(n=300))
    assert status["trained"] is True
    assert status["auc"] is not None
    assert 0.0 < status["auc"] < 1.0
    assert status["samples"] == 300


def test_predict_always_in_range(tmp_path) -> None:
    pred = MLPredictor(model_path=tmp_path / "m.pkl", min_train_samples=100)
    pred.train(_synthetic_df(n=300))
    for _ in range(20):
        row = _feat_row()
        row["vix_level"] = random.uniform(5, 60)
        p = pred.predict(row)
        assert 0.0 <= p <= 1.0


def test_predict_missing_features_does_not_crash(tmp_path) -> None:
    pred = MLPredictor(model_path=tmp_path / "m.pkl", min_train_samples=100)
    pred.train(_synthetic_df(n=300))
    assert 0.0 <= pred.predict({}) <= 1.0
    assert 0.0 <= pred.predict({"session": "ny"}) <= 1.0
    assert 0.0 <= pred.predict({"bogus": 123}) <= 1.0


def test_save_load_same_predictions(tmp_path) -> None:
    path = tmp_path / "m.pkl"
    pred = MLPredictor(model_path=path, min_train_samples=100)
    pred.train(_synthetic_df(n=300))
    row = _feat_row()
    before = pred.predict(row)
    # nueva instancia que carga el modelo persistido
    reloaded = MLPredictor(model_path=path, min_train_samples=100)
    assert reloaded.get_status()["trained"] is True
    after = reloaded.predict(row)
    assert abs(before - after) < 1e-9


def test_feature_importance_non_empty_when_trained(tmp_path) -> None:
    pred = MLPredictor(model_path=tmp_path / "m.pkl", min_train_samples=100)
    pred.train(_synthetic_df(n=300))
    imp = pred.feature_importance(top=5)
    assert isinstance(imp, list) and len(imp) > 0
    assert all(isinstance(name, str) and isinstance(w, float) for name, w in imp)
    assert len(imp) <= 5


def test_softfail_when_not_trained(tmp_path) -> None:
    # predictor fresco, sin entrenar y sin modelo persistido -> degradado total
    pred = MLPredictor(model_path=tmp_path / "nope.pkl", min_train_samples=100)
    assert pred.get_status()["trained"] is False
    assert pred.predict(_feat_row()) == NEUTRAL_CONFIDENCE
    assert pred.feature_importance() == []


def test_retrain_reverts_on_auc_drop(tmp_path, monkeypatch) -> None:
    pred = MLPredictor(model_path=tmp_path / "m.pkl", min_train_samples=100)
    pred.train(_synthetic_df(n=300))
    good_auc = pred.get_status()["auc"]
    # forzar un _fit que devuelve AUC mucho peor -> debe revertir
    bad = {"model": pred._model, "feature_columns": pred._feature_columns,
           "auc": (good_auc or 0.6) - 0.2, "samples": 400, "trained_at": "x"}
    monkeypatch.setattr(pred, "_fit", lambda df: bad)
    res = pred.retrain_if_needed(_synthetic_df(n=400), min_new_trades=20)
    assert res["reverted"] is True
    assert pred.get_status()["auc"] == good_auc  # conserva el modelo bueno


def test_ml_gate_decision_thresholds() -> None:
    # downward-only: >conf_pass pasa, conf_low..pass low, <conf_low block
    assert ml_gate_decision(0.80, 0.65, 0.50)[:2] == (True, False)
    assert ml_gate_decision(0.65, 0.65, 0.50)[:2] == (True, False)
    assert ml_gate_decision(0.60, 0.65, 0.50)[:2] == (True, True)
    assert ml_gate_decision(0.50, 0.65, 0.50)[:2] == (True, True)
    assert ml_gate_decision(0.40, 0.65, 0.50)[:2] == (False, False)


def test_should_consult_ml_guard_keeps_system_unchanged(tmp_path) -> None:
    # Test 8 del plan: en modo degradado/dormido el gate NO se modula (sin cambios).
    assert should_consult_ml(None, 400) is False
    pred = MLPredictor(model_path=tmp_path / "x.pkl", min_train_samples=100)
    assert should_consult_ml(pred, 400) is False        # sin entrenar -> dormido
    pred.train(_synthetic_df(n=300))
    assert should_consult_ml(pred, 400) is False         # 300 < 400 -> dormido
    assert should_consult_ml(pred, 200) is True          # 300 >= 200 -> activo


def test_ml_status_command_when_disabled(tmp_path) -> None:
    from app.assistant.command_handler import BasicTelegramAssistant
    from app.database.db import init_db
    from app.database.repository import Repository
    from tests.test_score import _settings

    db = tmp_path / "s.db"
    init_db(db)
    assistant = BasicTelegramAssistant(_settings(), Repository(db))  # ML off
    resp = assistant.handle("/ml_status")
    assert "DESACTIVADA" in resp
