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

    def insert_trade_lesson(self, lesson: dict[str, Any]) -> bool:
        """v3.2.0 / Fase C: persiste UNA leccion por paper_trade (UNIQUE
        paper_trade_id). Idempotente: si el trade ya tiene leccion -> no duplica y
        devuelve False. Solo registro; no toca ninguna decision ni orden."""
        with get_connection(self.db_path) as connection:
            existing = connection.execute(
                "SELECT id FROM trade_lessons WHERE paper_trade_id = ?",
                (lesson["paper_trade_id"],),
            ).fetchone()
            if existing:
                return False
            connection.execute(
                """
                INSERT INTO trade_lessons (
                    paper_trade_id, symbol, category, strategy_name, direction,
                    outcome, r_multiple, lesson, lesson_key, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson["paper_trade_id"],
                    lesson.get("symbol"),
                    lesson.get("category"),
                    lesson.get("strategy_name"),
                    lesson.get("direction"),
                    lesson.get("outcome"),
                    lesson.get("r_multiple"),
                    lesson.get("lesson"),
                    lesson.get("lesson_key"),
                    lesson["created_at"],
                ),
            )
        return True

    def fetch_trade_lesson_ids(self) -> set[int]:
        """Set de paper_trade_id que YA tienen leccion (filtro barato de pendientes)."""
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                "SELECT paper_trade_id FROM trade_lessons"
            ).fetchall()
        return {int(row["paper_trade_id"]) for row in rows}

    def count_trade_lessons_by_key(self, lesson_key: str) -> int:
        """Cuantas lecciones comparten la misma clave (strategy|cat|dir|outcome)."""
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM trade_lessons WHERE lesson_key = ?",
                (lesson_key,),
            ).fetchone()
        return int(row["count"] if row else 0)

    def fetch_trade_lessons(
        self, lesson_key: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Lecciones registradas (opcionalmente filtradas por clave), mas recientes
        primero. Para inspeccion / comandos futuros."""
        with get_connection(self.db_path) as connection:
            if lesson_key:
                rows = connection.execute(
                    """
                    SELECT * FROM trade_lessons WHERE lesson_key = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (lesson_key, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM trade_lessons ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def fetch_executed_paper_trade_ids(self) -> set[int]:
        """v3.3.0: set de paper_trade_id con demo_order 'sent' (ejecutados a MT5 demo —
        los que tocaron el balance real). Para la performance desde el baseline limpio."""
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                "SELECT DISTINCT paper_trade_id FROM demo_orders "
                "WHERE status = 'sent' AND paper_trade_id IS NOT NULL"
            ).fetchall()
        return {int(row["paper_trade_id"]) for row in rows}

    def insert_r_sample(self, paper_trade_id: int, unrealized_r: float, at_iso: str) -> None:
        """v3.4.0 / exit shadow: registra el R no-realizado de un trade abierto en este
        ciclo. Construye el camino de R para simular salidas con trailing (read/registro)."""
        with get_connection(self.db_path) as connection:
            connection.execute(
                "INSERT INTO trade_r_samples (paper_trade_id, unrealized_r, recorded_at) "
                "VALUES (?, ?, ?)",
                (int(paper_trade_id), float(unrealized_r), at_iso),
            )

    def fetch_r_path(self, paper_trade_id: int) -> list[float]:
        """Camino cronologico de R no-realizado de un trade (para la simulacion de salida)."""
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                "SELECT unrealized_r FROM trade_r_samples WHERE paper_trade_id = ? "
                "ORDER BY recorded_at ASC, id ASC",
                (int(paper_trade_id),),
            ).fetchall()
        return [float(r["unrealized_r"]) for r in rows]

    def prune_r_samples(self, before_iso: str) -> int:
        """Borra las muestras de trades CERRADOS hace mas de `before_iso` (por closed_at).
        Nunca poda trades abiertos ni recien cerrados: podar por recorded_at decapitaba el
        camino (perdia el pico temprano) de trades longevos — justo lo que el shadow mide.
        Devuelve filas borradas."""
        with get_connection(self.db_path) as connection:
            cur = connection.execute(
                """
                DELETE FROM trade_r_samples WHERE paper_trade_id IN (
                    SELECT id FROM paper_trades
                    WHERE status != 'open' AND closed_at IS NOT NULL AND closed_at < ?
                )
                """,
                (before_iso,),
            )
            return int(cur.rowcount or 0)

    def count_closed_trades_with_features(self) -> int:
        """v3.3.0: cerrados (status != 'open') con rsi_entry persistido = el universo de
        trades con features tecnicos reales (los de v2.11.0), que es el gate de la Fase D
        y un indicador para /readiness."""
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM paper_trades "
                "WHERE status != 'open' AND rsi_entry IS NOT NULL"
            ).fetchone()
        return int(row["count"] if row else 0)

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
                    account_balance_at_open, is_scalping,
                    rsi_entry, atr_value, macd_value, macd_signal_value,
                    vwap_dist_pct, vwap_week_dist_pct,
                    hurst_entry, clv_entry, candle_strength
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    trade.get("rsi_entry"),               # v2.11.0 features tecnicas
                    trade.get("atr_value"),               # al entry (None si no hay)
                    trade.get("macd_value"),
                    trade.get("macd_signal_value"),
                    trade.get("vwap_dist_pct"),           # v3.12.0 VWAP al entry
                    trade.get("vwap_week_dist_pct"),      # (None si sin volumen)
                    trade.get("hurst_entry"),             # v3.12.0 Hurst al entry
                    trade.get("clv_entry"),               # v3.12.0 footprint lite
                    trade.get("candle_strength"),
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

    def has_successful_demo_order(self, paper_trade_id: int) -> bool:
        """v2.7.1: Devuelve True si el paper_trade tuvo al menos UN demo_order
        con status='sent' a MT5 demo.

        Usado por portfolio_manager.realized_pnl_today para EXCLUIR del calculo
        USD-impact los paper_trades que NUNCA llegaron a MT5 (memecoin paper,
        stock paper, o forex/gold paper que fallo en prep o que no matchea el
        DEMO_ALLOWED_SYMBOLS map post-yahoo_to_mt5).

        Tapa el kill switch falso del 2026-06-01: paper_trades de gold con
        symbol=GC=F nunca se ejecutaban a MT5 (allowed list tiene XAUUSD/GOLD,
        no GC=F) pero su size_notional teorico (~$184k) hacia que
        realized_pnl_today reportara -3.20% drawdown cuando el daño real al
        balance MT5 era cero.
        """
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT 1 FROM demo_orders
                WHERE paper_trade_id = ? AND status = 'sent'
                LIMIT 1
                """,
                (int(paper_trade_id),),
            ).fetchone()
        return row is not None

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

    def upsert_sliced_performance(self, perf: dict[str, Any]) -> None:
        """v2.8.0: persiste expectancy realizada en R por
        (strategy_name, category, dimension, bucket) — sesión / dirección."""
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO strategy_performance_sliced (
                    strategy_name, category, dimension, bucket, trades, wins,
                    losses, scratches, win_rate, avg_r, avg_return_pct,
                    sum_return_pct, artifacts_excluded, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_name, category, dimension, bucket) DO UPDATE SET
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
                    perf["dimension"],
                    perf["bucket"],
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

    def fetch_sliced_performance(self, limit: int = 200) -> list[dict[str, Any]]:
        """v2.8.0: todas las filas de expectancy sliceada, para el comando /edge."""
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM strategy_performance_sliced
                ORDER BY dimension, trades DESC, avg_r DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_sliced_performance_for(
        self, strategy_name: str, category: str, buckets: list[str]
    ) -> list[dict[str, Any]]:
        """v2.8.0: filas sliceadas de UNA estrategia cuyo bucket está en `buckets`
        (típicamente la sesión y la dirección del trade en curso), para el
        promotion gate sliceado. Devuelve [] si no hay buckets."""
        clean = [b for b in (buckets or []) if b]
        if not clean:
            return []
        placeholders = ",".join("?" for _ in clean)
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM strategy_performance_sliced "
                f"WHERE strategy_name = ? AND category = ? AND bucket IN ({placeholders})",
                (strategy_name, category, *clean),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_realized_feature_lesson(self, lesson: dict[str, Any]) -> None:
        """v2.7.0 Fase 2b: lesson de realized-R por (feature, category) desde
        paper_trades cerrados. Señal honesta para learned_weights y learning_gate."""
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO realized_feature_lessons (
                    feature, category, sample_count, wins, win_rate, avg_r,
                    avg_return_pct, confidence, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feature, category) DO UPDATE SET
                    sample_count = excluded.sample_count,
                    wins = excluded.wins,
                    win_rate = excluded.win_rate,
                    avg_r = excluded.avg_r,
                    avg_return_pct = excluded.avg_return_pct,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at
                """,
                (
                    lesson["feature"],
                    lesson["category"],
                    lesson["sample_count"],
                    lesson["wins"],
                    lesson["win_rate"],
                    lesson["avg_r"],
                    lesson["avg_return_pct"],
                    lesson["confidence"],
                    lesson["updated_at"],
                ),
            )

    def fetch_realized_feature_lessons(
        self, category: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            if category:
                rows = connection.execute(
                    """
                    SELECT * FROM realized_feature_lessons
                    WHERE category = ?
                    ORDER BY confidence DESC, sample_count DESC
                    LIMIT ?
                    """,
                    (category, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM realized_feature_lessons
                    ORDER BY confidence DESC, sample_count DESC
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

    # v3.9.0 — COT (Commitments of Traders, CFTC semanal). Solo captura para research.
    def insert_cot_snapshot(self, snapshot: dict[str, Any]) -> bool:
        """Idempotente por (report_date, market_code). True si inserto una fila nueva."""
        with get_connection(self.db_path) as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO cot_snapshots (
                        report_date, market_code, market_label,
                        noncomm_long, noncomm_short, comm_long, comm_short,
                        open_interest, net_noncomm, net_comm, captured_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot["report_date"],
                        snapshot["market_code"],
                        snapshot.get("market_label"),
                        snapshot.get("noncomm_long"),
                        snapshot.get("noncomm_short"),
                        snapshot.get("comm_long"),
                        snapshot.get("comm_short"),
                        snapshot.get("open_interest"),
                        snapshot.get("net_noncomm"),
                        snapshot.get("net_comm"),
                        snapshot["captured_at"],
                    ),
                )
                return cursor.rowcount > 0
            except Exception:
                return False

    def fetch_latest_cot_snapshot(self, market_code: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM cot_snapshots
                WHERE market_code = ?
                ORDER BY report_date DESC
                LIMIT 1
                """,
                (market_code,),
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

    def purge_old_learning_data(self, retention_days: int) -> dict[str, int]:
        """v3.9.5: retencion para las tablas calientes que crecian sin limite
        (~65k filas/dia CADA UNA; la DB viva llego a 5.3GB creciendo 130MB/dia).

        Conserva SIEMPRE: alerts enviadas a Telegram y alerts vinculadas a
        paper_trades (el ml_dataset_builder extrae features de esas). Los
        alert_outcome_horizons huerfanos no se tocan (chicos, y se leen via
        el alert -> quedan inertes)."""
        cutoff = minutes_ago(retention_days * 24 * 60)
        out: dict[str, int] = {}
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                DELETE FROM alerts
                WHERE created_at < ? AND sent_to_telegram = 0
                  AND id NOT IN (SELECT alert_id FROM paper_trades)
                """,
                (cutoff,),
            )
            out["alerts"] = int(cursor.rowcount or 0)
            cursor = connection.execute(
                "DELETE FROM signal_outcomes WHERE evaluated_at < ?", (cutoff,)
            )
            out["signal_outcomes"] = int(cursor.rowcount or 0)
            cursor = connection.execute(
                "DELETE FROM security_checks WHERE checked_at < ?", (cutoff,)
            )
            out["security_checks"] = int(cursor.rowcount or 0)
        return out

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

    # v3.6.0 — Backtest Replay Harness (ESPEC_BACKTEST_REPLAY_v1.md §5).
    # CRUD de tablas backtest_* SOLAMENTE: nada de esto toca tablas vivas y
    # nada del ciclo vivo lo llama. Cero contaminacion de la medicion viva.
    def insert_backtest_run(self, run: dict[str, Any]) -> int:
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO backtest_runs (
                    created_at_utc, git_commit, mode, timeframe, symbols,
                    strategies, data_ranges_json, config_json,
                    cost_multiplier, n_configs_tested, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.get("created_at_utc") or utc_now_iso(),
                    run.get("git_commit"),
                    run.get("mode", "A"),
                    run.get("timeframe"),
                    run.get("symbols"),
                    run.get("strategies"),
                    run.get("data_ranges_json"),
                    run.get("config_json"),
                    run.get("cost_multiplier"),
                    run.get("n_configs_tested", 0),
                    run.get("notes"),
                ),
            )
            return int(cursor.lastrowid)

    def fetch_backtest_run(self, run_id: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM backtest_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def fetch_backtest_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM backtest_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_backtest_run_notes(self, run_id: int, notes: str) -> None:
        """Documenta el porque de un re-run (anti data-dredging, ESPEC §10):
        el historial de intentos es parte de la evidencia."""
        with get_connection(self.db_path) as connection:
            connection.execute(
                "UPDATE backtest_runs SET notes = ? WHERE id = ?",
                (notes, run_id),
            )

    def insert_backtest_trades(
        self, run_id: int, trades: list[dict[str, Any]]
    ) -> int:
        """Inserta los trades simulados de un run (bulk). Devuelve cuantos."""
        if not trades:
            return 0
        with get_connection(self.db_path) as connection:
            connection.executemany(
                """
                INSERT INTO backtest_trades (
                    run_id, config_id, strategy, symbol, category, direction,
                    signal_bar_utc, entry_utc, entry_price, sl_initial,
                    tp_initial, exit_utc, exit_price, exit_reason, bars_held,
                    r_gross, cost_r, r_net, mfe_r, mae_r, session,
                    regime_trend, regime_vol, year
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        t.get("config_id"),
                        t["strategy"],
                        t["symbol"],
                        t.get("category"),
                        t["direction"],
                        t.get("signal_bar_utc"),
                        t.get("entry_utc"),
                        t.get("entry_price"),
                        t.get("sl_initial"),
                        t.get("tp_initial"),
                        t.get("exit_utc"),
                        t.get("exit_price"),
                        t.get("exit_reason"),
                        t.get("bars_held"),
                        t.get("r_gross"),
                        t.get("cost_r"),
                        t.get("r_net"),
                        t.get("mfe_r"),
                        t.get("mae_r"),
                        t.get("session"),
                        t.get("regime_trend"),
                        t.get("regime_vol"),
                        t.get("year"),
                    )
                    for t in trades
                ],
            )
        return len(trades)

    def fetch_backtest_trades(
        self,
        run_id: int,
        strategy: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["run_id = ?"]
        params: list[Any] = [run_id]
        if strategy is not None:
            clauses.append("strategy = ?")
            params.append(strategy)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM backtest_trades
                WHERE {' AND '.join(clauses)}
                ORDER BY entry_utc ASC, id ASC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_backtest_walkforward(self, row: dict[str, Any]) -> int:
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO backtest_walkforward (
                    run_id, config_id, train_from, train_to, test_from,
                    test_to, strategy, n, avg_r_net, median_r_net,
                    win_rate, max_dd_r, profit_factor
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["run_id"],
                    row.get("config_id"),
                    row.get("train_from"),
                    row.get("train_to"),
                    row.get("test_from"),
                    row.get("test_to"),
                    row["strategy"],
                    row.get("n", 0),
                    row.get("avg_r_net"),
                    row.get("median_r_net"),
                    row.get("win_rate"),
                    row.get("max_dd_r"),
                    row.get("profit_factor"),
                ),
            )
            return int(cursor.lastrowid)

    def fetch_backtest_walkforward(self, run_id: int) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM backtest_walkforward
                WHERE run_id = ?
                ORDER BY test_from ASC, id ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_mt5_cache_candles(
        self, symbol: str, timeframe: int, candles: list[dict[str, Any]]
    ) -> int:
        """Bulk upsert de velas al cache historico (una sola transaccion).

        El upsert_mt5_cache_candle existente abre una conexion por vela;
        para profundidad maxima (miles de barras D1/H1) eso es inviable y
        alarga la ventana de lock contra el bot vivo. Devuelve cuantas filas
        se escribieron (0 en soft-fail)."""
        if not candles:
            return 0
        rows = [
            (
                symbol,
                timeframe,
                int(c.get("time") or 0),
                c.get("open"),
                c.get("high"),
                c.get("low"),
                c.get("close"),
                c.get("volume"),
            )
            for c in candles
        ]
        try:
            with get_connection(self.db_path) as connection:
                connection.executemany(
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
                    rows,
                )
            return len(rows)
        except Exception:
            return 0

    def fetch_mt5_cache_depth(
        self, symbol: str, timeframe: int
    ) -> dict[str, Any]:
        """Profundidad REAL del cache historico para (symbol, timeframe):
        cuantas barras hay y el rango [first, last] en epoch. Nunca asumir
        profundidad: se mide (ESPEC §4)."""
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS bars,
                       MIN(time) AS first_epoch,
                       MAX(time) AS last_epoch
                FROM mt5_historical_cache
                WHERE symbol = ? AND timeframe = ?
                """,
                (symbol, timeframe),
            ).fetchone()
        return {
            "bars": int(row["bars"] or 0),
            "first_epoch": row["first_epoch"],
            "last_epoch": row["last_epoch"],
        }

    # ------------------------------------------------------------------ #
    # v3.13.0 — agente IA en sandbox demo (ai_agent_decisions)
    # ------------------------------------------------------------------ #
    _AI_DECISION_UPDATABLE = {
        "executed", "block_reason", "demo_request_id", "reward_r", "rewarded_at",
    }

    def create_ai_agent_decision(self, decision: dict[str, Any]) -> int | None:
        """Inserta la decisión del agente para un paper trade. Idempotente: si ya
        hay una para ese paper_trade_id (UNIQUE), no duplica y devuelve None."""
        with get_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO ai_agent_decisions (
                    paper_trade_id, created_at, symbol, category, strategy_name,
                    direction, features_json, mean_r, std_r, sampled_r, intended,
                    executed, block_reason, demo_request_id, model_n
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(decision["paper_trade_id"]),
                    decision["created_at"],
                    decision.get("symbol"),
                    decision.get("category"),
                    decision.get("strategy_name"),
                    decision.get("direction"),
                    decision["features_json"],
                    decision.get("mean_r"),
                    decision.get("std_r"),
                    decision.get("sampled_r"),
                    decision["intended"],
                    int(bool(decision.get("executed"))),
                    decision.get("block_reason"),
                    decision.get("demo_request_id"),
                    decision.get("model_n"),
                ),
            )
        return int(cursor.lastrowid) if cursor.rowcount else None

    def update_ai_agent_decision(self, decision_id: int, updates: dict[str, Any]) -> None:
        fields = [k for k in updates if k in self._AI_DECISION_UPDATABLE]
        if not fields:
            return
        assignments = ", ".join(f"{f} = ?" for f in fields)
        with get_connection(self.db_path) as connection:
            connection.execute(
                f"UPDATE ai_agent_decisions SET {assignments} WHERE id = ?",
                [updates[f] for f in fields] + [int(decision_id)],
            )

    def fetch_ai_agent_decisions(
        self, pending_reward_only: bool = False, limit: int = 5000
    ) -> list[dict[str, Any]]:
        """Decisiones con el estado/fechas de su paper trade (para aprender y medir)."""
        where = "WHERE d.rewarded_at IS NULL" if pending_reward_only else ""
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT d.*, p.status AS trade_status, p.closed_at AS trade_closed_at
                FROM ai_agent_decisions d
                LEFT JOIN paper_trades p ON p.id = d.paper_trade_id
                {where}
                ORDER BY d.id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]
