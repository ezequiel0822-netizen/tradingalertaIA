from pathlib import Path
from uuid import uuid4

from app.analyzers.trading_readiness import build_trade_readiness
from app.database.db import init_db
from app.database.models import AlertRecord, EstimateResult, SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from app.learning.feature_extractor import extract_features
from app.learning.training_engine import run_learning_cycle
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"learning_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_feature_extractor_detects_pro_and_anti_hype() -> None:
    features = extract_features(
        {
            "category": "memecoin",
            "alert_type": "TRENDING_POOL",
            "risk_level": "orange",
            "score": 82,
            "estimate_confidence": 70,
            "estimated_gain_pct": 650,
            "reasons": '["IA Pro: pro_high_conviction", "Filtro anti-hype: seguridad unknown"]',
            "estimate_summary": '["Volumen relativo fuerte"]',
            "security_summary": "unknown",
        }
    )

    assert "ia_pro" in features
    assert "anti_hype" in features
    assert "category:memecoin" in features


def test_trade_readiness_blocks_critical_risk() -> None:
    settings = _settings()
    snapshot = TokenSnapshot(
        chain="base",
        token_address="0xabc",
        symbol="BAD",
        price=1.0,
    )
    estimate = EstimateResult(
        estimated_gain_pct=600,
        estimated_loss_pct=90,
        confidence=80,
        label="high",
        reasons=[],
        eligible_for_gain_alert=True,
    )

    readiness = build_trade_readiness(snapshot, estimate, 90, "critical", settings)

    assert readiness.blocked is True
    assert readiness.grade == "BLOCKED"


def test_learning_cycle_creates_outcomes_and_lessons() -> None:
    settings = _settings()
    repo = _repo()
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        name="NVIDIA",
        price=100,
        liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10,
        estimated_loss_pct=5,
        confidence=80,
        label="high",
        reasons=["IA Pro"],
        eligible_for_gain_alert=True,
    )
    token_id = repo.upsert_token(snapshot, 85, "orange", estimate)
    repo.upsert_token(
        TokenSnapshot(
            chain="stock",
            token_address="NVDA",
            category="stock",
            symbol="NVDA",
            name="NVIDIA",
            price=108,
            liquidity_usd=1_000_000,
        ),
        85,
        "orange",
        estimate,
    )
    for _ in range(2):
        repo.insert_alert(
            AlertRecord(
                token_id=token_id,
                alert_type="STOCK_BREAKOUT",
                snapshot=snapshot,
                app_version=settings.app_version,
                category="stock",
                score=85,
                risk_level="orange",
                reasons=["IA Pro: pro_high_conviction", "Patron grafico: bullish_breakout"],
                security=SecuritySummary(raw_summary="unknown"),
                estimate=estimate,
                sent_to_telegram=True,
            )
        )

    settings = type(settings)(
        **{
            **settings.__dict__,
            "learning_min_alert_age_minutes": 0,
            "paper_trade_max_active": 5,
        }
    )
    result = run_learning_cycle(settings, repo)

    assert result.alerts_evaluated >= 2
    assert repo.fetch_signal_outcomes()
    assert repo.fetch_strategy_lessons()
