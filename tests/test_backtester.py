import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from app.database.db import init_db
from app.database.models import (
    AlertRecord,
    EstimateResult,
    SecuritySummary,
    TokenSnapshot,
)
from app.database.repository import Repository
from app.learning.backtester import (
    backtest_strategy,
    rank_top_strategies,
)
from app.utils.time_utils import utc_now


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"backtester_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _make_alert(
    repo: Repository,
    chain: str,
    token_address: str,
    symbol: str,
    score: int,
    reasons: list[str],
    category: str = "stock",
) -> int:
    snapshot = TokenSnapshot(
        chain=chain,
        token_address=token_address,
        category=category,
        symbol=symbol,
        name=symbol,
        source="test",
        price=100.0,
        liquidity_usd=1_000_000,
        volume_1h=200_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=10,
        estimated_loss_pct=3,
        confidence=80,
        label="high",
        reasons=[],
        eligible_for_gain_alert=True,
    )
    token_id = repo.upsert_token(snapshot, score, "orange", estimate)
    alert_id = repo.insert_alert(
        AlertRecord(
            token_id=token_id,
            alert_type="STOCK_BREAKOUT",
            snapshot=snapshot,
            app_version="test",
            category=category,
            score=score,
            risk_level="orange",
            reasons=reasons,
            security=SecuritySummary(raw_summary="unknown"),
            estimate=estimate,
            sent_to_telegram=True,
        )
    )
    return int(alert_id)


def _insert_horizon(
    repo: Repository,
    alert_id: int,
    horizon: int,
    return_pct: float,
    mfe_pct: float | None = None,
    mae_pct: float | None = None,
    label: str = "win",
) -> None:
    mfe = mfe_pct if mfe_pct is not None else max(return_pct, 0.0) + 1.0
    mae = mae_pct if mae_pct is not None else min(return_pct, 0.0) - 1.0
    with sqlite3.connect(repo.db_path) as connection:
        connection.execute(
            """
            INSERT INTO alert_outcome_horizons (
                alert_id, horizon_hours, entry_price, exit_price,
                return_pct, mfe_pct, mae_pct, snapshots_used,
                outcome_label, status, evaluated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                horizon,
                100.0,
                100.0 * (1 + return_pct / 100),
                return_pct,
                mfe,
                mae,
                3,
                label,
                "final",
                utc_now().isoformat(),
            ),
        )


def _backdate_alert(repo: Repository, alert_id: int, hours_ago: float) -> None:
    iso = (utc_now() - timedelta(hours=hours_ago)).isoformat()
    with sqlite3.connect(repo.db_path) as connection:
        connection.execute(
            "UPDATE alerts SET created_at = ? WHERE id = ?", (iso, alert_id)
        )


def test_backtest_filters_by_features() -> None:
    repo = _repo()
    pro_ids = [
        _make_alert(repo, "stock", f"NVDA{i}", f"NVDA{i}", 85, ["IA Pro: pro_high_conviction"])
        for i in range(3)
    ]
    other_ids = [
        _make_alert(repo, "stock", f"AMD{i}", f"AMD{i}", 70, ["sin tesis"])
        for i in range(2)
    ]
    for alert_id in pro_ids + other_ids:
        _insert_horizon(repo, alert_id, 24, return_pct=5.0)
        _backdate_alert(repo, alert_id, hours_ago=25)

    result = backtest_strategy(
        repo,
        filter_features=["ia_pro"],
        horizon_hours=24,
        since_days=7,
    )
    assert result.sample_count == 3


def test_backtest_metrics_correct() -> None:
    repo = _repo()
    returns = [10.0, -5.0, 8.0, 12.0, -3.0]
    for index, ret in enumerate(returns):
        alert_id = _make_alert(
            repo,
            "stock",
            f"SYM{index}",
            f"SYM{index}",
            80,
            ["IA Pro: pro_high_conviction"],
        )
        _insert_horizon(
            repo,
            alert_id,
            24,
            return_pct=ret,
            mfe_pct=ret + 2,
            mae_pct=ret - 4,
            label="win" if ret >= 5 else ("loss" if ret <= -3 else "neutral"),
        )
        _backdate_alert(repo, alert_id, hours_ago=25)

    result = backtest_strategy(
        repo,
        filter_features=["ia_pro"],
        horizon_hours=24,
        since_days=7,
    )

    assert result.sample_count == 5
    expected_avg = sum(returns) / len(returns)
    assert abs(result.avg_return_pct - round(expected_avg, 4)) < 0.01
    # 3 retornos >=5 -> wins (10, 8, 12)
    assert abs(result.win_rate - 0.6) < 0.01
    # peor MAE
    assert result.max_drawdown_pct <= -9.0


def test_rank_top_strategies_min_samples() -> None:
    repo = _repo()
    # Solo 2 alertas con ia_pro (menos que min_samples=3)
    for index in range(2):
        alert_id = _make_alert(
            repo,
            "stock",
            f"SOLO{index}",
            f"SOLO{index}",
            80,
            ["IA Pro: pro_high_conviction"],
        )
        _insert_horizon(repo, alert_id, 24, return_pct=10.0)
        _backdate_alert(repo, alert_id, hours_ago=25)

    # 5 alertas con bullish_pattern
    for index in range(5):
        alert_id = _make_alert(
            repo,
            "stock",
            f"BULL{index}",
            f"BULL{index}",
            70,
            ["Patron grafico: bullish_breakout"],
        )
        _insert_horizon(repo, alert_id, 24, return_pct=4.0)
        _backdate_alert(repo, alert_id, hours_ago=25)

    ranking = rank_top_strategies(
        repo,
        horizon_hours=24,
        since_days=7,
        min_samples=3,
        top_n=10,
    )
    labels = [rule.rule_label for rule in ranking]
    # ia_pro tiene solo 2 muestras -> NO debe aparecer como regla aislada
    assert "ia_pro" not in labels
    assert any("bullish_pattern" in label for label in labels)


def test_backtest_equity_curve_compounds() -> None:
    repo = _repo()
    returns = [10.0, -5.0, 20.0]
    for index, ret in enumerate(returns):
        alert_id = _make_alert(
            repo,
            "stock",
            f"COMP{index}",
            f"COMP{index}",
            80,
            ["IA Pro: pro_high_conviction"],
        )
        _insert_horizon(repo, alert_id, 24, return_pct=ret)
        _backdate_alert(repo, alert_id, hours_ago=25)

    result = backtest_strategy(
        repo,
        filter_features=["ia_pro"],
        horizon_hours=24,
        since_days=7,
    )

    assert len(result.equity_curve) == 3
    # Es producto acumulado de (1 + r/100)
    # El orden depende del orden de fetch_horizons_by_features (created_at DESC).
    expected_final = 1.0
    for ret in returns:
        expected_final *= 1 + (ret / 100.0)
    assert abs(result.equity_curve[-1] - round(expected_final, 6)) < 0.01
