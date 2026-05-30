import sqlite3
from pathlib import Path


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: Path) -> None:
    try:
        _init_db_unsafe(db_path)
    except sqlite3.DatabaseError as exc:
        # NO loguear el path completo (filesystem leak). Solo nombre.
        raise RuntimeError(
            f"DB initialization failed (possible corruption in '{db_path.name}'). "
            f"Backup and remove the file to recreate the schema. Error: {exc}"
        ) from exc


def _init_db_unsafe(db_path: Path) -> None:
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

            CREATE TABLE IF NOT EXISTS signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL UNIQUE,
                token_id INTEGER NOT NULL,
                category TEXT,
                chain TEXT,
                token_address TEXT,
                symbol TEXT,
                entry_price REAL,
                latest_price REAL,
                observed_return_pct REAL,
                score INTEGER,
                confidence INTEGER,
                outcome_label TEXT,
                age_minutes INTEGER,
                features TEXT,
                evaluated_at TEXT NOT NULL,
                FOREIGN KEY(alert_id) REFERENCES alerts(id),
                FOREIGN KEY(token_id) REFERENCES tokens(id)
            );

            CREATE TABLE IF NOT EXISTS strategy_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature TEXT NOT NULL,
                category TEXT,
                sample_count INTEGER,
                win_rate REAL,
                avg_return_pct REAL,
                avg_score REAL,
                confidence INTEGER,
                lesson TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(feature, category)
            );

            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL UNIQUE,
                token_id INTEGER NOT NULL,
                category TEXT,
                chain TEXT,
                token_address TEXT,
                symbol TEXT,
                thesis TEXT,
                readiness_grade TEXT,
                entry_price REAL,
                latest_price REAL,
                stop_loss REAL,
                take_profit_1 REAL,
                take_profit_2 REAL,
                invalidation TEXT,
                status TEXT,
                unrealized_return_pct REAL,
                opened_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT,
                FOREIGN KEY(alert_id) REFERENCES alerts(id),
                FOREIGN KEY(token_id) REFERENCES tokens(id)
            );

            CREATE TABLE IF NOT EXISTS training_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_version TEXT,
                alerts_evaluated INTEGER,
                outcomes_created INTEGER,
                lessons_updated INTEGER,
                paper_trades_created INTEGER,
                summary TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id INTEGER NOT NULL,
                chain TEXT NOT NULL,
                token_address TEXT NOT NULL,
                category TEXT,
                price REAL NOT NULL,
                liquidity_usd REAL,
                volume_5m REAL,
                volume_1h REAL,
                volume_24h REAL,
                captured_at TEXT NOT NULL,
                source TEXT,
                FOREIGN KEY(token_id) REFERENCES tokens(id)
            );

            CREATE TABLE IF NOT EXISTS mt5_historical_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe INTEGER NOT NULL,
                time INTEGER NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                UNIQUE(symbol, timeframe, time)
            );

            CREATE INDEX IF NOT EXISTS idx_mt5_hist_symbol_tf
                ON mt5_historical_cache(symbol, timeframe, time);

            CREATE TABLE IF NOT EXISTS walk_forward_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                symbol TEXT,
                category TEXT,
                train_start TEXT NOT NULL,
                train_end TEXT NOT NULL,
                test_start TEXT NOT NULL,
                test_end TEXT NOT NULL,
                train_sharpe REAL,
                train_win_rate REAL,
                train_avg_return REAL,
                test_sharpe REAL,
                test_win_rate REAL,
                test_avg_return REAL,
                degradation_pct REAL,
                train_samples INTEGER,
                test_samples INTEGER,
                computed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_wf_strategy
                ON walk_forward_results(strategy_name);
            CREATE INDEX IF NOT EXISTS idx_wf_computed
                ON walk_forward_results(computed_at);

            CREATE TABLE IF NOT EXISTS data_quality_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_at TEXT NOT NULL,
                gaps_detected INTEGER DEFAULT 0,
                stale_symbols INTEGER DEFAULT 0,
                collector_failures INTEGER DEFAULT 0,
                summary TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_dq_check_at
                ON data_quality_log(check_at);

            CREATE TABLE IF NOT EXISTS macro_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL UNIQUE,
                vix_value REAL,
                dxy_value REAL,
                spy_value REAL,
                regime TEXT
            );

            CREATE TABLE IF NOT EXISTS economic_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time TEXT NOT NULL,
                country TEXT NOT NULL,
                impact TEXT,
                title TEXT,
                captured_at TEXT NOT NULL,
                UNIQUE(event_time, country, title)
            );

            CREATE INDEX IF NOT EXISTS idx_events_time
                ON economic_events(event_time);

            CREATE INDEX IF NOT EXISTS idx_macro_captured
                ON macro_snapshots(captured_at);

            CREATE TABLE IF NOT EXISTS daily_pnl_log (
                date TEXT PRIMARY KEY,
                realized_pnl_pct REAL DEFAULT 0,
                realized_pnl_usd REAL DEFAULT 0,
                trades_closed INTEGER DEFAULT 0,
                trades_opened INTEGER DEFAULT 0,
                kill_switch_triggered INTEGER DEFAULT 0,
                kill_switch_reason TEXT,
                starting_equity REAL,
                ending_equity REAL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_daily_pnl_log_date
                ON daily_pnl_log(date);

            CREATE TABLE IF NOT EXISTS alert_outcome_horizons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL,
                horizon_hours INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                return_pct REAL,
                mfe_pct REAL,
                mae_pct REAL,
                snapshots_used INTEGER,
                outcome_label TEXT,
                status TEXT,
                evaluated_at TEXT NOT NULL,
                UNIQUE(alert_id, horizon_hours),
                FOREIGN KEY(alert_id) REFERENCES alerts(id)
            );

            CREATE TABLE IF NOT EXISTS demo_trade_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_trade_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                volume REAL NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                risk_pct REAL,
                strategy_name TEXT,
                status TEXT NOT NULL,
                reason TEXT,
                request_summary TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                confirmed_at TEXT,
                sent_at TEXT,
                result_message TEXT,
                FOREIGN KEY(paper_trade_id) REFERENCES paper_trades(id)
            );

            CREATE TABLE IF NOT EXISTS demo_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                demo_request_id INTEGER NOT NULL,
                paper_trade_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                volume REAL NOT NULL,
                price REAL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                retcode INTEGER,
                order_ticket INTEGER,
                deal_ticket INTEGER,
                status TEXT NOT NULL,
                strategy_name TEXT,
                result_summary TEXT,
                sent_at TEXT NOT NULL,
                FOREIGN KEY(demo_request_id) REFERENCES demo_trade_requests(id),
                FOREIGN KEY(paper_trade_id) REFERENCES paper_trades(id)
            );

            CREATE TABLE IF NOT EXISTS strategy_performance (
                strategy_name TEXT NOT NULL,
                category TEXT NOT NULL,
                trades INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                scratches INTEGER NOT NULL DEFAULT 0,
                win_rate REAL NOT NULL DEFAULT 0,
                avg_r REAL NOT NULL DEFAULT 0,
                avg_return_pct REAL NOT NULL DEFAULT 0,
                sum_return_pct REAL NOT NULL DEFAULT 0,
                artifacts_excluded INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (strategy_name, category)
            );

            CREATE INDEX IF NOT EXISTS idx_alerts_token_type_time
                ON alerts(chain, token_address, alert_type, created_at);
            CREATE INDEX IF NOT EXISTS idx_alerts_created_at
                ON alerts(created_at);
            CREATE INDEX IF NOT EXISTS idx_tokens_score
                ON tokens(latest_score);
            CREATE INDEX IF NOT EXISTS idx_signal_outcomes_label
                ON signal_outcomes(outcome_label);
            CREATE INDEX IF NOT EXISTS idx_paper_trades_status
                ON paper_trades(status);
            CREATE INDEX IF NOT EXISTS idx_price_snapshots_token_time
                ON price_snapshots(chain, token_address, captured_at);
            CREATE INDEX IF NOT EXISTS idx_price_snapshots_captured
                ON price_snapshots(captured_at);
            CREATE INDEX IF NOT EXISTS idx_outcome_horizons_alert
                ON alert_outcome_horizons(alert_id);
            CREATE INDEX IF NOT EXISTS idx_outcome_horizons_status
                ON alert_outcome_horizons(status);
            CREATE INDEX IF NOT EXISTS idx_demo_requests_status
                ON demo_trade_requests(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_demo_requests_paper
                ON demo_trade_requests(paper_trade_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_demo_orders_request
                ON demo_orders(demo_request_id);
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
        _ensure_column(connection, "paper_trades", "mfe_pct", "REAL DEFAULT 0")
        _ensure_column(connection, "paper_trades", "mae_pct", "REAL DEFAULT 0")
        _ensure_column(connection, "paper_trades", "original_stop_loss", "REAL")
        _ensure_column(connection, "paper_trades", "trailing_active", "INTEGER DEFAULT 0")
        _ensure_column(connection, "paper_trades", "strategy_name", "TEXT")
        _ensure_column(connection, "paper_trades", "direction", "TEXT DEFAULT 'long'")
        _ensure_column(connection, "paper_trades", "time_horizon_hours", "INTEGER")
        _ensure_column(connection, "paper_trades", "size_notional", "REAL")
        _ensure_column(connection, "paper_trades", "size_units", "REAL")
        _ensure_column(connection, "paper_trades", "risk_pct", "REAL")
        _ensure_column(connection, "paper_trades", "partial_closed", "INTEGER DEFAULT 0")
        _ensure_column(connection, "paper_trades", "account_balance_at_open", "REAL")
        _ensure_column(connection, "alerts", "strategy_name", "TEXT")
        # Phase 5.5 Bloque B v2.6.0 — scalping flag para diferenciar trades.
        _ensure_column(connection, "paper_trades", "is_scalping", "INTEGER DEFAULT 0")
        _ensure_column(connection, "demo_orders", "is_scalping", "INTEGER DEFAULT 0")
        _ensure_column(connection, "signal_outcomes", "is_scalping", "INTEGER DEFAULT 0")
        _ensure_column(connection, "strategy_lessons", "is_scalping", "INTEGER DEFAULT 0")


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
