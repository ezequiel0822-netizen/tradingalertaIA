import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from app.analyzers.learning_gate import evaluate_learning_gate
from app.database.db import init_db
from app.database.models import (
    AlertRecord,
    EstimateResult,
    SecuritySummary,
    TokenSnapshot,
)
from app.database.repository import Repository
from app.utils.time_utils import utc_now
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"gate_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _make_alert(repo: Repository, suffix: str, reasons: list[str]) -> int:
    snapshot = TokenSnapshot(
        chain="stock",
        token_address=f"SYM{suffix}",
        category="stock",
        symbol=f"SYM{suffix}",
        name=f"SYM{suffix}",
        source="test",
        price=100.0,
        liquidity_usd=1_000_000,
        volume_1h=200_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10,
        estimated_loss_pct=3,
        confidence=80,
        label="high",
        reasons=[],
        eligible_for_gain_alert=True,
    )
    token_id = repo.upsert_token(snapshot, 85, "orange", estimate)
    alert_id = repo.insert_alert(
        AlertRecord(
            token_id=token_id,
            alert_type="STOCK_BREAKOUT",
            snapshot=snapshot,
            app_version="test",
            category="stock",
            score=85,
            risk_level="orange",
            reasons=reasons,
            security=SecuritySummary(raw_summary="unknown"),
            estimate=estimate,
            sent_to_telegram=True,
        )
    )
    iso = (utc_now() - timedelta(hours=25)).isoformat()
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("UPDATE alerts SET created_at = ? WHERE id = ?", (iso, alert_id))
    return int(alert_id)


def _insert_horizon(repo: Repository, alert_id: int, return_pct: float, label: str) -> None:
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            """
            INSERT INTO alert_outcome_horizons (
                alert_id, horizon_hours, entry_price, exit_price,
                return_pct, mfe_pct, mae_pct, snapshots_used,
                outcome_label, status, evaluated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                24,
                100.0,
                100.0 * (1 + return_pct / 100),
                return_pct,
                max(return_pct, 0) + 1,
                min(return_pct, 0) - 1,
                3,
                label,
                "final",
                utc_now().isoformat(),
            ),
        )


def _enable_gate(base):
    return type(base)(
        **{
            **base.__dict__,
            "enable_learning_gate": True,
            "learning_gate_min_samples": 5,
            "learning_gate_min_win_rate": 0.45,
        }
    )


def test_gate_disabled_always_allows() -> None:
    settings = _settings()  # disabled
    repo = _repo()
    allowed, reason = evaluate_learning_gate(
        ["category:stock", "score:80-90"], "stock", settings, repo
    )
    assert allowed is True
    assert "disabled" in reason


def test_gate_allows_when_insufficient_samples() -> None:
    settings = _enable_gate(_settings())
    repo = _repo()
    # solo 1 muestra (< min_samples=5)
    alert_id = _make_alert(repo, "X1", ["IA Pro: pro_high_conviction"])
    _insert_horizon(repo, alert_id, 8.0, "win")

    allowed, reason = evaluate_learning_gate(
        ["category:stock", "score:80-90"], "stock", settings, repo
    )
    assert allowed is True
    assert "insufficient" in reason


def test_gate_blocks_low_win_rate() -> None:
    settings = _enable_gate(_settings())
    repo = _repo()
    # 6 muestras stock, 1 win, 5 losses → win_rate ~16%
    alert_ids = [_make_alert(repo, f"L{i}", ["sin tesis"]) for i in range(6)]
    _insert_horizon(repo, alert_ids[0], 6.0, "win")
    for i in range(1, 6):
        _insert_horizon(repo, alert_ids[i], -5.0, "loss")

    allowed, reason = evaluate_learning_gate(
        ["category:stock"], "stock", settings, repo
    )
    assert allowed is False
    assert "below" in reason


def test_gate_allows_high_win_rate() -> None:
    settings = _enable_gate(_settings())
    repo = _repo()
    # 6 muestras stock, 5 wins, 1 neutral → win_rate ~83%
    alert_ids = [_make_alert(repo, f"W{i}", ["IA Pro"]) for i in range(6)]
    for i in range(5):
        _insert_horizon(repo, alert_ids[i], 8.0, "win")
    _insert_horizon(repo, alert_ids[5], 1.0, "neutral")

    allowed, reason = evaluate_learning_gate(
        ["category:stock"], "stock", settings, repo
    )
    assert allowed is True
    assert "ok" in reason
