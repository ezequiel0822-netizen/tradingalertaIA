# PROMPT PARA CLAUDE CODE — Aplicar mejoras de calidad (v3.17 propuesta)

Copia TODO lo que está debajo de esta línea y pégalo como primer mensaje en Claude Code.

---

Retomamos Trading Alert AI (bot de trading LOCAL, Python 3.12, Windows).

**Tarea concreta de esta sesión:** aplicar las mejoras de **selectividad + datos limpios + quality gate + web news enhancer** que se prepararon el 2026-10-10. No abras hipótesis nuevas, no toques real-money, no re-cortes las 27 familias fallidas.

## Contexto rápido (lee esto primero)

- Versión actual del bot: **v3.16.0**
- 938 tests verdes.
- 27 familias de hipótesis con pre-registro → **0 operables**.
- Real-money sigue bloqueado por diseño (`enable_real_trading = False` hardcoded).
- El problema principal no es el código, es la falta de edge. Estas mejoras apuntan a **menos operaciones de más calidad** (objetivo win-rate ≥ 58-65 % y expectancy ≥ +0.10R).
- Todo lo nuevo debe ser **opt-in + soft-fail + downward-only**.

Lee antes de tocar nada (en este orden):
1. `research/LEDGER_FAMILIAS.md` (solo para no reabrir familias)
2. `HANDOFF.md` (reglas del proyecto)
3. `PROXIMOS_PASOS.md` (bloque del 7-oct)
4. Este prompt completo

## Reglas no negociables

- Real-money **BLOQUEADO**. No lo toques.
- `order_send` solo puede existir en `app/brokers/mt5_demo_trader.py`.
- Todo nuevo: **opt-in OFF por default** + soft-fail total.
- Downward-only: los nuevos filtros solo pueden bajar a paper o descartar, nunca habilitar más.
- Al tocar `Settings` sincroniza los helpers de tests (`tests/test_score.py` y `tests/test_alert_rules.py` si existen `_settings()`).
- Versionado: sube a **v3.17.0**.
- El push a main lo hace el user. Tú solo dejas los cambios listos.
- Una sola instancia del bot. No arranques el bot tú.
- Nunca leas ni muestres el `.env` real (secrets).

## Qué tienes que implementar (en este orden exacto)

### 1. Nuevos módulos (crear archivos)

#### 1.1 `app/collectors/web_news_enhancer.py`

Crea este archivo completo:

```python
"""
Web News Enhancer — v3.17
Busca noticias públicas frescas y calcula un sentimiento simple.
Soft-fail total: si falla o está desactivado, el bot se comporta igual que antes.

NO decide trades. Solo aporta features:
- news_freshness_score (0-100)
- news_sentiment (-1.0 a +1.0)
- news_has_catalyst (bool)
- news_headlines (lista corta)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests

logger = logging.getLogger(__name__)

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
    "warning", "layoff", "layoffs", "decline", "declines", "lower",
    "cae", "cayó", "baja", "pérdida", "débiles", "bajista", "recorta", "demanda",
    "investigación", "fraude", "despidos", "alerta",
}


@dataclass
class NewsEnrichment:
    symbol: str
    freshness_score: float = 0.0
    sentiment: float = 0.0
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
    def __init__(self, settings: Any, session: requests.Session | None = None):
        self.settings = settings
        self.enabled = bool(getattr(settings, "enable_web_news_enhancer", False))
        self.max_age_hours = float(getattr(settings, "web_news_max_age_hours", 18.0))
        self.timeout = int(getattr(settings, "request_timeout_seconds", 12))
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; TradingAlertAI/3.17; +local-research)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })

    def enrich(self, symbol: str, existing_news: list[dict] | None = None) -> NewsEnrichment:
        if not self.enabled:
            return NewsEnrichment(symbol=symbol, source="disabled")
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return NewsEnrichment(symbol=symbol, error="empty_symbol")
        try:
            result = self._from_google_news(symbol)
            if result and result.headlines:
                return result
        except Exception as exc:
            logger.debug("web_news google failed for %s: %s", symbol, exc)
        if existing_news:
            try:
                return self._from_existing(symbol, existing_news)
            except Exception as exc:
                logger.debug("web_news existing failed for %s: %s", symbol, exc)
        return NewsEnrichment(symbol=symbol, source="none", error="no_news")

    def _from_google_news(self, symbol: str) -> NewsEnrichment | None:
        query = f"{symbol} stock OR {symbol} shares when:1d"
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
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
```

#### 1.2 `app/risk/quality_gate.py`

Crea este archivo completo:

```python
"""
Quality Gate — v3.17
Capa de selectividad extra (downward-only).
Solo puede BAJAR un candidato a paper-only o descartarlo.
Nunca habilita una orden que las reglas anteriores hubieran rechazado.
Soft-fail total.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

Action = Literal["allow", "paper_only", "discard"]


@dataclass
class QualityDecision:
    action: Action = "allow"
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    confluence_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_action": self.action,
            "quality_score": round(self.score, 1),
            "quality_reasons": self.reasons,
            "quality_confluence": self.confluence_count,
        }


class QualityGate:
    def __init__(self, settings: Any):
        self.enabled = bool(getattr(settings, "enable_quality_gate", False))
        self.min_confluence = int(getattr(settings, "quality_min_confluence", 2))
        self.min_confidence = int(getattr(settings, "strategy_min_confidence", 70))
        self.min_score = int(getattr(settings, "alert_score_threshold", 70))

    def evaluate(
        self,
        candidate: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> QualityDecision:
        if not self.enabled:
            return QualityDecision(action="allow", reasons=["quality_gate_disabled"])
        context = context or {}
        reasons: list[str] = []
        confluence = 0
        score = 50.0
        try:
            confidence = float(candidate.get("confidence") or candidate.get("score") or 0)
            base_score = float(candidate.get("score") or candidate.get("alert_score") or 0)

            if confidence >= self.min_confidence + 5 or base_score >= self.min_score + 5:
                confluence += 1
                score += 15
                reasons.append("high_confidence")
            elif confidence < self.min_confidence - 10 and base_score < self.min_score - 10:
                reasons.append("low_confidence")
                score -= 20

            regime = context.get("regime") or candidate.get("regime")
            direction = (candidate.get("direction") or candidate.get("side") or "").lower()
            if regime in ("up", "down", "range"):
                if (regime == "up" and direction in ("long", "buy")) or (
                    regime == "down" and direction in ("short", "sell")
                ):
                    confluence += 1
                    score += 12
                    reasons.append("regime_aligned")
                elif (regime == "up" and direction in ("short", "sell")) or (
                    regime == "down" and direction in ("long", "buy")
                ):
                    score -= 18
                    reasons.append("regime_against")

            news = context.get("news") or {}
            if news.get("news_has_catalyst") and news.get("news_freshness_score", 0) >= 60:
                confluence += 1
                score += 10
                reasons.append("fresh_catalyst")
            elif news.get("news_sentiment", 0) <= -0.4 and direction in ("long", "buy"):
                score -= 12
                reasons.append("negative_news_vs_long")

            risk_r = candidate.get("risk_r") or candidate.get("stop_distance_r")
            if risk_r is not None:
                try:
                    risk_r = float(risk_r)
                    if 0.5 <= risk_r <= 2.2:
                        confluence += 1
                        score += 8
                        reasons.append("reasonable_risk")
                    elif risk_r < 0.3 or risk_r > 3.5:
                        score -= 15
                        reasons.append("extreme_risk")
                except (TypeError, ValueError):
                    pass

            if context.get("calendar_safe") is True:
                confluence += 1
                score += 8
                reasons.append("calendar_safe")
            elif context.get("calendar_safe") is False:
                score -= 25
                reasons.append("calendar_danger")

            score = max(0.0, min(100.0, score))

            if score < 35 or confluence < 1:
                action: Action = "discard"
                reasons.append("quality_too_low")
            elif confluence < self.min_confluence or score < 55:
                action = "paper_only"
                reasons.append("insufficient_confluence")
            else:
                action = "allow"

            return QualityDecision(
                action=action,
                score=score,
                reasons=reasons,
                confluence_count=confluence,
            )
        except Exception as exc:
            logger.exception("QualityGate failed: %s", exc)
            return QualityDecision(action="allow", reasons=["quality_gate_error_softfail"])
```

### 2. Extender Settings (`app/config/settings.py`)

Añade estos 4 campos al `@dataclass Settings` (junto a los otros `enable_*`):

```python
    # v3.17 — Quality Gate + Web News Enhancer
    enable_quality_gate: bool
    quality_min_confluence: int
    enable_web_news_enhancer: bool
    web_news_max_age_hours: float
```

En `load_settings()` lee y pasa:

```python
    enable_quality_gate=_get_bool("ENABLE_QUALITY_GATE", False),
    quality_min_confluence=_get_int("QUALITY_MIN_CONFLUENCE", 2),
    enable_web_news_enhancer=_get_bool("ENABLE_WEB_NEWS_ENHANCER", False),
    web_news_max_age_hours=_get_float("WEB_NEWS_MAX_AGE_HOURS", 18.0),
```

Sincroniza los helpers `_settings()` de los tests que existan (`tests/test_score.py`, `tests/test_alert_rules.py`, etc.).

### 3. Actualizar `.env.example`

Añade al final de `.env.example`:

```env
# v3.17 — Quality Gate + Web News Enhancer (opt-in OFF)
ENABLE_QUALITY_GATE=false
QUALITY_MIN_CONFLUENCE=2
ENABLE_WEB_NEWS_ENHANCER=false
WEB_NEWS_MAX_AGE_HOURS=18
```

### 4. Integrar en el flujo de decisión (mínimo viable)

Busca el lugar donde se decide si un candidato de forex/oro/acciones pasa a paper o a MT5 demo (típicamente strategy router, decision engine o el job principal).

Integra de forma **mínima y soft-fail**:

```python
# Ejemplo de integración (adapta a los nombres reales del código)
from app.collectors.web_news_enhancer import WebNewsEnhancer
from app.risk.quality_gate import QualityGate

# Instanciar una sola vez (en el job o donde convenga)
news_enhancer = WebNewsEnhancer(settings)
quality_gate = QualityGate(settings)

# Por cada candidato, antes de abrir paper / preparar demo:
news_extra = news_enhancer.enrich(
    symbol=candidate.get("symbol") or candidate.get("ticker") or "",
    existing_news=candidate.get("news"),
)
context = {
    "regime": candidate.get("regime"),
    "calendar_safe": candidate.get("calendar_safe"),  # si ya existe
    "news": news_extra.to_dict(),
}
qd = quality_gate.evaluate(candidate, context)

if qd.action == "discard":
    # no paper, no alerta, no MT5
    # opcional: loguear qd.reasons
    continue  # o return / skip
elif qd.action == "paper_only":
    candidate["force_paper"] = True
    # o marca el flag que use el sistema para no mandar a MT5
# si "allow" → flujo normal
```

Importante:
- Si el quality gate o el news enhancer fallan → soft-fail (el candidato sigue el flujo anterior).
- No cambies la lógica de riesgo ni de position sizing.
- No habilites más operaciones de las que ya se habilitarían.

### 5. Tests mínimos (obligatorio)

Crea `tests/test_quality_gate.py` y `tests/test_web_news_enhancer.py` con al menos:

- QualityGate disabled → siempre `allow`
- QualityGate con confluencia baja → `paper_only` o `discard`
- QualityGate soft-fail ante datos rotos → `allow`
- WebNewsEnhancer disabled → source `"disabled"`
- WebNewsEnhancer con symbol vacío → error controlado
- Sentiment simple básico (texto positivo / negativo)

Deben pasar sin red (mockea requests si hace falta).

### 6. Subir versión

- Cambia `app_version` / default en settings a **`v3.17.0`**
- Añade entrada en `CHANGELOG.md` (arriba) resumiendo:
  - Quality Gate (opt-in, downward-only)
  - Web News Enhancer (opt-in, soft-fail)
  - Selectividad recomendada documentada
  - Sin cambios en real-money ni en edge

### 7. Documentación breve

Añade al final de `PROXIMOS_PASOS.md` un bloque corto:

```markdown
### 10-oct-2026 — v3.17.0: Quality Gate + Web News (selectividad)

- `ENABLE_QUALITY_GATE` + `ENABLE_WEB_NEWS_ENHANCER` (opt-in OFF).
- Downward-only + soft-fail.
- Recomendación de .env de calidad (umbrales más altos + gates activos + PAPER_PRICE_FROM_MT5).
- Objetivo: menos operaciones, más calidad. Observar 7-14 días con `/expectancy` y `/edge`.
- No se reabrieron familias del ledger.
```

## Después de implementar

1. Corre los tests: `pytest tests/test_quality_gate.py tests/test_web_news_enhancer.py -q`
2. Corre la suite completa si es razonable (o al menos los tests de settings/score/alert_rules).
3. **No arranques el bot.**
4. Dile al user exactamente qué tiene que poner en su `.env` real (los valores de selectividad) y el comando de warm-start:

```powershell
python scripts/ai_agent_warmstart.py --version 2 --mt5-d1 --exclude-mixed-gold --apply --force
```

5. Recuérdale verificar con `/agente` que aparezca el tag `|px1` y “modelo sin oro mezclado: sí”.

## Valores de .env que el user debe aplicar (tú no los pongas en el repo)

Dile al user que en su `.env` real ponga (entre otras):

```env
STRATEGY_MIN_CONFIDENCE=74
ALERT_SCORE_THRESHOLD=72
READINESS_MIN_SCORE=78
MAX_OPEN_TRADES_TOTAL=3
RISK_PER_TRADE_PCT=0.8
PAPER_PRICE_FROM_MT5=true
ENABLE_CALENDAR_GATE=true
ENABLE_USD_EXPOSURE_CAP=true
MAX_NET_USD_EXPOSURE=2
ENABLE_REGIME_GATE=true
ENABLE_VWAP_GATE=true
ENABLE_EXIT_SHADOW=true
ENABLE_QUALITY_GATE=true
ENABLE_WEB_NEWS_ENHANCER=true
QUALITY_MIN_CONFLUENCE=2
ENABLE_MEMECOIN_ENGINE=false
ENABLE_SCALPING_ENGINE=false
ENABLE_AI_AGENT=true
AI_AGENT_VERSION=2
AI_AGENT_EXPLORE_PCT=0.10
AI_AGENT_SHADOWS=true
```

## Criterio de éxito de esta sesión

- [ ] Los 2 módulos nuevos existen y son soft-fail
- [ ] Settings tiene los 4 campos nuevos (default OFF)
- [ ] `.env.example` actualizado
- [ ] Integración mínima en el decision path
- [ ] Tests nuevos pasan
- [ ] Versión = v3.17.0
- [ ] CHANGELOG + PROXIMOS_PASOS actualizados
- [ ] Real-money intacto
- [ ] No se arrancó el bot
- [ ] Le diste al user el bloque de .env y el comando de warm-start

Empieza por crear los dos módulos y extender Settings. Cuando termines, resume qué archivos tocaste y qué debe hacer el user a continuación.
