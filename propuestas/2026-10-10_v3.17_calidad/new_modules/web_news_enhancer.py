"""
Web News Enhancer — v3.17 propuesta
-----------------------------------
Busca noticias públicas frescas y calcula un sentimiento simple.
Soft-fail total: si falla o está desactivado, el bot se comporta igual que antes.

Fuentes usadas (gratis, sin API key obligatoria):
- Yahoo Finance news (vía yfinance si está disponible)
- Google News RSS (pública)
- Fallback: titulares ya existentes del bot

NO decide trades. Solo aporta features:
- news_freshness_score (0-100)
- news_sentiment (-1.0 a +1.0)
- news_has_catalyst (bool)
- news_headlines (lista corta)

Integración sugerida:
  from app.collectors.web_news_enhancer import WebNewsEnhancer
  enhancer = WebNewsEnhancer(settings)
  extra = enhancer.enrich(symbol, existing_news=None)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests

logger = logging.getLogger(__name__)

# Palabras simples de sentimiento (español + inglés) — sin dependencias externas
_POSITIVE = {
    "beat", "beats", "surge", "surges", "rally", "rallies", "upgrade", "upgraded",
    "record", "growth", "profit", "profits", "strong", "bullish", "breakthrough",
    "approval", "approved", "buy", "outperform", "raised", "higher", "gain", "gains",
    "sube", "subió", "alza", "ganancia", "beneficio", "récord", "crecimiento",
    "aprobado", "alcista", "mejora", "superó", "supera",
}
_NEGATIVE = {
    "miss", "misses", "fall", "falls", "drop", "drops", "downgrade", "downgraded",
    "loss", "losses", "weak", "bearish", "cut", "cuts", "lawsuit", "probe", "fraud",
    "warning", "warning", "layoff", "layoffs", "decline", "declines", "lower",
    "cae", "cayó", "baja", "pérdida", "débiles", "bajista", "recorta", "demanda",
    "investigación", "fraude", "despidos", "alerta",
}


@dataclass
class NewsEnrichment:
    symbol: str
    freshness_score: float = 0.0          # 0-100
    sentiment: float = 0.0                # -1.0 a +1.0
    has_catalyst: bool = False
    headlines: list[str] = field(default_factory=list)
    source: str = "none"
    age_hours: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "news_freshness_score": round(self.freshness_score, 1),
            "news_sentiment": round(self.sentiment, 3),
            "news_has_catalyst": self.has_catalyst,
            "news_headlines": self.headlines[:5],
            "news_source": self.source,
            "news_age_hours": self.age_hours,
        }


class WebNewsEnhancer:
    """Enriquecedor de noticias web. Soft-fail en todo."""

    def __init__(self, settings: Any, session: requests.Session | None = None):
        self.settings = settings
        self.enabled = bool(getattr(settings, "enable_web_news_enhancer", False))
        self.max_age_hours = float(getattr(settings, "web_news_max_age_hours", 18.0))
        self.timeout = int(getattr(settings, "request_timeout_seconds", 12))
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; TradingAlertAI/3.17; +local-research)"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })

    def enrich(
        self,
        symbol: str,
        existing_news: list[dict] | None = None,
    ) -> NewsEnrichment:
        """Devuelve enriquecimiento. Nunca lanza excepción hacia arriba."""
        if not self.enabled:
            return NewsEnrichment(symbol=symbol, source="disabled")

        symbol = (symbol or "").strip().upper()
        if not symbol:
            return NewsEnrichment(symbol=symbol, error="empty_symbol")

        # 1) Intentar Google News RSS (rápido y sin key)
        try:
            result = self._from_google_news(symbol)
            if result and result.headlines:
                return result
        except Exception as exc:
            logger.debug("web_news google failed for %s: %s", symbol, exc)

        # 2) Fallback a noticias ya existentes del bot
        if existing_news:
            try:
                return self._from_existing(symbol, existing_news)
            except Exception as exc:
                logger.debug("web_news existing failed for %s: %s", symbol, exc)

        return NewsEnrichment(symbol=symbol, source="none", error="no_news")

    # ------------------------------------------------------------------
    def _from_google_news(self, symbol: str) -> NewsEnrichment | None:
        # Query simple: símbolo + "stock" o "forex" según contexto
        query = f"{symbol} stock OR {symbol} shares when:1d"
        url = (
            "https://news.google.com/rss/search?"
            f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        )
        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code != 200:
            return None

        root = ElementTree.fromstring(resp.content)
        items = root.findall(".//item")[:8]
        if not items:
            return None

        headlines: list[str] = []
        sentiments: list[float] = []
        newest_ts: float | None = None
        now = time.time()

        for item in items:
            title_el = item.find("title")
            pub_el = item.find("pubDate")
            if title_el is None or not title_el.text:
                continue
            title = title_el.text.strip()
            headlines.append(title)
            sentiments.append(self._simple_sentiment(title))

            if pub_el is not None and pub_el.text:
                try:
                    # Formato RFC 2822 típico de Google
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pub_el.text)
                    ts = dt.timestamp()
                    if newest_ts is None or ts > newest_ts:
                        newest_ts = ts
                except Exception:
                    pass

        if not headlines:
            return None

        age_hours = None
        freshness = 40.0
        if newest_ts is not None:
            age_hours = max(0.0, (now - newest_ts) / 3600.0)
            if age_hours <= 3:
                freshness = 95.0
            elif age_hours <= 8:
                freshness = 80.0
            elif age_hours <= self.max_age_hours:
                freshness = 60.0
            else:
                freshness = 25.0

        avg_sent = sum(sentiments) / len(sentiments) if sentiments else 0.0
        has_catalyst = abs(avg_sent) >= 0.25 or any(
            w in " ".join(headlines).lower()
            for w in ("earnings", "guidance", "fda", "merger", "acquisition", "cpi", "fomc", "nfp")
        )

        return NewsEnrichment(
            symbol=symbol,
            freshness_score=freshness,
            sentiment=max(-1.0, min(1.0, avg_sent)),
            has_catalyst=has_catalyst,
            headlines=headlines[:5],
            source="google_news_rss",
            age_hours=round(age_hours, 2) if age_hours is not None else None,
        )

    def _from_existing(self, symbol: str, news: list[dict]) -> NewsEnrichment:
        headlines = []
        sentiments = []
        for n in news[:6]:
            title = (n.get("title") or n.get("headline") or "").strip()
            if title:
                headlines.append(title)
                sentiments.append(self._simple_sentiment(title))

        avg_sent = sum(sentiments) / len(sentiments) if sentiments else 0.0
        return NewsEnrichment(
            symbol=symbol,
            freshness_score=50.0,
            sentiment=max(-1.0, min(1.0, avg_sent)),
            has_catalyst=abs(avg_sent) >= 0.3,
            headlines=headlines[:5],
            source="existing",
        )

    @staticmethod
    def _simple_sentiment(text: str) -> float:
        if not text:
            return 0.0
        words = set(re.findall(r"[a-záéíóúñü]+", text.lower()))
        pos = len(words & _POSITIVE)
        neg = len(words & _NEGATIVE)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total
