"""v2.10.0 — OllamaProcessor (LLM local, gratis) + factory de proveedor.

Mockea `requests` (no necesita Ollama corriendo). Verifica soft-fail total: si
Ollama no responde, todo retorna None y el bot sigue igual. El LLM solo enriquece
texto; no toca decisiones de trading.
"""

from __future__ import annotations

from dataclasses import replace

import requests

from app.intelligence import ollama_processor  # noqa: F401 (asegura import)
from app.intelligence.claude_processor import ClaudeProcessor
from app.intelligence.ollama_processor import OllamaProcessor, build_llm_processor
from tests.test_score import _settings


def _ollama_settings(**over):
    return replace(_settings(), enable_ollama_integration=True, **over)


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("http err")

    def json(self):
        return self._payload


def _ok_ping(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, {"models": []}))


def _pro_snap():
    pro = type("P", (), {"bias": "bull", "score": 80, "setup": "range breakout"})()
    snap = type("S", (), {"symbol": "EURUSD"})()
    return pro, snap


def test_not_available_when_flag_off() -> None:
    p = OllamaProcessor(_settings())  # enable_ollama_integration=False
    assert p.is_available() is False


def test_available_when_reachable(monkeypatch) -> None:
    _ok_ping(monkeypatch)
    p = OllamaProcessor(_ollama_settings())
    assert p.is_available() is True


def test_not_available_when_ollama_down(monkeypatch) -> None:
    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", boom)
    p = OllamaProcessor(_ollama_settings())
    assert p.is_available() is False  # soft-fail


def test_call_returns_text_on_success(monkeypatch) -> None:
    _ok_ping(monkeypatch)
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: _Resp(200, {"message": {"content": "  Sesgo alcista claro.  "}}),
    )
    p = OllamaProcessor(_ollama_settings())
    pro, snap = _pro_snap()
    assert p.expand_pro_analysis(pro, snap) == "Sesgo alcista claro."


def test_softfail_when_post_raises(monkeypatch) -> None:
    _ok_ping(monkeypatch)

    def boom(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr(requests, "post", boom)
    p = OllamaProcessor(_ollama_settings())
    assert p.summarize_news([{"title": "Fed sube tasas"}], "EURUSD") is None


def test_softfail_when_http_error(monkeypatch) -> None:
    _ok_ping(monkeypatch)
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(500, {}))
    p = OllamaProcessor(_ollama_settings())
    assert p.summarize_news([{"title": "x"}], "EURUSD") is None


def test_throttle_cap(monkeypatch) -> None:
    _ok_ping(monkeypatch)
    counter = {"n": 0}

    def post(*a, **k):
        counter["n"] += 1
        return _Resp(200, {"message": {"content": f"r{counter['n']}"}})

    monkeypatch.setattr(requests, "post", post)
    p = OllamaProcessor(_ollama_settings(ollama_calls_per_cycle_cap=2))
    a = p.interpret_free_text("aaa", ["/pro"])
    b = p.interpret_free_text("bbb", ["/pro"])
    c = p.interpret_free_text("ccc", ["/pro"])  # excede el cap
    assert a is not None and b is not None and c is None
    p.reset_cycle()
    assert p.interpret_free_text("ddd", ["/pro"]) is not None


def test_estimated_cost_is_zero() -> None:
    assert OllamaProcessor(_ollama_settings()).estimated_cost_today() == 0.0


def test_factory_picks_ollama_when_enabled() -> None:
    assert isinstance(build_llm_processor(_ollama_settings()), OllamaProcessor)


def test_factory_falls_back_to_claude_when_ollama_off() -> None:
    # con ollama off, el factory devuelve ClaudeProcessor (que soft-failea si no hay key)
    assert isinstance(build_llm_processor(_settings()), ClaudeProcessor)
