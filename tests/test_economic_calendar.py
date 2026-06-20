"""Tests para EconomicCalendarCollector con XML fixture."""

from unittest.mock import MagicMock, patch

from app.collectors.economic_calendar_collector import (
    EconomicCalendarCollector,
    parse_forexfactory_xml,
)
from tests.test_score import _settings


_SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8'?>
<weeklyevents>
  <event>
    <title>Non-Farm Payrolls</title>
    <country>USD</country>
    <date>05-19-2026</date>
    <time>8:30am</time>
    <impact>High</impact>
  </event>
  <event>
    <title>ECB Press Conference</title>
    <country>EUR</country>
    <date>05-20-2026</date>
    <time>2:30pm</time>
    <impact>High</impact>
  </event>
  <event>
    <title>Retail Sales</title>
    <country>USD</country>
    <date>05-19-2026</date>
    <time>8:30am</time>
    <impact>Medium</impact>
  </event>
  <event>
    <title>BOJ Press Conference</title>
    <country>JPY</country>
    <date>05-21-2026</date>
    <time>All Day</time>
    <impact>High</impact>
  </event>
</weeklyevents>"""


def test_parser_extracts_events() -> None:
    events = parse_forexfactory_xml(_SAMPLE_XML)
    assert len(events) >= 3
    titles = [e["title"] for e in events]
    assert "Non-Farm Payrolls" in titles
    assert "ECB Press Conference" in titles


def test_parser_handles_bad_xml() -> None:
    events = parse_forexfactory_xml("not xml")
    assert events == []


def test_collect_filters_high_impact_only() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_economic_calendar": True})
    c = EconomicCalendarCollector(settings)
    response = MagicMock()
    response.text = _SAMPLE_XML
    response.raise_for_status = MagicMock()
    with patch.object(c.session, "get", return_value=response):
        events = c.collect()
    assert len(events) >= 1
    for e in events:
        assert e["impact"] == "high"
        assert e["country"] in {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD"}


def test_collect_disabled() -> None:
    c = EconomicCalendarCollector(_settings())
    assert c.collect() == []


_NEXTWEEK_XML = """<?xml version='1.0' encoding='UTF-8'?>
<weeklyevents>
  <event>
    <title>FOMC Statement</title>
    <country>USD</country>
    <date>05-27-2026</date>
    <time>2:00pm</time>
    <impact>High</impact>
  </event>
</weeklyevents>"""


def _enabled():
    base = _settings()
    return type(base)(**{**base.__dict__, "enable_economic_calendar": True})


def test_collect_merges_thisweek_and_nextweek() -> None:
    """v3.9.3: el collector junta esta semana + la proxima (lookahead) para que el
    calendar_gate no quede ciego cuando el feed thisweek no rota."""
    c = EconomicCalendarCollector(_enabled())

    def fake_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = _NEXTWEEK_XML if "nextweek" in url else _SAMPLE_XML
        return resp

    with patch.object(c.session, "get", side_effect=fake_get):
        events = c.collect()
    titles = {e["title"] for e in events}
    assert "Non-Farm Payrolls" in titles  # thisweek
    assert "FOMC Statement" in titles      # nextweek (lookahead)


def test_collect_dedups_week_overlap() -> None:
    """Si ambos feeds traen el mismo evento (solape de bordes), aparece una sola vez."""
    c = EconomicCalendarCollector(_enabled())

    def fake_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.text = _SAMPLE_XML
        return resp

    with patch.object(c.session, "get", side_effect=fake_get):
        events = c.collect()
    nfp = [e for e in events if e["title"] == "Non-Farm Payrolls"]
    assert len(nfp) == 1
