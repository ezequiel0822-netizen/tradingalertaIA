from pathlib import Path
from uuid import uuid4

from app.analyzers.learned_weights import apply_learned_weights
from app.database.db import init_db
from app.database.repository import Repository
from app.utils.time_utils import utc_now_iso
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"weights_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _lesson(
    feature: str,
    win_rate: float,
    sample_count: int,
    confidence: int,
    category: str = "stock",
    avg_return: float = 2.0,
) -> dict:
    return {
        "feature": feature,
        "category": category,
        "sample_count": sample_count,
        "win_rate": win_rate,
        "avg_return_pct": avg_return,
        "avg_score": 80.0,
        "confidence": confidence,
        "lesson": "test",
        "updated_at": utc_now_iso(),
    }


def _enable_weights(base):
    return type(base)(**{**base.__dict__, "enable_learned_weights": True})


def test_learned_weights_disabled_returns_base_score() -> None:
    settings = _settings()  # disabled by default
    repo = _repo()
    repo.upsert_strategy_lesson(_lesson("ia_pro", 0.9, 20, 80))

    adjusted, reasons = apply_learned_weights(
        70, ["ia_pro"], "stock", settings, repo
    )

    assert adjusted == 70
    assert reasons == []


def test_learned_weights_boost_for_winning_feature() -> None:
    settings = _enable_weights(_settings())
    repo = _repo()
    repo.upsert_strategy_lesson(_lesson("ia_pro", 0.9, 20, 80))

    adjusted, reasons = apply_learned_weights(
        70, ["ia_pro"], "stock", settings, repo
    )

    # bonus = (0.9-0.5)*2*0.8*3 = 1.92, round to 2
    assert adjusted == 72
    assert any("ia_pro" in r for r in reasons)


def test_learned_weights_penalty_for_losing_feature() -> None:
    settings = _enable_weights(_settings())
    repo = _repo()
    repo.upsert_strategy_lesson(_lesson("anti_hype", 0.2, 20, 70))

    adjusted, reasons = apply_learned_weights(
        70, ["anti_hype"], "stock", settings, repo
    )

    # bonus = (0.2-0.5)*2*0.7*3 = -1.26, round to -1
    assert adjusted < 70
    assert any("anti_hype" in r for r in reasons)


def test_learned_weights_clamped_to_max_adjustment() -> None:
    settings = _enable_weights(_settings())
    repo = _repo()
    # 5 winning features, each ~2pts → total ~10, clamped at 10
    for feat in ["ia_pro", "bullish_pattern", "positive_news", "volume_strength", "liquidity_strength"]:
        repo.upsert_strategy_lesson(_lesson(feat, 0.95, 30, 90))

    adjusted, reasons = apply_learned_weights(
        70,
        ["ia_pro", "bullish_pattern", "positive_news", "volume_strength", "liquidity_strength"],
        "stock",
        settings,
        repo,
    )

    # Each bonus ~(0.95-0.5)*2*0.9*3 = 2.43; 5 features = 12.15
    # Clamped at max_adjustment=10 → adjusted = 80
    assert adjusted == 80


def test_learned_weights_ignores_low_sample_lessons() -> None:
    settings = _enable_weights(_settings())
    repo = _repo()
    # sample_count=2 below min_samples=5 → ignored
    repo.upsert_strategy_lesson(_lesson("ia_pro", 0.9, 2, 80))

    adjusted, reasons = apply_learned_weights(
        70, ["ia_pro"], "stock", settings, repo
    )

    assert adjusted == 70
    assert reasons == []
