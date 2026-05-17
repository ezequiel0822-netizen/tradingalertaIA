from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.models import AlertRecord, EstimateResult, SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from app.utils.obsidian_memory import write_daily_memory_if_needed
from tests.test_score import _settings


def test_obsidian_memory_waits_for_meaningful_cycle() -> None:
    base_dir = Path.cwd() / ".test_dbs" / f"vault_{uuid4().hex}"
    db_path = Path.cwd() / ".test_dbs" / f"memory_{uuid4().hex}.db"
    init_db(db_path)
    repository = Repository(db_path)
    settings = _settings()
    settings = type(settings)(
        **{
            **settings.__dict__,
            "enable_obsidian_memory": True,
            "obsidian_vault_path": base_dir,
        }
    )

    write_daily_memory_if_needed(settings, repository, [], 0)
    assert not (base_dir / "09 - Memoria Automatica.md").exists()

    snapshot = TokenSnapshot(
        chain="base",
        token_address="0xaaa",
        category="memecoin",
        symbol="AAA",
    )
    estimate = EstimateResult(
        estimated_gain_pct=550,
        estimated_loss_pct=40,
        confidence=70,
        label="high-conviction",
        reasons=["test"],
        eligible_for_gain_alert=True,
    )
    record = AlertRecord(
        token_id=1,
        alert_type="TRENDING_POOL",
        snapshot=snapshot,
        app_version="v1.5",
        category="memecoin",
        score=82,
        risk_level="orange",
        reasons=["test"],
        security=SecuritySummary(raw_summary="unknown"),
        estimate=estimate,
        sent_to_telegram=True,
    )

    write_daily_memory_if_needed(settings, repository, [record], 1)
    memory_file = base_dir / "09 - Memoria Automatica.md"
    assert memory_file.exists()
    assert "AAA" in memory_file.read_text(encoding="utf-8")
