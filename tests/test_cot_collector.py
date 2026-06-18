"""Tests para COTCollector con mocks de la API Socrata de la CFTC."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.collectors.cot_collector import (
    COTCollector,
    _COT_MARKETS,
    net_position,
    parse_cot_row,
)
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"cot_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _enable_cot(base):
    return type(base)(**{**base.__dict__, "enable_cot_collector": True})


def _row(report_date="2026-06-10T00:00:00.000", nc_long=120000, nc_short=40000,
         c_long=50000, c_short=130000, oi=300000):
    """Fila cruda al estilo del dataset 6dca-aqww."""
    return {
        "report_date_as_yyyy_mm_dd": report_date,
        "noncomm_positions_long_all": nc_long,
        "noncomm_positions_short_all": nc_short,
        "comm_positions_long_all": c_long,
        "comm_positions_short_all": c_short,
        "open_interest_all": oi,
    }


# ---- funciones puras ---- #

def test_net_position_logic() -> None:
    assert net_position(120000, 40000) == 80000
    assert net_position(40000, 120000) == -80000
    assert net_position(None, 100) is None
    assert net_position(100, None) is None


def test_parse_cot_row_valido() -> None:
    snap = parse_cot_row(_row(), "EUR", "Euro FX")
    assert snap is not None
    assert snap["report_date"] == "2026-06-10"  # normalizado a YYYY-MM-DD
    assert snap["market_code"] == "EUR"
    assert snap["market_label"] == "Euro FX"
    assert snap["net_noncomm"] == 80000  # 120000 - 40000
    assert snap["net_comm"] == -80000    # 50000 - 130000
    assert snap["open_interest"] == 300000
    assert "captured_at" in snap


def test_parse_cot_row_sin_fecha_devuelve_none() -> None:
    row = _row()
    del row["report_date_as_yyyy_mm_dd"]
    assert parse_cot_row(row, "EUR", "Euro FX") is None


def test_parse_cot_row_conteos_ausentes_quedan_none() -> None:
    snap = parse_cot_row({"report_date_as_yyyy_mm_dd": "2026-06-10"}, "GBP", "British Pound")
    assert snap is not None
    assert snap["noncomm_long"] is None
    assert snap["net_noncomm"] is None
    assert snap["net_comm"] is None


def test_parse_cot_row_tolera_strings_y_floats() -> None:
    snap = parse_cot_row(_row(nc_long="120000.0", nc_short="40000"), "JPY", "Japanese Yen")
    assert snap["net_noncomm"] == 80000


# ---- collect ---- #

def test_cot_disabled_returns_none() -> None:
    c = COTCollector(_settings())  # enable_cot_collector=False
    assert c.collect() is None


def test_cot_collect_fetches_all_markets() -> None:
    settings = _enable_cot(_settings())
    c = COTCollector(settings)

    def fake_get(url, **kwargs):
        code = kwargs["params"]["cftc_contract_market_code"]
        response = MagicMock()
        # net distinto por mercado para distinguirlos
        response.json.return_value = [_row(nc_long=100000 + int(code[:3]), nc_short=40000)]
        response.raise_for_status = MagicMock()
        return response

    with patch.object(c.session, "get", side_effect=fake_get):
        snaps = c.collect()

    assert snaps is not None
    assert len(snaps) == len(_COT_MARKETS)
    codes = {s["market_code"] for s in snaps}
    assert codes == set(_COT_MARKETS.keys())
    for s in snaps:
        assert s["net_noncomm"] is not None
        assert s["report_date"] == "2026-06-10"


def test_cot_collect_soft_fail_por_mercado() -> None:
    """Un mercado que falla la HTTP no tumba a los demas."""
    settings = _enable_cot(_settings())
    c = COTCollector(settings)

    def fake_get(url, **kwargs):
        code = kwargs["params"]["cftc_contract_market_code"]
        response = MagicMock()
        if code == _COT_MARKETS["EUR"][1]:
            response.raise_for_status.side_effect = __import__("requests").RequestException("boom")
            return response
        response.json.return_value = [_row()]
        response.raise_for_status = MagicMock()
        return response

    with patch.object(c.session, "get", side_effect=fake_get):
        snaps = c.collect()

    assert snaps is not None
    codes = {s["market_code"] for s in snaps}
    assert "EUR" not in codes               # el que fallo se salteo
    assert len(snaps) == len(_COT_MARKETS) - 1


def test_cot_collect_payload_vacio_no_crashea() -> None:
    settings = _enable_cot(_settings())
    c = COTCollector(settings)

    def fake_get(url, **kwargs):
        response = MagicMock()
        response.json.return_value = []  # sin filas
        response.raise_for_status = MagicMock()
        return response

    with patch.object(c.session, "get", side_effect=fake_get):
        snaps = c.collect()

    assert snaps == []


# ---- should_run ---- #

class _FakeRepo:
    def __init__(self, last: str | None = None):
        self._last = last

    def get_state(self, key, default=None):
        return self._last if self._last is not None else default


def test_should_run_false_si_disabled() -> None:
    c = COTCollector(_settings())
    assert c.should_run(_FakeRepo()) is False


def test_should_run_true_sin_estado_previo() -> None:
    c = COTCollector(_enable_cot(_settings()))
    assert c.should_run(_FakeRepo(last=None)) is True


def test_should_run_false_si_reciente() -> None:
    c = COTCollector(_enable_cot(_settings()))
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    assert c.should_run(_FakeRepo(last=recent)) is False


def test_should_run_true_si_paso_el_intervalo() -> None:
    c = COTCollector(_enable_cot(_settings()))
    old = (datetime.now(timezone.utc) - timedelta(minutes=800)).isoformat()
    assert c.should_run(_FakeRepo(last=old)) is True


# ---- repository (init_db crea la tabla; idempotencia por (report_date, market_code)) ---- #

def test_repository_insert_y_fetch_cot() -> None:
    repo = _repo()
    snap = parse_cot_row(_row(), "EUR", "Euro FX")
    assert repo.insert_cot_snapshot(snap) is True
    latest = repo.fetch_latest_cot_snapshot("EUR")
    assert latest is not None
    assert latest["market_code"] == "EUR"
    assert latest["net_noncomm"] == 80000
    assert latest["report_date"] == "2026-06-10"


def test_repository_insert_cot_idempotente() -> None:
    repo = _repo()
    snap = parse_cot_row(_row(), "EUR", "Euro FX")
    assert repo.insert_cot_snapshot(snap) is True
    # mismo (report_date, market_code) -> no inserta de nuevo
    assert repo.insert_cot_snapshot(snap) is False


def test_repository_fetch_cot_inexistente_devuelve_none() -> None:
    repo = _repo()
    assert repo.fetch_latest_cot_snapshot("EUR") is None
