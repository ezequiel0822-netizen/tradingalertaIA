import statistics
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from app.database.repository import Repository
from app.learning.feature_extractor import extract_features
from app.utils.time_utils import utc_now


PAIR_RULES: tuple[tuple[str, str], ...] = (
    ("ia_pro", "score:80-90"),
    ("ia_pro", "score:90+"),
    ("ia_pro", "category:stock"),
    ("ia_pro", "category:memecoin"),
    ("ia_pro", "positive_news"),
    ("ia_pro", "sec_catalyst"),
    ("bullish_pattern", "score:80-90"),
    ("bullish_pattern", "category:stock"),
    ("bullish_pattern", "ia_pro"),
    ("positive_news", "score:80-90"),
    ("positive_news", "category:stock"),
    ("sec_catalyst", "score:65-80"),
    ("volume_strength", "ia_pro"),
    ("volume_strength", "boosted_or_trending"),
    ("liquidity_strength", "ia_pro"),
    ("category:stock", "score:80-90"),
    ("category:memecoin", "score:80-90"),
    ("category:memecoin", "boosted_or_trending"),
    ("anti_hype", "category:memecoin"),
    ("critical_security", "category:memecoin"),
)


@dataclass
class BacktestResult:
    rule_label: str
    horizon_hours: int
    sample_count: int
    win_rate: float
    avg_return_pct: float
    median_return_pct: float
    avg_mfe_pct: float
    avg_mae_pct: float
    max_drawdown_pct: float
    sharpe_approx: float
    equity_curve: list[float] = field(default_factory=list)


def backtest_strategy(
    repository: Repository,
    filter_features: list[str],
    horizon_hours: int,
    since_days: int = 30,
    category: str | None = None,
) -> BacktestResult:
    since_iso = (utc_now() - timedelta(days=since_days)).isoformat()
    rows = repository.fetch_horizons_by_features(
        horizon_hours=horizon_hours,
        since_iso=since_iso,
        limit=2000,
    )
    if category:
        rows = [row for row in rows if str(row.get("category") or "") == category]
    filtered = _filter_by_features(rows, filter_features) if filter_features else rows
    label = " + ".join(filter_features) if filter_features else "all"
    if category:
        label = f"{label} ({category})"
    return _compute_metrics(label, horizon_hours, filtered)


def rank_top_strategies(
    repository: Repository,
    horizon_hours: int,
    since_days: int = 30,
    min_samples: int = 5,
    top_n: int = 10,
) -> list[BacktestResult]:
    since_iso = (utc_now() - timedelta(days=since_days)).isoformat()
    rows = repository.fetch_horizons_by_features(
        horizon_hours=horizon_hours,
        since_iso=since_iso,
        limit=2000,
    )
    if not rows:
        return []

    feature_index: dict[str, list[dict[str, Any]]] = {}
    feature_cache: dict[int, set[str]] = {}
    for row in rows:
        features = set(extract_features(row))
        feature_cache[int(row.get("horizon_id") or id(row))] = features
        for feature in features:
            feature_index.setdefault(feature, []).append(row)

    candidates: list[BacktestResult] = []
    for feature, feat_rows in feature_index.items():
        if len(feat_rows) < min_samples:
            continue
        candidates.append(_compute_metrics(feature, horizon_hours, feat_rows))

    for left, right in PAIR_RULES:
        if left not in feature_index or right not in feature_index:
            continue
        combined = [
            row
            for row in rows
            if {left, right}.issubset(
                feature_cache.get(int(row.get("horizon_id") or id(row)), set())
            )
        ]
        if len(combined) < min_samples:
            continue
        candidates.append(
            _compute_metrics(f"{left} + {right}", horizon_hours, combined)
        )

    candidates.sort(
        key=lambda r: (r.sharpe_approx, r.win_rate, r.sample_count),
        reverse=True,
    )
    return candidates[:top_n]


def _filter_by_features(
    rows: list[dict[str, Any]],
    filter_features: list[str],
) -> list[dict[str, Any]]:
    target = set(filter_features)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if target.issubset(set(extract_features(row))):
            filtered.append(row)
    return filtered


def _compute_metrics(
    rule_label: str,
    horizon_hours: int,
    rows: list[dict[str, Any]],
) -> BacktestResult:
    if not rows:
        return BacktestResult(
            rule_label=rule_label,
            horizon_hours=horizon_hours,
            sample_count=0,
            win_rate=0.0,
            avg_return_pct=0.0,
            median_return_pct=0.0,
            avg_mfe_pct=0.0,
            avg_mae_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe_approx=0.0,
            equity_curve=[],
        )

    returns = [_to_float(row.get("return_pct")) or 0.0 for row in rows]
    mfes = [_to_float(row.get("mfe_pct")) or 0.0 for row in rows]
    maes = [_to_float(row.get("mae_pct")) or 0.0 for row in rows]
    labels = [str(row.get("outcome_label") or "") for row in rows]
    wins = sum(1 for label in labels if label == "win")
    win_rate = wins / len(rows)
    avg_return = sum(returns) / len(returns)
    median_return = statistics.median(returns)
    avg_mfe = sum(mfes) / len(mfes)
    avg_mae = sum(maes) / len(maes)
    max_drawdown = min(maes) if maes else 0.0
    if len(returns) >= 2:
        stdev = statistics.stdev(returns)
        sharpe = avg_return / stdev if stdev > 0 else 0.0
    else:
        sharpe = 0.0

    equity = 1.0
    curve: list[float] = []
    for r in returns:
        equity *= 1 + (r / 100.0)
        curve.append(round(equity, 6))

    return BacktestResult(
        rule_label=rule_label,
        horizon_hours=horizon_hours,
        sample_count=len(rows),
        win_rate=round(win_rate, 4),
        avg_return_pct=round(avg_return, 4),
        median_return_pct=round(median_return, 4),
        avg_mfe_pct=round(avg_mfe, 4),
        avg_mae_pct=round(avg_mae, 4),
        max_drawdown_pct=round(max_drawdown, 4),
        sharpe_approx=round(sharpe, 4),
        equity_curve=curve,
    )


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
