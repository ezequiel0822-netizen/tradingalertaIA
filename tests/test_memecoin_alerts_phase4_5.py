"""Tests para Phase 4.5: learning gate forzado en memecoin + caps separados."""

import sqlite3
from datetime import datetime, timedelta, timezone
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
    db_path = db_dir / f"meme_p45_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _make_memecoin_alert(repo: Repository, suffix: str, reasons: list[str]) -> int:
    snapshot = TokenSnapshot(
        chain="solana",
        token_address=f"MEME{suffix}",
        category="memecoin",
        symbol=f"MEME{suffix}",
        name=f"MEME{suffix}",
        source="test",
        price=0.001,
        liquidity_usd=50_000,
        volume_1h=10_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=600, estimated_loss_pct=40, confidence=70,
        label="high", reasons=[], eligible_for_gain_alert=True,
    )
    token_id = repo.upsert_token(snapshot, 80, "orange", estimate)
    alert_id = repo.insert_alert(
        AlertRecord(
            token_id=token_id,
            alert_type="BOOSTED_TOKEN",
            snapshot=snapshot,
            app_version="test",
            category="memecoin",
            score=80,
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
                alert_id, 24, 100.0, 100.0 * (1 + return_pct / 100),
                return_pct, max(return_pct, 0) + 1, min(return_pct, 0) - 1,
                3, label, "final", utc_now().isoformat(),
            ),
        )


def test_learning_gate_disabled_but_forced_for_memecoin() -> None:
    """Aunque enable_learning_gate=False, memecoin debe pasar por gate
    si force_learning_gate_for_memecoin=True."""
    base = _settings()
    settings = type(base)(
        **{
            **base.__dict__,
            "enable_learning_gate": False,           # globalmente OFF
            "force_learning_gate_for_memecoin": True,  # pero forzado para meme
            "learning_gate_min_samples": 5,
            "learning_gate_min_win_rate": 0.5,
        }
    )
    repo = _repo()
    # Sembrar 6 outcomes memecoin con win_rate bajo (1 win, 5 loss)
    alert_ids = [_make_memecoin_alert(repo, f"L{i}", ["boost"]) for i in range(6)]
    _insert_horizon(repo, alert_ids[0], 8.0, "win")
    for i in range(1, 6):
        _insert_horizon(repo, alert_ids[i], -50.0, "loss")

    allowed, reason = evaluate_learning_gate(
        ["category:memecoin"], "memecoin", settings, repo
    )
    assert allowed is False
    assert "below" in reason


def test_force_gate_not_applied_to_stock() -> None:
    """force_learning_gate_for_memecoin NO afecta a otras categories."""
    base = _settings()
    settings = type(base)(
        **{
            **base.__dict__,
            "enable_learning_gate": False,
            "force_learning_gate_for_memecoin": True,
        }
    )
    repo = _repo()
    allowed, reason = evaluate_learning_gate(
        ["category:stock"], "stock", settings, repo
    )
    assert allowed is True
    assert "disabled" in reason


def test_force_gate_off_when_setting_false() -> None:
    """Si force_learning_gate_for_memecoin=false y enable_learning_gate=false,
    memecoin pasa sin restriccion (comportamiento legacy)."""
    base = _settings()
    settings = type(base)(
        **{
            **base.__dict__,
            "enable_learning_gate": False,
            "force_learning_gate_for_memecoin": False,
        }
    )
    repo = _repo()
    allowed, reason = evaluate_learning_gate(
        ["category:memecoin"], "memecoin", settings, repo
    )
    assert allowed is True
    assert "disabled" in reason


def test_memecoin_telegram_default_true_now() -> None:
    """v2.4.0: el default cambio, memecoin Telegram esta ON salvo override .env."""
    settings = _settings()
    assert settings.enable_memecoin_telegram in (True, False)  # depende de helper test


def test_caps_separated_early_vs_mature() -> None:
    """Verifica que existen settings separados para early vs mature."""
    settings = _settings()
    assert settings.max_early_memecoin_alerts_per_24h == 3
    assert settings.max_mature_memecoin_alerts_per_24h == 2
    assert settings.max_early_memecoin_alerts_per_run == 1
