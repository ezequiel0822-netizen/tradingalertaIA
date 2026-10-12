"""v3.17.0 — Quality gate (filtro de confluencia), adaptado del paquete "v3.17 calidad"
(propuestas/2026-10-10_v3.17_calidad/, revisión REVISION_CLAUDE_2026-10-12.md).

PURO: sin DB, sin red, sin MT5. Recibe los datos YA calculados de un candidato
(`QualityInputs`) y devuelve qué diría el gate (`QualityDecision`). No decide nada solo:

- con ENABLE_QUALITY_GATE, jobs.py ANOTA la decisión de cada candidato en
  `quality_gate_shadow` (medición en sombra; reglas en research/CALIDAD_SOMBRA_2026-10-12.md);
- con QUALITY_GATE_ENFORCE, en el camino a MT5 que NO es del agente, `paper_only` deja el
  candidato en paper (sin order_send). Downward-only: nunca habilita nada.

Nunca descarta. El paquete tenía "discard" (sin paper trade no hay dato para medir si el
filtro sirve y el agente no aprende de ese candidato): acá ese escalón es `paper_only` con
motivo `quality_too_low`.

Mapeo a los datos reales del bot (el paquete leía claves que los candidatos no tienen y,
pegado tal cual, mandaba TODO a "discard"):
- confianza = StrategySignal.confidence; score = AlertRecord.score;
- régimen D1 'up' / 'down' / 'flat' (el 'range' del paquete no existe en el bot);
- riesgo = distancia al stop en ATR (el stop ya ES 1R, "risk_r" no medía nada);
- calendario = ventana de eventos de alto impacto (None = sin dato).

Reglas congeladas como GATE_VERSION "qg1": cambiar un punto = otra versión.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

GATE_VERSION = "qg1"
ALLOW = "allow"
PAPER_ONLY = "paper_only"


@dataclass(frozen=True)
class QualityInputs:
    """Lo que el gate mira de un candidato, todo as-of la apertura. None = sin dato."""

    direction: str                       # "long" | "short"
    confidence: float | None = None      # StrategySignal.confidence (0-100)
    alert_score: float | None = None     # AlertRecord.score (0-100)
    regime: str | None = None            # 'up' | 'down' | 'flat' (D1 de MT5; acciones: None)
    calendar_safe: bool | None = None    # False = evento de alto impacto cerca
    stop_atr: float | None = None        # |entrada - stop| en múltiplos de ATR
    news_catalyst: bool | None = None    # solo acciones
    news_freshness: float | None = None  # 0-100
    news_sentiment: float | None = None  # -1 a +1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QualityDecision:
    action: str = ALLOW
    score: float | None = None
    confluence: int = 0
    reasons: list[str] = field(default_factory=list)
    version: str = GATE_VERSION

    @property
    def paper_only(self) -> bool:
        return self.action == PAPER_ONLY


@dataclass
class QualityCandidate:
    """Contexto de un candidato mientras pasa por jobs.py: lo que solo se conoce al abrir
    (confianza de la señal, score de la alerta) y lo que el gate ya calculó."""

    paper_trade_id: int
    confidence: float | None = None
    alert_score: float | None = None
    inputs: QualityInputs | None = None
    decision: QualityDecision | None = None
    enforced: bool = False


def stop_distance_atr(entry: Any, stop: Any, atr_pct: Any) -> float | None:
    """|entrada - stop| / entrada en %, dividido por el ATR en % del precio."""
    e, s, a = _num(entry), _num(stop), _num(atr_pct)
    if e is None or s is None or a is None or e <= 0 or a <= 0:
        return None
    return round(abs(e - s) / e * 100.0 / a, 4)


def evaluate(
    inputs: QualityInputs,
    *,
    min_confidence: float,
    min_score: float,
    min_confluence: int,
) -> QualityDecision:
    """Qué diría el gate. Nunca lanza: ante un error devuelve `allow` (soft-fail)."""
    try:
        return _evaluate(inputs, float(min_confidence), float(min_score), int(min_confluence))
    except Exception:
        logger.exception("Quality gate fallo; soft-fail -> allow")
        return QualityDecision(action=ALLOW, score=None, reasons=["quality_gate_error"])


def _evaluate(
    inputs: QualityInputs, min_conf: float, min_score: float, min_confluence: int
) -> QualityDecision:
    reasons: list[str] = []
    confluence = 0
    score = 50.0
    direction = _direction(inputs.direction)

    # 1) Confianza de la señal / score de la alerta
    conf = _num(inputs.confidence)
    base = _num(inputs.alert_score)
    if conf is None and base is None:
        reasons.append("confidence_unknown")
    else:
        c = conf if conf is not None else 0.0
        b = base if base is not None else 0.0
        if c >= min_conf + 5 or b >= min_score + 5:
            confluence += 1
            score += 15
            reasons.append("high_confidence")
        elif c < min_conf - 10 and b < min_score - 10:
            score -= 20
            reasons.append("low_confidence")

    # 2) Régimen D1 ('flat' o sin dato: nada)
    regime = str(inputs.regime or "").lower()
    if (regime == "up" and direction == "long") or (regime == "down" and direction == "short"):
        confluence += 1
        score += 12
        reasons.append("regime_aligned")
    elif (regime == "up" and direction == "short") or (regime == "down" and direction == "long"):
        score -= 18
        reasons.append("regime_against")

    # 3) Noticias (solo acciones)
    freshness = _num(inputs.news_freshness)
    sentiment = _num(inputs.news_sentiment)
    if inputs.news_catalyst and (freshness or 0.0) >= 60:
        confluence += 1
        score += 10
        reasons.append("fresh_catalyst")
    elif sentiment is not None and sentiment <= -0.4 and direction == "long":
        score -= 12
        reasons.append("negative_news_vs_long")

    # 4) Distancia al stop en ATR
    stop_atr = _num(inputs.stop_atr)
    if stop_atr is not None:
        if 0.5 <= stop_atr <= 2.2:
            confluence += 1
            score += 8
            reasons.append("reasonable_risk")
        elif stop_atr < 0.3 or stop_atr > 3.5:
            score -= 15
            reasons.append("extreme_risk")

    # 5) Calendario
    if inputs.calendar_safe is True:
        confluence += 1
        score += 8
        reasons.append("calendar_safe")
    elif inputs.calendar_safe is False:
        score -= 25
        reasons.append("calendar_danger")

    score = max(0.0, min(100.0, score))
    if score < 35 or confluence < 1:
        action = PAPER_ONLY
        reasons.append("quality_too_low")      # el "discard" del paquete
    elif confluence < min_confluence or score < 55:
        action = PAPER_ONLY
        reasons.append("insufficient_confluence")
    else:
        action = ALLOW
    return QualityDecision(action=action, score=score, confluence=confluence, reasons=reasons)


def _direction(value: Any) -> str:
    d = str(value or "").strip().lower()
    if d in ("long", "buy"):
        return "long"
    if d in ("short", "sell"):
        return "short"
    return ""


def _num(value: Any) -> float | None:
    """Número finito o None (texto, NaN, bool o vacío = sin dato)."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None
