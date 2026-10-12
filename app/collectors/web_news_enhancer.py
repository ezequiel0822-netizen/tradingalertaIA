"""v3.17.0 — Web News Enhancer, adaptado del paquete "v3.17 calidad" (propuestas/
2026-10-10_v3.17_calidad/, revisión REVISION_CLAUDE_2026-10-12.md).

NO decide trades: produce features de noticias (frescura, sentimiento simple, catalizador)
para el quality gate EN SOMBRA (research/CALIDAD_SOMBRA_2026-10-12.md).

Cambios respecto del paquete:
- Solo ACCIONES. Para forex/oro no sirve: Google News buscaría "EURUSD=X stock".
- Nunca frena la decisión del bot. En el momento del candidato se usan los titulares de
  Yahoo que el bot YA bajó (caché, sin red). Google News RSS se busca DESPUÉS, en un paso
  aparte del ciclo, con presupuesto por ciclo, timeout corto, caché por símbolo y pausa
  tras fallos seguidos.
- As-of: solo cuentan titulares publicados ANTES de la apertura del candidato. Los de
  Google sin fecha se descartan (no se puede verificar que sean anteriores). La frescura
  se mide contra la apertura, no contra la hora de la búsqueda.
- Sentimiento: se sacan palabras cuyo signo depende del contexto ("cut"/"cuts" en una baja
  de tasas, "lower"/"higher", "baja"). Los títulos se guardan para que un pre-registro
  futuro pueda usar otro método sobre los mismos datos.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests

logger = logging.getLogger(__name__)

# Las palabras del paquete, sin las ambiguas (cut, cuts, lower, higher, baja).
_POSITIVE = {
    "beat", "beats", "surge", "surges", "rally", "rallies", "upgrade", "upgraded",
    "record", "growth", "profit", "profits", "strong", "bullish", "breakthrough",
    "approval", "approved", "buy", "outperform", "raised", "gain", "gains",
    "sube", "subió", "alza", "ganancia", "beneficio", "récord", "crecimiento",
    "aprobado", "alcista", "mejora", "superó", "supera",
}
_NEGATIVE = {
    "miss", "misses", "fall", "falls", "drop", "drops", "downgrade", "downgraded",
    "loss", "losses", "weak", "bearish", "lawsuit", "probe", "fraud",
    "warning", "layoff", "layoffs", "decline", "declines",
    "cae", "cayó", "pérdida", "débiles", "bajista", "recorta", "demanda",
    "investigación", "fraude", "despidos", "alerta",
}
_CATALYST_WORDS = ("earnings", "guidance", "fda", "merger", "acquisition", "cpi", "fomc", "nfp")

GOOGLE_TIMEOUT_SECONDS = 5
GOOGLE_CACHE_SECONDS = 30 * 60
GOOGLE_MAX_FETCHES_PER_CYCLE = 2
GOOGLE_FAILS_BEFORE_PAUSE = 3
GOOGLE_PAUSE_SECONDS = 30 * 60
GOOGLE_MAX_BYTES = 2_000_000
MAX_HEADLINES = 8
# Un candidato de acciones espera las noticias de Google hasta esto; después se cierra
# con lo que haya (Yahoo).
PENDING_MAX_HOURS = 6.0

SOURCE_YAHOO = "yahoo"
SOURCE_GOOGLE = "google"


@dataclass(frozen=True)
class Headline:
    title: str
    published: datetime | None     # UTC; None = sin fecha
    source: str                    # yahoo | google

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "published": self.published.isoformat() if self.published else None,
            "source": self.source,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Headline":
        return Headline(
            title=str(d.get("title") or ""),
            published=parse_iso(d.get("published")),
            source=str(d.get("source") or ""),
        )


@dataclass
class NewsEnrichment:
    freshness_score: float = 0.0     # 0-100
    sentiment: float = 0.0           # -1 a +1
    has_catalyst: bool = False
    age_hours: float | None = None   # apertura - titular más nuevo
    headlines: list[Headline] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return sorted({h.source for h in self.headlines})


def simple_sentiment(text: str) -> float:
    """(positivas - negativas) / (positivas + negativas) sobre las palabras del título."""
    if not text:
        return 0.0
    words = set(re.findall(r"[a-záéíóúñü]+", text.lower()))
    pos = len(words & _POSITIVE)
    neg = len(words & _NEGATIVE)
    total = pos + neg
    return 0.0 if total == 0 else (pos - neg) / total


def parse_pub_date(text: Any) -> datetime | None:
    """pubDate RFC 2822 de un RSS -> datetime UTC (sin zona = UTC). None si no se puede."""
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(str(text).strip())
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso(text: Any) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_rss(content: bytes | str, source: str) -> list[Headline]:
    """Títulos + fecha de los <item> de un RSS. Lanza ante un XML inválido."""
    root = ElementTree.fromstring(content)
    out: list[Headline] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if title:
            out.append(Headline(title, parse_pub_date(item.findtext("pubDate")), source))
    return out


def merge_as_of(groups: list[list[Headline]], as_of: datetime) -> list[Headline]:
    """Une fuentes sin repetir títulos y deja solo lo publicado hasta `as_of`.

    Titulares sin fecha: los de Yahoo se guardan (se bajaron ANTES de la decisión: no
    pueden ser del futuro); los de Google se descartan (se buscan después)."""
    seen: set[str] = set()
    kept: list[Headline] = []
    for group in groups:
        for h in group:
            key = re.sub(r"\s+", " ", h.title.strip().lower())
            if not key or key in seen:
                continue
            if h.published is None:
                if h.source != SOURCE_YAHOO:
                    continue
            elif h.published > as_of:
                continue
            seen.add(key)
            kept.append(h)
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    kept.sort(key=lambda h: h.published or epoch, reverse=True)
    return kept[:MAX_HEADLINES]


def features_from_headlines(
    headlines: list[Headline], as_of: datetime, max_age_hours: float = 18.0
) -> NewsEnrichment:
    """Frescura / sentimiento / catalizador (fórmulas del paquete), medidos contra la
    apertura. Sin titulares: todo en 0 (sin catalizador)."""
    if not headlines:
        return NewsEnrichment()
    dated = [h.published for h in headlines if h.published is not None]
    age_hours = None
    freshness = 40.0
    if dated:
        age_hours = max(0.0, (as_of - max(dated)).total_seconds() / 3600.0)
        if age_hours <= 3:
            freshness = 95.0
        elif age_hours <= 8:
            freshness = 80.0
        elif age_hours <= max_age_hours:
            freshness = 60.0
        else:
            freshness = 25.0
    sentiments = [simple_sentiment(h.title) for h in headlines]
    avg = sum(sentiments) / len(sentiments)
    text = " ".join(h.title for h in headlines).lower()
    catalyst = abs(avg) >= 0.25 or any(w in text for w in _CATALYST_WORDS)
    return NewsEnrichment(
        freshness_score=freshness,
        sentiment=max(-1.0, min(1.0, avg)),
        has_catalyst=catalyst,
        age_hours=round(age_hours, 2) if age_hours is not None else None,
        headlines=list(headlines),
    )


def is_stock_symbol(symbol: str) -> bool:
    """Tickers de acciones (AAPL, BRK.B). Forex/futuros de Yahoo (EURUSD=X, GC=F, ^VIX) no."""
    s = str(symbol or "").strip().upper()
    return bool(s) and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", s) is not None


class GoogleNewsSource:
    """Google News RSS por símbolo, con caché, timeout corto y pausa tras fallos seguidos.

    `fetch` devuelve la lista (vacía si no hay titulares) o None si falló / está en pausa /
    el símbolo no es una acción. Solo la llama el paso diferido del ciclo (jobs.py)."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = GOOGLE_TIMEOUT_SECONDS,
        cache_seconds: float = GOOGLE_CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; TradingAlertAI/3.17; +local-research)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self.clock = clock
        self._cache: dict[str, tuple[float, list[Headline]]] = {}
        self._fails = 0
        self._paused_until = 0.0

    def is_cached(self, symbol: str) -> bool:
        hit = self._cache.get(str(symbol or "").strip().upper())
        return hit is not None and self.clock() - hit[0] < self.cache_seconds

    @property
    def paused(self) -> bool:
        return self.clock() < self._paused_until

    def fetch(self, symbol: str) -> list[Headline] | None:
        sym = str(symbol or "").strip().upper()
        if not is_stock_symbol(sym):
            return None
        hit = self._cache.get(sym)
        if hit is not None and self.clock() - hit[0] < self.cache_seconds:
            return list(hit[1])
        if self.paused:
            return None
        query = f"{sym} stock OR {sym} shares when:1d"
        url = (
            "https://news.google.com/rss/search?"
            f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        )
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                raise ValueError(f"HTTP {resp.status_code}")
            content = resp.content or b""
            if len(content) > GOOGLE_MAX_BYTES:
                raise ValueError("respuesta demasiado grande")
            items = parse_rss(content, SOURCE_GOOGLE)
        except Exception as exc:
            self._fails += 1
            if self._fails >= GOOGLE_FAILS_BEFORE_PAUSE:
                self._paused_until = self.clock() + GOOGLE_PAUSE_SECONDS
                self._fails = 0
                logger.warning(
                    "Noticias web: %d fallos seguidos, pausa de %d min (ultimo: %s)",
                    GOOGLE_FAILS_BEFORE_PAUSE, GOOGLE_PAUSE_SECONDS // 60, exc,
                )
            else:
                logger.info("Noticias web: Google News fallo para %s: %s", sym, exc)
            return None
        self._fails = 0
        self._cache[sym] = (self.clock(), items)
        return list(items)
