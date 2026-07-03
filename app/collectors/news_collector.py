import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

from app.config.settings import Settings


logger = logging.getLogger(__name__)

# v3.9.5: TTL del cache de titulares. El ciclo llamaba el RSS por CADA stock cada
# ~92s (46 GETs/ciclo ~= 40k hits/dia a Yahoo -> parte del 429 autoinfligido)
# para noticias que no cambian en minutos.
NEWS_CACHE_TTL_SECONDS = 1200.0


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
        self.session.headers.update({"User-Agent": "TradingAlertAI/2.4"})
        self._cache: dict[str, tuple[float, list[NewsItem]]] = {}

    def collect_for_symbol(self, symbol: str) -> list[NewsItem]:
        if not self.settings.enable_news_intel:
            return []

        key = symbol.upper()
        hit = self._cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < NEWS_CACHE_TTL_SECONDS:
            return hit[1]

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
        result = items[: self.settings.max_news_per_symbol]
        self._cache[key] = (time.monotonic(), result)  # solo exitos; fallos reintentan
        return result
