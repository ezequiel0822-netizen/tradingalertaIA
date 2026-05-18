import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from app.config.settings import Settings


logger = logging.getLogger(__name__)


@dataclass
class SECFiling:
    symbol: str
    cik: str
    form: str
    filing_date: str
    report_date: str
    accession_number: str
    primary_document: str
    description: str
    url: str


class SECFilingsCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self._ticker_map: dict[str, str] | None = None

    def collect_for_symbol(self, symbol: str) -> list[SECFiling]:
        if not self.settings.enable_sec_filings_intel:
            return []

        ticker = symbol.upper().strip()
        cik = self._cik_for_symbol(ticker)
        if not cik:
            return []

        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        try:
            response = self.session.get(
                url,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("SEC submissions failed for %s: %s", ticker, exc)
            return []

        recent = (payload.get("filings") or {}).get("recent") or {}
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=self.settings.sec_recent_days)
        filings: list[SECFiling] = []
        for index, form in enumerate(recent.get("form") or []):
            filing_date = _safe_index(recent.get("filingDate"), index)
            if not _is_recent_date(filing_date, cutoff):
                continue
            accession = _safe_index(recent.get("accessionNumber"), index)
            primary_doc = _safe_index(recent.get("primaryDocument"), index)
            filings.append(
                SECFiling(
                    symbol=ticker,
                    cik=cik,
                    form=str(form or "unknown"),
                    filing_date=filing_date,
                    report_date=_safe_index(recent.get("reportDate"), index),
                    accession_number=accession,
                    primary_document=primary_doc,
                    description=_safe_index(recent.get("primaryDocDescription"), index),
                    url=_filing_url(cik, accession, primary_doc),
                )
            )
            if len(filings) >= self.settings.max_sec_filings_per_symbol:
                break
        return filings

    def _cik_for_symbol(self, symbol: str) -> str | None:
        ticker_map = self._load_ticker_map()
        return ticker_map.get(symbol.upper())

    def _load_ticker_map(self) -> dict[str, str]:
        if self._ticker_map is not None:
            return self._ticker_map

        url = "https://www.sec.gov/files/company_tickers.json"
        try:
            response = self.session.get(
                url,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("SEC ticker map failed: %s", exc)
            self._ticker_map = {}
            return self._ticker_map

        ticker_map: dict[str, str] = {}
        rows = payload.values() if isinstance(payload, dict) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").upper()
            cik = row.get("cik_str")
            if ticker and cik is not None:
                ticker_map[ticker] = str(cik).zfill(10)
        self._ticker_map = ticker_map
        return ticker_map


def _safe_index(values: Any, index: int) -> str:
    if not isinstance(values, list) or index >= len(values):
        return ""
    value = values[index]
    return "" if value is None else str(value)


def _is_recent_date(value: str, cutoff: date) -> bool:
    if not value:
        return False
    try:
        return datetime.fromisoformat(value).date() >= cutoff
    except ValueError:
        return False


def _filing_url(cik: str, accession: str, primary_document: str) -> str:
    if not accession or not primary_document:
        return ""
    compact_accession = accession.replace("-", "")
    cik_int = str(int(cik))
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int}/{compact_accession}/{primary_document}"
    )
