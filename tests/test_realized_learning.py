"""v2.7.0 Fase 2b — learned_weights y learning_gate sobre realized-R.

El loop de aprendizaje (lessons/weights/gate) medía el DRIFT de la alerta con
umbrales absolutos (~99% 'neutral'). Ahora, con enable_realized_learning=True,
aprende del P&L realizado de paper_trades (realized_feature_lessons). El drift
path se mantiene como fallback cuando el flag está off (cubierto por
test_learned_weights.py y test_learning_gate.py, que usan el helper con el flag
en False).
"""
from pathlib import Path
from uuid import uuid4

from app.analyzers.learned_weights import apply_learned_weights
from app.analyzers.learning_gate import evaluate_learning_gate
from app.database.db import init_db
from app.database.repository import Repository
from app.learning.trade_outcomes import build_realized_feature_lessons
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"realized_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _trade(alert_id, entry, latest, ostop, cat="stock", direction="long"):
    return {
        "alert_id": alert_id,
        "entry_price": entry,
        "latest_price": latest,
        "original_stop_loss": ostop,
        "stop_loss": ostop,
        "direction": direction,
        "category": cat,
        "status": "stopped_simulated",
        "closed_at": "2026-05-30T00:00:00+00:00",
        "partial_closed": 0,
        "take_profit_1": entry * 1.01,
    }


def _seed_realized(repo, feature, category, n, win_rate, avg_r=0.0):
    repo.upsert_realized_feature_lesson(
        {
            "feature": feature,
            "category": category,
            "sample_count": n,
            "wins": int(round(win_rate * n)),
            "win_rate": win_rate,
            "avg_r": avg_r,
            "avg_return_pct": 0.0,
            "confidence": min(100, n * 8),
            "updated_at": utc_now_iso(),
        }
    )


# ---------------- build_realized_feature_lessons ----------------

def test_build_realized_feature_lessons_basic() -> None:
    trades = [
        _trade(1, 100.0, 110.0, 95.0),  # +2R win
        _trade(2, 100.0, 92.0, 95.0),   # -1.6R loss
        _trade(3, 100.0, 100.0, 95.0),  # artifact (precio congelado) → excluido
    ]
    feats = {1: ["ia_pro"], 2: ["ia_pro"], 3: ["ia_pro"]}
    lessons = build_realized_feature_lessons(trades, feats)
    by = {(l["feature"], l["category"]): l for l in lessons}

    ia = by[("ia_pro", "stock")]
    assert ia["sample_count"] == 2  # el artifact fue excluido
    assert ia["wins"] == 1
    assert ia["win_rate"] == 0.5
    assert abs(ia["avg_r"] - 0.2) < 1e-6  # (2.0 + -1.6)/2
    assert ("category:stock", "stock") in by  # feature de categoría siempre incluida


def test_build_realized_feature_lessons_applies_cost() -> None:
    trades = [_trade(1, 100.0, 110.0, 95.0), _trade(2, 100.0, 111.0, 95.0)]
    feats = {1: ["ia_pro"], 2: ["ia_pro"]}
    gross = build_realized_feature_lessons(trades, feats)
    net = build_realized_feature_lessons(
        trades, feats, cost_pct_by_category={"stock": 0.5}
    )
    g = next(l for l in gross if l["feature"] == "ia_pro")
    nlesson = next(l for l in net if l["feature"] == "ia_pro")
    assert nlesson["avg_r"] < g["avg_r"]  # el costo siempre reduce el R


# ---------------- learning_gate sobre realized-R ----------------

def _gate_settings(base):
    return type(base)(
        **{
            **base.__dict__,
            "enable_realized_learning": True,
            "enable_learning_gate": True,
            "learning_gate_min_samples": 5,
            "learning_gate_min_win_rate": 0.45,
        }
    )


def test_realized_gate_blocks_proven_low_win_rate() -> None:
    settings = _gate_settings(_settings())
    repo = _repo()
    _seed_realized(repo, "category:stock", "stock", 10, 0.2)
    allowed, reason = evaluate_learning_gate(
        ["category:stock"], "stock", settings, repo
    )
    assert allowed is False
    assert "realized win_rate" in reason


def test_realized_gate_allows_high_win_rate() -> None:
    settings = _gate_settings(_settings())
    repo = _repo()
    _seed_realized(repo, "category:stock", "stock", 10, 0.8)
    allowed, _ = evaluate_learning_gate(["category:stock"], "stock", settings, repo)
    assert allowed is True


def test_realized_gate_allows_insufficient_samples() -> None:
    settings = _gate_settings(_settings())
    repo = _repo()
    _seed_realized(repo, "category:stock", "stock", 3, 0.1)  # n < min_samples=5
    allowed, reason = evaluate_learning_gate(
        ["category:stock"], "stock", settings, repo
    )
    assert allowed is True
    assert "insufficient" in reason


# ---------------- learned_weights sobre realized-R ----------------

def test_realized_weights_boost_from_realized_lesson() -> None:
    base = _settings()
    settings = type(base)(
        **{**base.__dict__, "enable_realized_learning": True, "enable_learned_weights": True}
    )
    repo = _repo()
    _seed_realized(repo, "ia_pro", "stock", 20, 0.9)
    adjusted, reasons = apply_learned_weights(70, ["ia_pro"], "stock", settings, repo)
    # bonus = (0.9-0.5)*2*(conf/100)*per_feature_max(3); conf=100 → 2.4 → round 2
    assert adjusted == 72
    assert any("ia_pro" in r for r in reasons)


def test_realized_weights_no_data_no_adjustment() -> None:
    """Con la data escasa actual, el realized path no ajusta hasta tener muestra
    — comportamiento esperado y honesto."""
    base = _settings()
    settings = type(base)(
        **{**base.__dict__, "enable_realized_learning": True, "enable_learned_weights": True}
    )
    repo = _repo()  # realized_feature_lessons vacía
    adjusted, reasons = apply_learned_weights(70, ["ia_pro"], "stock", settings, repo)
    assert adjusted == 70
    assert reasons == []
