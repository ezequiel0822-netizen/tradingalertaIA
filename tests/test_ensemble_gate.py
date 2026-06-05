"""v3.0.0 / Fase B p2 — tests del veto del ensemble LLM en el gate.

Mockea el processor LLM (sin Ollama). Verifica:
  - SUBTRACTIVO: el unico output fuerte es un VETO; jamas habilita nada.
  - soft-fail total -> NO veta (flag off / sin processor / errores / ambiguo).
  - veta si CUALQUIERA de los dos modelos marca red flag.
  - aislamiento: el error de un modelo no descarta el flag del otro.
  - el hook de jobs (_llm_ensemble_gate) baja a paper-only solo cuando hay veto.
"""

from __future__ import annotations

from dataclasses import replace

from app.intelligence.ensemble_gate import ensemble_veto, _says_red_flag
from app.scheduler.jobs import TradingAlertJob
from tests.test_score import _settings


def _ens_settings(**over):
    return replace(_settings(), enable_llm_ensemble=True, **over)


class _FakeProc:
    def __init__(self, by_model=None, raises_for=(), default="NO"):
        self.by_model = by_model or {}
        self.raises_for = set(raises_for)
        self.default = default
        self.calls = []

    def generate(self, system, user, max_tokens=None, model=None):
        self.calls.append(model)
        if model in self.raises_for:
            raise RuntimeError("boom")
        return self.by_model.get(model, self.default)


_CTX = {"symbol": "EURUSD", "direction": "long", "strategy_name": "breakout",
        "entry": 1.1, "stop": 1.099, "tp": 1.102, "session": "london",
        "rsi": 71.0, "atr": 1.2, "vix": 18.0}


# ------------------------- _says_red_flag parsing ------------------------ #
def test_says_red_flag_parsing() -> None:
    assert _says_red_flag("SI")
    assert _says_red_flag("Sí, hay riesgo")
    assert _says_red_flag("  'si'. ")
    assert _says_red_flag("yes")
    assert not _says_red_flag("NO")
    assert not _says_red_flag("no hay red flags")
    assert not _says_red_flag("tal vez")
    assert not _says_red_flag(None)
    assert not _says_red_flag("")


# ----------------------------- ensemble_veto ----------------------------- #
def test_no_veto_when_disabled() -> None:
    proc = _FakeProc(by_model={"llama3.1": "SI", "mistral": "SI"})
    veto, _ = ensemble_veto(_settings(), _CTX, proc)  # flag off
    assert veto is False
    assert proc.calls == []  # ni intento llamar al LLM


def test_no_veto_when_processor_has_no_generate() -> None:
    veto, _ = ensemble_veto(_ens_settings(), _CTX, object())
    assert veto is False


def test_no_veto_when_processor_none() -> None:
    veto, _ = ensemble_veto(_ens_settings(), _CTX, None)
    assert veto is False


def test_veto_when_primary_flags() -> None:
    proc = _FakeProc(by_model={"llama3.1": "SI", "mistral": "NO"})
    veto, reason = ensemble_veto(_ens_settings(), _CTX, proc)
    assert veto is True
    assert "llama3.1" in reason


def test_veto_when_second_model_flags() -> None:
    proc = _FakeProc(by_model={"llama3.1": "NO", "mistral": "SI"})
    veto, reason = ensemble_veto(_ens_settings(), _CTX, proc)
    assert veto is True
    assert "mistral" in reason


def test_no_veto_when_both_say_no() -> None:
    proc = _FakeProc(by_model={"llama3.1": "NO", "mistral": "NO"})
    veto, _ = ensemble_veto(_ens_settings(), _CTX, proc)
    assert veto is False
    assert proc.calls == ["llama3.1", "mistral"]  # consulto ambos


def test_no_veto_when_ambiguous_or_none() -> None:
    proc = _FakeProc(by_model={"llama3.1": "tal vez", "mistral": None})
    veto, _ = ensemble_veto(_ens_settings(), _CTX, proc)
    assert veto is False


def test_softfail_no_veto_when_all_models_raise() -> None:
    proc = _FakeProc(raises_for=("llama3.1", "mistral"))
    veto, _ = ensemble_veto(_ens_settings(), _CTX, proc)
    assert veto is False  # soft-fail -> no veta


def test_per_model_isolation_keeps_surviving_flag() -> None:
    # primario marca red flag, el segundo revienta -> el flag del primario sobrevive.
    proc = _FakeProc(by_model={"llama3.1": "SI"}, raises_for=("mistral",))
    veto, reason = ensemble_veto(_ens_settings(), _CTX, proc)
    assert veto is True and "llama3.1" in reason


def test_same_primary_and_second_model_consulted_once() -> None:
    proc = _FakeProc(by_model={"llama3.1": "NO"})
    veto, _ = ensemble_veto(_ens_settings(ollama_second_model="llama3.1"), _CTX, proc)
    assert veto is False
    assert proc.calls == ["llama3.1"]  # dedupe: no consulta el mismo modelo 2 veces


# --------------------- hook de jobs (_llm_ensemble_gate) ----------------- #
class _Stub:
    _llm_ensemble_gate = TradingAlertJob._llm_ensemble_gate

    def __init__(self, settings, claude_processor, repository):
        self.settings = settings
        self.claude_processor = claude_processor
        self.repository = repository


class _FakeRepo:
    def fetch_latest_macro_snapshot(self):
        return {"vix_value": 18.0}


_PT = {"symbol": "EURUSD", "direction": "long", "strategy_name": "breakout",
       "entry_price": 1.1, "stop_loss": 1.099, "take_profit_1": 1.102,
       "opened_at": "2026-06-04T10:00:00+00:00", "rsi_entry": 71.0, "atr_value": 1.2}


def test_hook_allows_when_disabled() -> None:
    proc = _FakeProc(by_model={"llama3.1": "SI"})
    job = _Stub(_settings(), proc, _FakeRepo())  # ensemble off
    assert job._llm_ensemble_gate(_PT) is True
    assert proc.calls == []


def test_hook_vetoes_when_model_flags() -> None:
    proc = _FakeProc(by_model={"llama3.1": "SI", "mistral": "NO"})
    job = _Stub(_ens_settings(), proc, _FakeRepo())
    assert job._llm_ensemble_gate(_PT) is False  # veto -> paper-only


def test_hook_allows_when_no_flags() -> None:
    proc = _FakeProc(by_model={"llama3.1": "NO", "mistral": "NO"})
    job = _Stub(_ens_settings(), proc, _FakeRepo())
    assert job._llm_ensemble_gate(_PT) is True


def test_hook_softfails_to_allow_on_error() -> None:
    proc = _FakeProc(raises_for=("llama3.1", "mistral"))
    job = _Stub(_ens_settings(), proc, _FakeRepo())
    assert job._llm_ensemble_gate(_PT) is True  # soft-fail -> sin cambios
