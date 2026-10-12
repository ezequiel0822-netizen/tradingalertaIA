"""
Quality Gate — v3.17 propuesta
------------------------------
Capa de selectividad extra (downward-only).

Reglas:
- Solo puede BAJAR un candidato a paper-only o descartarlo.
- Nunca habilita una orden que las reglas anteriores hubieran rechazado.
- Soft-fail: si está OFF o falla, el flujo sigue igual.

Confluencia mínima configurable (default 2):
  1. Régimen alineado (si enable_regime_gate y hay dato)
  2. Score / confianza altos
  3. Noticias frescas con catalizador (si hay web_news)
  4. ATR / riesgo razonable (stop no demasiado apretado ni demasiado ancho)
  5. No hay evento de calendario cercano (si calendar_gate)

Uso sugerido (en el router o decision engine):

  from app.risk.quality_gate import QualityGate, QualityDecision
  gate = QualityGate(settings)
  decision = gate.evaluate(candidate, context)
  if decision.action == "discard":
      ...
  elif decision.action == "paper_only":
      ...
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
        """Evalúa un candidato. Nunca lanza."""
        if not self.enabled:
            return QualityDecision(action="allow", reasons=["quality_gate_disabled"])

        context = context or {}
        reasons: list[str] = []
        confluence = 0
        score = 50.0

        try:
            confidence = float(candidate.get("confidence") or candidate.get("score") or 0)
            base_score = float(candidate.get("score") or candidate.get("alert_score") or 0)

            # 1) Confianza / score altos
            if confidence >= self.min_confidence + 5 or base_score >= self.min_score + 5:
                confluence += 1
                score += 15
                reasons.append("high_confidence")
            elif confidence < self.min_confidence - 10 and base_score < self.min_score - 10:
                reasons.append("low_confidence")
                score -= 20

            # 2) Régimen alineado
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

            # 3) Noticias / catalizador
            news = context.get("news") or {}
            if news.get("news_has_catalyst") and news.get("news_freshness_score", 0) >= 60:
                confluence += 1
                score += 10
                reasons.append("fresh_catalyst")
            elif news.get("news_sentiment", 0) <= -0.4 and direction in ("long", "buy"):
                score -= 12
                reasons.append("negative_news_vs_long")

            # 4) Riesgo / ATR razonable (stop entre 0.4R y 2.5R típicos)
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

            # 5) Calendario limpio
            if context.get("calendar_safe") is True:
                confluence += 1
                score += 8
                reasons.append("calendar_safe")
            elif context.get("calendar_safe") is False:
                score -= 25
                reasons.append("calendar_danger")

            # Decisión final
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
            # Soft-fail: no bloqueamos
            return QualityDecision(
                action="allow",
                reasons=["quality_gate_error_softfail"],
            )
