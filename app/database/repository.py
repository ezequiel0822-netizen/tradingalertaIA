import json
from pathlib import Path
from typing import Any

from app.database.db import get_connection
from app.database.models import AlertRecord, EstimateResult, SecuritySummary, TokenSnapshot
from app.utils.time_utils import minutes_ago, utc_now_iso


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def get_token(self, chain: str, token_address: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM tokens
                WHERE chain = ? AND token_address = ?
                """,
                (chain, token_address),
            ).fetchone()
        return dict(row) if row else None

    def upsert_token(
        self,
        snapshot: TokenSnapshot,
        score: int,
        risk_level: str,
        estimate: EstimateResult,
    ) -> int:
        now = utc_now_iso()
        existing = self.get_token(snapshot.chain, snapshot.token_address)
        with get_connection(self.db_path) as connection:
            if existing:
                connection.execute(
                    """
                    UPDATE tokens
                    SET category = ?, symbol = ?, name = ?, last_seen_at = ?, source = ?,
                        latest_price = ?, latest_liquidity_usd = ?,
                        latest_volume_5m = ?, latest_volume_1h = ?,
                        latest_volume_24h = ?, latest_score = ?,
                        latest_risk_level = ?, latest_estimated_gain_pct = ?,
                        latest_estimated_loss_pct = ?,
                        latest_estimate_confidence = ?
                    WHERE id = ?
                    """,
                    (
                        snapshot.category,
                        snapshot.symbol,
                        snapshot.name,
                        now,
                        snapshot.source,
                        snapshot.price,
                        snapshot.liquidity_usd,
                        snapshot.volume_5m,
                        snapshot.volume_1h,
                        snapshot.volume_24h,
                        score,
                        risk_level,
                        estimate.estimated_gain_pct,
                        estimate.estimated_loss_pct,
                        estimate.confidence,
                        existing["id"],
                    ),
                )
                return int(existing["id"])

            cursor = connection.execute(
                """
                INSERT INTO tokens (
                    chain, token_address, category, symbol, name, first_seen_at,
                    last_seen_at, source, latest_price, latest_liquidity_usd,
                    latest_volume_5m, latest_volume_1h, latest_volume_24h,
                    latest_score, latest_risk_level, latest_estimated_gain_pct,
                    latest_estimated_loss_pct, latest_estimate_confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.chain,
                    snapshot.token_address,
                    snapshot.category,
                    snapshot.symbol,
                    snapshot.name,
                    now,
                    now,
                    snapshot.source,
                    snapshot.price,
                    snapshot.liquidity_usd,
                    snapshot.volume_5m,
                    snapshot.volume_1h,
                    snapshot.volume_24h,
                    score,
                    risk_level,
                    estimate.estimated_gain_pct,
                    estimate.estimated_loss_pct,
                    estimate.confidence,
                ),
            )
            return int(cursor.lastrowid)

    def save_security_check(
        self, chain: str, token_address: str, security: SecuritySummary
    ) -> None:
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO security_checks (
                    chain, token_address, honeypot_status, buy_tax, sell_tax,
                    owner_status, mint_risk, blacklist_risk, raw_summary,
                    checked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chain,
                    token_address,
                    security.honeypot_status,
                    security.buy_tax,
                    security.sell_tax,
                    security.owner_status,
                    security.mint_risk,
                    security.blacklist_risk,
                    security.raw_summary,
                    utc_now_iso(),
                ),
            )

    def insert_alert(self, record: AlertRecord) -> int:
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO alerts (
                    token_id, alert_type, category, chain, token_address, symbol, name,
                    score, risk_level, reasons, security_summary, price,
                    liquidity_usd, volume_5m, volume_1h, source,
                    estimated_gain_pct, estimated_loss_pct, estimate_confidence,
                    estimate_summary, app_version, created_at, sent_to_telegram
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.token_id,
                    record.alert_type,
                    record.category,
                    record.snapshot.chain,
                    record.snapshot.token_address,
                    record.snapshot.symbol,
                    record.snapshot.name,
                    record.score,
                    record.risk_level,
                    json.dumps(record.reasons, ensure_ascii=False),
                    record.security.raw_summary,
                    record.snapshot.price,
                    record.snapshot.liquidity_usd,
                    record.snapshot.volume_5m,
                    record.snapshot.volume_1h,
                    record.snapshot.source,
                    record.estimate.estimated_gain_pct,
                    record.estimate.estimated_loss_pct,
                    record.estimate.confidence,
                    json.dumps(record.estimate.reasons, ensure_ascii=False),
                    record.app_version,
                    utc_now_iso(),
                    1 if record.sent_to_telegram else 0,
                ),
            )
            return int(cursor.lastrowid)

    def latest_sent_alert(
        self,
        chain: str,
        token_address: str,
        alert_type: str,
        window_minutes: int,
    ) -> dict[str, Any] | None:
        since = minutes_ago(window_minutes)
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM alerts
                WHERE chain = ?
                  AND token_address = ?
                  AND alert_type = ?
                  AND sent_to_telegram = 1
                  AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (chain, token_address, alert_type, since),
            ).fetchone()
        return dict(row) if row else None

    def sent_alert_count(self, category: str, window_hours: int) -> int:
        since = minutes_ago(window_hours * 60)
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM alerts
                WHERE category = ?
                  AND sent_to_telegram = 1
                  AND created_at >= ?
                """,
                (category, since),
            ).fetchone()
        return int(row["count"] if row else 0)

    def get_state(self, key: str, default: str | None = None) -> str | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT value FROM bot_state WHERE key = ?",
                (key,),
            ).fetchone()
        return str(row["value"]) if row else default

    def set_state(self, key: str, value: str) -> None:
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO bot_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, utc_now_iso()),
            )

    def alerts_paused(self) -> bool:
        return self.get_state("alerts_paused", "false") == "true"

    def top_tokens(self, category: str, limit: int = 5) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM tokens
                WHERE category = ?
                ORDER BY
                    COALESCE(latest_estimated_gain_pct, 0) DESC,
                    COALESCE(latest_score, 0) DESC,
                    last_seen_at DESC
                LIMIT ?
                """,
                (category, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_alerts_by_category(
        self,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            if category:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM alerts
                    WHERE category = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (category, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM alerts
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def recent_unsent_alerts(
        self,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            if category:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM alerts
                    WHERE category = ?
                      AND sent_to_telegram = 0
                    ORDER BY
                        COALESCE(estimated_gain_pct, 0) DESC,
                        COALESCE(score, 0) DESC,
                        created_at DESC
                    LIMIT ?
                    """,
                    (category, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM alerts
                    WHERE sent_to_telegram = 0
                    ORDER BY
                        COALESCE(estimated_gain_pct, 0) DESC,
                        COALESCE(score, 0) DESC,
                        created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def find_token(self, query: str) -> dict[str, Any] | None:
        normalized = query.strip()
        if not normalized:
            return None
        like = f"%{normalized}%"
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM tokens
                WHERE token_address = ?
                   OR UPPER(symbol) = UPPER(?)
                   OR UPPER(name) LIKE UPPER(?)
                   OR UPPER(token_address) LIKE UPPER(?)
                ORDER BY last_seen_at DESC
                LIMIT 1
                """,
                (normalized, normalized, like, like),
            ).fetchone()
        return dict(row) if row else None

    def fetch_recent_alerts(self, limit: int = 200) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM alerts
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_tokens(self, limit: int = 500) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM tokens
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_alerts_for_learning(
        self,
        min_age_minutes: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        since_cutoff = minutes_ago(min_age_minutes)
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    alerts.*,
                    tokens.latest_price AS token_latest_price,
                    tokens.latest_score AS token_latest_score,
                    tokens.latest_estimate_confidence AS token_latest_confidence
                FROM alerts
                JOIN tokens ON tokens.id = alerts.token_id
                WHERE alerts.price IS NOT NULL
                  AND tokens.latest_price IS NOT NULL
                  AND alerts.created_at <= ?
                ORDER BY alerts.created_at DESC
                LIMIT ?
                """,
                (since_cutoff, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_signal_outcome(self, outcome: dict[str, Any]) -> bool:
        with get_connection(self.db_path) as connection:
            existing = connection.execute(
                "SELECT id FROM signal_outcomes WHERE alert_id = ?",
                (outcome["alert_id"],),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO signal_outcomes (
                    alert_id, token_id, category, chain, token_address, symbol,
                    entry_price, latest_price, observed_return_pct, score,
                    confidence, outcome_label, age_minutes, features, evaluated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    latest_price = excluded.latest_price,
                    observed_return_pct = excluded.observed_return_pct,
                    outcome_label = excluded.outcome_label,
                    age_minutes = excluded.age_minutes,
                    features = excluded.features,
                    evaluated_at = excluded.evaluated_at
                """,
                (
                    outcome["alert_id"],
                    outcome["token_id"],
                    outcome["category"],
                    outcome["chain"],
                    outcome["token_address"],
                    outcome["symbol"],
                    outcome["entry_price"],
                    outcome["latest_price"],
                    outcome["observed_return_pct"],
                    outcome["score"],
                    outcome["confidence"],
                    outcome["outcome_label"],
                    outcome["age_minutes"],
                    outcome["features"],
                    outcome["evaluated_at"],
                ),
            )
        return existing is None

    def fetch_signal_outcomes(self, limit: int = 1000) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM signal_outcomes
                ORDER BY evaluated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_strategy_lesson(self, lesson: dict[str, Any]) -> None:
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO strategy_lessons (
                    feature, category, sample_count, win_rate, avg_return_pct,
                    avg_score, confidence, lesson, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feature, category) DO UPDATE SET
                    sample_count = excluded.sample_count,
                    win_rate = excluded.win_rate,
                    avg_return_pct = excluded.avg_return_pct,
                    avg_score = excluded.avg_score,
                    confidence = excluded.confidence,
                    lesson = excluded.lesson,
                    updated_at = excluded.updated_at
                """,
                (
                    lesson["feature"],
                    lesson["category"],
                    lesson["sample_count"],
                    lesson["win_rate"],
                    lesson["avg_return_pct"],
                    lesson["avg_score"],
                    lesson["confidence"],
                    lesson["lesson"],
                    lesson["updated_at"],
                ),
            )

    def fetch_strategy_lessons(
        self,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            if category:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM strategy_lessons
                    WHERE category = ?
                    ORDER BY confidence DESC, win_rate DESC, sample_count DESC
                    LIMIT ?
                    """,
                    (category, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM strategy_lessons
                    ORDER BY confidence DESC, win_rate DESC, sample_count DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def count_active_paper_trades(self) -> int:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM paper_trades WHERE status = 'open'"
            ).fetchone()
        return int(row["count"] if row else 0)

    def create_paper_trade(self, trade: dict[str, Any]) -> bool:
        with get_connection(self.db_path) as connection:
            existing = connection.execute(
                "SELECT id FROM paper_trades WHERE alert_id = ?",
                (trade["alert_id"],),
            ).fetchone()
            if existing:
                return False
            connection.execute(
                """
                INSERT INTO paper_trades (
                    alert_id, token_id, category, chain, token_address, symbol,
                    thesis, readiness_grade, entry_price, latest_price, stop_loss,
                    take_profit_1, take_profit_2, invalidation, status,
                    unrealized_return_pct, opened_at, updated_at, closed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade["alert_id"],
                    trade["token_id"],
                    trade["category"],
                    trade["chain"],
                    trade["token_address"],
                    trade["symbol"],
                    trade["thesis"],
                    trade["readiness_grade"],
                    trade["entry_price"],
                    trade["latest_price"],
                    trade["stop_loss"],
                    trade["take_profit_1"],
                    trade["take_profit_2"],
                    trade["invalidation"],
                    trade["status"],
                    trade["unrealized_return_pct"],
                    trade["opened_at"],
                    trade["updated_at"],
                    trade.get("closed_at"),
                ),
            )
        return True

    def fetch_paper_trades(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            if status:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM paper_trades
                    WHERE status = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM paper_trades
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def update_paper_trade(self, trade_id: int, updates: dict[str, Any]) -> None:
        allowed = {
            "latest_price",
            "status",
            "unrealized_return_pct",
            "updated_at",
            "closed_at",
        }
        fields = [key for key in updates if key in allowed]
        if not fields:
            return
        assignments = ", ".join(f"{field} = ?" for field in fields)
        values = [updates[field] for field in fields]
        values.append(trade_id)
        with get_connection(self.db_path) as connection:
            connection.execute(
                f"UPDATE paper_trades SET {assignments} WHERE id = ?",
                values,
            )

    def insert_training_run(self, run: dict[str, Any]) -> None:
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO training_runs (
                    app_version, alerts_evaluated, outcomes_created,
                    lessons_updated, paper_trades_created, summary, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["app_version"],
                    run["alerts_evaluated"],
                    run["outcomes_created"],
                    run["lessons_updated"],
                    run["paper_trades_created"],
                    run["summary"],
                    run["created_at"],
                ),
            )

    def latest_training_runs(self, limit: int = 5) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM training_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
