"""v3.14.0 — agente IA v2 (research/AGENTE_IA_V2_PREREGISTRO_2026-10-06.md).

Features as-of (sin mirar el futuro), exploración con riesgo y presupuesto propios,
ajuste de realismo con el P&L REAL de MT5 (solo lectura) y policy_tag. Cuentas demo
simuladas: real-money sigue bloqueado por construcción.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.ai_agent.agent import MODEL_STATE_KEY, MODEL_STATE_KEYS, AiAgent
from app.ai_agent.features import (
    DIM,
    DIM_V2,
    FEATURE_NAMES,
    FEATURE_NAMES_V2,
    build_features,
    build_features_v2,
    cost_r_feature,
    cot_index_signed,
    cot_market_for,
    event_proximity,
    recent_strategy_r,
)
from app.ai_agent.model import LinearThompson
from app.brokers.mt5_demo_trader import MT5DemoTrader
from app.scheduler.jobs import TradingAlertJob, _complete_d1_bars
from app.utils.time_utils import utc_now
from tests.test_ai_agent import _StubJob, _agent_settings, _open_trade, _repo
from tests.test_auto_confirm_demo import _paper_trade_row
from tests.test_mt5_demo_trader import _fake_mt5

PREREG_TAG = "v2|eps0.20|xr0.10|r0.50|thr0.05|pv0.25|nv1.00|xmax3|xstop2.0"
T0 = "2026-10-06T14:00:00+00:00"   # martes


def _v2_settings(**overrides):
    base = {"ai_agent_version": 2, "ai_agent_explore_pct": 0.20}
    return _agent_settings(**{**base, **overrides})


class _StubJobV2(_StubJob):
    _ai_agent_extras = TradingAlertJob._ai_agent_extras
    _ai_agent_live_d1 = TradingAlertJob._ai_agent_live_d1
    _format_daily_summary = TradingAlertJob._format_daily_summary
    claude_processor = None


def _seed_v2(repo, settings, x, reward, n=300) -> None:
    m = LinearThompson(FEATURE_NAMES_V2, settings.ai_agent_prior_var, settings.ai_agent_noise_var)
    for _ in range(n):
        m.update(x, reward)
    repo.set_state(MODEL_STATE_KEYS[2], m.to_json())


def _closed(strategy, closed_at, latest, status="closed_stop", **kw):
    row = {**_paper_trade_row(), "strategy_name": strategy, "category": "forex",
           "status": status, "closed_at": closed_at, "latest_price": latest}
    row.update(kw)
    return row


# ------------------------------------------------------------------ features
def test_v2_vector_extends_v1_and_missing_is_zero() -> None:
    x = build_features_v2({"direction": "long"})
    assert len(x) == DIM_V2 == 24 == len(FEATURE_NAMES_V2)
    assert FEATURE_NAMES_V2[:DIM] == FEATURE_NAMES
    assert x[0] == 1.0 and all(v == 0.0 for v in x[1:])
    pt = {**_paper_trade_row(), "opened_at": T0}
    assert build_features_v2(pt)[:DIM] == build_features(pt)    # las 16 de v1, idénticas


def test_v2_time_cost_and_extras() -> None:
    pt = {**_paper_trade_row(), "opened_at": "2026-10-09T18:00:00+00:00"}   # viernes 18h
    f = dict(zip(FEATURE_NAMES_V2, build_features_v2(
        pt, extras={"event_near": 3.0, "cot_signed": -0.4, "strat_recent_r": -9.0})))
    assert f["dow_fri"] == 1.0 and f["dow_mon"] == 0.0
    assert f["hour_sin"] == pytest.approx(math.sin(2 * math.pi * 18 / 24))
    assert f["hour_cos"] == pytest.approx(math.cos(2 * math.pi * 18 / 24))
    assert f["event_near"] == 1.0 and f["cot_signed"] == -0.4 and f["strat_recent_r"] == -1.0
    # costo de definición 0.02 % / riesgo 0.0909 % (100 pips de 1.10002)
    assert f["cost_r"] == pytest.approx(0.02 / (0.001 / 1.10002 * 100), rel=1e-6)
    # usa el stop ORIGINAL (no el que movió un trailing) y se acota a 1
    assert cost_r_feature({**pt, "original_stop_loss": 1.09998}) == 1.0
    assert cost_r_feature({**pt, "category": "stock"}) == 0.0


def test_event_proximity_window() -> None:
    ev = lambda m: {"event_time": (datetime(2026, 10, 6, 14, tzinfo=timezone.utc)
                                   + timedelta(minutes=m)).isoformat()}
    assert event_proximity(T0, [ev(0)]) == 1.0
    assert event_proximity(T0, [ev(60)]) == pytest.approx(0.5)
    assert event_proximity(T0, [ev(-90), ev(30)]) == pytest.approx(0.75)
    assert event_proximity(T0, [ev(121)]) == 0.0 and event_proximity(T0, []) == 0.0


def test_cot_market_mapping() -> None:
    assert cot_market_for("EURUSD=X") == ("EUR", 1.0)
    assert cot_market_for("USDJPY=X") == ("JPY", -1.0)
    assert cot_market_for("GC=F") == ("GOLD", 1.0)
    assert cot_market_for("EURJPY=X") is None and cot_market_for("AAPL") is None


def _cot_reports(n, last_value, start="2023-01-03"):
    d0 = datetime.fromisoformat(start)
    rows = [{"report_date": (d0 + timedelta(weeks=i)).date().isoformat(),
             "net_noncomm": (i % 10) * 100 - 400, "open_interest": 10_000} for i in range(n)]
    rows[-1]["net_noncomm"] = last_value
    return rows


def test_cot_index_is_as_of_and_signed() -> None:
    rows = _cot_reports(80, 500)                    # el último = máximo -> idx 1
    last = datetime.fromisoformat(rows[-1]["report_date"]).replace(tzinfo=timezone.utc)
    opened = last + timedelta(days=4, hours=1)      # ya publicado (lag 4 días)
    assert cot_index_signed("EURUSD=X", "long", opened, rows) == pytest.approx(1.0)
    assert cot_index_signed("EURUSD=X", "short", opened, rows) == pytest.approx(-1.0)
    assert cot_index_signed("USDJPY=X", "long", opened, rows) == pytest.approx(-1.0)
    # 3 días después del reporte todavía NO se usa: manda el anterior (no es extremo)
    early = cot_index_signed("EURUSD=X", "long", last + timedelta(days=3), rows)
    assert early < 1.0
    assert cot_index_signed("EURUSD=X", "long", opened, rows[:40]) == 0.0   # < 52 reportes


def test_recent_strategy_r_never_looks_ahead() -> None:
    opened = datetime(2026, 10, 6, 14, tzinfo=timezone.utc)
    past = [_closed("mean_reversion", (opened - timedelta(hours=h)).isoformat(), 1.09902)
            for h in range(1, 7)]                          # 6 cerrados a -1R antes
    future = [_closed("mean_reversion", (opened + timedelta(hours=1)).isoformat(), 1.10402)]
    other = [_closed("forex_session_breakout", (opened - timedelta(hours=1)).isoformat(), 1.10402)]
    v = recent_strategy_r("mean_reversion", opened, past + future + other)
    assert v == pytest.approx(-0.5)                         # -1R / 2; el futuro no entra
    assert recent_strategy_r("mean_reversion", opened, past[:4]) == 0.0   # < 5


# ------------------------------------------------------------ modelo / tag
def test_v2_model_is_separate_from_v1() -> None:
    repo = _repo()
    v1 = AiAgent(_agent_settings(), repo)
    m1 = v1.load_model()
    m1.update([1.0] + [0.0] * (DIM - 1), 1.0)
    v1.save_model(m1)
    v2 = AiAgent(_v2_settings(), repo)
    assert v2.dim == DIM_V2 and v2.load_model().n == 0
    m2 = v2.load_model()
    m2.update([1.0] + [0.0] * (DIM_V2 - 1), -1.0)
    v2.save_model(m2)
    assert AiAgent(_agent_settings(), repo).load_model().n == 1    # v1 intacto
    assert repo.get_state(MODEL_STATE_KEY) != repo.get_state(MODEL_STATE_KEYS[2])


def test_policy_tag_matches_preregistration() -> None:
    assert AiAgent(_v2_settings(), _repo()).policy_tag() == PREREG_TAG
    assert AiAgent(_v2_settings(ai_agent_explore_pct=0.3), _repo()).policy_tag() != PREREG_TAG
    assert AiAgent(_agent_settings(), _repo()).policy_tag().startswith("v1|")


def test_choose_v1_is_exactly_decide() -> None:
    repo = _repo()
    agent = AiAgent(_agent_settings(ai_agent_explore_pct=0.9), repo)   # v1 ignora ε
    m, x = agent.load_model(), build_features(_paper_trade_row())
    for i in range(50):
        d = agent.choose(m, x, i)
        assert (d.mean, d.sd, d.sampled, d.intended) == agent.decide(m, x, i)
        assert d.intended != "explore"


def test_choose_v2_explores_only_what_it_would_skip() -> None:
    repo = _repo()
    s = _v2_settings(ai_agent_explore_pct=0.25)
    agent = AiAgent(s, repo)
    x = build_features_v2({**_paper_trade_row(), "opened_at": T0})
    _seed_v2(repo, s, x, -2.0)
    m = agent.load_model()
    picks = [agent.choose(m, x, i) for i in range(800)]
    assert agent.choose(m, x, 5) == agent.choose(m, x, 5)          # reproducible
    explored = [d for d in picks if d.intended == "explore"]
    assert all(d.intended in {"skip", "explore"} for d in picks)
    assert 0.20 < len(explored) / 800 < 0.30
    assert all(d.risk_cap_pct == pytest.approx(0.10) for d in explored)
    s0 = _v2_settings(ai_agent_explore_pct=0.0)
    assert all(AiAgent(s0, repo).choose(m, x, i).intended == "skip" for i in range(200))
    _seed_v2(repo, s, x, +2.0)
    good = agent.choose(agent.load_model(), x, 1)
    assert good.intended == "execute" and good.risk_cap_pct == pytest.approx(0.5)


def _decision(repo, pt, **kw):
    row = {"paper_trade_id": pt["id"], "created_at": utc_now().isoformat(),
           "features_json": "[]", "intended": "execute", "executed": True,
           "agent_version": 2}
    row.update(kw)
    did = repo.create_ai_agent_decision(row)
    return did


def test_realism_gap_shrinks_and_is_clipped() -> None:
    repo = _repo()
    agent = AiAgent(_v2_settings(), repo)
    assert agent.realism_gap() == 0.0
    for i in range(5):
        pt = _open_trade(repo, alert_id=500 + i)
        did = _decision(repo, pt)
        repo.update_ai_agent_decision(did, {"reward_r": -1.0, "mt5_r": -1.4, "mt5_status": "closed"})
    # 5 × (−0.4) / (5 + 5) = −0.2
    assert agent.realism_gap() == pytest.approx(-0.2)
    pt = _open_trade(repo, alert_id=600)
    did = _decision(repo, pt, agent_version=1)          # v1 no cuenta
    repo.update_ai_agent_decision(did, {"reward_r": -1.0, "mt5_r": 9.0, "mt5_status": "closed"})
    assert agent.realism_gap() == pytest.approx(-0.2)
    for i in range(40):
        pt = _open_trade(repo, alert_id=700 + i)
        did = _decision(repo, pt)
        repo.update_ai_agent_decision(did, {"reward_r": 3.0, "mt5_r": -3.0, "mt5_status": "closed"})
    assert agent.realism_gap() == -1.0                   # acotado


# ------------------------------------------------------------------ límites
def test_explore_budget_per_day_and_daily_stop() -> None:
    repo = _repo()
    s = _v2_settings(ai_agent_max_open=99, ai_agent_max_trades_per_day=99,
                     ai_agent_daily_stop_r=99, ai_agent_explore_max_per_day=2,
                     ai_agent_explore_daily_stop_r=1.5)
    agent = AiAgent(s, repo)
    now = utc_now()
    pts = [_open_trade(repo, alert_id=800 + i) for i in range(2)]
    for pt in pts:
        _decision(repo, pt, intended="explore")
    assert agent.guardrail_block(now) is None                       # explotar: libre
    assert "exploraciones por día" in agent.guardrail_block(now, kind="explore")
    s2 = _v2_settings(ai_agent_max_open=99, ai_agent_max_trades_per_day=99,
                      ai_agent_daily_stop_r=99, ai_agent_explore_max_per_day=9,
                      ai_agent_explore_daily_stop_r=1.5)
    for pt in pts:
        repo.update_paper_trade(int(pt["id"]), {"status": "closed_stop", "latest_price": 1.09902,
                                                "closed_at": now.isoformat()})
    assert "stop diario de exploración" in AiAgent(s2, repo).guardrail_block(now, kind="explore")


# -------------------------------------------------------------- aprendizaje
def test_learn_records_every_reward_but_updates_only_active_version() -> None:
    repo = _repo()
    s = _v2_settings()
    agent = AiAgent(s, repo)
    now = utc_now().isoformat()
    pt1 = _open_trade(repo, alert_id=900, opened_at=T0)
    pt2 = _open_trade(repo, alert_id=901, opened_at=T0)
    repo.create_ai_agent_decision({"paper_trade_id": pt1["id"], "created_at": now,
                                   "features_json": json.dumps(build_features(pt1)),
                                   "intended": "skip"})                         # v1
    repo.create_ai_agent_decision({"paper_trade_id": pt2["id"], "created_at": now,
                                   "features_json": json.dumps(build_features_v2(pt2)),
                                   "intended": "skip", "agent_version": 2})
    for pt in (pt1, pt2):
        repo.update_paper_trade(int(pt["id"]), {"status": "closed_target",
                                                "latest_price": 1.10202, "closed_at": now})
    assert agent.learn() == 1
    rows = {d["paper_trade_id"]: d for d in repo.fetch_ai_agent_decisions()}
    assert rows[pt1["id"]]["reward_r"] == pytest.approx(2.0, rel=1e-6)   # medido igual
    assert rows[pt2["id"]]["reward_r"] == pytest.approx(2.0, rel=1e-6)
    assert agent.load_model().n == 1 and AiAgent(_agent_settings(), repo).load_model().n == 0


# ------------------------------------------------------------ MT5 real (lectura)
def _fake_mt5_history(*, open_now=False, exit_deal=True, profit=-9.82, at_sl=-9.81):
    fake = _fake_mt5()
    fake.DEAL_ENTRY_IN, fake.DEAL_ENTRY_OUT, fake.DEAL_ENTRY_OUT_BY = 0, 1, 3
    fake.DEAL_TYPE_BUY = 0
    fake.positions_get = MagicMock(
        side_effect=lambda **kw: [SimpleNamespace(ticket=kw.get("ticket"))] if open_now else [])
    deals = [SimpleNamespace(entry=0, type=1, symbol="USDCAD", volume=0.1, price=1.42391,
                             profit=0.0, swap=0.0, commission=0.0, fee=0.0)]
    if exit_deal:
        deals.append(SimpleNamespace(entry=1, type=0, symbol="USDCAD", volume=0.1,
                                     price=1.42531, profit=profit, swap=0.0,
                                     commission=0.0, fee=0.0))
    fake.history_deals_get = MagicMock(return_value=deals)
    fake.order_calc_profit = MagicMock(return_value=at_sl)
    return fake


def test_closed_position_outcome_reads_real_pnl(monkeypatch) -> None:
    from tests.test_mt5_demo_trader import _demo_settings

    fake = _fake_mt5_history()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    out = MT5DemoTrader(_demo_settings()).closed_position_outcome(58767513767, 1.42530832)
    assert out["profit_usd"] == -9.82 and out["risk_usd"] == 9.81
    assert out["r"] == pytest.approx(-9.82 / 9.81, rel=1e-4)
    fake.history_deals_get.assert_called_with(position=58767513767)    # sin rango de fechas
    args = fake.order_calc_profit.call_args[0]
    assert args[0] == fake.ORDER_TYPE_SELL and args[2] == pytest.approx(0.1)
    assert not fake.order_send.called                                   # solo lectura
    for kw in ({"open_now": True}, {"exit_deal": False}):
        monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5_history(**kw))
        assert MT5DemoTrader(_demo_settings()).closed_position_outcome(1, 1.4) is None


def test_collect_mt5_outcomes_and_give_up() -> None:
    repo = _repo()
    agent = AiAgent(_v2_settings(), repo)
    factory = MagicMock()
    assert agent.collect_mt5_outcomes(factory) == 0 and not factory.called   # nada pendiente
    now = utc_now()
    pts, dids = [], []
    for i in range(2):
        pt = _open_trade(repo, alert_id=950 + i)
        req = repo.create_demo_trade_request({
            "paper_trade_id": pt["id"], "symbol": "EURUSD", "direction": "long",
            "volume": 0.01, "entry_price": 1.1, "stop_loss": 1.099, "take_profit": 1.102,
            "risk_pct": 0.1, "strategy_name": "ai_agent/x", "status": "sent", "reason": "t",
            "request_summary": "t", "created_at": now.isoformat(),
            "expires_at": now.isoformat()})
        repo.create_demo_order({
            "demo_request_id": req, "paper_trade_id": pt["id"], "symbol": "EURUSD",
            "direction": "long", "volume": 0.01, "price": 1.1, "stop_loss": 1.099,
            "take_profit": 1.102, "retcode": 10009, "order_ticket": 1000 + i,
            "deal_ticket": 2000 + i, "status": "sent", "strategy_name": "ai_agent/x",
            "result_summary": "ok", "sent_at": now.isoformat()})
        dids.append(_decision(repo, pt, demo_request_id=req))
        pts.append(pt)
    closed_long_ago = (now - timedelta(days=8)).isoformat()
    repo.update_paper_trade(int(pts[0]["id"]), {"status": "closed_stop", "latest_price": 1.09902,
                                                "closed_at": now.isoformat()})
    repo.update_paper_trade(int(pts[1]["id"]), {"status": "closed_stop", "latest_price": 1.09902,
                                                "closed_at": closed_long_ago})
    trader = MagicMock()
    trader.closed_position_outcome.side_effect = lambda ticket, sl: (
        {"r": -1.2, "profit_usd": -1.2} if ticket == 1000 else None)
    assert agent.collect_mt5_outcomes(lambda: trader) == 1
    rows = {d["id"]: d for d in repo.fetch_ai_agent_decisions()}
    assert rows[dids[0]]["mt5_r"] == -1.2 and rows[dids[0]]["mt5_status"] == "closed"
    assert rows[dids[1]]["mt5_r"] is None and rows[dids[1]]["mt5_status"] == "unavailable"
    assert agent.collect_mt5_outcomes(lambda: trader) == 0          # no reintenta


# ---------------------------------------------------------------- medición
def test_scoreboard_weights_exploration_by_risk() -> None:
    repo = _repo()
    agent = AiAgent(_v2_settings(), repo)
    assert agent.explore_weight() == pytest.approx(0.2)
    for i, (intended, r) in enumerate([("execute", 1.0), ("explore", -1.0), ("skip", -1.0)]):
        pt = _open_trade(repo, alert_id=1100 + i)
        did = _decision(repo, pt, intended=intended, executed=intended != "skip",
                        policy_tag=PREREG_TAG)
        repo.update_ai_agent_decision(did, {"reward_r": r, "rewarded_at": utc_now().isoformat()})
    sb = agent.scoreboard(version=2, policy_tag=PREREG_TAG)
    assert sb["policy_sum_r"] == pytest.approx(1.0 - 0.2)
    assert sb["exploit_sum_r"] == pytest.approx(1.0)
    assert sb["execute_all_mean_r"] == pytest.approx(-1.0 / 3)
    assert sb["explore_n"] == 1 and sb["intended_explore"] == 1
    assert agent.scoreboard(version=2, policy_tag="otro")["decisions"] == 0


# ------------------------------------------------------------- job: v2
def test_job_v2_explores_with_reduced_risk_and_records_tag(monkeypatch) -> None:
    fake = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    repo, notifier = _repo(), MagicMock()
    s = _v2_settings(ai_agent_explore_pct=1.0)
    pt = _open_trade(repo)
    _seed_v2(repo, s, build_features_v2(pt), -2.0)             # el modelo saltearía
    _StubJobV2(s, repo, notifier)._try_prepare_demo_order(pt)
    sent = fake.order_send.call_args[0][0]
    assert sent["magic"] == MT5DemoTrader.AGENT_MAGIC
    assert sent["comment"] == "TradingAlertAI agent explore"
    d = repo.fetch_ai_agent_decisions()[0]
    assert d["intended"] == "explore" and d["executed"] == 1 and d["agent_version"] == 2
    assert d["risk_cap_pct"] == pytest.approx(0.10) and d["policy_tag"].startswith("v2|eps1.00")
    assert len(json.loads(d["features_json"])) == DIM_V2
    req = repo.fetch_demo_trade_request(d["demo_request_id"])
    assert req["strategy_name"] == "ai_agent_explore/breakout" and req["risk_pct"] <= 0.10


def test_job_v2_explore_budget_blocks_order(monkeypatch) -> None:
    fake = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    repo = _repo()
    s = _v2_settings(ai_agent_explore_pct=1.0, ai_agent_explore_max_per_day=0)
    pt = _open_trade(repo)
    _seed_v2(repo, s, build_features_v2(pt), -2.0)
    _StubJobV2(s, repo, MagicMock())._try_prepare_demo_order(pt)
    assert not fake.order_send.called
    d = repo.fetch_ai_agent_decisions()[0]
    assert d["intended"] == "explore" and d["executed"] == 0
    assert "exploraciones por día" in d["block_reason"]


def test_job_v2_features_use_db_as_of(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    repo = _repo()
    s = _v2_settings(ai_agent_explore_pct=0.0)
    pt = _open_trade(repo, opened_at=T0)
    repo.upsert_economic_event({"event_time": "2026-10-06T14:30:00+00:00", "country": "USD",
                                "impact": "high", "title": "CPI"})
    repo.upsert_economic_event({"event_time": "2026-10-06T14:10:00+00:00", "country": "JPY",
                                "impact": "high", "title": "otra moneda"})   # no es del par
    for rd in _cot_reports(60, 500):
        repo.insert_cot_snapshot({**rd, "market_code": "EUR", "captured_at": "2026-10-01"})
    job = _StubJobV2(s, repo, MagicMock())
    extras = job._ai_agent_extras(pt)
    assert extras["event_near"] == pytest.approx(0.75)        # CPI a 30 min
    assert extras["strat_recent_r"] == 0.0                     # sin historia
    assert extras["cot_signed"] == pytest.approx(1.0)          # EUR en máximo, long EURUSD
    job._try_prepare_demo_order(pt)
    x = json.loads(repo.fetch_ai_agent_decisions()[0]["features_json"])
    assert len(x) == DIM_V2 and x[FEATURE_NAMES_V2.index("hour_cos")] == pytest.approx(
        math.cos(2 * math.pi * 14 / 24))
    assert x[FEATURE_NAMES_V2.index("event_near")] == pytest.approx(0.75)


def test_complete_d1_bars_drops_the_open_day() -> None:
    now = datetime(2026, 10, 6, 10, tzinfo=timezone.utc)
    day = lambda d: {"time": int(datetime(2026, 10, d, tzinfo=timezone.utc).timestamp())}
    assert [c["time"] for c in _complete_d1_bars([day(4), day(5), day(6)], now)] == [
        day(4)["time"], day(5)["time"]]


def test_live_d1_fallback_when_cache_is_stale(monkeypatch) -> None:
    repo = _repo()
    reader = MagicMock()
    reader._mt5 = SimpleNamespace(TIMEFRAME_D1=16408)
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    reader.get_rates.return_value = [
        {"time": int((t0 + timedelta(days=i)).timestamp()), "open": 1.0 + i * 1e-3,
         "high": 1.001 + i * 1e-3, "low": 0.999 + i * 1e-3, "close": 1.0 + i * 1e-3,
         "volume": 100.0} for i in range(300)]
    job = _StubJobV2(_v2_settings(), repo, MagicMock(), mt5_reader=reader)
    regime, _ = job._ai_agent_context({"symbol": "EURUSD=X"}, live_fallback=True)
    reader.get_rates.assert_called_with("EURUSD", 16408, 400)
    assert regime == "up"
    assert job._ai_agent_context({"symbol": "EURUSD=X"}) == (None, None)  # v1: sin fallback


def test_daily_summary_and_status_include_agent_v2() -> None:
    repo = _repo()
    s = _v2_settings(enable_daily_summary=True)
    job = _StubJobV2(s, repo, MagicMock())
    msg = job._format_daily_summary("2026-10-06", {"total": 0, "wins": 0, "losses": 0,
                                                   "net_r": 0.0})
    assert "Agente IA v2: hoy 0 candidatos" in msg
    text = AiAgent(s, repo).status_text("v3.14.0")
    assert "Versión del agente: v2" in text and "Pesos de las features nuevas" in text
    assert "Exploración hoy: OK" in text and "AGENTE_IA_V2_PREREGISTRO" in text
