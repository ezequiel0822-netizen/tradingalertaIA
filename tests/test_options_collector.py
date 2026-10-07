"""v3.16.0 — colector de options flow (Yahoo). Sin red: Yahoo falso."""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.assistant.command_handler import BasicTelegramAssistant
from app.collectors import options_collector as oc
from app.collectors.options_collector import (
    OptionsFlowCollector,
    RateLimited,
    collector_symbols,
    compact_chain,
    summarize_chain,
    target_session_date,
)
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_score import _settings

SESSION = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)          # miércoles
T_SESSION = int(SESSION.timestamp())
DAY = 86400


def _repo() -> tuple[Repository, Path]:
    d = Path.cwd() / ".test_dbs" / f"opts_{uuid4().hex}"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "bot.db"
    init_db(p)
    return Repository(p), p


def _c(strike, vol, oi, px, iv=0.2):
    return {"strike": strike, "volume": vol, "openInterest": oi, "lastPrice": px,
            "impliedVolatility": iv, "bid": px - 0.05, "ask": px + 0.05,
            "lastTradeDate": T_SESSION, "inTheMoney": False, "contractSymbol": "X",
            "currency": "USD", "change": 0.1}


def _chain(spot=100.0, t=T_SESSION):
    near = {"expirationDate": t + 2 * DAY,                 # 2 días: no es la de referencia
            "calls": [_c(100, 50, 10, 1.0, 0.5)], "puts": [_c(100, 40, 10, 1.0, 0.5)]}
    ref = {"expirationDate": t + 10 * DAY,                 # 10 días: referencia
           "calls": [_c(95, 10, 100, 6.0, 0.22), _c(100, 300, 100, 2.0, 0.20),
                     _c(105, 1000, 50, 0.5, 0.18)],        # 105C: inusual (vol > OI, ≥ 100)
           "puts": [_c(95, 400, 1000, 0.8, 0.27), _c(100, 200, 100, 2.1, 0.21),
                    _c(105, 5, 5, 5.5, 0.00001)]}          # IV basura (Yahoo usa ~1e-5)
    return {"quote": {"regularMarketPrice": spot, "regularMarketTime": t, "currency": "USD",
                      "regularMarketVolume": 1000},
            "options": [near, ref]}


def _on(**kw):
    base = {"enable_options_collector": True, "options_collector_symbols": ["SPY", "QQQ"],
            "stock_symbols": ["aapl", "spy", "EURUSD=X"], "options_collector_symbols_per_cycle": 2,
            "options_collector_save_raw": False}          # los tests que lo usan lo prenden
    return replace(_settings(), **{**base, **kw})


# ------------------------------------------------------------- funciones puras
def test_target_session_window() -> None:
    wed = lambda h: datetime(2026, 10, 7, h, tzinfo=timezone.utc)
    assert target_session_date(wed(22)) == date(2026, 10, 7)
    assert target_session_date(wed(23)) == date(2026, 10, 7)
    assert target_session_date(wed(3)) == date(2026, 10, 6)       # completa la sesión del martes
    assert target_session_date(wed(12)) is None                   # de día: nada
    assert target_session_date(datetime(2026, 10, 10, 23, tzinfo=timezone.utc)) is None   # sábado
    assert target_session_date(datetime(2026, 10, 12, 2, tzinfo=timezone.utc)) is None    # dom → nada
    assert target_session_date(datetime(2026, 10, 10, 2, tzinfo=timezone.utc)) == date(2026, 10, 9)


def test_symbols_merge_etfs_and_stocks_without_fx() -> None:
    assert collector_symbols(_on()) == ["SPY", "QQQ", "AAPL"]
    assert collector_symbols(replace(_settings(), stock_symbols=[]))[:3] == ["SPY", "QQQ", "IWM"]


def test_summary_counts_unusual_iv_and_skew() -> None:
    s = summarize_chain("SPY", _chain(), SESSION)
    assert s["session_date"] == "2026-10-07" and s["n_expiries"] == 2 and s["n_contracts"] == 8
    assert s["call_volume"] == 50 + 10 + 300 + 1000 and s["put_volume"] == 40 + 400 + 200 + 5
    assert s["call_oi"] == 10 + 100 + 100 + 50 and s["put_oi"] == 10 + 1000 + 100 + 5
    assert s["call_premium"] == pytest.approx((50 * 1 + 10 * 6 + 300 * 2 + 1000 * 0.5) * 100)
    # inusual = volumen ≥ 100 y > OI: 105C (1000 > 50) y 100C (300 > 100); en puts 100P
    assert s["unusual_call_count"] == 2 and s["unusual_put_count"] == 1
    assert s["unusual_call_premium"] == pytest.approx((1000 * 0.5 + 300 * 2) * 100)
    # referencia = el vencimiento de ≥ 7 días; ATM = strike 100 (0.20 y 0.21)
    assert s["ref_expiry_days"] == pytest.approx(10.0)
    assert s["atm_iv"] == pytest.approx(0.205)
    assert s["skew_iv"] == pytest.approx(0.27 - 0.18)              # put 95 − call 105


def test_summary_ignores_garbage_iv_and_handles_empty() -> None:
    ch = _chain()
    ch["options"][1]["calls"][2]["impliedVolatility"] = 0.00001    # call 105 sin IV
    assert summarize_chain("SPY", ch, SESSION)["skew_iv"] is None  # sin vecino a ±3 %
    ch = _chain()
    ch["options"][1]["calls"][1]["impliedVolatility"] = 0.00001    # call ATM sin IV...
    ch["options"][1]["calls"].append(_c(101, 1, 1, 1.5, 0.19))      # ...vecino a 1 %
    assert summarize_chain("SPY", ch, SESSION)["atm_iv"] == pytest.approx((0.19 + 0.21) / 2)
    empty = summarize_chain("SPY", {"quote": {}, "options": []}, SESSION)
    assert empty["session_date"] is None and empty["atm_iv"] is None and empty["n_contracts"] == 0


def test_compact_chain_keeps_only_useful_fields() -> None:
    c = compact_chain("SPY", _chain(), SESSION)
    first = c["options"][0]["calls"][0]
    assert set(first) == set(oc.CONTRACT_FIELDS) and "contractSymbol" not in first
    assert c["quote"]["regularMarketPrice"] == 100.0


# ---------------------------------------------------------------- colector
class _FakeCollector(OptionsFlowCollector):
    def __init__(self, settings, chains: dict, fail: dict | None = None) -> None:
        super().__init__(settings, session=MagicMock(), pause_seconds=0)
        self.chains, self.fail, self.calls = chains, fail or {}, []

    def fetch_chain(self, symbol: str) -> dict:
        self.calls.append(symbol)
        f = self.fail.get(symbol)
        if f:
            raise f
        return self.chains[symbol]


def test_off_by_default_does_nothing() -> None:
    repo, _ = _repo()
    col = _FakeCollector(_settings(), {})
    assert _settings().enable_options_collector is False
    assert col.step(repo, datetime(2026, 10, 7, 22, 30, tzinfo=timezone.utc)) == 0
    assert col.calls == []


def test_incremental_capture_saves_summary_and_raw_and_is_idempotent() -> None:
    repo, db = _repo()
    col = _FakeCollector(_on(options_collector_save_raw=True, sqlite_path=db),
                         {s: _chain() for s in ("SPY", "QQQ", "AAPL")})
    now = datetime(2026, 10, 7, 22, 30, tzinfo=timezone.utc)
    assert col.step(repo, now) == 2 and col.calls == ["SPY", "QQQ"]          # 2 por ciclo
    assert col.step(repo, now) == 1 and col.calls[-1] == "AAPL"
    assert col.step(repo, now) == 0 and len(col.calls) == 3                 # ya completo
    st = repo.options_collection_stats()
    assert st == {"rows": 3, "days": 1, "first": "2026-10-07", "last": "2026-10-07",
                  "symbols_last_day": 3}
    raw = db.parent / "options_raw" / "2026-10-07" / "SPY.json.gz"
    with gzip.open(raw, "rt", encoding="utf-8") as fh:
        assert json.load(fh)["symbol"] == "SPY"
    assert repo.insert_options_snapshot(summarize_chain("SPY", _chain(), SESSION)) is False


def test_holiday_session_is_not_saved() -> None:
    repo, _ = _repo()
    stale = _chain(t=T_SESSION - DAY)                       # la cotización es del día anterior
    col = _FakeCollector(_on(options_collector_symbols=["SPY"], stock_symbols=[]), {"SPY": stale})
    assert col.step(repo, datetime(2026, 10, 7, 22, 30, tzinfo=timezone.utc)) == 0
    assert repo.options_collection_stats()["rows"] == 0
    col.step(repo, datetime(2026, 10, 7, 23, 0, tzinfo=timezone.utc))
    assert col.calls == ["SPY"]                             # no lo reintenta esa sesión


def test_errors_retry_up_to_three_times_then_give_up() -> None:
    repo, _ = _repo()
    col = _FakeCollector(_on(options_collector_symbols=["SPY"], stock_symbols=[]), {},
                         fail={"SPY": RuntimeError("boom")})
    now = datetime(2026, 10, 7, 22, 30, tzinfo=timezone.utc)
    for _ in range(5):
        assert col.step(repo, now) == 0
    assert col.calls == ["SPY"] * 3


def test_rate_limit_pauses_the_collector() -> None:
    repo, _ = _repo()
    col = _FakeCollector(_on(), {"QQQ": _chain()}, fail={"SPY": RateLimited()})
    now = datetime(2026, 10, 7, 22, 30, tzinfo=timezone.utc)
    assert col.step(repo, now) == 0 and col.calls == ["SPY"]               # cortó el lote
    assert col.step(repo, now) == 0 and col.calls == ["SPY"]               # en pausa


def test_new_session_resets_progress() -> None:
    repo, _ = _repo()
    col = _FakeCollector(_on(options_collector_symbols=["SPY"], stock_symbols=[]),
                         {"SPY": _chain()})
    col.step(repo, datetime(2026, 10, 7, 22, 30, tzinfo=timezone.utc))
    col.chains["SPY"] = _chain(t=T_SESSION + DAY)
    assert col.step(repo, datetime(2026, 10, 8, 22, 30, tzinfo=timezone.utc)) == 1
    assert repo.options_collection_stats()["days"] == 2


# --------------------------------------------------------------- HTTP (crumb)
class _Resp:
    def __init__(self, status: int, payload=None, text: str = "") -> None:
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise oc.requests.HTTPError(str(self.status_code))


def test_crumb_is_refreshed_once_on_401_and_429_raises() -> None:
    session = MagicMock()
    payload = {"optionChain": {"result": [{"quote": {"regularMarketTime": T_SESSION},
                                           "expirationDates": [], "options": []}]}}
    session.get.side_effect = [
        _Resp(404), _Resp(200, text="crumb1"),             # cookie + crumb
        _Resp(401),                                         # crumb vencido
        _Resp(404), _Resp(200, text="crumb2"),              # cookie + crumb nuevo
        _Resp(200, payload),
    ]
    col = OptionsFlowCollector(_on(), session=session, pause_seconds=0)
    assert col._get("SPY") == payload and col._crumb == "crumb2"
    session.get.side_effect = [_Resp(429)]
    with pytest.raises(RateLimited):
        col._get("SPY")


def test_fetch_chain_requests_only_expiries_within_limits() -> None:
    col = OptionsFlowCollector(_on(options_collector_max_expiries=3,
                                   options_collector_max_days=30), session=MagicMock(),
                               pause_seconds=0)
    exps = [T_SESSION + d * DAY for d in (1, 8, 15, 22, 45)]
    first = {"optionChain": {"result": [{"quote": {"regularMarketTime": T_SESSION},
                                         "expirationDates": exps,
                                         "options": [{"expirationDate": exps[0], "calls": [],
                                                      "puts": []}]}]}}
    asked = []

    def fake_get(symbol, expiry=None):
        asked.append(expiry)
        if expiry is None:
            return first
        return {"optionChain": {"result": [{"options": [{"expirationDate": expiry,
                                                         "calls": [], "puts": []}]}]}}

    col._get = fake_get
    chain = col.fetch_chain("SPY")
    assert asked == [None, exps[1], exps[2]]                # 3 vencimientos, ≤ 30 días
    assert [o["expirationDate"] for o in chain["options"]] == exps[:3]


# ------------------------------------------------------------ bot / Telegram
def test_opciones_command_shows_counts_but_never_values() -> None:
    repo, _ = _repo()
    repo.insert_options_snapshot(summarize_chain("SPY", _chain(), SESSION))
    a = BasicTelegramAssistant(_on(), repo)
    text = a.handle("/opciones")
    assert "ENCENDIDO" in text and "Sesiones guardadas: 1 (2026-10-07 -> 2026-10-07)" in text
    assert "1/3 simbolos" in text and "pre-registro" in text
    for leak in ("0.205", "1860", "put/call", "skew", "IV"):
        assert leak not in text
    assert "APAGADO" in BasicTelegramAssistant(_settings(), repo).handle("/opciones")


def test_job_wrapper_is_soft_fail() -> None:
    from app.scheduler.jobs import TradingAlertJob

    job = MagicMock()
    job.settings = _on()
    job.options_collector.step.side_effect = RuntimeError("yahoo caído")
    TradingAlertJob._maybe_collect_options(job)               # no propaga
    job.options_collector.step.assert_called_once()
    job.settings = _settings()
    job.options_collector.step.reset_mock()
    TradingAlertJob._maybe_collect_options(job)               # apagado: ni lo llama
    job.options_collector.step.assert_not_called()
