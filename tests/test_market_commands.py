"""v2.12.0 / Fase B — tests de /market y /porque_perdi (capa asesora en Telegram).

Read-only: solo texto. Usa un reasoner FALSO (sin Ollama) y un repo FALSO (sin DB).
Verifica el gating por `enable_llm_advisor`, el soft-fail (None -> mensaje), y que el
contexto correcto (incluidos rsi/atr del entry) llega al reasoner.
"""

from __future__ import annotations

from dataclasses import replace

from app.assistant.command_handler import BasicTelegramAssistant
from tests.test_score import _settings


def _advisor_settings(**over):
    return replace(_settings(), enable_llm_advisor=True, **over)


class _FakeReasoner:
    def __init__(self, market="Mercado cauto hoy.", loss="Mal setup: RSI alto."):
        self._market = market
        self._loss = loss
        self.calls = []

    def assess_market(self, macro):
        self.calls.append(("market", macro))
        return self._market

    def analyze_loss(self, trade):
        self.calls.append(("loss", trade))
        return self._loss


class _FakeRepo:
    def __init__(self, macro=None, trades=None):
        self._macro = macro
        self._trades = trades or []

    def fetch_latest_macro_snapshot(self):
        return self._macro

    def fetch_paper_trades(self, status=None, limit=20):
        return list(self._trades)


_MACRO_SNAP = {"regime": "risk_on", "vix_value": 18.0, "dxy_value": 104.0,
               "captured_at": "2026-06-04T12:00:00+00:00"}

# Long que perdio: latest < entry (no-artifact) y stop por debajo -> R<0.
_LOSER = {
    "symbol": "EURUSD", "direction": "long", "strategy_name": "breakout",
    "entry_price": 100.0, "latest_price": 95.0, "stop_loss": 98.0,
    "original_stop_loss": 98.0, "take_profit_1": 103.0, "take_profit_2": 105.0,
    "partial_closed": 0, "status": "stopped_simulated",
    "closed_at": "2026-06-04T12:00:00+00:00", "updated_at": "2026-06-04T12:00:00+00:00",
    "rsi_entry": 71.0, "atr_value": 1.2,
}


# ------------------------------- /market --------------------------------- #
def test_market_disabled_returns_hint_and_skips_llm() -> None:
    rea = _FakeReasoner()
    a = BasicTelegramAssistant(_settings(), _FakeRepo(_MACRO_SNAP), reasoner=rea)
    out = a.handle("/market")
    assert "apagado" in out.lower()
    assert rea.calls == []  # ni intento llamar al LLM


def test_market_returns_assessment_text_with_macro_context() -> None:
    rea = _FakeReasoner(market="VIX bajo, evita el CPI de las 12:30.")
    a = BasicTelegramAssistant(_advisor_settings(), _FakeRepo(_MACRO_SNAP), reasoner=rea)
    out = a.handle("/market")
    assert "VIX bajo, evita el CPI" in out
    kind, macro = rea.calls[0]
    assert kind == "market"
    assert macro["vix"] == 18.0 and macro["dxy"] == 104.0
    assert macro["session"]  # alguna sesion activa u 'off-hours'


def test_market_softfails_when_llm_returns_none() -> None:
    rea = _FakeReasoner(market=None)
    a = BasicTelegramAssistant(_advisor_settings(), _FakeRepo(_MACRO_SNAP), reasoner=rea)
    assert "no pude generar" in a.handle("/market").lower()


# ---------------------------- /porque_perdi ------------------------------ #
def test_loss_disabled_returns_hint() -> None:
    a = BasicTelegramAssistant(_settings(), _FakeRepo(trades=[_LOSER]), reasoner=_FakeReasoner())
    assert "apagado" in a.handle("/porque_perdi").lower()


def test_loss_review_uses_last_loser_with_entry_features() -> None:
    rea = _FakeReasoner(loss="Entraste con RSI 71 (sobrecompra). Mal setup.")
    a = BasicTelegramAssistant(_advisor_settings(), _FakeRepo(trades=[_LOSER]), reasoner=rea)
    out = a.handle("/porque_perdi")
    assert "EURUSD" in out and "Mal setup" in out
    kind, trade = rea.calls[0]
    assert kind == "loss"
    # los features del entry (Fase 0) viajan al reasoner:
    assert trade["rsi_entry"] == 71.0 and trade["atr_value"] == 1.2
    assert trade["r_multiple"] < 0


def test_loss_review_no_losers_skips_llm() -> None:
    rea = _FakeReasoner()
    a = BasicTelegramAssistant(_advisor_settings(), _FakeRepo(trades=[]), reasoner=rea)
    assert "no encontre" in a.handle("/porque_perdi").lower()
    assert rea.calls == []


def test_loss_review_softfails_when_llm_returns_none() -> None:
    rea = _FakeReasoner(loss=None)
    a = BasicTelegramAssistant(_advisor_settings(), _FakeRepo(trades=[_LOSER]), reasoner=rea)
    assert "no pude generar" in a.handle("/porque_perdi").lower()
