import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.analyzers.trading_readiness import build_trade_readiness
from app.config.settings import Settings
from app.database.models import EstimateResult, TokenSnapshot
from app.database.repository import Repository
from app.learning.feature_extractor import extract_features
from app.learning.trade_outcomes import build_strategy_performance
from app.utils.time_utils import utc_now_iso


@dataclass
class LearningRunResult:
    alerts_evaluated: int
    outcomes_created: int
    lessons_updated: int
    paper_trades_created: int
    summary: str
    horizons_created: int = 0
    horizons_updated: int = 0
    strategy_perf_updated: int = 0


def run_learning_cycle(settings: Settings, repository: Repository) -> LearningRunResult:
    alerts = repository.fetch_alerts_for_learning(
        settings.learning_min_alert_age_minutes,
        settings.learning_max_alerts_per_run,
    )
    outcomes_created = 0
    for alert in alerts:
        outcome = _build_outcome(alert, settings)
        if outcome and repository.upsert_signal_outcome(outcome):
            outcomes_created += 1

    horizons_created = 0
    horizons_updated = 0
    if settings.enable_horizon_evaluator:
        # Import local para evitar ciclo: horizon_evaluator importa _outcome_label de este modulo.
        from app.learning.horizon_evaluator import evaluate_horizons

        horizon_counts = evaluate_horizons(settings, repository)
        horizons_created = horizon_counts.get("horizons_created", 0)
        horizons_updated = horizon_counts.get("horizons_updated", 0)

    lessons = _build_lessons(repository.fetch_signal_outcomes(limit=2000))
    for lesson in lessons:
        repository.upsert_strategy_lesson(lesson)

    paper_trades_created = 0
    strategy_perf_updated = 0
    if settings.enable_paper_trading:
        paper_trades_created += _create_paper_trades(settings, repository, alerts)
        _update_paper_trades(repository, settings)
        strategy_perf_updated = _refresh_strategy_performance(repository, settings)

    summary = (
        f"Evaluadas {len(alerts)} señales; outcomes nuevos {outcomes_created}; "
        f"lecciones {len(lessons)}; paper trades nuevos {paper_trades_created}; "
        f"horizontes nuevos {horizons_created} (refrescados {horizons_updated}); "
        f"expectancy por estrategia (R) {strategy_perf_updated}."
    )
    repository.insert_training_run(
        {
            "app_version": settings.app_version,
            "alerts_evaluated": len(alerts),
            "outcomes_created": outcomes_created,
            "lessons_updated": len(lessons),
            "paper_trades_created": paper_trades_created,
            "summary": summary,
            "created_at": utc_now_iso(),
        }
    )
    return LearningRunResult(
        alerts_evaluated=len(alerts),
        outcomes_created=outcomes_created,
        lessons_updated=len(lessons),
        paper_trades_created=paper_trades_created,
        summary=summary,
        horizons_created=horizons_created,
        horizons_updated=horizons_updated,
        strategy_perf_updated=strategy_perf_updated,
    )


def _build_outcome(alert: dict[str, Any], settings: Settings) -> dict[str, Any] | None:
    entry = _to_float(alert.get("price"))
    latest = _to_float(alert.get("token_latest_price"))
    if entry is None or latest is None or entry <= 0:
        return None

    observed_return = ((latest - entry) / entry) * 100
    category = str(alert.get("category") or "memecoin")
    label = _outcome_label(observed_return, category, settings)
    created_at = _parse_dt(str(alert.get("created_at") or ""))
    age_minutes = 0
    if created_at:
        age_minutes = int((datetime.now(timezone.utc) - created_at).total_seconds() / 60)
    features = extract_features(alert)

    return {
        "alert_id": int(alert["id"]),
        "token_id": int(alert["token_id"]),
        "category": category,
        "chain": alert.get("chain"),
        "token_address": alert.get("token_address"),
        "symbol": alert.get("symbol"),
        "entry_price": entry,
        "latest_price": latest,
        "observed_return_pct": round(observed_return, 4),
        "score": int(alert.get("score") or 0),
        "confidence": int(alert.get("estimate_confidence") or 0),
        "outcome_label": label,
        "age_minutes": age_minutes,
        "features": json.dumps(features, ensure_ascii=False),
        "evaluated_at": utc_now_iso(),
    }


def _outcome_label(return_pct: float, category: str, settings: Settings) -> str:
    if category == "stock":
        if return_pct >= settings.outcome_win_return_stock_pct:
            return "win"
        if return_pct <= settings.outcome_loss_return_stock_pct:
            return "loss"
        return "neutral"
    if return_pct >= settings.outcome_win_return_memecoin_pct:
        return "win"
    if return_pct <= settings.outcome_loss_return_memecoin_pct:
        return "loss"
    return "neutral"


def _build_lessons(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa outcomes en lessons por (feature, category).

    v2.6.0 Phase 5.5 Bloque B: si outcome.is_scalping=1, la category del
    bucket lleva sufijo `_scalping` (ej. 'forex_scalping') para no mezclar
    lessons de scalping con las de swing. Esto evita schema change a la
    constraint UNIQUE(feature, category) de strategy_lessons.
    """
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for outcome in outcomes:
        category = str(outcome.get("category") or "unknown")
        if int(outcome.get("is_scalping") or 0) == 1:
            category = f"{category}_scalping"
        try:
            features = json.loads(outcome.get("features") or "[]")
        except json.JSONDecodeError:
            features = []
        for feature in features:
            buckets.setdefault((str(feature), category), []).append(outcome)

    lessons: list[dict[str, Any]] = []
    for (feature, category), rows in buckets.items():
        if len(rows) < 2:
            continue
        wins = sum(1 for row in rows if row.get("outcome_label") == "win")
        losses = sum(1 for row in rows if row.get("outcome_label") == "loss")
        returns = [_to_float(row.get("observed_return_pct")) or 0 for row in rows]
        scores = [_to_float(row.get("score")) or 0 for row in rows]
        win_rate = wins / len(rows)
        avg_return = sum(returns) / len(returns)
        avg_score = sum(scores) / len(scores)
        confidence = min(100, int(len(rows) * 8 + abs(avg_return) * 0.5))
        lesson = _lesson_text(feature, category, len(rows), win_rate, avg_return, losses)
        lessons.append(
            {
                "feature": feature,
                "category": category,
                "sample_count": len(rows),
                "win_rate": round(win_rate, 4),
                "avg_return_pct": round(avg_return, 4),
                "avg_score": round(avg_score, 2),
                "confidence": confidence,
                "lesson": lesson,
                "updated_at": utc_now_iso(),
            }
        )
    return sorted(lessons, key=lambda row: (row["confidence"], row["win_rate"]), reverse=True)[:80]


def _lesson_text(
    feature: str,
    category: str,
    sample_count: int,
    win_rate: float,
    avg_return: float,
    losses: int,
) -> str:
    if win_rate >= 0.6 and avg_return > 0:
        return (
            f"En {category}, '{feature}' esta funcionando: {win_rate:.0%} wins, "
            f"retorno medio {avg_return:.2f}% en {sample_count} casos."
        )
    if losses > 0 and avg_return < 0:
        return (
            f"En {category}, '{feature}' esta castigando resultados: "
            f"retorno medio {avg_return:.2f}% en {sample_count} casos."
        )
    return (
        f"En {category}, '{feature}' sigue inconcluso: {win_rate:.0%} wins, "
        f"retorno medio {avg_return:.2f}%."
    )


def _create_paper_trades(
    settings: Settings,
    repository: Repository,
    alerts: list[dict[str, Any]],
) -> int:
    created = 0
    active = repository.count_active_paper_trades()
    for alert in alerts:
        if active + created >= settings.paper_trade_max_active:
            break
        if not alert.get("sent_to_telegram"):
            continue
        snapshot = _snapshot_from_alert(alert)
        estimate = EstimateResult(
            estimated_gain_pct=_to_float(alert.get("estimated_gain_pct")) or 0,
            estimated_loss_pct=_to_float(alert.get("estimated_loss_pct")) or 0,
            confidence=int(alert.get("estimate_confidence") or 0),
            label="paper",
            reasons=[],
            eligible_for_gain_alert=True,
        )
        readiness = build_trade_readiness(
            snapshot,
            estimate,
            int(alert.get("score") or 0),
            str(alert.get("risk_level") or "unknown"),
            settings,
            _reasons(alert),
        )
        if readiness.blocked or readiness.grade not in {"A", "B"}:
            continue
        now = utc_now_iso()
        trade = {
            "alert_id": int(alert["id"]),
            "token_id": int(alert["token_id"]),
            "category": alert.get("category"),
            "chain": alert.get("chain"),
            "token_address": alert.get("token_address"),
            "symbol": alert.get("symbol"),
            "thesis": readiness.thesis,
            "readiness_grade": readiness.grade,
            "entry_price": snapshot.price,
            "latest_price": _to_float(alert.get("token_latest_price")) or snapshot.price,
            "stop_loss": readiness.stop_loss,
            "take_profit_1": readiness.take_profit_1,
            "take_profit_2": readiness.take_profit_2,
            "invalidation": readiness.invalidation,
            "status": "open",
            "unrealized_return_pct": 0,
            "opened_at": now,
            "updated_at": now,
            "closed_at": None,
            "mfe_pct": 0,
            "mae_pct": 0,
            "original_stop_loss": readiness.stop_loss,
            "trailing_active": 0,
        }
        if repository.create_paper_trade(trade):
            created += 1
    return created


def _update_paper_trades(
    repository: Repository, settings: Settings | None = None
) -> None:
    """Mark-to-market + exit checks para paper trades abiertos.

    v2.7.0 BUGFIX (direction-aware): este updater era LONG-ONLY. Para un trade
    SHORT el stop está POR ENCIMA del entry, así que la condición long-only
    `latest <= stop` era trivialmente verdadera apenas se creaba el trade →
    cada short se marcaba `stopped_simulated` en el MISMO ciclo (run_learning_cycle
    corre después de _try_open_paper_trades), con vida ~12s y precio congelado en
    entry. Eso envenenó ~85% del historial de paper_trades (forex/gold shorts) y
    alimentó el feedback loop (al cerrarse al instante, el dedup de posiciones
    abiertas no protegía y se reabría el mismo setup). Ahora respeta `direction`,
    igual que lifecycle_manager.manage_open_positions.
    """
    for trade in repository.fetch_paper_trades(status="open", limit=200):
        token = repository.get_token(str(trade.get("chain")), str(trade.get("token_address")))
        latest = _to_float((token or {}).get("latest_price"))
        entry = _to_float(trade.get("entry_price"))
        if latest is None or entry is None or entry <= 0:
            continue
        direction = str(trade.get("direction") or "long")
        if direction == "short":
            return_pct = ((entry - latest) / entry) * 100
        else:
            return_pct = ((latest - entry) / entry) * 100

        prior_mfe = _to_float(trade.get("mfe_pct")) or 0.0
        prior_mae = _to_float(trade.get("mae_pct")) or 0.0
        new_mfe = max(prior_mfe, return_pct)
        new_mae = min(prior_mae, return_pct)

        updates: dict[str, Any] = {
            "latest_price": latest,
            "unrealized_return_pct": round(return_pct, 4),
            "mfe_pct": round(new_mfe, 4),
            "mae_pct": round(new_mae, 4),
            "updated_at": utc_now_iso(),
        }

        stop = _to_float(trade.get("stop_loss"))

        if settings is not None and settings.enable_trailing_stop:
            category = str(trade.get("category") or "memecoin")
            if category == "stock":
                activation = settings.trailing_activation_pct_stock
                distance = settings.trailing_distance_pct_stock
            else:
                activation = settings.trailing_activation_pct_memecoin
                distance = settings.trailing_distance_pct_memecoin
            trailing_active = int(trade.get("trailing_active") or 0)
            if not trailing_active and return_pct >= activation:
                trailing_active = 1
                updates["trailing_active"] = 1
            if trailing_active:
                if direction == "short":
                    # short: el trailing BAJA el stop hacia el precio (nunca sube)
                    new_stop = latest * (1 + distance / 100)
                    if stop is None or new_stop < stop:
                        stop = new_stop
                        updates["stop_loss"] = round(new_stop, 8)
                else:
                    new_stop = latest * (1 - distance / 100)
                    if stop is None or new_stop > stop:
                        stop = new_stop
                        updates["stop_loss"] = round(new_stop, 8)

        target_2 = _to_float(trade.get("take_profit_2"))
        status = "open"
        closed_at = None
        if direction == "short":
            if stop is not None and latest >= stop:
                status = "stopped_simulated"
                closed_at = utc_now_iso()
            elif target_2 is not None and latest <= target_2:
                status = "target_2_simulated"
                closed_at = utc_now_iso()
        else:
            if stop is not None and latest <= stop:
                status = "stopped_simulated"
                closed_at = utc_now_iso()
            elif target_2 is not None and latest >= target_2:
                status = "target_2_simulated"
                closed_at = utc_now_iso()
        updates["status"] = status
        updates["closed_at"] = closed_at

        repository.update_paper_trade(int(trade["id"]), updates)


def _refresh_strategy_performance(repository: Repository, settings: Settings) -> int:
    """v2.7.0: recomputa expectancy realizada en R por (strategy_name, category)
    desde paper_trades cerrados, excluyendo artifacts del feedback-loop, y la
    persiste en strategy_performance. Devuelve cuántas filas se upsertearon.

    Señal HONESTA de aprendizaje: a diferencia de signal_outcomes (drift de la
    alerta a horizonte fijo con umbrales absolutos, ~99% 'neutral'), mide el P&L
    realizado del trade normalizado por el riesgo asumido al entry.
    """
    closed = repository.fetch_closed_paper_trades(limit=5000)
    if not closed:
        return 0
    frac = float(getattr(settings, "partial_close_fraction", 0.5) or 0.5)
    perfs = build_strategy_performance(closed, partial_fraction=frac)
    now = utc_now_iso()
    count = 0
    for p in perfs:
        repository.upsert_strategy_performance(
            {
                "strategy_name": p.strategy_name,
                "category": p.category,
                "trades": p.trades,
                "wins": p.wins,
                "losses": p.losses,
                "scratches": p.scratches,
                "win_rate": p.win_rate,
                "avg_r": p.avg_r,
                "avg_return_pct": p.avg_return_pct,
                "sum_return_pct": p.sum_return_pct,
                "artifacts_excluded": p.artifacts_excluded,
                "updated_at": now,
            }
        )
        count += 1
    return count


def _snapshot_from_alert(alert: dict[str, Any]) -> TokenSnapshot:
    return TokenSnapshot(
        chain=str(alert.get("chain") or "unknown"),
        token_address=str(alert.get("token_address") or ""),
        category=str(alert.get("category") or "memecoin"),
        symbol=str(alert.get("symbol") or "unknown"),
        name=str(alert.get("name") or "unknown"),
        source=str(alert.get("source") or "SQLite"),
        price=_to_float(alert.get("price")),
        liquidity_usd=_to_float(alert.get("liquidity_usd")),
        volume_5m=_to_float(alert.get("volume_5m")),
        volume_1h=_to_float(alert.get("volume_1h")),
        raw={},
    )


def _reasons(alert: dict[str, Any]) -> list[str]:
    try:
        parsed = json.loads(alert.get("reasons") or "[]")
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
