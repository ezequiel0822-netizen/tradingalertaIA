"""v3.2.0 / Fase C — tests del ContinuousLearner (leccion por trade + propuestas).

Usa repo/reasoner/notifier FALSOS (no necesita Ollama ni DB real). Verifica:
  - gating: requiere enable_continuous_learner AND store_trade_lessons.
  - win -> analyze_win; loss -> analyze_loss; outcome y lesson_key correctos.
  - exclusiones: artifacts y trades que ya tienen leccion (idempotencia).
  - soft-fail: si el reasoner devuelve None (advisor off / Ollama caido) -> no registra.
  - cap por ciclo respetado.
  - propuesta: cuando N lecciones comparten clave -> UNA propuesta; dedupe via bot_state.
  - INVARIANTE: el learner solo registra/propone; no expone ejecucion de ordenes.
"""

from __future__ import annotations

from dataclasses import replace

from app.learning.continuous_learner import ContinuousLearner
from tests.test_score import _settings


def _cl_settings(**over):
    return replace(
        _settings(),
        enable_continuous_learner=True,
        store_trade_lessons=True,
        enable_llm_advisor=True,
        **over,
    )


class _FakeReasoner:
    """Imita TradingReasoner: solo analyze_win / analyze_loss -> texto o None."""

    def __init__(self, win="Buen setup repetible.", loss="Mal setup: RSI alto."):
        self._win = win
        self._loss = loss
        self.win_calls = []
        self.loss_calls = []

    def analyze_win(self, ctx):
        self.win_calls.append(ctx)
        return self._win

    def analyze_loss(self, ctx):
        self.loss_calls.append(ctx)
        return self._loss


class _Notifier:
    def __init__(self):
        self.sent = []

    def send_message(self, msg):
        self.sent.append(msg)
        return True


class _FakeRepo:
    def __init__(self, trades=None, lessoned=None, state=None):
        self._trades = trades or []
        self._lessoned_ids = set(lessoned or [])
        self._lessons = []  # dicts insertados
        self._state = dict(state or {})

    # -- lo que usa el learner -- #
    def fetch_trade_lesson_ids(self):
        return set(self._lessoned_ids)

    def fetch_closed_paper_trades(self, limit=500):
        return list(self._trades)

    def insert_trade_lesson(self, lesson):
        if lesson["paper_trade_id"] in self._lessoned_ids:
            return False
        self._lessoned_ids.add(lesson["paper_trade_id"])
        self._lessons.append(lesson)
        return True

    def count_trade_lessons_by_key(self, key):
        return sum(1 for x in self._lessons if x.get("lesson_key") == key)

    def get_state(self, key, default=None):
        return self._state.get(key, default)

    def set_state(self, key, value):
        self._state[key] = value


def _trade(tid, *, entry, latest, ostop, direction="long", strategy="forex_session_breakout",
           category="forex", status="closed_by_time"):
    return {
        "id": tid, "symbol": "EURUSD", "category": category, "direction": direction,
        "strategy_name": strategy, "entry_price": entry, "latest_price": latest,
        "stop_loss": ostop, "original_stop_loss": ostop, "take_profit_1": entry * 1.02,
        "partial_closed": 0, "status": status, "opened_at": "2026-06-05T14:00:00+00:00",
        "closed_at": "2026-06-05T16:00:00+00:00", "rsi_entry": 71.0, "atr_value": 0.8,
    }


def _win(tid, **over):
    return _trade(tid, entry=100.0, latest=103.0, ostop=99.0, **over)  # r = +3.0


def _loss(tid, **over):
    return _trade(tid, entry=100.0, latest=98.0, ostop=99.0, **over)  # r = -2.0


# ------------------------------- gating ---------------------------------- #
def test_disabled_when_master_flag_off():
    repo = _FakeRepo(trades=[_win(1)])
    s = ContinuousLearner(
        replace(_cl_settings(), enable_continuous_learner=False), repo,
        reasoner=_FakeReasoner(), notifier=_Notifier(),
    ).run()
    assert s.enabled is False
    assert repo._lessons == []


def test_disabled_when_store_flag_off():
    repo = _FakeRepo(trades=[_win(1)])
    reasoner = _FakeReasoner()
    s = ContinuousLearner(
        replace(_cl_settings(), store_trade_lessons=False), repo,
        reasoner=reasoner, notifier=_Notifier(),
    ).run()
    assert s.enabled is False
    assert repo._lessons == []
    assert reasoner.win_calls == []  # ni siquiera analiza


# --------------------------- registro de lecciones ----------------------- #
def test_win_trade_creates_lesson_with_analyze_win():
    repo = _FakeRepo(trades=[_win(1)])
    reasoner = _FakeReasoner()
    s = ContinuousLearner(_cl_settings(), repo, reasoner=reasoner, notifier=_Notifier()).run()
    assert s.lessons_created == 1
    assert len(reasoner.win_calls) == 1 and reasoner.loss_calls == []
    lesson = repo._lessons[0]
    assert lesson["outcome"] == "win"
    assert lesson["lesson_key"] == "forex_session_breakout|forex|long|win"
    assert lesson["paper_trade_id"] == 1
    assert lesson["lesson"] == "Buen setup repetible."
    # el contexto que recibe el reasoner trae el R y la sesion derivados
    ctx = reasoner.win_calls[0]
    assert ctx["r_multiple"] == 3.0 and ctx["session"]


def test_loss_trade_uses_analyze_loss():
    repo = _FakeRepo(trades=[_loss(2)])
    reasoner = _FakeReasoner()
    ContinuousLearner(_cl_settings(), repo, reasoner=reasoner, notifier=_Notifier()).run()
    assert len(reasoner.loss_calls) == 1 and reasoner.win_calls == []
    assert repo._lessons[0]["outcome"] == "loss"


# ------------------------------ exclusiones ------------------------------ #
def test_artifact_excluded():
    # latest == entry -> artifact (precio congelado) -> no se aprende de el.
    artifact = _trade(3, entry=100.0, latest=100.0, ostop=99.0)
    repo = _FakeRepo(trades=[artifact])
    reasoner = _FakeReasoner()
    s = ContinuousLearner(_cl_settings(), repo, reasoner=reasoner, notifier=_Notifier()).run()
    assert s.lessons_created == 0 and repo._lessons == []
    assert reasoner.win_calls == [] and reasoner.loss_calls == []


def test_already_lessoned_trade_skipped():
    repo = _FakeRepo(trades=[_win(1)], lessoned=[1])  # ya tiene leccion
    reasoner = _FakeReasoner()
    s = ContinuousLearner(_cl_settings(), repo, reasoner=reasoner, notifier=_Notifier()).run()
    assert s.lessons_created == 0
    assert reasoner.win_calls == []  # no lo reanaliza


def test_scratch_trade_skipped():
    # entry == latest daria artifact; uso un movimiento nulo de R via stop == entry?
    # Mejor: r exactamente 0 no es facil; uso un trade con riesgo invalido -> r None.
    bad = _trade(4, entry=100.0, latest=101.0, ostop=100.0)  # risk 0 -> r None
    repo = _FakeRepo(trades=[bad])
    s = ContinuousLearner(_cl_settings(), repo, reasoner=_FakeReasoner(), notifier=_Notifier()).run()
    assert s.lessons_created == 0


# ------------------------------- soft-fail ------------------------------- #
def test_softfail_when_reasoner_returns_none():
    repo = _FakeRepo(trades=[_win(1)])
    reasoner = _FakeReasoner(win=None)  # advisor off / Ollama caido
    s = ContinuousLearner(_cl_settings(), repo, reasoner=reasoner, notifier=_Notifier()).run()
    assert s.lessons_created == 0 and s.skipped_no_text == 1
    assert repo._lessons == []  # no registra sin texto -> reintenta luego


# --------------------------------- cap ----------------------------------- #
def test_cap_per_cycle_respected():
    repo = _FakeRepo(trades=[_win(10), _win(11), _win(12)])
    reasoner = _FakeReasoner()
    s = ContinuousLearner(
        _cl_settings(), repo, reasoner=reasoner, notifier=_Notifier(), max_per_cycle=2
    ).run()
    assert s.lessons_created == 2
    assert len(reasoner.win_calls) == 2  # no analiza mas alla del cap


# ------------------------------ propuestas ------------------------------- #
def test_proposal_when_threshold_reached():
    repo = _FakeRepo(trades=[_win(20), _win(21)])  # misma clave
    notifier = _Notifier()
    ContinuousLearner(
        _cl_settings(), repo, reasoner=_FakeReasoner(), notifier=notifier,
        max_per_cycle=5, proposal_threshold=2,
    ).run()
    assert len(notifier.sent) == 1
    assert "PROPUESTA" in notifier.sent[0]
    assert "forex_session_breakout|forex|long|win" in notifier.sent[0]
    # dedupe persistido
    assert repo.get_state("cl_proposed::forex_session_breakout|forex|long|win")


def test_proposal_not_repeated_when_already_proposed():
    key = "forex_session_breakout|forex|long|win"
    repo = _FakeRepo(trades=[_win(30), _win(31)], state={f"cl_proposed::{key}": "x"})
    notifier = _Notifier()
    ContinuousLearner(
        _cl_settings(), repo, reasoner=_FakeReasoner(), notifier=notifier,
        max_per_cycle=5, proposal_threshold=2,
    ).run()
    assert notifier.sent == []  # ya estaba propuesta -> no re-propone


def test_proposal_below_threshold_is_silent():
    repo = _FakeRepo(trades=[_win(40)])
    notifier = _Notifier()
    ContinuousLearner(
        _cl_settings(), repo, reasoner=_FakeReasoner(), notifier=notifier,
        proposal_threshold=10,
    ).run()
    assert notifier.sent == []


# ----------------------- invariante de seguridad ------------------------- #
def test_learner_exposes_no_execution():
    # El learner registra y PROPONE; jamas ejecuta/abre/modifica ordenes.
    learner = ContinuousLearner(_cl_settings(), _FakeRepo(), reasoner=_FakeReasoner())
    for forbidden in ("order_send", "open_trade", "execute", "apply_change",
                      "place_order", "send_prepared_request"):
        assert not hasattr(learner, forbidden), f"el learner NO debe exponer {forbidden}"
