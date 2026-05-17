import sqlite3
from pathlib import Path


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: Path) -> None:
    with get_connection(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain TEXT NOT NULL,
                token_address TEXT NOT NULL,
                category TEXT DEFAULT 'memecoin',
                symbol TEXT,
                name TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                source TEXT,
                latest_price REAL,
                latest_liquidity_usd REAL,
                latest_volume_5m REAL,
                latest_volume_1h REAL,
                latest_volume_24h REAL,
                latest_score INTEGER,
                latest_risk_level TEXT,
                latest_estimated_gain_pct REAL,
                latest_estimated_loss_pct REAL,
                latest_estimate_confidence INTEGER,
                UNIQUE(chain, token_address)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id INTEGER NOT NULL,
                alert_type TEXT NOT NULL,
                category TEXT DEFAULT 'memecoin',
                chain TEXT NOT NULL,
                token_address TEXT NOT NULL,
                symbol TEXT,
                name TEXT,
                score INTEGER,
                risk_level TEXT,
                reasons TEXT,
                security_summary TEXT,
                price REAL,
                liquidity_usd REAL,
                volume_5m REAL,
                volume_1h REAL,
                source TEXT,
                estimated_gain_pct REAL,
                estimated_loss_pct REAL,
                estimate_confidence INTEGER,
                estimate_summary TEXT,
                app_version TEXT,
                created_at TEXT NOT NULL,
                sent_to_telegram INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(token_id) REFERENCES tokens(id)
            );

            CREATE TABLE IF NOT EXISTS security_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain TEXT NOT NULL,
                token_address TEXT NOT NULL,
                honeypot_status TEXT,
                buy_tax REAL,
                sell_tax REAL,
                owner_status TEXT,
                mint_risk TEXT,
                blacklist_risk TEXT,
                raw_summary TEXT,
                checked_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_alerts_token_type_time
                ON alerts(chain, token_address, alert_type, created_at);
            CREATE INDEX IF NOT EXISTS idx_alerts_created_at
                ON alerts(created_at);
            CREATE INDEX IF NOT EXISTS idx_tokens_score
                ON tokens(latest_score);
            """
        )
        _ensure_column(connection, "tokens", "latest_estimated_gain_pct", "REAL")
        _ensure_column(connection, "tokens", "latest_estimated_loss_pct", "REAL")
        _ensure_column(connection, "tokens", "latest_estimate_confidence", "INTEGER")
        _ensure_column(connection, "tokens", "category", "TEXT DEFAULT 'memecoin'")
        _ensure_column(connection, "alerts", "estimated_gain_pct", "REAL")
        _ensure_column(connection, "alerts", "estimated_loss_pct", "REAL")
        _ensure_column(connection, "alerts", "estimate_confidence", "INTEGER")
        _ensure_column(connection, "alerts", "estimate_summary", "TEXT")
        _ensure_column(connection, "alerts", "app_version", "TEXT")
        _ensure_column(connection, "alerts", "category", "TEXT DEFAULT 'memecoin'")


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    existing = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in existing:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )
