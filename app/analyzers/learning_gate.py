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
    if not settings.enable_learning_gate:
        return True, "gate disabled"

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
