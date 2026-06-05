"""v3.1.0 / Fase B p3 — tests del resumen diario por Telegram.

Read-only: solo manda texto. Bindea los metodos de jobs a un stub (sin construir el
job completo) + repo/notifier falsos + utc_now monkeypatcheado para el gate horario.
Los numeros se mandan siempre; la leccion LLM es opcional (requiere el asesor on).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import app.scheduler.jobs as jobs_mod
from app.intelligence.reasoner import TradingReasoner
from app.scheduler.jobs import TradingAlertJob
from tests.test_score import _settings


def _ds_settings(**over):
    return replace(_settings(), enable_daily_summary=True, daily_summary_hour_utc=21, **over)


class _FakeReasonerProc:
    def __init__(self, reply="Dia flojo. Leccion: evitar gold en NY."):
        self.reply = reply

    def generate(self, system, user, max_tokens=None, model=None):
        return self.reply


class _Notifier:
    def __init__(self):
        self.sent = []

    def send_message(self, msg):
        self.sent.append(msg)
        return True


class _FakeRepo:
    def __init__(self, trades=None, state=None, macro=None):
        self._trades = trades or []
        self._state = dict(state or {})
        self._macro = macro

    def get_state(self, key, default=None):
        return self._state.get(key, default)

    def set_state(self, key, value):
        self._state[key] = value

    def fetch_paper_trades(self, status=None, limit=20):
        return list(self._trades)

    def fetch_latest_macro_snapshot(self):
        return self._macro


class _Stub:
    _maybe_send_daily_summary = TradingAlertJob._maybe_send_daily_summary
    _today_trade_stats = TradingAlertJob._today_trade_stats
    _format_daily_summary = TradingAlertJob._format_daily_summary

    def __init__(self, settings, repository, notifier, claude_processor=None):
        self.settings = settings
        self.repository = repository
        self.notifier = notifier
        self.claude_processor = claude_processor


def _closed(symbol, entry, latest, stop, closed_at, direction="long"):
    return {"symbol": symbol, "direction": direction, "strategy_name": "breakout",
            "entry_price": entry, "latest_price": latest, "stop_loss": stop,
            "original_stop_loss": stop, "take_profit_1": entry * 1.02,
            "partial_closed": 0, "status": "closed", "closed_at": closed_at,
            "updated_at": closed_at}


def _fix_hour(monkeypatch, hour):
    fixed = datetime(2026, 6, 5, hour, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(jobs_mod, "utc_now", lambda: fixed)
    return fixed.date().isoformat()


# ---------------------- TradingReasoner.daily_summary -------------------- #
def test_daily_summary_text_when_advisor_on() -> None:
    r = TradingReasoner(replace(_settings(), enable_llm_advisor=True),
                        processor=_FakeReasonerProc())
    assert r.daily_summary({"total": 3, "wins": 1, "losses": 2, "net_r": -1.0})


def test_daily_summary_none_when_advisor_off() -> None:
    r = TradingReasoner(_settings(), processor=_FakeReasonerProc())  # advisor off
    assert r.daily_summary({"total": 3, "wins": 1, "losses": 2, "net_r": -1.0}) is None


# --------------------------- _today_trade_stats -------------------------- #
def test_today_stats_counts_only_today_closed() -> None:
    today = "2026-06-05"
    trades = [
        _closed("EURUSD", 100.0, 103.0, 99.0, f"{today}T15:00:00+00:00"),    # win
        _closed("GBPUSD", 100.0, 95.0, 99.0, f"{today}T16:00:00+00:00"),     # loss
        _closed("USDJPY", 100.0, 110.0, 99.0, "2026-06-04T16:00:00+00:00"),  # ayer
    ]
    job = _Stub(_ds_settings(), _FakeRepo(trades=trades), _Notifier())
    stats = job._today_trade_stats(today)
    assert stats["total"] == 2 and stats["wins"] == 1 and stats["losses"] == 1


# ------------------------------- gating ---------------------------------- #
def test_no_send_when_disabled(monkeypatch) -> None:
    _fix_hour(monkeypatch, 22)
    notifier = _Notifier()
    job = _Stub(_settings(), _FakeRepo(), notifier)  # daily_summary off
    job._maybe_send_daily_summary()
    assert notifier.sent == []


def test_no_send_before_cutoff_hour(monkeypatch) -> None:
    _fix_hour(monkeypatch, 10)  # antes de las 21 UTC
    notifier = _Notifier()
    job = _Stub(_ds_settings(), _FakeRepo(), notifier)
    job._maybe_send_daily_summary()
    assert notifier.sent == []


def test_no_resend_when_already_sent_today(monkeypatch) -> None:
    today = _fix_hour(monkeypatch, 22)
    notifier = _Notifier()
    repo = _FakeRepo(state={"daily_summary_last_date": today})
    job = _Stub(_ds_settings(), repo, notifier)
    job._maybe_send_daily_summary()
    assert notifier.sent == []


def test_sends_once_and_marks_date(monkeypatch) -> None:
    today = _fix_hour(monkeypatch, 22)
    trades = [_closed("EURUSD", 100.0, 95.0, 99.0, f"{today}T16:00:00+00:00")]
    notifier = _Notifier()
    repo = _FakeRepo(trades=trades)
    job = _Stub(_ds_settings(), repo, notifier)
    job._maybe_send_daily_summary()
    assert len(notifier.sent) == 1
    assert "Resumen del dia - 2026-06-05" in notifier.sent[0]
    assert repo.get_state("daily_summary_last_date") == today
    job._maybe_send_daily_summary()  # mismo dia -> no re-manda
    assert len(notifier.sent) == 1


# -------------------------- _format_daily_summary ------------------------ #
def test_format_includes_numbers_no_lesson_when_advisor_off() -> None:
    job = _Stub(_ds_settings(), _FakeRepo(), _Notifier())  # advisor off
    msg = job._format_daily_summary(
        "2026-06-05", {"total": 2, "wins": 1, "losses": 1, "net_r": -0.5}
    )
    assert "Trades cerrados: 2" in msg
    assert "R neto del dia: -0.50" in msg


def test_format_appends_lesson_when_advisor_on() -> None:
    job = _Stub(_ds_settings(enable_llm_advisor=True), _FakeRepo(macro={"vix_value": 18.0}),
                _Notifier(), claude_processor=_FakeReasonerProc("Leccion del dia."))
    msg = job._format_daily_summary(
        "2026-06-05", {"total": 1, "wins": 0, "losses": 1, "net_r": -1.0}
    )
    assert "Leccion del dia." in msg
