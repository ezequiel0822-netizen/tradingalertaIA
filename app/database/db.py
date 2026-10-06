import sqlite3
from pathlib import Path


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    # v3.9.5: WAL (persistente en el archivo) + NORMAL + busy_timeout. El repo abre
    # una conexion por operacion con commit propio -> cientos de transacciones de
    # una fila por ciclo; en journal_mode=delete cada commit crea/borra el journal
    # con fsync sobre una DB de GB, y la contencion daba "database is locked"
    # (cot_backfill, dashboard). WAL baja ese costo y permite lectores concurrentes.
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=5000")
    except sqlite3.DatabaseError:
        pass  # DB corrupta se reporta en init_db; no bloquear la conexion aca
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

            CREATE TABLE IF NOT EXISTS trade_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_trade_id INTEGER NOT NULL UNIQUE,
                symbol TEXT,
                category TEXT,
                strategy_name TEXT,
                direction TEXT,
                outcome TEXT,
                r_multiple REAL,
                lesson TEXT,
                lesson_key TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(paper_trade_id) REFERENCES paper_trades(id)
            );

            CREATE INDEX IF NOT EXISTS idx_trade_lessons_key
                ON trade_lessons(lesson_key);

            CREATE TABLE IF NOT EXISTS trade_r_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_trade_id INTEGER NOT NULL,
                unrealized_r REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY(paper_trade_id) REFERENCES paper_trades(id)
            );

            CREATE INDEX IF NOT EXISTS idx_trade_r_samples_trade
                ON trade_r_samples(paper_trade_id, recorded_at);

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

            -- v3.13.3: base horaria de cada serie INTRADIA del cache MT5.
            -- time_basis: 'utc' (instantes UTC real) | 'server' (hora del
            -- servidor MT5, legacy). Sin fila = legacy ('server'). D1+ no se
            -- marca: su epoch es una etiqueta de fecha (ver brokers/mt5_time.py).
            CREATE TABLE IF NOT EXISTS mt5_cache_meta (
                symbol TEXT NOT NULL,
                timeframe INTEGER NOT NULL,
                time_basis TEXT NOT NULL,
                server_tz TEXT,
                updated_at TEXT NOT NULL,
                note TEXT,
                PRIMARY KEY(symbol, timeframe)
            );

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

            CREATE TABLE IF NOT EXISTS cot_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                market_code TEXT NOT NULL,
                market_label TEXT,
                noncomm_long INTEGER,
                noncomm_short INTEGER,
                comm_long INTEGER,
                comm_short INTEGER,
                open_interest INTEGER,
                net_noncomm INTEGER,
                net_comm INTEGER,
                captured_at TEXT NOT NULL,
                UNIQUE(report_date, market_code)
            );

            CREATE INDEX IF NOT EXISTS idx_cot_report
                ON cot_snapshots(report_date);

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

            CREATE TABLE IF NOT EXISTS strategy_performance_sliced (
                strategy_name TEXT NOT NULL,
                category TEXT NOT NULL,
                dimension TEXT NOT NULL,
                bucket TEXT NOT NULL,
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
                PRIMARY KEY (strategy_name, category, dimension, bucket)
            );

            CREATE TABLE IF NOT EXISTS realized_feature_lessons (
                feature TEXT NOT NULL,
                category TEXT NOT NULL,
                sample_count INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                win_rate REAL NOT NULL DEFAULT 0,
                avg_r REAL NOT NULL DEFAULT 0,
                avg_return_pct REAL NOT NULL DEFAULT 0,
                confidence INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (feature, category)
            );

            -- v3.6.0 — Backtest Replay Harness (ESPEC_BACKTEST_REPLAY_v1.md §5).
            -- Tablas SEPARADAS de la medicion viva: cero FKs hacia tablas vivas,
            -- nada del ciclo vivo las lee. El backtest NO cuenta para /readiness,
            -- /expectancy, /edge ni los 400 de Fase D.
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_utc TEXT NOT NULL,
                git_commit TEXT,
                mode TEXT NOT NULL DEFAULT 'A',
                timeframe TEXT,
                symbols TEXT,
                strategies TEXT,
                data_ranges_json TEXT,
                config_json TEXT,
                cost_multiplier REAL,
                n_configs_tested INTEGER NOT NULL DEFAULT 0,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS backtest_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                config_id TEXT,
                strategy TEXT NOT NULL,
                symbol TEXT NOT NULL,
                category TEXT,
                direction TEXT NOT NULL,
                signal_bar_utc TEXT,
                entry_utc TEXT,
                entry_price REAL,
                sl_initial REAL,
                tp_initial REAL,
                exit_utc TEXT,
                exit_price REAL,
                exit_reason TEXT,
                bars_held INTEGER,
                r_gross REAL,
                cost_r REAL,
                r_net REAL,
                mfe_r REAL,
                mae_r REAL,
                session TEXT,
                regime_trend TEXT,
                regime_vol TEXT,
                year INTEGER,
                FOREIGN KEY(run_id) REFERENCES backtest_runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
                ON backtest_trades(run_id);
            CREATE INDEX IF NOT EXISTS idx_backtest_trades_strategy_symbol
                ON backtest_trades(strategy, symbol);

            CREATE TABLE IF NOT EXISTS backtest_walkforward (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                config_id TEXT,
                train_from TEXT,
                train_to TEXT,
                test_from TEXT,
                test_to TEXT,
                strategy TEXT NOT NULL,
                n INTEGER NOT NULL DEFAULT 0,
                avg_r_net REAL,
                median_r_net REAL,
                win_rate REAL,
                max_dd_r REAL,
                profit_factor REAL,
                FOREIGN KEY(run_id) REFERENCES backtest_runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_backtest_wf_run
                ON backtest_walkforward(run_id);

            CREATE INDEX IF NOT EXISTS idx_alerts_token_type_time
                ON alerts(chain, token_address, alert_type, created_at);
            CREATE INDEX IF NOT EXISTS idx_alerts_created_at
                ON alerts(created_at);
            CREATE INDEX IF NOT EXISTS idx_tokens_score
                ON tokens(latest_score);
            CREATE INDEX IF NOT EXISTS idx_signal_outcomes_label
                ON signal_outcomes(outcome_label);
            CREATE INDEX IF NOT EXISTS idx_signal_outcomes_evaluated
                ON signal_outcomes(evaluated_at);
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

            -- v3.13.0 — agente IA en sandbox demo: una fila por candidato forex/gold
            -- consultado. intended = lo que el agente quiso (execute/skip);
            -- executed = si de verdad salió a MT5 demo; reward_r = R realizado del
            -- paper trade (aprende de TODOS los candidatos, ejecutados o no).
            CREATE TABLE IF NOT EXISTS ai_agent_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_trade_id INTEGER NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                symbol TEXT,
                category TEXT,
                strategy_name TEXT,
                direction TEXT,
                features_json TEXT NOT NULL,
                mean_r REAL,
                std_r REAL,
                sampled_r REAL,
                intended TEXT NOT NULL,
                executed INTEGER NOT NULL DEFAULT 0,
                block_reason TEXT,
                demo_request_id INTEGER,
                model_n INTEGER,
                reward_r REAL,
                rewarded_at TEXT,
                FOREIGN KEY(paper_trade_id) REFERENCES paper_trades(id)
            );
            CREATE INDEX IF NOT EXISTS idx_ai_agent_decisions_reward
                ON ai_agent_decisions(rewarded_at);
            CREATE INDEX IF NOT EXISTS idx_ai_agent_decisions_created
                ON ai_agent_decisions(created_at);
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
        # v2.11.0 — features tecnicas capturadas al ENTRY (habilitan el ML, que
        # hoy las recibia NaN). Se llenan desde el TechnicalPattern al abrir el
        # swing trade (jobs._try_open_paper_trades). NULL para trades viejos (no
        # retroactivo) y para scalping (su ScalpingSignal no expone indicadores).
        # atr_value guarda ATR en % (atr_pct): normalizado y comparable entre simbolos.
        _ensure_column(connection, "paper_trades", "rsi_entry", "REAL")
        _ensure_column(connection, "paper_trades", "atr_value", "REAL")
        _ensure_column(connection, "paper_trades", "macd_value", "REAL")
        _ensure_column(connection, "paper_trades", "macd_signal_value", "REAL")
        # v3.12.0 — VWAP al ENTRY (mismo patron v2.11.0: captura para research/
        # ML dataset; el ML sigue OFF). Distancia % al VWAP de sesion y al VWAP
        # semanal anclado. NULL para trades viejos y para forex sin volumen
        # (Yahoo da volumen 0 en forex -> el VWAP honesto es None, no 0).
        _ensure_column(connection, "paper_trades", "vwap_dist_pct", "REAL")
        _ensure_column(connection, "paper_trades", "vwap_week_dist_pct", "REAL")
        # v3.12.0 — Hurst y footprint lite al ENTRY (research/ML; ML sigue OFF).
        # hurst_entry: H de la ventana mas larga disponible; clv_entry: close
        # location value de la vela de entrada; candle_strength: fuerza
        # direccional normalizada por ATR (categorica).
        _ensure_column(connection, "paper_trades", "hurst_entry", "REAL")
        _ensure_column(connection, "paper_trades", "clv_entry", "REAL")
        _ensure_column(connection, "paper_trades", "candle_strength", "TEXT")


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
