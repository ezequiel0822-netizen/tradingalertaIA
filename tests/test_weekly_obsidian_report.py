from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.repository import Repository
from app.utils.obsidian_memory import write_weekly_report_if_needed
from app.utils.time_utils import utc_now
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"weekly_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _settings_with_vault(vault_path: Path, enable_weekly: bool = True):
    base = _settings()
    return type(base)(
        **{
            **base.__dict__,
            "obsidian_vault_path": vault_path,
            "enable_obsidian_memory": True,
            "enable_weekly_obsidian_report": enable_weekly,
        }
    )


def test_writes_weekly_when_7_days_passed(tmp_path: Path) -> None:
    repo = _repo()
    settings = _settings_with_vault(tmp_path)
    # Marca la ultima ejecucion hace 8 dias
    repo.set_state(
        "obsidian_weekly_last_date",
        (utc_now() - timedelta(days=8)).date().isoformat(),
    )

    write_weekly_report_if_needed(settings, repo)

    report = tmp_path / "11 - Reporte Semanal.md"
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "Reporte Semanal" in content
    assert settings.app_version in content


def test_skips_when_recent(tmp_path: Path) -> None:
    repo = _repo()
    settings = _settings_with_vault(tmp_path)
    repo.set_state(
        "obsidian_weekly_last_date",
        (utc_now() - timedelta(days=2)).date().isoformat(),
    )

    write_weekly_report_if_needed(settings, repo)

    report = tmp_path / "11 - Reporte Semanal.md"
    assert not report.exists()
