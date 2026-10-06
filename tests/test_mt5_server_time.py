"""v3.13.3 — hora del servidor MT5 -> UTC real.

MT5 entrega las epocas en HORA DEL SERVIDOR (MetaQuotes-Demo: EET, UTC+2 en
invierno / UTC+3 en verano, regla UE; medido 2026-10-06). Estos tests usan epocas
SINTETICAS de verano/invierno y de los cambios de hora, el lector con un modulo
MT5 falso, la migracion del cache y una regresion de forex_session_breakout en el
harness H1 (con sesiones corridas, la estrategia opera a la hora equivocada).
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.backtest.historical_loader import BacktestHistoricalLoader
from app.backtest.replay_harness import WARMUP_BARS, ReplayHarness, RunConfig
from app.brokers import mt5_time as mt
from app.brokers.mt5_reader import MT5Reader, MT5Timeframe
from app.database.db import init_db
from app.database.repository import Repository
from app.strategies.forex_session_breakout import ForexSessionBreakoutStrategy
from tests.test_score import _settings

_H = 3600
_API_H1 = 0x4001
_API_D1 = 0x4018


def _ts(*args) -> int:
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"mt5tz_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _eet_settings(tz: str = "EET"):
    return replace(_settings(), mt5_server_tz=tz)


# -- normalizacion y timeframes ---------------------------------------------


def test_normalize_server_tz_values() -> None:
    assert mt.normalize_server_tz("") == ""
    assert mt.normalize_server_tz(None) == ""
    assert mt.normalize_server_tz("utc") == ""
    assert mt.normalize_server_tz(" eet ") == "EET"
    assert mt.normalize_server_tz("ny+7") == "NY+7"
    assert mt.normalize_server_tz("UTC+2") == "UTC+2"
    assert mt.normalize_server_tz("utc-05") == "UTC-5"
    # typo -> sin conversion (nunca inventa un offset) y se marca como desconocido
    assert mt.normalize_server_tz("Europe/Athens") == ""
    assert mt.is_known_server_tz("Europe/Athens") is False
    assert mt.is_known_server_tz("") is True


def test_intraday_timeframes_minutes_and_api_constants() -> None:
    for tf in (1, 5, 15, 30, 60, 240, _API_H1, 0x4004, 0x400C):
        assert mt.is_intraday_timeframe(tf), tf
    for tf in (1440, _API_D1, 10080, 0x8001, 0xC001, 0, None, "x"):
        assert not mt.is_intraday_timeframe(tf), tf


# -- offsets: verano / invierno / cambios de hora ---------------------------


def test_eet_offsets_summer_winter_and_transitions() -> None:
    off = mt.utc_offset_seconds
    assert off("EET", _ts(2026, 7, 1, 12)) == 3 * _H   # verano
    assert off("EET", _ts(2026, 1, 15, 12)) == 2 * _H  # invierno
    # 2026: UE cambia el 29-mar y el 25-oct a las 01:00 UTC
    assert off("EET", _ts(2026, 3, 29, 0, 59, 59)) == 2 * _H
    assert off("EET", _ts(2026, 3, 29, 1)) == 3 * _H
    assert off("EET", _ts(2026, 10, 25, 0, 59, 59)) == 3 * _H
    assert off("EET", _ts(2026, 10, 25, 1)) == 2 * _H
    # Proximo cambio desde la medicion (6-oct-2026, UTC+3): domingo 25-oct
    assert off("EET", _ts(2026, 10, 6, 12)) == 3 * _H
    assert off("EET", _ts(2026, 10, 26, 12)) == 2 * _H


def test_eet_vs_ny7_differ_only_in_gap_weeks() -> None:
    # EE.UU. ya en verano (8-mar-2026) y la UE todavia no (29-mar)
    gap_march = _ts(2026, 3, 20, 12)
    assert mt.utc_offset_seconds("EET", gap_march) == 2 * _H
    assert mt.utc_offset_seconds("NY+7", gap_march) == 3 * _H
    # UE ya en invierno (26-oct-2025) y EE.UU. todavia no (2-nov)
    gap_oct = _ts(2025, 10, 31, 12)
    assert mt.utc_offset_seconds("EET", gap_oct) == 2 * _H
    assert mt.utc_offset_seconds("NY+7", gap_oct) == 3 * _H
    # fuera de esas semanas coinciden
    for t in (_ts(2026, 1, 15), _ts(2026, 7, 1), _ts(2025, 12, 1)):
        assert mt.utc_offset_seconds("EET", t) == mt.utc_offset_seconds("NY+7", t)
    # regla de EE.UU. anterior a 2007 (1er domingo de abril -> ultimo de octubre)
    assert mt.utc_offset_seconds("NY+7", _ts(2005, 3, 20, 12)) == 2 * _H
    assert mt.utc_offset_seconds("NY+7", _ts(2005, 4, 5, 12)) == 3 * _H


def test_fixed_offsets() -> None:
    assert mt.utc_offset_seconds("UTC+2", _ts(2026, 7, 1)) == 2 * _H
    assert mt.server_epoch_to_utc(_ts(2026, 7, 1, 10), "UTC+2") == _ts(2026, 7, 1, 8)
    assert mt.server_epoch_to_utc(_ts(2026, 7, 1, 10), "UTC-5") == _ts(2026, 7, 1, 15)
    assert mt.server_epoch_to_utc(_ts(2026, 7, 1, 10), "") == _ts(2026, 7, 1, 10)


def test_reproduces_the_agent_position_case() -> None:
    """Posicion 58767513767 (agente IA, USDCAD SELL): history_deals_get daba
    17:56:48 'UTC' y el bot la habia enviado a las 14:56 UTC -> +3 h (verano)."""
    server = _ts(2026, 10, 5, 17, 56, 48)
    assert mt.server_epoch_to_utc(server, "EET") == _ts(2026, 10, 5, 14, 56, 48)


@pytest.mark.parametrize("tz", ["EET", "NY+7"])
def test_round_trip_every_hour_2025_2026(tz: str) -> None:
    t = _ts(2025, 1, 1)
    end = _ts(2027, 1, 1)
    while t < end:
        server = mt.utc_to_server_epoch(t, tz)
        back = mt.server_epoch_to_utc(server, tz)
        # La hora repetida del fin del verano es ambigua: se resuelve como verano.
        ambiguous = mt.utc_offset_seconds(tz, t) == 2 * _H and mt.utc_offset_seconds(
            tz, t - _H
        ) == 3 * _H
        if not ambiguous:
            assert back == t, (tz, datetime.fromtimestamp(t, tz=timezone.utc))
        t += _H


@pytest.mark.parametrize(
    "tz, zone, extra",
    [("EET", "Europe/Athens", 0), ("NY+7", "America/New_York", 7 * _H)],
)
def test_matches_iana_tzdata_when_available(tz: str, zone: str, extra: int) -> None:
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        info = zoneinfo.ZoneInfo(zone)
    except Exception:  # sin tzdata en Windows
        pytest.skip("tzdata no disponible")
    t = _ts(2018, 1, 1)
    end = _ts(2027, 1, 1)
    while t < end:
        dt = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(info)
        expected = int(dt.utcoffset().total_seconds()) + extra
        assert mt.utc_offset_seconds(tz, t) == expected, (tz, dt)
        t += 6 * _H


def test_convert_candles_only_intraday() -> None:
    server = _ts(2026, 7, 1, 16)
    h1 = [{"time": server, "close": 1.1}]
    d1 = [{"time": _ts(2026, 7, 1), "close": 1.1}]
    assert mt.convert_candles_to_utc(h1, _API_H1, "EET")[0]["time"] == _ts(2026, 7, 1, 13)
    # D1 = etiqueta de fecha: NO se corre al dia anterior
    assert mt.convert_candles_to_utc(d1, _API_D1, "EET")[0]["time"] == _ts(2026, 7, 1)
    assert mt.convert_candles_to_utc(d1, 1440, "EET")[0]["time"] == _ts(2026, 7, 1)
    # sin zona: identico al comportamiento anterior
    raw = [{"time": server}]
    assert mt.convert_candles_to_utc(raw, _API_H1, "")[0]["time"] == server


# -- lector MT5 con modulo falso --------------------------------------------


def _fake_mt5(rows: list[dict], tick_time: int = 0, tick_msc: int = 0):
    calls: dict = {}

    def copy_rates_range(symbol, timeframe, start, end):
        calls["range"] = (start, end)
        return rows

    return SimpleNamespace(
        symbol_select=lambda symbol, enable: True,
        copy_rates_from_pos=lambda symbol, timeframe, pos, count: rows[-count:],
        copy_rates_range=copy_rates_range,
        symbol_info_tick=lambda symbol: SimpleNamespace(
            bid=1.1, ask=1.1001, last=0.0, time=tick_time, time_msc=tick_msc
        ),
        calls=calls,
    )


def _reader(settings, fake) -> MT5Reader:
    reader = MT5Reader(settings)
    reader._mt5 = fake
    reader._connected = True
    return reader


def _row(epoch: int) -> dict:
    return {"time": epoch, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15,
            "tick_volume": 10}


def test_reader_converts_intraday_and_ticks_with_eet() -> None:
    summer_server = _ts(2026, 7, 1, 16)
    winter_server = _ts(2026, 1, 15, 16)
    fake = _fake_mt5([_row(winter_server), _row(summer_server)], tick_time=summer_server)
    reader = _reader(_eet_settings(), fake)

    h1 = reader.get_rates("EURUSD", _API_H1, 2)
    assert [c["time"] for c in h1] == [_ts(2026, 1, 15, 14), _ts(2026, 7, 1, 13)]
    m1 = reader.get_rates("EURUSD", 1, 2)  # scalping engine (minutos)
    assert m1[-1]["time"] == _ts(2026, 7, 1, 13)
    d1 = reader.get_rates("EURUSD", _API_D1, 2)
    assert [c["time"] for c in d1] == [winter_server, summer_server]  # sin tocar
    assert reader.get_tick("EURUSD")["time"] == _ts(2026, 7, 1, 13)


def test_reader_without_tz_is_backward_compatible() -> None:
    server = _ts(2026, 7, 1, 16)
    reader = _reader(_settings(), _fake_mt5([_row(server)], tick_time=server))
    assert reader.server_tz == ""
    assert reader.get_rates("EURUSD", _API_H1, 1)[0]["time"] == server
    assert reader.get_tick("EURUSD")["time"] == server


def test_historical_range_request_in_server_time() -> None:
    """MT5 interpreta el rango en hora del servidor: los bordes UTC se corren +3 h
    en verano para que la ventana devuelta sea la pedida."""
    fake = _fake_mt5([_row(_ts(2026, 7, 1, 16))])
    reader = _reader(_eet_settings(), fake)
    start = datetime(2026, 7, 1, 10, tzinfo=timezone.utc)
    end = datetime(2026, 7, 1, 20)  # naive = UTC (convencion del proyecto)
    candles = reader.get_historical_range("EURUSD", MT5Timeframe.M15, start, end)
    req_start, req_end = fake.calls["range"]
    assert req_start == datetime(2026, 7, 1, 13, tzinfo=timezone.utc)
    assert req_end == datetime(2026, 7, 1, 23, tzinfo=timezone.utc)
    assert candles[0]["time"] == _ts(2026, 7, 1, 13)
    # D1: sin corrimiento (fechas)
    reader.get_historical_range("EURUSD", MT5Timeframe.D1, start, end)
    assert fake.calls["range"] == (start, end)


def test_measured_offset_and_mismatch_warning(monkeypatch, caplog) -> None:
    import app.brokers.mt5_reader as reader_mod

    now = 1_791_274_880.0
    monkeypatch.setattr(reader_mod, "time", SimpleNamespace(time=lambda: now))
    fake = _fake_mt5([], tick_msc=int((now + 3 * _H) * 1000))
    reader = _reader(_eet_settings("UTC+2"), fake)
    assert reader.measure_server_offset_seconds() == 3 * _H
    with caplog.at_level("WARNING"):
        reader._check_server_tz()
    assert "MT5_SERVER_TZ=UTC+2" in caplog.text
    # tick viejo (mercado cerrado): no hay medicion
    stale = _fake_mt5([], tick_msc=int((now - 50_000) * 1000))
    assert _reader(_eet_settings(), stale).measure_server_offset_seconds() is None


# -- diagnostico de la regla de DST -----------------------------------------


def _weekly_h1_server_epochs(tz: str, start: datetime, weeks: int) -> list[int]:
    """Velas H1 lun-vie de un servidor con zona `tz`: mercado abierto de
    domingo 17:00 NY a viernes 17:00 NY (via la regla de EE.UU.)."""
    epochs: list[int] = []
    t = int(start.timestamp())
    end = t + weeks * 7 * 24 * _H
    while t < end:
        ny = t - (4 if mt._us_dst(t) else 5) * _H  # NY como "UTC" naive
        ny_dt = datetime.fromtimestamp(ny, tz=timezone.utc)
        closed = (
            ny_dt.weekday() == 5
            or (ny_dt.weekday() == 4 and ny_dt.hour >= 17)
            or (ny_dt.weekday() == 6 and ny_dt.hour < 17)
        )
        if not closed:
            epochs.append(mt.utc_to_server_epoch(t, tz))
        t += _H
    return epochs


@pytest.mark.parametrize("true_tz", ["EET", "NY+7"])
def test_weekly_close_votes_identify_the_rule(true_tz: str) -> None:
    epochs = _weekly_h1_server_epochs(true_tz, datetime(2025, 1, 6, tzinfo=timezone.utc), 52)
    votes = mt.weekly_close_rule_votes(epochs)
    assert votes["n"] >= 49
    assert votes[true_tz] == votes["n"]
    other = "NY+7" if true_tz == "EET" else "EET"
    assert votes[other] < votes["n"]  # falla en las semanas de desfase UE/EE.UU.


# -- cache: marca de base horaria y migracion --------------------------------


def _h1_rows(start_utc: int, n: int, tz: str) -> list[dict]:
    """n velas H1 consecutivas expresadas en hora del servidor de `tz`."""
    return [
        {"time": mt.utc_to_server_epoch(start_utc + i * _H, tz), "open": 1.0,
         "high": 1.0, "low": 1.0, "close": 1.0 + i * 1e-5, "volume": 1}
        for i in range(n)
    ]


def test_migration_converts_in_place_marks_and_is_idempotent() -> None:
    repo = _repo()
    start = _ts(2026, 7, 1)
    repo.upsert_mt5_cache_candles("EURUSD", 60, _h1_rows(start, 48, "EET"))
    repo.upsert_mt5_cache_candles("EURUSD", 1440, [{"time": _ts(2026, 7, 1), "close": 1.0}])
    assert mt.cache_time_basis(repo, "EURUSD", 60) == "server"  # legacy sin marca

    dry = mt.migrate_series_to_utc(repo, "EURUSD", 60, "EET", apply=False)
    assert dry["rows"] == 48 and dry["applied"] is False
    assert repo.fetch_mt5_cache_depth("EURUSD", 60)["first_epoch"] == start + 3 * _H

    res = mt.migrate_series_to_utc(repo, "EURUSD", 60, "EET")
    assert res["applied"] is True and res["rows"] == 48
    rows = repo.fetch_mt5_cache_window("EURUSD", 60, 0, 9_999_999_999)
    assert [r["time"] for r in rows] == [start + i * _H for i in range(48)]
    assert rows[5]["close"] == pytest.approx(1.0 + 5e-5)  # OHLC intacto
    assert mt.cache_time_basis(repo, "EURUSD", 60) == "utc"
    # D1 no se toca
    assert repo.fetch_mt5_cache_window("EURUSD", 1440, 0, 9_999_999_999)[0]["time"] == _ts(2026, 7, 1)
    # idempotente
    again = mt.migrate_series_to_utc(repo, "EURUSD", 60, "EET")
    assert again["applied"] is False and "UTC" in again["reason"]
    assert repo.fetch_mt5_cache_depth("EURUSD", 60)["first_epoch"] == start


def test_rewrite_with_collisions_touches_nothing() -> None:
    repo = _repo()
    repo.upsert_mt5_cache_candles("EURUSD", 60, _h1_rows(_ts(2026, 7, 1), 5, "UTC+0"))
    res = repo.rewrite_mt5_cache_times(
        "EURUSD", 60, lambda t: 0, time_basis="utc", server_tz="EET"
    )
    assert res["collisions"] == 4 and res["applied"] is False
    assert repo.fetch_mt5_cache_depth("EURUSD", 60)["bars"] == 5
    assert repo.get_mt5_cache_time_basis("EURUSD", 60) is None


def test_ensure_basis_never_mixes_server_and_utc() -> None:
    repo = _repo()
    start = _ts(2026, 7, 1)
    repo.upsert_mt5_cache_candles("EURUSD", 60, _h1_rows(start, 10, "EET"))
    # legacy + escritura en UTC -> migra primero
    ok, note = mt.ensure_cache_time_basis(repo, "EURUSD", 60, "EET")
    assert ok and "migrado" in note
    assert repo.fetch_mt5_cache_depth("EURUSD", 60)["first_epoch"] == start
    # serie en UTC + escritura sin zona (hora del servidor) -> se niega
    ok, note = mt.ensure_cache_time_basis(repo, "EURUSD", 60, "")
    assert not ok and "MT5_SERVER_TZ" in note
    # D1 siempre se puede escribir (etiqueta de fecha)
    assert mt.ensure_cache_time_basis(repo, "EURUSD", 1440, "") == (True, "")


def test_loader_migrates_legacy_then_upserts_without_duplicates() -> None:
    """Cache legacy (hora servidor) + loader con MT5_SERVER_TZ=EET: la serie
    vieja se migra y las velas nuevas (ya en UTC) se superponen sin duplicar."""
    repo = _repo()
    start = _ts(2026, 7, 1)
    repo.upsert_mt5_cache_candles("EURUSD", 60, _h1_rows(start, 48, "EET"))
    server_rows = [
        {**r, "tick_volume": 1} for r in _h1_rows(start + 24 * _H, 48, "EET")
    ]
    reader = _reader(_eet_settings(), _fake_mt5(server_rows))
    loader = BacktestHistoricalLoader(_eet_settings(), repo, reader)

    depth = loader.load_symbol("EURUSD", MT5Timeframe.H1)

    assert depth.bars == 72  # 48 viejas + 24 nuevas (24 superpuestas)
    assert depth.time_basis == "utc"
    times = [r["time"] for r in repo.fetch_mt5_cache_window("EURUSD", 60, 0, 9_999_999_999)]
    assert times == [start + i * _H for i in range(72)]


def test_loader_without_tz_refuses_to_write_over_utc_series() -> None:
    repo = _repo()
    start = _ts(2026, 7, 1)
    repo.upsert_mt5_cache_candles("EURUSD", 60, _h1_rows(start, 10, "UTC+0"))
    repo.set_mt5_cache_time_basis("EURUSD", 60, "utc", "EET")
    reader = _reader(_settings(), _fake_mt5(_h1_rows(start + 100 * _H, 5, "EET")))
    depth = BacktestHistoricalLoader(_settings(), repo, reader).load_symbol(
        "EURUSD", MT5Timeframe.H1
    )
    assert depth.fetched_from_mt5 is False
    assert depth.bars == 10
    assert "MT5_SERVER_TZ" in depth.note


# -- regresion: forex_session_breakout H1 en el harness ----------------------


def _session_market(
    first_day: datetime, weekdays: int, breakout_hour_utc: int, hold_hours: int = 24
) -> list[dict]:
    """Mercado H1 sintetico en UTC real (lun-vie): rango asiatico 1.0990-1.1010
    de 00 a 08 UTC, quieto en 1.1000 y un breakout a 1.1030 a `breakout_hour_utc`
    que se sostiene `hold_hours` velas (default: hasta el fin del dia)."""
    rows: list[dict] = []
    day = first_day
    added = 0
    while added < weekdays:
        if day.weekday() < 5:
            for hour in range(24):
                t = int((day + timedelta(hours=hour)).timestamp())
                if hour < 8:
                    o, h, lo, c = 1.1000, 1.1010, 1.0990, 1.1000
                elif hour < breakout_hour_utc:
                    o, h, lo, c = 1.1000, 1.1004, 1.0996, 1.1000
                elif hour == breakout_hour_utc:
                    o, h, lo, c = 1.1000, 1.1035, 1.0998, 1.1030
                elif hour <= breakout_hour_utc + hold_hours:
                    o, h, lo, c = 1.1030, 1.1034, 1.1026, 1.1030
                else:
                    o, h, lo, c = 1.1000, 1.1004, 1.0996, 1.1000
                rows.append({"time": t, "open": o, "high": h, "low": lo,
                             "close": c, "tick_volume": 100})
            added += 1
        day += timedelta(days=1)
    return rows


def _run_session_breakout(settings, utc_rows: list[dict]) -> tuple[list[dict], dict]:
    """MT5 falso que entrega las velas en HORA DEL SERVIDOR (EET) -> lector con
    `settings` -> loader -> cache -> harness H1 con la estrategia REAL."""
    server_rows = [
        {**r, "time": mt.utc_to_server_epoch(r["time"], "EET")} for r in utc_rows
    ]
    repo = _repo()
    reader = _reader(settings, _fake_mt5(server_rows))
    BacktestHistoricalLoader(settings, repo, reader).load_symbol("EURUSD", MT5Timeframe.H1)
    harness = ReplayHarness(settings, repo)
    run_id = harness.run(
        RunConfig(mode="A", timeframe="H1", symbols=["EURUSD"],
                  strategies=["forex_session_breakout"]),
        strategies={"forex_session_breakout": ForexSessionBreakoutStrategy()},
    )
    import json

    run = repo.fetch_backtest_run(run_id)
    return repo.fetch_backtest_trades(run_id), json.loads(run["data_ranges_json"])


_WEEKDAYS = 25  # 600 barras H1 > WARMUP_BARS (266)


@pytest.mark.parametrize(
    "first_day",
    [datetime(2025, 6, 2, tzinfo=timezone.utc),    # verano: servidor UTC+3
     datetime(2025, 1, 6, tzinfo=timezone.utc)],   # invierno: servidor UTC+2
)
def test_session_breakout_inside_overlap_is_seen_only_in_utc(first_day) -> None:
    """Breakout a las 15:00 UTC (dentro del overlap 13-17 UTC). Con la hora del
    servidor la vela dice 17:00/18:00 -> la estrategia NO lo ve (bug)."""
    assert _WEEKDAYS * 24 > WARMUP_BARS + 2
    rows = _session_market(first_day, _WEEKDAYS, breakout_hour_utc=15)

    trades, ranges = _run_session_breakout(_eet_settings(), rows)
    assert ranges["EURUSD"]["time_basis"] == "utc"
    assert len(trades) >= 10
    for trade in trades:
        bar = datetime.fromtimestamp(int(trade["signal_bar_utc"]), tz=timezone.utc)
        assert bar.hour == 15 and trade["direction"] == "long"

    legacy_trades, legacy_ranges = _run_session_breakout(_settings(), rows)
    assert legacy_ranges["EURUSD"]["time_basis"] == "server"
    assert legacy_trades == []


def test_session_breakout_before_overlap_is_traded_only_with_server_time() -> None:
    """Breakout a las 10:00 UTC (ANTES del overlap) que revierte a las 13:00 UTC.
    En hora del servidor de verano esa vela dice 13:00 -> la version legacy opera
    fuera de la sesion London/NY."""
    rows = _session_market(
        datetime(2025, 6, 2, tzinfo=timezone.utc), _WEEKDAYS, 10, hold_hours=2
    )

    trades, _ = _run_session_breakout(_eet_settings(), rows)
    assert trades == []

    legacy_trades, _ = _run_session_breakout(_settings(), rows)
    assert len(legacy_trades) >= 10
    hours = {
        datetime.fromtimestamp(int(t["signal_bar_utc"]), tz=timezone.utc).hour
        for t in legacy_trades
    }
    assert hours == {13}  # "13:00" del servidor = 10:00 UTC real
