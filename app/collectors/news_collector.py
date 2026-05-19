import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

from app.config.settings import Settings


logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    link: str
    published: str
    source: str = "Yahoo Finance RSS"


class NewsCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TradingAlertAI/2.2"})

    def collect_for_symbol(self, symbol: str) -> list[NewsItem]:
        if not self.settings.enable_news_intel:
            return []

        url = "https://feeds.finance.yahoo.com/rss/2.0/headline"
        params = {"s": symbol.upper(), "region": "US", "lang": "en-US"}
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("News RSS failed for %s: %s", symbol, exc)
            return []

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            logger.warning("News RSS parse failed for %s: %s", symbol, exc)
            return []

        items: list[NewsItem] = []
        for item in root.findall("./channel/item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            published = (item.findtext("pubDate") or "").strip()
            if title:
                items.append(NewsItem(title=title, link=link, published=published))
        return items[: self.settings.max_news_per_symbol]
