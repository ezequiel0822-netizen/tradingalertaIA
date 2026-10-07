"""v3.15.0 — agentes sombra (research/AGENTE_IA_SOMBRAS_PREREGISTRO_2026-10-07.md).

Tres políticas que deciden sobre los mismos candidatos que el agente v2 y NUNCA operan.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import app.ai_agent.shadows as shadows_mod
from app.ai_agent.agent import AiAgent
from app.ai_agent.features import FEATURE_NAMES_V2
from app.ai_agent.shadows import (
    SHADOWS,
    SIMPLE_FEATURES,
    candidate_x,
    daily_series,
    learnable_trades,
    shadow_decisions,
    shadow_scoreboard,
    shadow_values,
)
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_ai_agent_v2 import PREREG_TAG, _StubJobV2, _v2_settings

T0 = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
PX1 = PREREG_TAG + "|px1"

_SPEC = importlib.util.spec_from_file_location(
    "ai_agent_report_sh", Path(__file__).resolve().parents[1] / "scripts" / "ai_agent_report.py")
report = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(report)


def _repo() -> Repository:
    d = Path.cwd() / ".test_dbs"
    d.mkdir(exist_ok=True)
    p = d / f"shadows_{uuid4().hex}.db"
    init_db(p)
    return Repository(p)


def _dec(i: int, *, mean: float, sd: float = 0.1, gap: float = 0.0, reward: float | None = None,
         at: datetime = T0, strategy: str = "mean_reversion", direction: str = "long",
         category: str = "forex", tag: str = PX1) -> dict:
    return {"id": i, "created_at": at.isoformat(), "mean_r": mean, "std_r": sd,
            "realism_gap": gap, "reward_r": reward, "strategy_name": strategy,
            "direction": direction, "category": category, "policy_tag": tag,
            "agent_version": 2}


def _closed(r: float, at: datetime, *, strategy: str = "mean_reversion", direction: str = "long",
            category: str = "forex", price_source: str | None = "mt5") -> dict:
    entry, stop = 1.1, 1.099
    latest = entry + (entry - stop) * r if direction == "long" else entry - (entry - stop) * r
    stop_ = stop if direction == "long" else entry + (entry - stop)
    return {"category": category, "status": "stopped_simulated", "closed_at": at.isoformat(),
            "entry_price": entry, "latest_price": latest, "original_stop_loss": stop_,
            "stop_loss": stop_, "direction": direction, "strategy_name": strategy,
            "price_source": price_source}


# ------------------------------------------------------------------- reglas
def test_codicioso_and_prudente_rules_use_mean_sd_and_gap() -> None:
    decs = [_dec(1, mean=0.06), _dec(2, mean=0.04), _dec(3, mean=0.04, gap=0.02),
            _dec(4, mean=0.30, sd=0.20), _dec(5, mean=0.30, sd=0.30)]
    f = shadow_decisions(decs, [])
    assert [f[i]["codicioso"] for i in range(1, 6)] == [True, False, True, True, True]
    assert [f[i]["prudente"] for i in range(1, 6)] == [False, False, False, True, False]


def test_simple_uses_six_features_and_only_the_past() -> None:
    assert SIMPLE_FEATURES == FEATURE_NAMES_V2[:6] and len(candidate_x(_dec(1, mean=0))) == 6
    past = [_closed(+2.0, T0 - timedelta(hours=h)) for h in range(1, 40)]
    future = [_closed(-3.0, T0 + timedelta(hours=h)) for h in range(1, 400)]
    f = shadow_decisions([_dec(1, mean=-1.0)], past + future)
    assert f[1]["simple"] is True                 # aprendió del pasado (+2R), no del futuro
    assert f[1]["codicioso"] is False             # el agente (media −1) no la tomaría
    later = _dec(2, mean=-1.0, at=T0 + timedelta(days=30))
    assert shadow_decisions([later], past + future)[2]["simple"] is False   # ya vio los −3R


def test_simple_ignores_mixed_gold_and_artifacts() -> None:
    fake = [_closed(+3.0, T0 - timedelta(hours=h), category="gold", direction="short",
                    price_source=None) for h in range(1, 60)]          # ganancias falsas
    art = {**_closed(+3.0, T0 - timedelta(hours=1)), "latest_price": 1.1}   # precio congelado
    gold_short = _dec(1, mean=-1.0, category="gold", direction="short")
    assert learnable_trades(fake + [art]) == []
    assert shadow_decisions([gold_short], fake + [art])[1]["simple"] is False
    clean = [{**t, "price_source": "mt5"} for t in fake]
    assert shadow_decisions([gold_short], clean)[1]["simple"] is True


def test_values_scoreboard_and_daily_series() -> None:
    decs = [_dec(1, mean=0.5, reward=-1.0), _dec(2, mean=-0.5, reward=2.0),
            _dec(3, mean=0.5, reward=1.5, at=T0 + timedelta(days=1)), _dec(4, mean=0.5)]
    f = shadow_decisions(decs, [])
    assert shadow_values(decs, f, "codicioso") == [("2026-10-08", -1.0), ("2026-10-08", 0.0),
                                                   ("2026-10-09", 1.5)]   # sin R no cuenta
    sb = shadow_scoreboard(decs, f)
    assert sb["codicioso"]["n"] == 3 and sb["codicioso"]["executes"] == 2
    assert sb["codicioso"]["sum_r"] == pytest.approx(0.5)
    assert daily_series(shadow_values(decs, f, "codicioso")) == [-1.0, 1.5]
    assert set(sb) == set(SHADOWS)


def test_deterministic_and_order_independent() -> None:
    decs = [_dec(i, mean=0.1 * (i % 3) - 0.05, at=T0 + timedelta(hours=i)) for i in range(1, 20)]
    closed = [_closed(1.0 if h % 2 else -1.0, T0 - timedelta(hours=h)) for h in range(1, 50)]
    assert shadow_decisions(decs, closed) == shadow_decisions(list(reversed(decs)), closed)


def test_shadows_have_no_path_to_orders() -> None:
    src = inspect.getsource(shadows_mod)
    for needle in ("order_send", "mt5_demo_trader", "MT5DemoTrader", "create_demo_trade_request",
                   "MetaTrader5", "set_state", "update_ai_agent_decision"):
        assert needle not in src


# ------------------------------------------------------------ agente / display
def _decision_row(repo: Repository, *, mean: float, reward: float, tag: str) -> None:
    alert_id = int(uuid4().int % 10_000_000)
    now = datetime.now(timezone.utc).isoformat()
    entry, stop = 1.1, 1.099
    repo.create_paper_trade({
        "alert_id": alert_id, "token_id": 1, "category": "forex", "chain": "forex",
        "token_address": "EURUSD=X", "symbol": "EURUSD=X", "thesis": "t",
        "readiness_grade": "B", "entry_price": entry, "latest_price": entry + 0.001 * reward,
        "stop_loss": stop, "take_profit_1": None, "take_profit_2": None, "invalidation": None,
        "status": "stopped_simulated", "unrealized_return_pct": 0, "opened_at": now,
        "updated_at": now, "closed_at": now, "original_stop_loss": stop,
        "strategy_name": "mean_reversion", "direction": "long", "price_source": "mt5"})
    pt = repo.fetch_paper_trade_by_alert_id(alert_id)
    did = repo.create_ai_agent_decision({
        "paper_trade_id": pt["id"], "created_at": now, "symbol": "EURUSD=X",
        "category": "forex", "strategy_name": "mean_reversion", "direction": "long",
        "features_json": json.dumps([1.0] + [0.0] * 23), "mean_r": mean, "std_r": 0.1,
        "sampled_r": mean, "intended": "skip", "executed": False, "model_n": 1,
        "agent_version": 2, "policy_tag": tag, "realism_gap": 0.0})
    repo.update_ai_agent_decision(did, {"reward_r": reward, "rewarded_at": now})


def test_status_and_summary_show_shadows_only_with_the_flag() -> None:
    repo = _repo()
    _decision_row(repo, mean=0.4, reward=-1.0, tag=PREREG_TAG)
    _decision_row(repo, mean=-0.4, reward=1.0, tag=PREREG_TAG)
    off = AiAgent(_v2_settings(), repo)
    assert "Agentes sombra" not in off.status_text("v3.15.0")
    assert "Sombras" not in off.summary_line("2026-10-08")
    on = AiAgent(_v2_settings(ai_agent_shadows=True), repo)
    text = on.status_text("v3.15.0")
    assert "Agentes sombra (no operan; sobre 2 decisiones cerradas)" in text
    assert "codicioso  -1.00R (ejecutaría 1)" in text and "prudente" in text and "simple" in text
    assert "Sombras (no operan): codicioso -1.00R" in on.summary_line("2026-10-08")
    assert repo.fetch_demo_trade_request(1) is None                        # ninguna orden


def test_daily_summary_carries_the_shadow_line() -> None:
    repo = _repo()
    _decision_row(repo, mean=0.4, reward=-1.0, tag=PREREG_TAG)
    s = _v2_settings(enable_daily_summary=True, ai_agent_shadows=True)
    job = _StubJobV2(s, repo, MagicMock())
    msg = job._format_daily_summary("2026-10-08", {"total": 0, "wins": 0, "losses": 0,
                                                   "net_r": 0.0})
    assert "Sombras (no operan)" in msg


# ------------------------------------------------------------------ reporte
def _report_db(n: int, reward: float, tag: str = PX1, start: date = date(2026, 10, 12)) -> Path:
    repo = _repo()
    for i in range(n):
        alert_id = 9000 + i
        day = start + timedelta(days=i % 90)
        at = f"{day.isoformat()}T12:00:00+00:00"
        repo.create_paper_trade({
            "alert_id": alert_id, "token_id": 1, "category": "forex", "chain": "forex",
            "token_address": "EURUSD=X", "symbol": "EURUSD=X", "thesis": "t",
            "readiness_grade": "B", "entry_price": 1.1, "latest_price": 1.1 + 0.001 * reward,
            "stop_loss": 1.099, "take_profit_1": None, "take_profit_2": None,
            "invalidation": None, "status": "stopped_simulated", "unrealized_return_pct": 0,
            "opened_at": at, "updated_at": at, "closed_at": at, "original_stop_loss": 1.099,
            "strategy_name": "mean_reversion", "direction": "long", "price_source": "mt5"})
        pt = repo.fetch_paper_trade_by_alert_id(alert_id)
        did = repo.create_ai_agent_decision({
            "paper_trade_id": pt["id"], "created_at": at, "symbol": "EURUSD=X",
            "category": "forex", "strategy_name": "mean_reversion", "direction": "long",
            "features_json": "[]", "mean_r": 0.2 if i % 2 else -0.2, "std_r": 0.1,
            "sampled_r": 0.0, "intended": "skip", "executed": False, "agent_version": 2,
            "policy_tag": tag, "realism_gap": 0.0})
        repo.update_ai_agent_decision(did, {"reward_r": reward, "rewarded_at": "x"})
    return repo.db_path


def test_report_evaluates_shadows_only_from_the_date_and_on_px1() -> None:
    db = _report_db(210, -1.0)
    con = report.connect_ro(db)
    rows, closed = report.load_decisions(con), report.load_closed_trades(con)
    assert report.evaluate_shadows(rows, closed, date(2026, 12, 31))["status"] == "TODAVIA_NO"
    late = report.evaluate_shadows(rows, closed, date(2027, 1, 11))
    assert late["n"] == 210 and set(late["shadows"]) == set(SHADOWS)
    cod = late["shadows"]["codicioso"]
    assert cod["status"] == "NO PASA" and cod["criteria"]["1_media_v_pos"] is False
    assert cod["days"] == 90                         # la serie existe (no es vacía)
    assert late["shadows"]["prudente"]["criteria"]["1_media_v_pos"] is False   # 0.2−0.1 > 0.05
    other = _report_db(210, 1.0, tag=PREREG_TAG)                               # tag original
    con2 = report.connect_ro(other)
    assert report.evaluate_shadows(report.load_decisions(con2), report.load_closed_trades(con2),
                                   date(2027, 1, 11))["status"] == "TODAVIA_NO"


def test_report_groups_show_shadow_board() -> None:
    db = _report_db(6, -1.0)
    con = report.connect_ro(db)
    rows = report.load_decisions(con)
    pop = report.shadow_population(rows, tag=None)
    board = report.shadows_for(pop, report.load_closed_trades(con))["board"]
    assert board["codicioso"]["executes"] == 3 and board["codicioso"]["sum_r"] == pytest.approx(-3.0)
    assert board["prudente"]["executes"] == 3          # 0.2 − 0.1 > 0.05
