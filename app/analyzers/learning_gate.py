"""Filtra alertas usando el backtester historico.

Si una combinacion de features tiene historial pobre (win_rate por debajo
del umbral con muestras suficientes), bloquea el envio.

Read-only: solo decide si enviar, no toca el broker.
"""

from app.config.settings import Settings
from app.database.repository import Repository
from app.learning.backtester import backtest_strategy


def evaluate_learning_gate(
    features: list[str],
    category: str,
    settings: Settings,
    repository: Repository,
) -> tuple[bool, str]:
    # Phase 4.5 v2.4.0: memecoin SIEMPRE pasa por gate (defensa anti-rug).
    # Aunque ENABLE_LEARNING_GATE=false a nivel global, para category=memecoin
    # se fuerza ON si force_learning_gate_for_memecoin=true.
    force_for_category = (
        category == "memecoin"
        and getattr(settings, "force_learning_gate_for_memecoin", False)
    )
    if not settings.enable_learning_gate and not force_for_category:
        return True, "gate disabled"

    # v2.7.0 Fase 2b: si enable_realized_learning, el gate decide por realized-R
    # (lessons honestas desde paper_trades cerrados) en vez del drift de alerta.
    if getattr(settings, "enable_realized_learning", False):
        return _evaluate_gate_realized(features, category, settings, repository)

    subset = [
        feature
        for feature in features
        if feature.startswith(("category:", "alert:", "score:"))
    ]
    if not subset:
        subset = [f"category:{category}"]

    result = backtest_strategy(
        repository=repository,
        filter_features=subset,
        horizon_hours=settings.learning_gate_horizon_hours,
        since_days=settings.learning_gate_since_days,
        category=category,
    )

    if result.sample_count < settings.learning_gate_min_samples:
        return True, f"insufficient samples ({result.sample_count})"

    if result.win_rate < settings.learning_gate_min_win_rate:
        return (
            False,
            f"win_rate {result.win_rate:.0%} below {settings.learning_gate_min_win_rate:.0%} ({result.sample_count} samples)",
        )

    return True, f"win_rate {result.win_rate:.0%} ok ({result.sample_count} samples)"


def _evaluate_gate_realized(
    features: list[str],
    category: str,
    settings: Settings,
    repository: Repository,
) -> tuple[bool, str]:
    """Gate basado en realized-R (Fase 2b): bloquea el alert si alguna de sus
    features tiene win_rate REALIZADO probado por debajo del umbral (con
    n >= learning_gate_min_samples). 'Inocente hasta probarse culpable': si
    ninguna feature tiene muestra suficiente, pasa. Usa las realized_feature_lessons
    (P&L real de paper_trades), no el drift de la alerta.
    """
    subset = [
        feature
        for feature in features
        if feature.startswith(("category:", "alert:", "score:"))
    ]
    if not subset:
        subset = [f"category:{category}"]
    lessons = repository.fetch_realized_feature_lessons(category=category, limit=200)
    by_feature = {str(lesson.get("feature")): lesson for lesson in lessons}
    candidates = [
        by_feature[f]
        for f in subset
        if f in by_feature
        and int(by_feature[f].get("sample_count") or 0) >= settings.learning_gate_min_samples
    ]
    if not candidates:
        return True, "realized: insufficient samples"
    worst = min(candidates, key=lambda lesson: float(lesson.get("win_rate") or 0.0))
    wr = float(worst.get("win_rate") or 0.0)
    n = int(worst.get("sample_count") or 0)
    if wr < settings.learning_gate_min_win_rate:
        return (
            False,
            f"realized win_rate {wr:.0%} below {settings.learning_gate_min_win_rate:.0%} "
            f"(feature {worst.get('feature')}, n={n})",
        )
    return True, f"realized win_rate {wr:.0%} ok (feature {worst.get('feature')}, n={n})"
