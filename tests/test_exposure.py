"""v3.5.0 — tests del cap de exposicion USD + calendar gate + comando /exposicion.

Cubre: usd_direction/net/would_exceed_cap (puras), los gates de jobs (downward-only,
opt-in OFF, soft-fail), el parsing nuevo de currencies_for_symbol (formato MT5 sin =X),
y el dispatch del comando. Nada de esto habilita ordenes: solo puede bajar a paper-only.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from app.assistant.command_handler import BasicTelegramAssistant
from app.intelligence.calendar_filter import currencies_for_symbol
from app.risk.exposure import net_usd_exposure, usd_direction, would_exceed_cap
from app.scheduler.jobs import TradingAlertJob
from app.utils.time_utils import utc_now
from tests.test_score import _settings


# ----------------------------- usd_direction ----------------------------- #
def test_usd_direction_usd_base_pairs():
    assert usd_direction("USDCAD=X", "long") == 1   # long USDCAD = long USD
    assert usd_direction("USDCHF", "short") == -1
    assert usd_direction("USDJPY=X", "long") == 1


def test_usd_direction_usd_quote_pairs():
    assert usd_direction("EURUSD=X", "long") == -1  # long EURUSD = short USD
    assert usd_direction("EURUSD", "short") == 1
    assert usd_direction("GBPUSD=X", "short") == 1
    assert usd_direction("AUDUSD", "long") == -1


def test_usd_direction_non_fx_is_zero():
    assert usd_direction("GC=F", "long") == 0       # oro: no entra al neto
    assert usd_direction("AAPL", "long") == 0
    assert usd_direction("", "long") == 0
    assert usd_direction("EURGBP", "long") == 0     # par sin pata USD


def test_net_usd_exposure_mix():
    opens = [
        {"symbol": "EURUSD=X", "direction": "short"},  # +1
        {"symbol": "GBPUSD=X", "direction": "short"},  # +1
        {"symbol": "USDCAD=X", "direction": "long"},   # +1
        {"symbol": "AUDUSD=X", "direction": "long"},   # -1
        {"symbol": "AAPL", "direction": "long"},       # 0
    ]
    assert net_usd_exposure(opens) == 2


# ---------------------------- would_exceed_cap ---------------------------- #
def _n_long_usd(n):
    return [{"symbol": "EURUSD=X", "direction": "short"} for _ in range(n)]


def test_cap_blocks_additional_concentration():
    blocked, reason = would_exceed_cap(_n_long_usd(3), "USDCAD=X", "long", max_net=3)
    assert blocked and "concentrada" in reason


def test_cap_allows_reducing_the_net():
    # neto +3; candidato long EURUSD (-1) REDUCE -> siempre pasa
    blocked, _ = would_exceed_cap(_n_long_usd(3), "EURUSD=X", "long", max_net=3)
    assert not blocked


def test_cap_allows_at_exact_cap():
    blocked, _ = would_exceed_cap(_n_long_usd(2), "USDCAD=X", "long", max_net=3)
    assert not blocked  # proyectado +3, |3| no excede |3|


def test_cap_symmetric_for_short_usd():
    shorts = [{"symbol": "USDCAD=X", "direction": "short"} for _ in range(3)]  # -3
    blocked, _ = would_exceed_cap(shorts, "EURUSD=X", "long", max_net=3)  # -> -4
    assert blocked


def test_cap_ignores_candidates_without_usd_leg():
    blocked, reason = would_exceed_cap(_n_long_usd(5), "GC=F", "long", max_net=3)
    assert not blocked and "sin pata USD" in reason


# --------------------- currencies_for_symbol (parsing) -------------------- #
def test_currencies_parses_mt5_format_without_suffix():
    assert currencies_for_symbol("EURUSD") == {"EUR", "USD"}   # scalping usa este formato
    assert currencies_for_symbol("eurusd=x") == {"EUR", "USD"}
    assert currencies_for_symbol("AAPL") == {"USD"}            # default conservador


# --------------------------- gates de jobs (stub) -------------------------- #
class _Repo:
    def __init__(self, opens=None, events=None, raise_on_fetch=False):
        self._opens = opens or []
        self._events = events or []
        self._raise = raise_on_fetch

    def fetch_open_positions_full(self):
        if self._raise:
            raise RuntimeError("boom")
        return list(self._opens)

    def has_successful_demo_order(self, tid):
        return True

    def fetch_economic_events_window(self, start_iso, end_iso, countries, impact):
        if self._raise:
            raise RuntimeError("boom")
        return list(self._events)


class _Stub:
    _calendar_gate = TradingAlertJob._calendar_gate
    _usd_exposure_gate = TradingAlertJob._usd_exposure_gate

    def __init__(self, settings, repository):
        self.settings = settings
        self.repository = repository


def _fx(symbol, direction, tid=1):
    return {"id": tid, "symbol": symbol, "direction": direction, "category": "forex"}


def test_exposure_gate_off_by_default_allows():
    job = _Stub(_settings(), _Repo(opens=[_fx("EURUSD=X", "short", i) for i in range(9)]))
    assert job._usd_exposure_gate(_fx("USDCAD=X", "long")) is True


def test_exposure_gate_blocks_concentration_when_enabled():
    s = replace(_settings(), enable_usd_exposure_cap=True, max_net_usd_exposure=3)
    opens = [_fx("EURUSD=X", "short", i) for i in range(3)]  # neto +3
    job = _Stub(s, _Repo(opens=opens))
    assert job._usd_exposure_gate(_fx("USDCAD=X", "long")) is False   # -> +4 bloquea
    assert job._usd_exposure_gate(_fx("EURUSD=X", "long")) is True    # reduce -> pasa


def test_exposure_gate_softfail_allows():
    s = replace(_settings(), enable_usd_exposure_cap=True)
    job = _Stub(s, _Repo(raise_on_fetch=True))
    assert job._usd_exposure_gate(_fx("USDCAD=X", "long")) is True


def test_calendar_gate_off_by_default_allows():
    event = {"event_time": (utc_now() + timedelta(minutes=10)).isoformat(),
             "title": "CPI m/m", "country": "USD"}
    job = _Stub(_settings(), _Repo(events=[event]))
    assert job._calendar_gate(_fx("EURUSD=X", "short")) is True


def test_calendar_gate_blocks_near_high_impact_event():
    s = replace(_settings(), enable_calendar_gate=True, enable_economic_calendar=True)
    event = {"event_time": (utc_now() + timedelta(minutes=10)).isoformat(),
             "title": "BOC Rate Statement", "country": "CAD"}
    job = _Stub(s, _Repo(events=[event]))
    assert job._calendar_gate(_fx("USDCAD=X", "long")) is False


def test_calendar_gate_allows_when_no_events():
    s = replace(_settings(), enable_calendar_gate=True, enable_economic_calendar=True)
    job = _Stub(s, _Repo(events=[]))
    assert job._calendar_gate(_fx("EURUSD=X", "short")) is True


def test_calendar_gate_softfail_allows():
    s = replace(_settings(), enable_calendar_gate=True, enable_economic_calendar=True)
    job = _Stub(s, _Repo(raise_on_fetch=True))
    assert job._calendar_gate(_fx("EURUSD=X", "short")) is True


# ------------------------- comando /exposicion ---------------------------- #
def test_exposure_command_dispatch_and_content():
    opens = [_fx("EURUSD=X", "short", 1), _fx("USDCAD=X", "long", 2)]
    bot = BasicTelegramAssistant(_settings(), _Repo(opens=opens))
    msg = bot.handle("/exposicion")
    assert "Exposicion neta USD" in msg
    assert "Neto: +2" in msg
    assert "EURUSD=X" in msg and "USDCAD=X" in msg
    assert "Exposicion neta USD" in bot.handle("/usd")  # alias
