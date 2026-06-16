"""Tests del stock_historical_loader (ESPEC_BACKTEST_STOCKS_v1 §9, S1).

Lo central: un SPLIT conocido NO debe fabricar un gap espurio (se usa adjusted
close). Mas: soft-fail sin data / ante error de red, y persistencia + medicion
de profundidad. Yahoo se mockea (sin red en los tests).
"""

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import requests

from app.backtest.stock_historical_loader import (
    StockHistoricalLoader,
    fetch_yahoo_daily,
)
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_score import _settings

_DAY = 86_400


def _yahoo_payload(ts, opens, highs, lows, closes, adjcloses, volumes):
    return {"chart": {"result": [{
        "timestamp": ts,
        "indicators": {
            "quote": [{"open": opens, "high": highs, "low": lows,
                       "close": closes, "volume": volumes}],
            "adjclose": [{"adjclose": adjcloses}],
        },
    }]}}


def _session(payload=None, error=None):
    sess = MagicMock()
    if error is not None:
        sess.get.side_effect = error
        return sess
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    sess.get.return_value = resp
    return sess


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"stockloader_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_split_does_not_fabricate_a_gap() -> None:
    # 2 barras PRE-split (raw ~400, adjclose 100) + 2 POST-split (raw ~100,
    # adjclose 100). Crudo: salto 4:1 (400 -> 100). Ajustado: continuo en ~100.
    ts = [i * _DAY for i in range(4)]
    raw = [400.0, 400.0, 100.0, 100.0]
    adj = [100.0, 100.0, 100.0, 100.0]
    payload = _yahoo_payload(ts, raw, raw, raw, raw, adj, [1000] * 4)

    candles = fetch_yahoo_daily("SPLIT", _session(payload), 10)

    closes = [c["close"] for c in candles]
    assert closes == [100.0, 100.0, 100.0, 100.0]      # sin salto 4:1
    # el open ajustado de la barra pre-split tambien es ~100 (no 400)
    assert all(abs(c["open"] - 100.0) < 1e-6 for c in candles)
    # ningun gap bar-a-bar mayor a centavos
    gaps = [abs(candles[i]["close"] - candles[i - 1]["close"]) for i in range(1, 4)]
    assert max(gaps) < 0.01


def test_skips_bars_with_missing_values() -> None:
    ts = [0, _DAY, 2 * _DAY]
    payload = _yahoo_payload(
        ts, [10, None, 12], [11, 11, 13], [9, 9, 11], [10, 10, 12],
        [10, 10, 12], [100, 100, 100])
    candles = fetch_yahoo_daily("X", _session(payload), 10)
    assert len(candles) == 2  # la barra con open=None se descarta


def test_no_data_soft_fails() -> None:
    empty = {"chart": {"result": [None]}}
    assert fetch_yahoo_daily("NODATA", _session(empty), 10) == []


def test_request_error_soft_fails() -> None:
    sess = _session(error=requests.RequestException("boom"))
    assert fetch_yahoo_daily("ERR", sess, 10) == []


def test_load_symbol_persists_and_measures() -> None:
    repo = _repo()
    ts = [1_600_000_000 + i * _DAY for i in range(5)]  # epoch real (no 0/1970)
    payload = _yahoo_payload(
        ts, [10] * 5, [11] * 5, [9] * 5, [10] * 5, [10] * 5, [100] * 5)
    loader = StockHistoricalLoader(_settings(), repo, session=_session(payload))

    depth = loader.load_symbol("aapl")

    assert depth.symbol == "AAPL"          # normalizado
    assert depth.timeframe_label == "D1"
    assert depth.bars == 5
    assert depth.first_utc is not None and depth.last_utc is not None
    assert depth.fetched_from_mt5 is True


def test_load_symbol_without_data_notes_softfail() -> None:
    repo = _repo()
    loader = StockHistoricalLoader(
        _settings(), repo, session=_session({"chart": {"result": [None]}}))
    depth = loader.load_symbol("ZZZZ")
    assert depth.bars == 0
    assert "Yahoo sin data" in depth.note
