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
                    estimate_summary, app_version, created_at, sent_to_telegram,
                    strategy_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    getattr(record, "strategy_name", None),
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
        """v2.6.0: ahora persiste is_scalping flag (default 0 para outcomes pre-existentes)."""
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
                    confidence, outcome_label, age_minutes, features, evaluated_at,
                    is_scalping
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    latest_price = excluded.latest_price,
                    observed_return_pct = excluded.observed_return_pct,
                    outcome_label = excluded.outcome_label,
                    age_minutes = excluded.age_minutes,
                    features = excluded.features,
                    evaluated_at = excluded.evaluated_at,
                    is_scalping = excluded.is_scalping
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
                    int(outcome.get("is_scalping") or 0),
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
                    unrealized_return_pct, opened_at, updated_at, closed_at,
                    mfe_pct, mae_pct, original_stop_loss, trailing_active,
                    strategy_name, direction, time_horizon_hours,
                    size_notional, size_units, risk_pct, partial_closed,
                    account_balance_at_open, is_scalping
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    trade.get("mfe_pct", 0),
                    trade.get("mae_pct", 0),
                    trade.get("original_stop_loss", trade["stop_loss"]),
                    trade.get("trailing_active", 0),
                    trade.get("strategy_name"),
                    trade.get("direction", "long"),
                    trade.get("time_horizon_hours"),
                    trade.get("size_notional"),
                    trade.get("size_units"),
                    trade.get("risk_pct"),
                    trade.get("partial_closed", 0),
                    trade.get("account_balance_at_open"),
                    int(trade.get("is_scalping") or 0),  # v2.6.0 Phase 5.5 Bloque B
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

    def fetch_paper_trade(self, trade_id: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM paper_trades WHERE id = ?",
                (trade_id,),
            ).fetchone()
        return dict(row) if row else None

    def fetch_paper_trade_by_alert_id(self, alert_id: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM paper_trades WHERE alert_id = ?",
                (alert_id,),
            ).fetchone()
        return dict(row) if row else None

    def create_demo_trade_request(self, request: dict[str, Any]) -> int:
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO demo_trade_requests (
                    paper_trade_id, symbol, direction, volume, entry_price,
                    stop_loss, take_profit, risk_pct, strategy_name, status,
                    reason, request_summary, created_at, expires_at,
                    confirmed_at, sent_at, result_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request["paper_trade_id"],
                    request["symbol"],
                    request["direction"],
                    request["volume"],
                    request["entry_price"],
                    request["stop_loss"],
                    request["take_profit"],
                    request.get("risk_pct"),
                    request.get("strategy_name"),
                    request.get("status", "pending"),
                    request.get("reason"),
                    request.get("request_summary"),
                    request["created_at"],
                    request["expires_at"],
                    request.get("confirmed_at"),
                    request.get("sent_at"),
                    request.get("result_message"),
                ),
            )
        return int(cursor.lastrowid)

    def fetch_demo_trade_request(self, request_id: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM demo_trade_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
        return dict(row) if row else None

    def fetch_demo_trade_requests(
        self,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            if status:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM demo_trade_requests
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM demo_trade_requests
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def update_demo_trade_request(
        self, request_id: int, updates: dict[str, Any]
    ) -> None:
        allowed = {
            "status",
            "reason",
            "request_summary",
            "confirmed_at",
            "sent_at",
            "result_message",
        }
        fields = [key for key in updates if key in allowed]
        if not fields:
            return
        assignments = ", ".join(f"{field} = ?" for field in fields)
        values = [updates[field] for field in fields]
        values.append(request_id)
        with get_connection(self.db_path) as connection:
            connection.execute(
                f"UPDATE demo_trade_requests SET {assignments} WHERE id = ?",
                values,
            )

    def create_demo_order(self, order: dict[str, Any]) -> int:
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO demo_orders (
                    demo_request_id, paper_trade_id, symbol, direction,
                    volume, price, stop_loss, take_profit, retcode,
                    order_ticket, deal_ticket, status, strategy_name,
                    result_summary, sent_at, is_scalping
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order["demo_request_id"],
                    order["paper_trade_id"],
                    order["symbol"],
                    order["direction"],
                    order["volume"],
                    order.get("price"),
                    order["stop_loss"],
                    order["take_profit"],
                    order.get("retcode"),
                    order.get("order_ticket"),
                    order.get("deal_ticket"),
                    order.get("status", "sent"),
                    order.get("strategy_name"),
                    order.get("result_summary"),
                    order["sent_at"],
                    int(order.get("is_scalping") or 0),  # v2.6.0 Phase 5.5 Bloque B
                ),
            )
        return int(cursor.lastrowid)

    def fetch_demo_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM demo_orders
                ORDER BY sent_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_latest_demo_order_for_paper_trade(
        self, paper_trade_id: int
    ) -> dict[str, Any] | None:
        """v2.6.7: Devuelve el demo_order más reciente vinculado a un paper_trade.

        Usado por MT5Reconciler para resolver paper_trade_id -> order_ticket
        cuando matcheamos posiciones MT5 con paper_trades.
        """
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM demo_orders
                WHERE paper_trade_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(paper_trade_id),),
            ).fetchone()
        return dict(row) if row else None

    def fetch_paper_trade_by_id(self, trade_id: int) -> dict[str, Any] | None:
        """v2.6.7: lookup directo de paper_trade por id (reconciler-friendly)."""
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM paper_trades WHERE id = ?",
                (int(trade_id),),
            ).fetchone()
        return dict(row) if row else None

    def has_recent_paper_trade_for_symbol(
        self, symbol: str, after_iso: str
    ) -> bool:
        """v2.6.9: Devuelve True si hay algún paper_trade del símbolo con
        opened_at >= after_iso. Usado por risk_manager para implementar
        per-symbol cooldown anti-feedback-loop.

        Match case-sensitive sobre `symbol`. Caller debe normalizar a UPPER
        si quiere case-insensitive (mayoría de signals son uppercase).
        """
        if not symbol:
            return False
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT 1 FROM paper_trades
                WHERE symbol = ? AND opened_at >= ?
                LIMIT 1
                """,
                (symbol, after_iso),
            ).fetchone()
        return row is not None

    def fetch_demo_orders_by_tickets(
        self, tickets: list[int]
    ) -> dict[int, dict[str, Any]]:
        """v2.6.7: Bulk lookup. Para cada order_ticket en la lista, devuelve el
        demo_order más reciente. Resultado: dict[ticket -> demo_order_row].

        Usado por reconciler para resolver todas las posiciones MT5 en una sola query.
        """
        if not tickets:
            return {}
        # Tomamos el demo_order más reciente para cada ticket.
        placeholders = ",".join("?" for _ in tickets)
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM demo_orders
                WHERE order_ticket IN ({placeholders})
                ORDER BY id DESC
                """,
                tickets,
            ).fetchall()
        result: dict[int, dict[str, Any]] = {}
        for row in rows:
            ticket = row["order_ticket"]
            if ticket is None:
                continue
            ticket_int = int(ticket)
            # Como ORDER BY id DESC, el primer hit es el más reciente
            if ticket_int not in result:
                result[ticket_int] = dict(row)
        return result

    def update_paper_trade(self, trade_id: int, updates: dict[str, Any]) -> None:
        allowed = {
            "latest_price",
            "status",
            "unrealized_return_pct",
            "updated_at",
            "closed_at",
            "mfe_pct",
            "mae_pct",
            "stop_loss",
            "trailing_active",
            "partial_closed",
            "size_notional",
            "size_units",
            "strategy_name",
            "direction",
            "time_horizon_hours",
            "risk_pct",
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

    def count_open_trades_by_category(self) -> dict[str, int]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT category, COUNT(*) AS count
                FROM paper_trades
                WHERE status = 'open'
                GROUP BY category
                """
            ).fetchall()
        return {str(row["category"] or "unknown"): int(row["count"]) for row in rows}

    def fetch_open_positions_full(self) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM paper_trades
                WHERE status = 'open'
                ORDER BY opened_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_closed_trades_since(self, since_iso: str) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM paper_trades
                WHERE status != 'open' AND closed_at >= ?
                ORDER BY closed_at DESC
                """,
                (since_iso,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_closed_paper_trades(self, limit: int = 5000) -> list[dict[str, Any]]:
        """v2.7.0: todos los paper_trades cerrados (cualquier status != 'open'),
        para computar expectancy realizada por estrategia."""
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM paper_trades
                WHERE status != 'open' AND closed_at IS NOT NULL
                ORDER BY closed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_strategy_performance(self, perf: dict[str, Any]) -> None:
        """v2.7.0: persiste expectancy realizada en R por (strategy_name, category)."""
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO strategy_performance (
                    strategy_name, category, trades, wins, losses, scratches,
                    win_rate, avg_r, avg_return_pct, sum_return_pct,
                    artifacts_excluded, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_name, category) DO UPDATE SET
                    trades = excluded.trades,
                    wins = excluded.wins,
                    losses = excluded.losses,
                    scratches = excluded.scratches,
                    win_rate = excluded.win_rate,
                    avg_r = excluded.avg_r,
                    avg_return_pct = excluded.avg_return_pct,
                    sum_return_pct = excluded.sum_return_pct,
                    artifacts_excluded = excluded.artifacts_excluded,
                    updated_at = excluded.updated_at
                """,
                (
                    perf["strategy_name"],
                    perf["category"],
                    perf["trades"],
                    perf["wins"],
                    perf["losses"],
                    perf["scratches"],
                    perf["win_rate"],
                    perf["avg_r"],
                    perf["avg_return_pct"],
                    perf["sum_return_pct"],
                    perf["artifacts_excluded"],
                    perf["updated_at"],
                ),
            )

    def fetch_strategy_performance_for(
        self, strategy_name: str, category: str
    ) -> dict[str, Any] | None:
        """v2.7.0: fila de expectancy de UNA estrategia, para el promotion gate."""
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM strategy_performance WHERE strategy_name = ? AND category = ?",
                (strategy_name, category),
            ).fetchone()
        return dict(row) if row else None

    def fetch_strategy_performance(self, limit: int = 100) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM strategy_performance
                ORDER BY trades DESC, avg_r DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_daily_pnl_row(self, row: dict[str, Any]) -> None:
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO daily_pnl_log (
                    date, realized_pnl_pct, realized_pnl_usd, trades_closed,
                    trades_opened, kill_switch_triggered, kill_switch_reason,
                    starting_equity, ending_equity, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    realized_pnl_pct = excluded.realized_pnl_pct,
                    realized_pnl_usd = excluded.realized_pnl_usd,
                    trades_closed = excluded.trades_closed,
                    trades_opened = excluded.trades_opened,
                    kill_switch_triggered = excluded.kill_switch_triggered,
                    kill_switch_reason = excluded.kill_switch_reason,
                    starting_equity = excluded.starting_equity,
                    ending_equity = excluded.ending_equity,
                    updated_at = excluded.updated_at
                """,
                (
                    row["date"],
                    row.get("realized_pnl_pct", 0),
                    row.get("realized_pnl_usd", 0),
                    row.get("trades_closed", 0),
                    row.get("trades_opened", 0),
                    row.get("kill_switch_triggered", 0),
                    row.get("kill_switch_reason"),
                    row.get("starting_equity"),
                    row.get("ending_equity"),
                    row.get("updated_at", utc_now_iso()),
                ),
            )

    def get_daily_pnl_row(self, date_str: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM daily_pnl_log WHERE date = ?",
                (date_str,),
            ).fetchone()
        return dict(row) if row else None

    def fetch_daily_pnl_log(self, days: int = 14) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM daily_pnl_log
                ORDER BY date DESC
                LIMIT ?
                """,
                (days,),
            ).fetchall()
        return [dict(row) for row in rows]

    # Phase 4 v2.3.0 - MT5 historical cache
    def upsert_mt5_cache_candle(
        self, symbol: str, timeframe: int, candle: dict[str, Any]
    ) -> bool:
        with get_connection(self.db_path) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO mt5_historical_cache (
                        symbol, timeframe, time, open, high, low, close, volume
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, timeframe, time) DO UPDATE SET
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        volume = excluded.volume
                    """,
                    (
                        symbol,
                        timeframe,
                        int(candle.get("time") or 0),
                        candle.get("open"),
                        candle.get("high"),
                        candle.get("low"),
                        candle.get("close"),
                        candle.get("volume"),
                    ),
                )
                return True
            except Exception:
                return False

    def fetch_mt5_cache_window(
        self, symbol: str, timeframe: int, start_epoch: int, end_epoch: int
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT symbol, timeframe, time, open, high, low, close, volume
                FROM mt5_historical_cache
                WHERE symbol = ? AND timeframe = ?
                  AND time BETWEEN ? AND ?
                ORDER BY time ASC
                """,
                (symbol, timeframe, start_epoch, end_epoch),
            ).fetchall()
        return [dict(row) for row in rows]

    # Phase 4 v2.3.0 - walk-forward results
    def insert_walk_forward_result(self, row: dict[str, Any]) -> int:
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO walk_forward_results (
                    strategy_name, symbol, category,
                    train_start, train_end, test_start, test_end,
                    train_sharpe, train_win_rate, train_avg_return,
                    test_sharpe, test_win_rate, test_avg_return,
                    degradation_pct, train_samples, test_samples, computed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["strategy_name"],
                    row.get("symbol"),
                    row.get("category"),
                    row["train_start"],
                    row["train_end"],
                    row["test_start"],
                    row["test_end"],
                    row.get("train_sharpe"),
                    row.get("train_win_rate"),
                    row.get("train_avg_return"),
                    row.get("test_sharpe"),
                    row.get("test_win_rate"),
                    row.get("test_avg_return"),
                    row.get("degradation_pct"),
                    row.get("train_samples"),
                    row.get("test_samples"),
                    row.get("computed_at", utc_now_iso()),
                ),
            )
            return int(cursor.lastrowid)

    def fetch_walk_forward_results(
        self,
        strategy_name: str | None = None,
        since_iso: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            sql = "SELECT * FROM walk_forward_results WHERE 1=1"
            params: list[Any] = []
            if strategy_name:
                sql += " AND strategy_name = ?"
                params.append(strategy_name)
            if since_iso:
                sql += " AND computed_at >= ?"
                params.append(since_iso)
            sql += " ORDER BY computed_at DESC LIMIT ?"
            params.append(limit)
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # Phase 4 v2.3.0 - data quality log
    def insert_data_quality_log(self, row: dict[str, Any]) -> int:
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO data_quality_log (
                    check_at, gaps_detected, stale_symbols,
                    collector_failures, summary
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row.get("check_at", utc_now_iso()),
                    row.get("gaps_detected", 0),
                    row.get("stale_symbols", 0),
                    row.get("collector_failures", 0),
                    row.get("summary"),
                ),
            )
            return int(cursor.lastrowid)

    def fetch_data_quality_log(self, limit: int = 20) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM data_quality_log
                ORDER BY check_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # Phase 3 v2.2.0 - macro snapshots
    def insert_macro_snapshot(self, snapshot: dict[str, Any]) -> bool:
        with get_connection(self.db_path) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO macro_snapshots (
                        captured_at, vix_value, dxy_value, spy_value, regime
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot["captured_at"],
                        snapshot.get("vix_value"),
                        snapshot.get("dxy_value"),
                        snapshot.get("spy_value"),
                        snapshot.get("regime"),
                    ),
                )
                return True
            except Exception:
                return False

    def fetch_latest_macro_snapshot(self) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM macro_snapshots
                ORDER BY captured_at DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    # Phase 3 v2.2.0 - economic events
    def upsert_economic_event(self, event: dict[str, Any]) -> bool:
        with get_connection(self.db_path) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO economic_events (
                        event_time, country, impact, title, captured_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(event_time, country, title) DO UPDATE SET
                        impact = excluded.impact,
                        captured_at = excluded.captured_at
                    """,
                    (
                        event["event_time"],
                        event["country"],
                        event.get("impact"),
                        event.get("title"),
                        event.get("captured_at", utc_now_iso()),
                    ),
                )
                return True
            except Exception:
                return False

    def fetch_economic_events_window(
        self, start_iso: str, end_iso: str, countries: list[str] | None = None,
        impact: str | None = None,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            sql = "SELECT * FROM economic_events WHERE event_time BETWEEN ? AND ?"
            params: list[Any] = [start_iso, end_iso]
            if impact:
                sql += " AND impact = ?"
                params.append(impact)
            if countries:
                placeholders = ",".join(["?"] * len(countries))
                sql += f" AND country IN ({placeholders})"
                params.extend(countries)
            sql += " ORDER BY event_time ASC"
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # Phase 3 v2.2.0 - dashboard heatmap queries
    def fetch_heatmap_horizon_hour(
        self, category: str | None = None
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            sql = """
                SELECT
                    aoh.horizon_hours AS horizon_hours,
                    strftime('%H', a.created_at) AS hour_of_day,
                    AVG(aoh.return_pct) AS avg_return,
                    COUNT(*) AS n
                FROM alert_outcome_horizons aoh
                JOIN alerts a ON a.id = aoh.alert_id
                WHERE aoh.status = 'final'
            """
            params: list[Any] = []
            if category:
                sql += " AND a.category = ?"
                params.append(category)
            sql += " GROUP BY aoh.horizon_hours, hour_of_day"
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def fetch_alert_full_detail(self, alert_id: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            alert_row = connection.execute(
                "SELECT * FROM alerts WHERE id = ?", (alert_id,)
            ).fetchone()
            if not alert_row:
                return None
            paper_row = connection.execute(
                "SELECT * FROM paper_trades WHERE alert_id = ?", (alert_id,)
            ).fetchone()
            horizon_rows = connection.execute(
                "SELECT * FROM alert_outcome_horizons WHERE alert_id = ?",
                (alert_id,),
            ).fetchall()
        return {
            "alert": dict(alert_row),
            "paper_trade": dict(paper_row) if paper_row else None,
            "horizons": [dict(r) for r in horizon_rows],
        }

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

    def latest_alert_for_token(
        self,
        chain: str,
        token_address: str,
    ) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM alerts
                WHERE chain = ? AND token_address = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (chain, token_address),
            ).fetchone()
        return dict(row) if row else None

    def insert_price_snapshot(self, snapshot: TokenSnapshot, token_id: int) -> int:
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO price_snapshots (
                    token_id, chain, token_address, category, price,
                    liquidity_usd, volume_5m, volume_1h, volume_24h,
                    captured_at, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    snapshot.chain,
                    snapshot.token_address,
                    snapshot.category,
                    snapshot.price,
                    snapshot.liquidity_usd,
                    snapshot.volume_5m,
                    snapshot.volume_1h,
                    snapshot.volume_24h,
                    utc_now_iso(),
                    snapshot.source,
                ),
            )
            return int(cursor.lastrowid)

    def fetch_snapshots_in_window(
        self,
        chain: str,
        token_address: str,
        start_iso: str,
        end_iso: str,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM price_snapshots
                WHERE chain = ?
                  AND token_address = ?
                  AND captured_at >= ?
                  AND captured_at <= ?
                ORDER BY captured_at ASC
                """,
                (chain, token_address, start_iso, end_iso),
            ).fetchall()
        return [dict(row) for row in rows]

    def purge_old_snapshots(self, retention_days: int) -> int:
        cutoff = minutes_ago(retention_days * 24 * 60)
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                "DELETE FROM price_snapshots WHERE captured_at < ?",
                (cutoff,),
            )
            return int(cursor.rowcount or 0)

    def upsert_alert_outcome_horizon(self, row: dict[str, Any]) -> bool:
        with get_connection(self.db_path) as connection:
            existing = connection.execute(
                """
                SELECT id FROM alert_outcome_horizons
                WHERE alert_id = ? AND horizon_hours = ?
                """,
                (row["alert_id"], row["horizon_hours"]),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO alert_outcome_horizons (
                    alert_id, horizon_hours, entry_price, exit_price,
                    return_pct, mfe_pct, mae_pct, snapshots_used,
                    outcome_label, status, evaluated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id, horizon_hours) DO UPDATE SET
                    exit_price = excluded.exit_price,
                    return_pct = excluded.return_pct,
                    mfe_pct = excluded.mfe_pct,
                    mae_pct = excluded.mae_pct,
                    snapshots_used = excluded.snapshots_used,
                    outcome_label = excluded.outcome_label,
                    status = excluded.status,
                    evaluated_at = excluded.evaluated_at
                """,
                (
                    row["alert_id"],
                    row["horizon_hours"],
                    row["entry_price"],
                    row.get("exit_price"),
                    row.get("return_pct"),
                    row.get("mfe_pct"),
                    row.get("mae_pct"),
                    row.get("snapshots_used", 0),
                    row.get("outcome_label"),
                    row.get("status"),
                    row.get("evaluated_at") or utc_now_iso(),
                ),
            )
        return existing is None

    def fetch_alert_outcome_horizons(
        self,
        alert_id: int | None = None,
        horizon_hours: int | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if alert_id is not None:
            clauses.append("alert_id = ?")
            params.append(alert_id)
        if horizon_hours is not None:
            clauses.append("horizon_hours = ?")
            params.append(horizon_hours)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM alert_outcome_horizons
                {where}
                ORDER BY evaluated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_horizons_by_features(
        self,
        horizon_hours: int,
        since_iso: str,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    h.id AS horizon_id,
                    h.alert_id,
                    h.horizon_hours,
                    h.entry_price,
                    h.exit_price,
                    h.return_pct,
                    h.mfe_pct,
                    h.mae_pct,
                    h.outcome_label,
                    h.status,
                    h.evaluated_at,
                    alerts.id AS alert_real_id,
                    alerts.alert_type,
                    alerts.category,
                    alerts.chain,
                    alerts.token_address,
                    alerts.symbol,
                    alerts.score,
                    alerts.risk_level,
                    alerts.reasons,
                    alerts.security_summary,
                    alerts.estimated_gain_pct,
                    alerts.estimate_confidence,
                    alerts.estimate_summary,
                    alerts.created_at
                FROM alert_outcome_horizons AS h
                JOIN alerts ON alerts.id = h.alert_id
                WHERE h.horizon_hours = ?
                  AND h.status = 'final'
                  AND alerts.created_at >= ?
                ORDER BY alerts.created_at DESC
                LIMIT ?
                """,
                (horizon_hours, since_iso, limit),
            ).fetchall()
        return [dict(row) for row in rows]
