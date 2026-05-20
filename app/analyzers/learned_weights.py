"""Aplica ajuste al score base usando strategy_lessons aprendidas.

Read-only: solo modifica el score in-memory, no persiste pesos en DB.
Si el setting esta off, devuelve el score sin cambios.
"""

from typing import Any

from app.config.settings import Settings
from app.database.repository import Repository


def apply_learned_weights(
    base_score: int,
    features: list[str],
    category: str,
    settings: Settings,
    repository: Repository,
) -> tuple[int, list[str]]:
    if not settings.enable_learned_weights:
        return base_score, []
    if base_score <= 0:
        return base_score, []

    lessons = repository.fetch_strategy_lessons(category=category, limit=200)
    if not lessons:
        return base_score, []

    feature_to_lesson: dict[str, dict[str, Any]] = {}
    for lesson in lessons:
        sample_count = int(lesson.get("sample_count") or 0)
        confidence = int(lesson.get("confidence") or 0)
        if sample_count < settings.learned_weights_min_samples:
            continue
        if confidence < settings.learned_weights_min_confidence:
            continue
        feature = str(lesson.get("feature") or "")
        if feature:
            feature_to_lesson[feature] = lesson

    if not feature_to_lesson:
        return base_score, []

    per_feature_max = float(settings.learned_weights_per_feature_max)
    adjustment = 0.0
    reasons: list[str] = []
    for feature in features:
        lesson = feature_to_lesson.get(feature)
        if not lesson:
            continue
        win_rate = float(lesson.get("win_rate") or 0)
        confidence = float(lesson.get("confidence") or 0)
        # bonus en [-per_feature_max, +per_feature_max]
        bonus = (win_rate - 0.5) * 2 * (confidence / 100) * per_feature_max
        adjustment += bonus
        if abs(bonus) >= 0.5:
            sign = "+" if bonus > 0 else ""
            reasons.append(
                f"Peso aprendido {feature} ({sign}{bonus:.1f}): "
                f"win_rate {win_rate:.0%} en {int(lesson.get('sample_count') or 0)} casos."
            )

    max_adj = float(settings.learned_weights_max_adjustment)
    if adjustment > max_adj:
        adjustment = max_adj
    elif adjustment < -max_adj:
        adjustment = -max_adj

    adjusted = base_score + int(round(adjustment))
    adjusted = max(0, min(100, adjusted))
    return adjusted, reasons
