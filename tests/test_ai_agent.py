"""v3.13.0 — agente IA en sandbox demo (app/ai_agent/ + wiring en jobs).

Cuentas demo simuladas (`_fake_mt5`): real-money sigue bloqueado por construcción.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import numpy as np
import pytest

from app.ai_agent.agent import MODEL_STATE_KEY, AiAgent
from app.ai_agent.features import DIM, FEATURE_NAMES, build_features
from app.ai_agent.model import R_CLIP, LinearThompson
from app.assistant.command_handler import BasicTelegramAssistant
from app.brokers.mt5_demo_trader import MT5DemoTrader
from app.config.settings import load_settings
from app.database.db import init_db
from app.database.repository import Repository
from app.scheduler.jobs import TradingAlertJob
from app.utils.time_utils import utc_now
from tests.test_auto_confirm_demo import _paper_trade_row
from tests.test_mt5_demo_trader import _demo_settings, _fake_mt5, _paper_trade


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"ai_agent_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _agent_settings(**overrides):
    base = {
        "enable_ai_agent": True,
        "enable_auto_confirm_demo": False,   # el agente ejecuta solo, sin este flag
        "demo_max_open_trades": 5,
    }
    return _demo_settings(**{**base, **overrides})


class _StubJob:
    def __init__(self, settings, repository, notifier, mt5_reader=None) -> None:
        self.settings = settings
        self.repository = repository
        self.notifier = notifier
        self.mt5_reader = mt5_reader

    _try_prepare_demo_order = TradingAlertJob._try_prepare_demo_order
    _auto_execute_demo_request = TradingAlertJob._auto_execute_demo_request
    _correct_paper_trade_notional = TradingAlertJob._correct_paper_trade_notional
    _ml_gate = TradingAlertJob._ml_gate
    _llm_ensemble_gate = TradingAlertJob._llm_ensemble_gate
    _ml_predictor = None
    _calendar_gate = TradingAlertJob._calendar_gate
    _usd_exposure_gate = TradingAlertJob._usd_exposure_gate
    _regime_gate = TradingAlertJob._regime_gate
    _vwap_gate = TradingAlertJob._vwap_gate
    _d1_candles_for_regime = TradingAlertJob._d1_candles_for_regime
    _ai_agent_path = TradingAlertJob._ai_agent_path
    _ai_agent_context = TradingAlertJob._ai_agent_context
    _ai_agent_block_reason = TradingAlertJob._ai_agent_block_reason
    _ai_agent_execute = TradingAlertJob._ai_agent_execute
    _maybe_ai_agent_learn = TradingAlertJob._maybe_ai_agent_learn


def _seed_model(repo: Repository, settings, x: list[float], reward: float, n: int = 300) -> None:
    m = LinearThompson(FEATURE_NAMES, settings.ai_agent_prior_var, settings.ai_agent_noise_var)
    for _ in range(n):
        m.update(x, reward)
    repo.set_state(MODEL_STATE_KEY, m.to_json())


def _open_trade(repo: Repository, alert_id: int = 101, **overrides) -> dict:
    row = {**_paper_trade_row(alert_id), **overrides}
    repo.create_paper_trade(row)
    return repo.fetch_paper_trade_by_alert_id(alert_id)


# ------------------------------------------------------------------- features
def test_features_dim_bias_and_missing_are_zero() -> None:
    x = build_features({"direction": "long"})
    assert len(x) == DIM == len(FEATURE_NAMES)
    assert x[0] == 1.0 and all(v == 0.0 for v in x[1:])


def test_features_one_hot_session_regime_and_signs() -> None:
    pt = {"strategy_name": "mean_reversion", "direction": "short", "category": "gold",
          "opened_at": "2026-10-05T13:00:00+00:00", "rsi_entry": 75.0, "atr_value": 6.0,
          "hurst_entry": 0.7, "clv_entry": 1.0}
    x = build_features(pt, regime="down", vwap_week_dist_pct=1.5)
    f = dict(zip(FEATURE_NAMES, x))
    assert f["strat_mean_reversion"] == 1.0 and f["strat_session_breakout"] == 0.0
    assert f["short"] == 1.0 and f["gold"] == 1.0 and f["sess_ldn_ny"] == 1.0
    assert f["regime_align"] == 1.0                 # short en régimen bajista = a favor
    assert f["vwap_week_signed"] == pytest.approx(-0.5)   # precio sobre VWAP pelea un short
    assert f["rsi_signed"] == pytest.approx(-0.5)
    assert f["atr_pct"] == 1.0                      # acotado
    assert f["hurst_centered"] == pytest.approx(0.4)
    assert f["clv_signed"] == pytest.approx(-1.0)   # cierre en el máximo pelea un short
    assert build_features({**pt, "direction": "long"}, regime="down")[10] == -1.0


# ---------------------------------------------------------------------- modelo
def test_model_posterior_equals_closed_form_ridge() -> None:
    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, DIM))
    y = rng.normal(size=50)
    m = LinearThompson(FEATURE_NAMES, prior_var=0.25, noise_var=1.5)
    for xi, yi in zip(X, y):
        m.update(xi, yi)
    A = np.eye(DIM) / 0.25 + X.T @ X / 1.5
    mu = np.linalg.solve(A, X.T @ y / 1.5)
    assert np.allclose(m.mean(), mu)
    mean, sd = m.predict(X[0])
    assert mean == pytest.approx(X[0] @ mu)
    assert sd == pytest.approx(np.sqrt(X[0] @ np.linalg.solve(A, X[0])))


def test_model_reward_clip_and_json_roundtrip() -> None:
    m = LinearThompson(FEATURE_NAMES)
    assert m.update([1.0] + [0.0] * (DIM - 1), 50.0) == R_CLIP[1]
    m2 = LinearThompson.from_json(m.to_json(), FEATURE_NAMES, 0.25, 1.0)
    assert m2.n == 1 and np.allclose(m2.A, m.A) and np.allclose(m2.b, m.b)
    # otro prior u otro set de features -> modelo nuevo (no mezcla)
    assert LinearThompson.from_json(m.to_json(), FEATURE_NAMES, 0.5, 1.0).n == 0
    assert LinearThompson.from_json(m.to_json(), FEATURE_NAMES[:-1], 0.25, 1.0).n == 0
    assert LinearThompson.from_json("basura{", FEATURE_NAMES, 0.25, 1.0).n == 0


def test_uncertainty_shrinks_with_experience() -> None:
    x = [1.0] + [0.0] * (DIM - 1)
    m = LinearThompson(FEATURE_NAMES)
    sd0 = m.predict(x)[1]
    for _ in range(100):
        m.update(x, 0.0)
    assert m.predict(x)[1] < sd0 / 5


# -------------------------------------------------------------------- decisión
def test_decide_is_reproducible_and_follows_the_model() -> None:
    repo = _repo()
    s = _agent_settings()
    agent = AiAgent(s, repo)
    x = build_features(_paper_trade_row())
    _seed_model(repo, s, x, +2.0)
    good = agent.load_model()
    assert agent.decide(good, x, 7) == agent.decide(good, x, 7)
    assert agent.decide(good, x, 7)[3] == "execute"
    _seed_model(repo, s, x, -2.0)
    assert agent.decide(agent.load_model(), x, 7)[3] == "skip"


def test_fresh_agent_explores_about_half() -> None:
    repo = _repo()
    agent = AiAgent(_agent_settings(), repo)
    m = agent.load_model()
    x = build_features(_paper_trade_row())
    picks = [agent.decide(m, x, i)[3] == "execute" for i in range(400)]
    assert 0.3 < sum(picks) / 400 < 0.6


# ------------------------------------------------------------- job: ejecución
def test_agent_executes_with_own_magic_and_records_decision(monkeypatch) -> None:
    fake = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    repo, notifier, s = _repo(), MagicMock(), _agent_settings()
    pt = _open_trade(repo)
    _seed_model(repo, s, build_features(pt), +2.0)
    _StubJob(s, repo, notifier)._try_prepare_demo_order(pt)

    sent = fake.order_send.call_args[0][0]
    assert sent["magic"] == MT5DemoTrader.AGENT_MAGIC
    assert sent["comment"] == "TradingAlertAI agent"
    d = repo.fetch_ai_agent_decisions()[0]
    assert d["intended"] == "execute" and d["executed"] == 1 and d["block_reason"] is None
    req = repo.fetch_demo_trade_request(d["demo_request_id"])
    assert req["status"] == "sent" and req["strategy_name"] == "ai_agent/breakout"
    assert "Agente IA: orden demo enviada" in notifier.send_message.call_args[0][0]


def test_agent_skip_sends_nothing_but_records(monkeypatch) -> None:
    fake = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    repo, s = _repo(), _agent_settings()
    pt = _open_trade(repo)
    _seed_model(repo, s, build_features(pt), -2.0)
    _StubJob(s, repo, MagicMock())._try_prepare_demo_order(pt)
    assert not fake.order_send.called
    d = repo.fetch_ai_agent_decisions()[0]
    assert d["intended"] == "skip" and d["executed"] == 0 and repo.fetch_demo_orders() == []
    # idempotente: el mismo candidato no se decide dos veces
    _StubJob(s, repo, MagicMock())._try_prepare_demo_order(pt)
    assert len(repo.fetch_ai_agent_decisions()) == 1


def test_agent_ignores_promotion_gate_but_not_risk_gates(monkeypatch) -> None:
    fake = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    repo, s = _repo(), _agent_settings(enable_strategy_promotion_gate=True)
    # promotion gate: 'breakout' con edge negativo PROBADO -> el camino normal no ejecutaría
    monkeypatch.setattr(Repository, "fetch_strategy_performance_for",
                        lambda self, a, b: {"trades": 300, "avg_r": -1.0})
    pt = _open_trade(repo)
    _seed_model(repo, s, build_features(pt), +2.0)
    _StubJob(s, repo, MagicMock())._try_prepare_demo_order(pt)
    assert fake.order_send.called                    # el agente decide por su cuenta

    fake2 = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake2)
    repo2 = _repo()
    pt2 = _open_trade(repo2)
    _seed_model(repo2, s, build_features(pt2), +2.0)
    job = _StubJob(s, repo2, MagicMock())
    job._calendar_gate = lambda trade: False         # evento de alto impacto cerca
    job._try_prepare_demo_order(pt2)
    assert not fake2.order_send.called
    d = repo2.fetch_ai_agent_decisions()[0]
    assert d["intended"] == "execute" and d["executed"] == 0
    assert "evento" in d["block_reason"]


def test_agent_decides_in_shadow_when_demo_trading_off(monkeypatch) -> None:
    fake = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    repo, s = _repo(), _agent_settings(enable_mt5_demo_trading=False)
    pt = _open_trade(repo)
    _seed_model(repo, s, build_features(pt), +2.0)
    _StubJob(s, repo, MagicMock())._try_prepare_demo_order(pt)
    assert not fake.order_send.called
    d = repo.fetch_ai_agent_decisions()[0]
    assert d["executed"] == 0 and "sombra" in d["block_reason"]


def test_agent_execution_error_is_recorded_not_raised(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    repo, s = _repo(), _agent_settings()
    pt = _open_trade(repo)
    _seed_model(repo, s, build_features(pt), +2.0)

    def boom(self):
        raise RuntimeError("terminal caído")

    monkeypatch.setattr(MT5DemoTrader, "positions", boom)
    _StubJob(s, repo, MagicMock())._try_prepare_demo_order(pt)   # no propaga
    d = repo.fetch_ai_agent_decisions()[0]
    assert d["intended"] == "execute" and d["executed"] == 0
    assert d["block_reason"] == "error: RuntimeError"


def test_agent_lot_is_shrunk_to_its_risk_cap(monkeypatch) -> None:
    fake = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    repo = _repo()
    # 1.0 lote = 1 % de riesgo con el MT5 falso; el agente admite 0.1 %
    s = _agent_settings(demo_max_lot=1.0, ai_agent_risk_pct=0.1)
    pt = _open_trade(repo)
    _seed_model(repo, s, build_features(pt), +2.0)
    _StubJob(s, repo, MagicMock())._try_prepare_demo_order(pt)
    sent = fake.order_send.call_args[0][0]
    assert sent["volume"] == pytest.approx(0.09)     # un step debajo de 0.1 (margen)


def test_trader_default_path_unchanged_and_rejects_unscalable_risk(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5())
    trader = MT5DemoTrader(_demo_settings(demo_max_lot=1.0))
    plain = trader.prepare_from_paper_trade(_paper_trade())
    assert plain.ok is False and "exceeds" in plain.reason   # sin tope: como antes
    tiny = trader.prepare_from_paper_trade(_paper_trade(), risk_cap_pct=0.001)
    assert tiny.ok is False and "lote mínimo" in tiny.reason


# ------------------------------------------------------------------ límites
def test_guardrails_max_open_per_day_and_daily_stop() -> None:
    repo = _repo()
    s = _agent_settings(ai_agent_max_open=2, ai_agent_max_trades_per_day=10,
                        ai_agent_daily_stop_r=1.5)
    agent = AiAgent(s, repo)
    now = utc_now()
    for i in range(2):
        pt = _open_trade(repo, alert_id=200 + i)
        repo.create_ai_agent_decision({"paper_trade_id": pt["id"], "created_at": now.isoformat(),
                                       "features_json": "[]", "intended": "execute",
                                       "executed": True})
    assert "posiciones" in agent.guardrail_block(now)
    # cierro ambas con -1R hoy -> stop diario (-2R <= -1.5R)
    for d in repo.fetch_ai_agent_decisions():
        repo.update_paper_trade(int(d["paper_trade_id"]),
                                {"status": "closed_stop", "latest_price": 1.09902,
                                 "closed_at": now.isoformat()})
    assert "stop diario" in agent.guardrail_block(now)
    s2 = _agent_settings(ai_agent_max_trades_per_day=2, ai_agent_daily_stop_r=99.0)
    assert "por día" in AiAgent(s2, repo).guardrail_block(now)


# -------------------------------------------------------------- aprendizaje
def test_learns_from_closed_trades_skips_artifacts_and_is_idempotent() -> None:
    repo = _repo()
    s = _agent_settings()
    agent = AiAgent(s, repo)
    now = utc_now().isoformat()
    ids = []
    for i, (status, latest) in enumerate([("closed_target", 1.10202),   # +2R
                                          ("closed_stop", 1.10002),     # artifact (no se movió)
                                          ("open", 1.10050)]):
        pt = _open_trade(repo, alert_id=300 + i)
        x = build_features(pt)
        repo.create_ai_agent_decision({"paper_trade_id": pt["id"], "created_at": now,
                                       "features_json": json.dumps(x), "intended": "skip"})
        upd = {"status": status, "latest_price": latest}
        if status != "open":
            upd["closed_at"] = now
        repo.update_paper_trade(int(pt["id"]), upd)
        ids.append(pt["id"])
    assert agent.learn() == 1
    rows = {d["paper_trade_id"]: d for d in repo.fetch_ai_agent_decisions()}
    assert rows[ids[0]]["reward_r"] == pytest.approx(2.0, rel=1e-6)
    assert rows[ids[1]]["reward_r"] is None and rows[ids[1]]["rewarded_at"] is not None
    assert rows[ids[2]]["rewarded_at"] is None          # sigue abierto: pendiente
    assert agent.load_model().n == 1
    assert agent.learn() == 0                           # no reaprende lo mismo
    sb = agent.scoreboard()
    assert sb["rewarded"] == 1 and sb["policy_sum_r"] == 0.0     # 'skip' -> 0R
    assert sb["execute_all_mean_r"] == pytest.approx(2.0, rel=1e-6)


# ------------------------------------------------------------- otros wiring
def test_agent_off_by_default(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.load_dotenv", lambda *a, **k: None)
    for k in ("ENABLE_AI_AGENT", "APP_VERSION", "AI_AGENT_VERSION", "AI_AGENT_EXPLORE_PCT",
              "PAPER_PRICE_FROM_MT5", "AI_AGENT_SHADOWS", "ENABLE_OPTIONS_COLLECTOR"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert s.enable_ai_agent is False and s.app_version.startswith("v3.16")
    # v3.14.0: v2 y la exploración también son opt-in (defaults = v1 tal cual)
    assert s.ai_agent_version == 1 and s.ai_agent_explore_pct == 0.0
    # v3.14.1 / v3.15.0: el precio de MT5 de punta a punta y las sombras, también opt-in
    assert s.paper_price_from_mt5 is False and s.ai_agent_shadows is False
    assert s.enable_options_collector is False          # v3.16.0: solo captura, opt-in


def test_ml_low_confidence_halves_lot_without_crashing(monkeypatch) -> None:
    """Fix v3.13.0: el draft es frozen; antes `draft.volume = x` lanzaba."""
    fake = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    repo = _repo()
    s = _demo_settings(enable_auto_confirm_demo=True, demo_max_lot=0.02)
    pt = _open_trade(repo)
    job = _StubJob(s, repo, MagicMock())
    job._ml_gate = lambda trade: (True, True)          # ML: confianza baja -> lote/2
    job._try_prepare_demo_order(pt)
    assert fake.order_send.call_args[0][0]["volume"] == pytest.approx(0.01)


def test_agente_command_reports_status() -> None:
    repo = _repo()
    text = BasicTelegramAssistant(_agent_settings(), repo).handle("/agente")
    assert "Agente IA (sandbox demo)" in text and "ENCENDIDO" in text
    assert "No operar" in text and "Real-money bloqueado" in text
