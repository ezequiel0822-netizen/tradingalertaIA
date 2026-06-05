"""v2.11.0 — tests de TradingReasoner (capa LLM asesora, read-only).

Usa un processor FALSO (no necesita Ollama). Verifica:
  - soft-fail total (advisor off, processor None/raise/sin generate) -> None
  - cuando hay texto, lo devuelve limpio (stripped)
  - INVARIANTE DE SEGURIDAD: el asesor solo produce texto; no expone ningun metodo
    que devuelva una decision/bool de ejecutar, y sus salidas son str|None.
"""

from __future__ import annotations

from dataclasses import replace

from app.intelligence.reasoner import TradingReasoner
from tests.test_score import _settings


def _advisor_settings(**over):
    return replace(_settings(), enable_llm_advisor=True, **over)


class _FakeProc:
    """Imita la primitiva publica `generate` de OllamaProcessor."""

    def __init__(self, reply="  Texto de prueba.  ", raises=False):
        self.reply = reply
        self.raises = raises
        self.calls = []

    def generate(self, system, user, max_tokens=None):
        self.calls.append((system, user, max_tokens))
        if self.raises:
            raise RuntimeError("boom")
        return self.reply


_MACRO = {"session": "london", "vix": 18.2, "dxy": 104.1, "wr_30d": 0.42}
_TRADE = {"symbol": "EURUSD", "direction": "long", "strategy_name": "breakout",
          "r_multiple": -1.0, "rsi_entry": 71.0, "atr_value": 1.2}
_SETUP = {"symbol": "XAUUSD", "strategy_name": "mean_reversion", "rsi": 28.0,
          "macd_state": "bullish", "prob_win": 0.61}


# --------------------------------------------------------------------------- #
def test_disabled_returns_none_even_with_working_processor() -> None:
    # enable_llm_advisor=False -> jamas llama al LLM.
    proc = _FakeProc()
    r = TradingReasoner(_settings(), processor=proc)
    assert r.assess_market(_MACRO) is None
    assert r.analyze_loss(_TRADE) is None
    assert r.explain_setup(_SETUP) is None
    assert proc.calls == []  # ni siquiera intento generar


def test_assess_market_returns_clean_text() -> None:
    proc = _FakeProc("  Mercado cauto hoy: VIX bajo, evita CPI.  ")
    r = TradingReasoner(_advisor_settings(), processor=proc)
    out = r.assess_market(_MACRO)
    assert out == "Mercado cauto hoy: VIX bajo, evita CPI."  # stripped
    assert len(proc.calls) == 1


def test_analyze_loss_returns_clean_text() -> None:
    proc = _FakeProc("RSI 71 en la entrada: comprado en sobrecompra. Mal setup.")
    r = TradingReasoner(_advisor_settings(), processor=proc)
    out = r.analyze_loss(_TRADE)
    assert out and "Mal setup" in out


def test_explain_setup_returns_clean_text() -> None:
    proc = _FakeProc("RSI 28 sugiere sobreventa en un rango; posible reversion.")
    r = TradingReasoner(_advisor_settings(), processor=proc)
    out = r.explain_setup(_SETUP)
    assert out and out.startswith("RSI 28")


def test_softfail_when_processor_returns_none() -> None:
    proc = _FakeProc(reply=None)
    r = TradingReasoner(_advisor_settings(), processor=proc)
    assert r.assess_market(_MACRO) is None


def test_softfail_when_processor_returns_blank() -> None:
    proc = _FakeProc(reply="   ")
    r = TradingReasoner(_advisor_settings(), processor=proc)
    assert r.analyze_loss(_TRADE) is None


def test_softfail_when_processor_raises() -> None:
    proc = _FakeProc(raises=True)
    r = TradingReasoner(_advisor_settings(), processor=proc)
    assert r.explain_setup(_SETUP) is None


def test_softfail_when_processor_has_no_generate() -> None:
    r = TradingReasoner(_advisor_settings(), processor=object())  # sin .generate
    assert r.assess_market(_MACRO) is None


def test_prompts_are_nonempty_and_in_spanish() -> None:
    proc = _FakeProc()
    r = TradingReasoner(_advisor_settings(), processor=proc)
    r.assess_market(_MACRO)
    system, user, _ = proc.calls[0]
    assert system and user
    assert "EURUSD" not in system  # el contexto va en el user, no en el system
    assert "Sesion" in user


def test_missing_fields_do_not_crash() -> None:
    # dicts vacios: _g rellena con 'N/A', nunca aplica format specs numericos.
    proc = _FakeProc("ok")
    r = TradingReasoner(_advisor_settings(), processor=proc)
    assert r.assess_market({}) == "ok"
    assert r.analyze_loss({}) == "ok"
    assert r.explain_setup({}) == "ok"


def test_safety_invariant_advisor_exposes_no_decision() -> None:
    # El asesor NO debe tener metodos de decision/ejecucion, y sus salidas son str|None.
    r = TradingReasoner(_advisor_settings(), processor=_FakeProc("texto"))
    for forbidden in ("decide", "should_execute", "vote", "ensemble_trade_decision",
                      "reason_about_trade", "predict_win_probability"):
        assert not hasattr(r, forbidden), f"el asesor NO debe exponer {forbidden}"
    for out in (r.assess_market(_MACRO), r.analyze_loss(_TRADE), r.explain_setup(_SETUP)):
        assert out is None or isinstance(out, str)
        assert not isinstance(out, bool)
