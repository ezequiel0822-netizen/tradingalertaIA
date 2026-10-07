"""v3.14.0 — scripts/ai_agent_report.py: solo lectura y criterio pre-registrado de v2."""

from __future__ import annotations

import importlib.util
import math
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.database.db import init_db
from app.database.repository import Repository
from tests.test_auto_confirm_demo import _paper_trade_row

_SPEC = importlib.util.spec_from_file_location(
    "ai_agent_report", Path(__file__).resolve().parents[1] / "scripts" / "ai_agent_report.py")
report = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(report)


def _db() -> Path:
    d = Path.cwd() / ".test_dbs"
    d.mkdir(exist_ok=True)
    p = d / f"report_{uuid4().hex}.db"
    init_db(p)
    return p


def test_newey_west_matches_hand_computation() -> None:
    x = [1.0, -0.5, 2.0, 0.3, -1.2, 0.8, 1.5, -0.2]
    n, m = len(x), sum(x) / len(x)
    d = [v - m for v in x]
    g = lambda k: sum(d[i] * d[i - k] for i in range(k, n)) / n
    lrv = g(0) + 2 * sum((1 - k / 3) * g(k) for k in (1, 2))
    assert report.newey_west_t(x, lags=2) == pytest.approx(m / math.sqrt(lrv / n))
    assert report.newey_west_t(x, lags=0) == pytest.approx(m / math.sqrt(g(0) / n))
    assert report.newey_west_t([1.0, 2.0]) is None


def test_prereg_tag_and_weight_match_the_agent() -> None:
    from tests.test_ai_agent_v2 import PREREG_TAG
    assert report.PREREG_TAG_V2_ORIGINAL == PREREG_TAG
    # adenda 2026-10-07: se evalúa el tag con el precio de MT5 y el modelo sin oro mezclado
    assert report.PREREG_TAG_V2 == PREREG_TAG + "|px1"
    assert report.weight("explore") == pytest.approx(0.2) and report.weight("skip") == 0.0


def _seed(db: Path, n: int, r: float, start: date, tag=None, offset: int = 0,
          **trade_kw) -> None:
    repo = Repository(db)
    for i in range(offset, offset + n):
        repo.create_paper_trade({**_paper_trade_row(5000 + i), **trade_kw})
        pt = repo.fetch_paper_trade_by_alert_id(5000 + i)
        did = repo.create_ai_agent_decision({
            "paper_trade_id": pt["id"],
            "created_at": f"{(start + timedelta(days=i % 90)).isoformat()}T12:00:00+00:00",
            "features_json": "[]", "intended": "execute" if i % 2 else "skip",
            "executed": False, "agent_version": 2,
            "policy_tag": tag or report.PREREG_TAG_V2})
        repo.update_ai_agent_decision(did, {"reward_r": r, "rewarded_at": "x"})


def test_evaluation_refuses_early_and_runs_after() -> None:
    db = _db()
    _seed(db, 210, -1.0, date(2026, 10, 12))
    con = report.connect_ro(db)
    rows = report.load_decisions(con)
    early = report.evaluate_v2(rows, con, date(2026, 12, 31))
    assert early["status"] == "TODAVIA_NO"
    late = report.evaluate_v2(rows, con, date(2027, 1, 11))
    assert late["status"] == "NO PASA" and late["n"] == 210
    assert late["criteria"]["1_media_v_pos"] is False
    assert late["criteria"]["5_sin_limites_rotos"] is True
    # solo cuenta el tag pre-registrado
    db2 = _db()
    _seed(db2, 210, 1.0, date(2026, 10, 12), tag="v2|eps0.50|otro")
    con2 = report.connect_ro(db2)
    assert report.evaluate_v2(report.load_decisions(con2), con2,
                              date(2027, 1, 11))["status"] == "TODAVIA_NO"


def test_adenda_original_tag_and_mixed_gold_do_not_count() -> None:
    db = _db()
    _seed(db, 210, 1.0, date(2026, 10, 12), tag=report.PREREG_TAG_V2_ORIGINAL)
    _seed(db, 50, -5.0, date(2026, 10, 12), offset=210, category="gold")   # oro mezclado
    con = report.connect_ro(db)
    rows = report.load_decisions(con)
    assert sum(d["mixed_gold"] for d in rows) == 50
    # el tag original no decide y el oro mezclado nunca se mide
    assert report.evaluate_v2(rows, con, date(2027, 1, 11))["status"] == "TODAVIA_NO"
    s = report.summarize([d for d in rows if d["policy_tag"] == report.PREREG_TAG_V2])
    assert s["excluded_mixed_gold"] == 50 and s["with_r"] == 0
    assert s["excluded_mixed_gold_sum_r"] == pytest.approx(-250.0)
    # con fuente única (price_source) el oro vuelve a contar
    db2 = _db()
    _seed(db2, 210, 1.0, date(2026, 10, 12), category="gold", price_source="mt5")
    con2 = report.connect_ro(db2)
    late = report.evaluate_v2(report.load_decisions(con2), con2, date(2027, 1, 11))
    assert late["n"] == 210


def test_report_connection_is_read_only() -> None:
    db = _db()
    con = report.connect_ro(db)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM ai_agent_decisions")
