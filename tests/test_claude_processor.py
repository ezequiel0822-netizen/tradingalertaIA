"""Tests para ClaudeProcessor soft-fail + behavior con mocks."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.intelligence.claude_processor import ClaudeProcessor
from tests.test_score import _settings


def _enable_claude(base):
    return type(base)(
        **{
            **base.__dict__,
            "enable_claude_integration": True,
            "anthropic_api_key": "sk-ant-test-fake",
        }
    )


def _fake_anthropic_module(response_text: str = "Test response"):
    fake = types.ModuleType("anthropic")
    fake_client = MagicMock()
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text=response_text)],
        usage=SimpleNamespace(input_tokens=50, output_tokens=20),
    )
    fake_client.messages.create.return_value = fake_response
    fake.Anthropic = MagicMock(return_value=fake_client)
    return fake


def test_disabled_returns_none() -> None:
    settings = _settings()  # enable_claude_integration=False
    p = ClaudeProcessor(settings)
    assert p.is_available() is False
    assert p.summarize_news([{"title": "test"}], "NVDA") is None
    assert p.expand_pro_analysis(None, None) is None
    assert p.interpret_free_text("hola", []) is None


def test_no_api_key_returns_none() -> None:
    base = _settings()
    settings = type(base)(
        **{**base.__dict__, "enable_claude_integration": True, "anthropic_api_key": None}
    )
    p = ClaudeProcessor(settings)
    assert p.is_available() is False
    assert p.summarize_news([{"title": "test"}], "NVDA") is None


def test_import_failure_soft_fails(monkeypatch) -> None:
    settings = _enable_claude(_settings())
    monkeypatch.setitem(sys.modules, "anthropic", None)
    p = ClaudeProcessor(settings)
    assert p.is_available() is False


def test_summarize_news_calls_api(monkeypatch) -> None:
    settings = _enable_claude(_settings())
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("Noticias bullish"))
    p = ClaudeProcessor(settings)
    result = p.summarize_news(
        [{"title": "Earnings beat by 30%"}, {"title": "Upgrade target $200"}],
        "NVDA",
    )
    assert result == "Noticias bullish"


def test_expand_pro_returns_text(monkeypatch) -> None:
    settings = _enable_claude(_settings())
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("Setup alcista solido"))
    p = ClaudeProcessor(settings)
    pro = SimpleNamespace(bias="bullish", score=80, setup="breakout")
    snapshot = SimpleNamespace(symbol="NVDA")
    result = p.expand_pro_analysis(pro, snapshot)
    assert result == "Setup alcista solido"


def test_interpret_free_text_returns_command(monkeypatch) -> None:
    settings = _enable_claude(_settings())
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("/pro NVDA"))
    p = ClaudeProcessor(settings)
    result = p.interpret_free_text("que opinas de nvda", ["/pro SIMBOLO", "/analiza"])
    assert result == "/pro NVDA"


def test_throttle_respects_cap(monkeypatch) -> None:
    base = _enable_claude(_settings())
    settings = type(base)(**{**base.__dict__, "claude_calls_per_cycle_cap": 2})
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module("ok"))
    p = ClaudeProcessor(settings)
    # 2 llamadas distintas pasan (diferentes prompts → cache no se hit)
    r1 = p.summarize_news([{"title": "T1"}], "A")
    r2 = p.summarize_news([{"title": "T2"}], "B")
    r3 = p.summarize_news([{"title": "T3"}], "C")
    assert r1 == "ok"
    assert r2 == "ok"
    # Tercera bloqueada por cap
    assert r3 is None


def test_cache_returns_stored(monkeypatch) -> None:
    settings = _enable_claude(_settings())
    fake = _fake_anthropic_module("cached")
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    p = ClaudeProcessor(settings)
    # Llamada 1 hace API call real
    r1 = p.summarize_news([{"title": "same"}], "NVDA")
    # Llamada 2 con mismo input → cache hit, NO incrementa _calls_this_cycle
    r2 = p.summarize_news([{"title": "same"}], "NVDA")
    assert r1 == r2 == "cached"
    assert p._calls_this_cycle == 1  # solo una API call real
