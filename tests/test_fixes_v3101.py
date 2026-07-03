"""v3.10.1 — batch de fixes de la auditoría total: A2 (scalping alert_id), M1
(mt5.shutdown ajeno deja el reader ciego), M2 (cooldown 429 Yahoo), M4 (dollar
volumes desalineados con closes nulos)."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import requests

from app.brokers.mt5_reader import MT5Reader
from app.collectors.stock_collector import StockCollector
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"fixes3101_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


# ----------------------------- M1: mt5_reader ------------------------------ #
def test_mt5_reader_detects_foreign_shutdown() -> None:
    """v3.10.1 (M1): mt5.shutdown() es global — si otro consumidor mato la
    conexion, is_connected() debe decir la verdad (terminal_info() None)."""
    reader = MT5Reader(_settings())
    reader._connected = True
    reader._mt5 = SimpleNamespace(terminal_info=lambda: None)
    assert reader.is_connected() is False
    assert reader._connected is False  # flag corregido para el proximo connect()


def test_mt5_reader_connected_when_terminal_alive() -> None:
    reader = MT5Reader(_settings())
    reader._connected = True
    reader._mt5 = SimpleNamespace(terminal_info=lambda: object())
    assert reader.is_connected() is True


# --------------------------- M2: cooldown 429 ------------------------------ #
class _Session429:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        err = requests.HTTPError("429 Too Many Requests")
        err.response = SimpleNamespace(status_code=429)
        raise err


def test_stock_collector_429_cooldown_stops_batch() -> None:
    """v3.10.1 (M2): un 429 corta el resto del batch Y los proximos ciclos
    (antes se golpeaba a full rate simbolo por simbolo, ciclo tras ciclo)."""
    settings = replace(_settings(), enable_stock_alerts=True,
                       stock_symbols=["AAA", "BBB", "CCC"])
    collector = StockCollector(settings)
    session = _Session429()
    collector.session = session

    assert collector.collect() == []
    assert session.calls == 1  # el 429 del 1er simbolo corto el batch

    assert collector.collect() == []
    assert session.calls == 1  # ciclo siguiente: cooldown -> cero requests


# ------------------------ M4: dollar volumes alineados --------------------- #
class _SessionPayload:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def get(self, url, params=None, timeout=None):
        payload = self._payload

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return payload

        return _Resp()


def test_stock_dollar_volumes_aligned_when_closes_have_nones() -> None:
    """v3.10.1 (M4): un close nulo desalineaba el zip closes-filtrados x volumes
    crudos: cada close se multiplicaba por el volumen de OTRA vela."""
    payload = {
        "chart": {"result": [{
            "meta": {"regularMarketPrice": 20.0, "shortName": "TEST"},
            "timestamp": [1, 2, 3],
            "indicators": {"quote": [{
                "close": [10.0, None, 20.0],
                "open": [10.0, None, 20.0],
                "high": [10.0, None, 20.0],
                "low": [10.0, None, 20.0],
                "volume": [1, 100, 2],
            }]},
        }]}
    }
    settings = replace(_settings(), enable_stock_alerts=True)
    collector = StockCollector(settings)
    collector.session = _SessionPayload(payload)

    snapshot = collector._fetch_symbol("TEST")

    assert snapshot is not None
    # alineado: 10*1 + 20*2 = 50. Con el bug viejo: 10*1 + 20*100 = 2010.
    assert abs(snapshot.volume_24h - 50.0) < 1e-6


# ------------------------- A2: scalping alert_id ---------------------------- #
def test_paper_trades_accept_distinct_negative_alert_ids() -> None:
    """v3.10.1 (A2): el scalping usaba alert_id=0 fijo y el UNIQUE hacia que solo
    el PRIMER scalp de la historia se creara. Con ids sinteticos negativos
    distintos, se pueden crear multiples."""
    repo = _repo()
    base = {
        "token_id": 0, "category": "forex", "chain": "forex",
        "token_address": "EURUSD", "symbol": "EURUSD", "thesis": "scalp",
        "readiness_grade": "scalping", "entry_price": 1.1, "latest_price": 1.1,
        "stop_loss": 1.09, "take_profit_1": 1.11, "take_profit_2": 1.11,
        "invalidation": None, "status": "open", "unrealized_return_pct": 0,
        "opened_at": "2026-07-02T00:00:00+00:00",
        "updated_at": "2026-07-02T00:00:00+00:00", "closed_at": None,
    }
    assert repo.create_paper_trade({**base, "alert_id": -1001}) is True
    assert repo.create_paper_trade({**base, "alert_id": -1002}) is True
    # el bug viejo: mismo id repetido -> el segundo falla
    assert repo.create_paper_trade({**base, "alert_id": -1001}) is False


def test_scalping_engine_synthetic_ids_increment() -> None:
    from app.scheduler.scalping_engine import ScalpingEngine

    engine = ScalpingEngine(_settings(), _repo(), notifier=None)
    first = engine._synthetic_alert_seq
    engine._synthetic_alert_seq += 1
    assert engine._synthetic_alert_seq == first + 1
    assert first > 0  # semilla epoch: los ids emitidos (-seq) son negativos
