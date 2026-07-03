"""v3.9.5 — performance y retención: WAL, índice, purga de tablas calientes,
cache TTL de news, y el expand LLM fuera del hot path (solo lo que se envía)."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from app.collectors.news_collector import NewsCollector
from app.database.db import get_connection, init_db
from app.database.models import (
    AlertRecord,
    EstimateResult,
    SecuritySummary,
    TokenSnapshot,
)
from app.database.repository import Repository
from app.scheduler.jobs import TradingAlertJob
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"perf395_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_connection_uses_wal_and_busy_timeout() -> None:
    repo = _repo()
    with get_connection(repo.db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_signal_outcomes_evaluated_index_exists() -> None:
    repo = _repo()
    with get_connection(repo.db_path) as connection:
        names = {
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    assert "idx_signal_outcomes_evaluated" in names


def test_purge_old_learning_data_keeps_valuable_alerts() -> None:
    """La purga borra alerts viejas no-enviadas sin trade; conserva enviadas,
    vinculadas a paper_trades, y recientes."""
    repo = _repo()
    old, new = "2020-01-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00"
    with get_connection(repo.db_path) as connection:
        # 1: vieja, no enviada, sin trade -> SE BORRA
        # 2: vieja, ENVIADA -> queda
        # 3: vieja, vinculada a paper_trade -> queda
        # 4: nueva -> queda
        for i, (created, sent) in enumerate(
            [(old, 0), (old, 1), (old, 0), (new, 0)], start=1
        ):
            connection.execute(
                "INSERT INTO alerts (id, token_id, alert_type, chain, token_address,"
                " created_at, sent_to_telegram) VALUES (?, 1, 'T', 'stock', 'X', ?, ?)",
                (i, created, sent),
            )
        connection.execute(
            "INSERT INTO paper_trades (alert_id, token_id, opened_at, updated_at)"
            " VALUES (3, 1, ?, ?)",
            (old, old),
        )
        connection.execute(
            "INSERT INTO signal_outcomes (alert_id, token_id, evaluated_at)"
            " VALUES (1, 1, ?)",
            (old,),
        )
        connection.execute(
            "INSERT INTO signal_outcomes (alert_id, token_id, evaluated_at)"
            " VALUES (4, 1, ?)",
            (new,),
        )
        connection.execute(
            "INSERT INTO security_checks (chain, token_address, checked_at)"
            " VALUES ('stock', 'X', ?)",
            (old,),
        )
        connection.commit()

    deleted = repo.purge_old_learning_data(90)

    assert deleted["alerts"] == 1
    assert deleted["signal_outcomes"] == 1
    assert deleted["security_checks"] == 1
    with get_connection(repo.db_path) as connection:
        ids = {r[0] for r in connection.execute("SELECT id FROM alerts")}
    assert ids == {2, 3, 4}


class _CountingSession:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1

        class _Resp:
            text = (
                "<rss><channel><item><title>t1</title><link>l</link>"
                "<pubDate>d</pubDate></item></channel></rss>"
            )

            def raise_for_status(self):
                return None

        return _Resp()


def test_news_collector_caches_by_ttl() -> None:
    """v3.9.5: el RSS se cachea por TTL — 2 llamadas seguidas = 1 solo GET."""
    collector = NewsCollector(_settings())
    session = _CountingSession()
    collector.session = session

    first = collector.collect_for_symbol("NVDA")
    second = collector.collect_for_symbol("NVDA")

    assert session.calls == 1
    assert first and second and first[0].title == "t1"


class _CountingProcessor:
    def __init__(self) -> None:
        self.calls = 0

    def expand_pro_analysis(self, pro, snapshot):
        self.calls += 1
        return "texto LLM"


def _record(symbol: str) -> AlertRecord:
    snapshot = TokenSnapshot(
        chain="stock",
        token_address=symbol,
        category="stock",
        symbol=symbol,
        name=symbol,
        source="test",
        price=10,
        liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10,
        estimated_loss_pct=5,
        confidence=60,
        label="x",
        reasons=[],
        eligible_for_gain_alert=True,
    )
    return AlertRecord(
        token_id=1,
        alert_type="T",
        snapshot=snapshot,
        app_version="test",
        category="stock",
        score=50,
        risk_level="yellow",
        reasons=["base"],
        security=SecuritySummary(raw_summary="unknown"),
        estimate=estimate,
        sent_to_telegram=False,
    )


def test_enrich_with_llm_only_for_records_with_pro() -> None:
    """v3.9.5: el expand LLM corre en el send-path, solo para records con pro
    (antes corria por CADA snapshot del ciclo, ~30-50s para alertas no enviadas)."""
    job = TradingAlertJob.__new__(TradingAlertJob)
    job.settings = replace(_settings(), enable_pro_intelligence=True)
    processor = _CountingProcessor()
    job.claude_processor = processor

    with_pro = _record("AAA")
    with_pro._pro_setup = object()
    without_pro = _record("BBB")
    without_pro._pro_setup = None

    job._enrich_with_llm([with_pro, without_pro])

    assert processor.calls == 1
    assert any("texto LLM" in r for r in with_pro.reasons)
    assert not any("texto LLM" in r for r in without_pro.reasons)
