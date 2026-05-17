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
