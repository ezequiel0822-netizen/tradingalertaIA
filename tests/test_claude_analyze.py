"""v3.12.0 — tests de /claude_analyze (analisis tecnico narrado por LLM).

Read-only: solo texto. Reasoner FALSO (sin Ollama/Claude), snapshot FALSO (sin
Yahoo). Verifica gating por enable_llm_advisor, soft-fail (None -> mensaje
honesto), hint sin simbolo, y que el CONTEXTO nuevo (VWAP/velas/Hurst) llega
al prompt del reasoner. El LLM es analista secundario: el comando jamas toca
gates ni ordenes.
"""

from __future__ import annotations

from dataclasses import replace

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.models import TokenSnapshot
from tests.test_score import _settings


def _advisor_settings(**over):
    return replace(_settings(), enable_llm_advisor=True, **over)


class _FakeReasoner:
    def __init__(self, text="Estructura alcista pero extendida; falta confirmacion."):
        self._text = text
        self.calls = []

    def analyze_symbol(self, context):
        self.calls.append(context)
        return self._text


class _FakeRepo:
    def fetch_paper_trades(self, status=None, limit=20):
        return []


def _snapshot_with_candles() -> TokenSnapshot:
    # 30 velas de 15m del mismo dia UTC con volumen: VWAP + footprint reales.
    base_ts = 1_781_700_000  # epoch fijo (determinista)
    candles = [
        {"timestamp": base_ts + i * 900, "open": 100 + i * 0.2,
         "high": 100 + i * 0.2 + 0.5, "low": 100 + i * 0.2 - 0.5,
         "close": 100 + i * 0.2, "volume": 1000.0}
        for i in range(30)
    ]
    return TokenSnapshot(
        chain="stock", token_address="NVDA", category="stock", symbol="NVDA",
        raw={"candles": candles},
    )


def _assistant(rea, monkeypatch, snapshot=None):
    a = BasicTelegramAssistant(_advisor_settings(), _FakeRepo(), reasoner=rea)
    from app.collectors.stock_collector import StockCollector

    monkeypatch.setattr(
        StockCollector, "_fetch_symbol", lambda self, s: snapshot, raising=True
    )
    # sin red: news soft-fail (el comando debe seguir vivo sin titulares)
    from app.collectors.news_collector import NewsCollector

    monkeypatch.setattr(
        NewsCollector, "collect_for_symbol",
        lambda self, s: (_ for _ in ()).throw(RuntimeError("sin red")),
        raising=True,
    )
    return a


def test_disabled_returns_hint_and_skips_llm(monkeypatch) -> None:
    rea = _FakeReasoner()
    a = BasicTelegramAssistant(_settings(), _FakeRepo(), reasoner=rea)
    out = a.handle("/claude_analyze NVDA")
    assert "apagado" in out.lower()
    assert rea.calls == []


def test_no_symbol_returns_usage_hint(monkeypatch) -> None:
    rea = _FakeReasoner()
    a = BasicTelegramAssistant(_advisor_settings(), _FakeRepo(), reasoner=rea)
    out = a.handle("/claude_analyze")
    assert "ejemplo" in out.lower()
    assert rea.calls == []


def test_analysis_includes_new_features_in_context(monkeypatch) -> None:
    rea = _FakeReasoner(text="Precio sobre VWAP con vela fuerte.")
    a = _assistant(rea, monkeypatch, snapshot=_snapshot_with_candles())
    out = a.handle("/claude_analyze NVDA")
    assert "Precio sobre VWAP con vela fuerte." in out
    ctx = rea.calls[0]
    # el contexto lleva la foto tecnica NUEVA completa
    assert ctx["symbol"] == "NVDA"
    assert ctx["vwap_dist_pct"] is not None
    assert ctx["vwap_position"] in {"above", "below", "at"}
    assert "candle_strength" in ctx and "hurst_regime" in ctx
    assert ctx["news_label"] == "no_recent_news"  # news soft-fail no rompe


def test_llm_none_returns_honest_fallback(monkeypatch) -> None:
    rea = _FakeReasoner(text=None)
    a = _assistant(rea, monkeypatch, snapshot=_snapshot_with_candles())
    out = a.handle("/claude_analyze NVDA")
    assert "no pude generar" in out.lower()


def test_symbol_without_data(monkeypatch) -> None:
    rea = _FakeReasoner()
    a = _assistant(rea, monkeypatch, snapshot=None)
    out = a.handle("/claude_analyze XXXX")
    assert "no pude obtener" in out.lower()
    assert rea.calls == []


def test_alias_analisis_llm(monkeypatch) -> None:
    rea = _FakeReasoner(text="ok")
    a = _assistant(rea, monkeypatch, snapshot=_snapshot_with_candles())
    out = a.handle("/analisis_llm NVDA")
    assert "ok" in out


def test_reasoner_analyze_symbol_prompt_is_text_only() -> None:
    # El prompt del reasoner PROHIBE senales: contrato de analista secundario.
    from app.intelligence.reasoner import TradingReasoner

    captured = {}

    class _Proc:
        def generate(self, system, user, max_tokens=None):
            captured["system"] = system
            captured["user"] = user
            return "texto"

    rea = TradingReasoner(_advisor_settings(), processor=_Proc())
    out = rea.analyze_symbol({"symbol": "NVDA", "vwap_dist_pct": 0.4})
    assert out == "texto"
    assert "NO des senales" in captured["system"]
    assert "NVDA" in captured["user"]
    assert "VWAP" in captured["user"]
    assert "Hurst" in captured["user"]