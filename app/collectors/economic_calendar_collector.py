"""Economic Calendar collector via ForexFactory XML publico.

Fetch semanal de eventos high/medium/low impact. Filtra solo high-impact + monedas
relevantes (USD, EUR, GBP, JPY, CHF, AUD, CAD, NZD). Persiste en `economic_events`.

Read-only HTTP GET. Si el feed cambia formato, parser defensivo retorna lista vacia.
"""

import logging
from datetime import datetime, timezone
from xml.etree import ElementTree as ET
from typing import Any

import requests

from app.config.settings import Settings
from app.utils.time_utils import utc_now_iso


logger = logging.getLogger(__name__)


FOREX_FACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
# v3.9.3: lookahead. Sin la proxima semana, el calendar_gate queda CIEGO apenas el feed
# de esta semana no rota (caso 18-jun: 0 eventos futuros -> gate no-op).
FOREX_FACTORY_NEXTWEEK_URL = "https://nfs.faireconomy.media/ff_calendar_nextweek.xml"
RELEVANT_COUNTRIES = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD"}


def parse_forexfactory_xml(xml_text: str) -> list[dict[str, Any]]:
    """Parsea XML de ForexFactory. Retorna lista de eventos."""
    events: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.warning("ForexFactory XML parse failed")
        return events

    for event in root.findall(".//event"):
        try:
            title_el = event.find("title")
            country_el = event.find("country")
            date_el = event.find("date")
            time_el = event.find("time")
            impact_el = event.find("impact")

            title = (title_el.text or "").strip() if title_el is not None else ""
            country = (country_el.text or "").strip() if country_el is not None else ""
            date_str = (date_el.text or "").strip() if date_el is not None else ""
            time_str = (time_el.text or "").strip() if time_el is not None else ""
            impact = (impact_el.text or "").strip().lower() if impact_el is not None else ""

            if not title or not country or not date_str:
                continue

            # Date format: "MM-DD-YYYY", time format "h:mma" or "All Day"
            event_dt = _parse_event_datetime(date_str, time_str)
            if event_dt is None:
                continue

            events.append({
                "event_time": event_dt.isoformat(),
                "country": country.upper(),
                "impact": impact,
                "title": title,
            })
        except Exception:
            continue

    return events


def _parse_event_datetime(date_str: str, time_str: str) -> datetime | None:
    try:
        m, d, y = date_str.split("-")
        if time_str and time_str.lower() not in {"all day", "tentative"}:
            # "10:30am" or "2:00pm"
            time_str_clean = time_str.lower().replace(" ", "")
            for fmt in ("%I:%M%p", "%H:%M"):
                try:
                    parsed_time = datetime.strptime(time_str_clean, fmt).time()
                    return datetime(
                        int(y), int(m), int(d),
                        parsed_time.hour, parsed_time.minute,
                        tzinfo=timezone.utc,
                    )
                except ValueError:
                    continue
            return None
        return datetime(int(y), int(m), int(d), tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


class EconomicCalendarCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TradingAlertAI/2.4"})

    def collect(self) -> list[dict[str, Any]]:
        """Junta eventos high-impact de ESTA semana Y la PROXIMA (lookahead). Cada feed
        es soft-fail independiente; dedup por (event_time, country, title) por el solape
        en los bordes de semana. El upsert ya es idempotente, esto evita mandar dobles."""
        if not self.settings.enable_economic_calendar:
            return []
        events: list[dict[str, Any]] = []
        for url in (FOREX_FACTORY_URL, FOREX_FACTORY_NEXTWEEK_URL):
            events.extend(self._fetch_feed(url))
        seen: set[tuple[str, str, str]] = set()
        deduped: list[dict[str, Any]] = []
        for e in events:
            key = (e["event_time"], e["country"], e["title"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(e)
        return deduped

    def _fetch_feed(self, url: str) -> list[dict[str, Any]]:
        """Baja + parsea + filtra (high-impact + monedas relevantes) un feed. Soft-fail -> []."""
        try:
            response = self.session.get(
                url, timeout=self.settings.request_timeout_seconds
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning(
                "ForexFactory fetch failed (%s): %s",
                url.rsplit("/", 1)[-1], exc.__class__.__name__,
            )
            return []
        events = parse_forexfactory_xml(response.text)
        filtered = [
            e for e in events
            if e.get("impact") == "high" and e.get("country") in RELEVANT_COUNTRIES
        ]
        for e in filtered:
            e["captured_at"] = utc_now_iso()
        return filtered

    def should_run(self, repository: Any) -> bool:
        if not self.settings.enable_economic_calendar:
            return False
        last = repository.get_state("calendar_last_refresh_iso") or ""
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        except ValueError:
            return True
        elapsed_h = (
            datetime.now(timezone.utc) - last_dt
        ).total_seconds() / 3600.0
        return elapsed_h >= self.settings.calendar_refresh_hours
