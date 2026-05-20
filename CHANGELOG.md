# Changelog

## Trading Alert AI v2.4.0

Phase 4.5: Memecoin Hunter Pro (early detection + scoring refinado) + Bot Mode Toggle (alerts_only / trader / hybrid). Sigue read-only para órdenes reales.

**Memecoin Hunter Pro:**
- `app/collectors/geckoterminal_collector.py`: nuevo método `_collect_new_pools_for_network` que llama `/networks/{network}/new_pools`. Filtra pools con edad > `MAX_EARLY_POOL_AGE_HOURS=6`. Marca como `event_type="EARLY_MEMECOIN"`.
- `app/analyzers/memecoin_hunter.py`: `MemecoinHunterResult` dataclass + `analyze_memecoin()`. Calcula `early_bonus` (0-20 pts), `volume_velocity_ratio` (aceleración 5m vs 1h), `anti_rug_multiplier` (0.5-1.0 que penaliza honeypot/risky/liquidity_unlocked/holder_concentration).
- Integrado en `jobs.py` después de `score_token`. Para `category=memecoin and enable_memecoin_hunter`: `adjusted_score = int((base_score + early_bonus) * anti_rug_multiplier)`.
- Holder concentration y liquidity_locked quedan `None` en v2.4.0 (requieren RPC blockchain). Phase 5+ agregará collector RPC dedicado.
- ALERT_PRIORITY: `EARLY_MEMECOIN=90` (alta, justo bajo SECURITY_RISK).

**Telegram memecoins re-activadas con filtros estrictos:**
- **Default flip:** `ENABLE_MEMECOIN_TELEGRAM=true` (antes `false`). Quien quiera silencio: setear `false` en `.env`.
- Caps separados: `MAX_EARLY_MEMECOIN_ALERTS_PER_24H=3`, `MAX_MATURE_MEMECOIN_ALERTS_PER_24H=2`, `MAX_EARLY_MEMECOIN_ALERTS_PER_RUN=1`.
- `_send_ranked_candidates` distingue early vs mature por `alert_type` (`EARLY_MEMECOIN` vs `BOOSTED_TOKEN`/`TRENDING_POOL`).
- **Learning gate FORZADO** para memecoins: `FORCE_LEARNING_GATE_FOR_MEMECOIN=true`. Aunque `ENABLE_LEARNING_GATE=false` globalmente, memecoins siempre pasan por gate (defensa anti-rug).

**Bot Mode Toggle:**
- `app/utils/bot_mode.py`: `resolve_bot_mode()` con prioridad CLI > bot_state > setting > default trader.
- 3 modos: `trader` (default), `alerts_only` (skip strategy router, mantiene Telegram + lifecycle), `hybrid` (en v2.4.0 = trader; Phase 5+ agregará confirmación manual).
- Setting `BOT_MODE=trader|alerts_only|hybrid` en `.env`.
- Comando Telegram `/mode [trader|alerts_only|hybrid]` persiste en `bot_state.bot_mode_active`.
- CLI flag `python main.py --mode alerts_only` override por sesión.
- En `run_once`: log "Bot mode active: X". Si `alerts_only`, skip strategy router (no abre paper trades nuevos) pero mantiene Telegram alerts y lifecycle manager (no abandona posiciones).
- Dashboard Streamlit: nueva metric "Bot mode" en sección Portfolio.

**Settings nuevos (10):** `enable_early_memecoin_detection`, `max_early_pool_age_hours`, `enable_memecoin_hunter`, `memecoin_hunter_min_volume_velocity_ratio`, `max_early_memecoin_alerts_per_24h`, `max_mature_memecoin_alerts_per_24h`, `max_early_memecoin_alerts_per_run`, `force_learning_gate_for_memecoin`, `bot_mode`, + default flip de `enable_memecoin_telegram` → `true`.

**Tests nuevos (32 en 7 archivos):** bot_mode_toggle (9), geckoterminal_new_pools (4), memecoin_hunter (7), memecoin_alerts_phase4_5 (5), telegram_mode_command (5), cli_mode_flag (2). Total **229 verdes** (197 → 229).

- `APP_VERSION` bump a `v2.4.0`. SEC user agent a 2.4.0.

Sigue read-only para órdenes. `order_send` recién en Phase 5 (cuenta demo ICMarkets autorizada).

## Trading Alert AI v2.3.0

Phase 4: validación MT5 demo + walk-forward backtester + data quality monitor + CSV export. Sigue read-only para órdenes. Phase 5 (`order_send` a demo) ya es el siguiente paso autorizado.

**MT5 extensiones (broker ICMarkets default):**
- `app/brokers/mt5_symbol_map.py`: mapping bidireccional Yahoo↔MT5 por broker_profile (icmarkets, metaquotes). EURUSD=X → EURUSD, GC=F → XAUUSD, etc.
- `app/brokers/mt5_reader.py`: nuevos métodos `validate_symbol`, `symbol_info` (spread, point, digits, contract_size, volume_min/step, tick_value), `compute_pip_value` (pip value en moneda de cuenta para 1 lote), `get_historical_range` (wrapper sobre copy_rates_range). Constants `MT5Timeframe.M1/M5/M15/H1/H4/D1`.
- `app/brokers/mt5_historical.py`: `MT5HistoricalFetcher` con cache local en SQLite (`mt5_historical_cache`). Evita pedir el mismo bar dos veces al broker.

**Walk-forward backtester:**
- `app/learning/walk_forward.py`: `WalkForwardBacktester` con train/test split deslizante. NO tunea parámetros (eso queda para Phase 6).
- Detecta degradación entre in-sample y out-of-sample: `(train_sharpe - test_sharpe) / |train_sharpe| * 100`.
- Settings: `walk_forward_train_days=14`, `walk_forward_test_days=7`, `walk_forward_slide_days=1`, `walk_forward_min_train_samples=10`.
- Persiste resultados en nueva tabla `walk_forward_results`.

**Data quality monitor:**
- `app/intelligence/data_quality.py`: `gap_check`, `staleness_check`, `collector_failure_check`, `run_full_check`.
- Persiste en nueva tabla `data_quality_log`.
- Integrado en `jobs.run_once` cada N ciclos (`data_quality_check_every_n_cycles=10`).

**CSV export:**
- `app/utils/csv_export.py`: `export_outcomes_csv`, `export_paper_trades_csv`, `export_horizons_csv`, `export_walk_forward_csv`. Path saneado con `safe_resolve_within`.

**Telegram commands nuevos:**
- `/mt5_status`: estado conexión MT5 + broker + account + symbol_info de EURUSD.
- `/data_quality`: stale symbols + gaps + collector failures.
- `/walk_forward STRATEGY [días] [categoría]`: corre walk-forward sobre 1 strategy.
- `/export_csv [outcomes|trades|horizons|walk_forward]`: genera archivo en `exports/`.

**Dashboard expansion:**
- Nueva sección "Walk-Forward Performance" con resumen por strategy y top 20 ventanas.
- Nueva sección "Data Quality" con últimos 20 checks.

**Schema (v2.3.0):**
- Tabla `mt5_historical_cache` (symbol, timeframe, time UNIQUE, ohlcv).
- Tabla `walk_forward_results` (strategy_name, train/test windows, métricas, degradation, samples).
- Tabla `data_quality_log` (check_at, gaps, stale, failures, summary JSON).

**Settings nuevos (12):** mt5_broker_profile, walk_forward_* (5), data_quality_* (4), enable_csv_export, csv_export_path.

**Packages:** `MetaTrader5 5.0.5735` y `anthropic 0.103.1` instalados en `.venv`. Soft-fail si faltan.

**Tests:** 34 nuevos (mt5_symbol_map 5, mt5_reader_extensions 6, mt5_historical 3, data_quality 4, csv_export 4, walk_forward 6, telegram_phase4 6). Total **197 verdes** (163 → 197).

- `APP_VERSION` bump a `v2.3.0`.
- User-Agents en collectors bumpeados a 2.3 + SEC user agent a 2.3.0.

Sigue read-only. `order_send` autorizado para Phase 5 (cuenta demo ICMarkets ya disponible).

## Trading Alert AI v2.2.0

Phase 3 + 3.5: forex price-action profesional + LLM integration con Claude API. Sigue read-only para ordenes reales.

**Phase 3 — Forex price-action + dashboard avanzado:**

- Nuevo `app/collectors/macro_collector.py`: pull periodico de VIX, DXY, SPY via Yahoo. Calcula regime `risk_on` / `risk_off` / `neutral`. Persiste en nueva tabla `macro_snapshots`.
- Nuevo `app/collectors/economic_calendar_collector.py`: parser ForexFactory XML, filtra eventos high-impact en USD/EUR/GBP/JPY/CHF/AUD/CAD/NZD. Persiste en nueva tabla `economic_events`.
- Nuevo `app/intelligence/calendar_filter.py::is_safe_window`: bloquea apertura de trades ± 30 min alrededor de NFP/FOMC/CPI para la moneda relevante.
- `app/intelligence/macro_context.py`: agrega `current_regime()` y `full_macro_context()` que combina sesion + regime.
- Nuevo `app/analyzers/technical_patterns.py::analyze_multitf`: combina pattern M15 + H1 con flag `aligned` + `confluence_score`.
- Nueva strategy `app/strategies/forex_session_breakout.py`: opera solo durante London/NY overlap, busca breakouts del Asian range. Horizon 8h.
- Las 4 strategies existentes ahora **usan** `ctx.macro`: breakout penaliza low liquidity, mean_reversion penaliza risk_off, momentum bonifica risk_on, news_catalyst permite forex/gold.
- Alertas Telegram activadas para forex/gold con caps separados (`max_forex_alerts_per_24h=3`, `max_gold_alerts_per_24h=2`). Controladas por `enable_forex_alerts` y `enable_gold_alerts`.
- Nueva columna `alerts.strategy_name` — cuando una strategy abre paper trade, el alert lo registra para drilldown.
- Dashboard Streamlit: nueva sección "Análisis profundo" con heatmap horizonte × hora del día, macro context panel (VIX/DXY/SPY/regime), calendario económico próximas 24h, drilldown por alerta (selectbox + paper_trade + horizons).

**Phase 3.5 — LLM integration (Claude API):**

- Nuevo `app/intelligence/claude_processor.py`: cliente centralizado para Anthropic Claude API. **Soft-fail completo**: si `ENABLE_CLAUDE_INTEGRATION=false`, sin API key o paquete `anthropic` no instalado → todos los metodos retornan None silenciosamente. Sin crashes.
- Caracteristicas: throttle por ciclo (`claude_calls_per_cycle_cap=6`), cache SHA256 (TTL 1h), telemetria de costo por dia en `bot_state` (`claude_input_tokens_<date>`, `claude_output_tokens_<date>`), safety cap `claude_max_cost_per_day_usd=2.0`.
- Métodos: `summarize_news`, `expand_pro_analysis`, `interpret_free_text`.
- `jobs.py::_market_intelligence` ahora llama `claude_processor.expand_pro_analysis` despues de armar `ProfessionalAnalysis`. Si Claude responde, agrega "🤖 IA: ..." a reasons.
- `command_handler.py` fallback "no entendi" ahora usa Claude para interpretar preguntas naturales. Si Claude retorna un comando slash valido, lo ejecuta recursivamente; sino devuelve texto natural.
- `AlertRecord` gana campo opcional `ai_reasoning: list[str]` para futuro storage de razonamiento Claude.
- Modelo default: `claude-haiku-4-5` (~$1/M input, $5/M output). Cost cap de $2/dia previene factura inesperada.
- Settings `_SECRET_FIELDS` incluye `anthropic_api_key` — enmascarado en `repr(settings)` y por `LogRedactor`.

**Schema changes (v2.2.0):**

- Tabla `macro_snapshots` (id, captured_at UNIQUE, vix_value, dxy_value, spy_value, regime).
- Tabla `economic_events` (id, event_time, country, impact, title, captured_at, UNIQUE(event_time, country, title)).
- Columna `alerts.strategy_name TEXT` via `_ensure_column`.
- Indices: `idx_events_time`, `idx_macro_captured`.

**Settings nuevos (19):** macro_collector (2), economic_calendar (3), forex_alerts (5), strategy_forex_session_breakout (1), claude integration (8 — incluye `ANTHROPIC_API_KEY` secret).

**Tests:** 28 nuevos en 5 archivos (claude_processor 8, macro_collector 3, economic_calendar 4, calendar_filter 3, forex_session_breakout 6, forex_alerts_phase3 4). Total **163 verdes** (135 → 163).

- `requirements.txt`: agrega `anthropic>=0.40.0,<1.0.0`.
- `APP_VERSION` bump a `v2.2.0`.

Sigue read-only. NO order_send a brokers ni demo MT5 (Phase 5).

## Trading Alert AI v2.1.0

Fase 2.6: hardening de seguridad y privacidad. Sin nuevas features funcionales. Sin breaking changes en API publica.

- `Settings.__repr__` ahora enmascara `telegram_bot_token`, `telegram_chat_id`, `mt5_login`, `mt5_password`, `mt5_server` con `<redacted>` y muestra paths solo como basename. Defensa contra logs accidentales de `repr(settings)`.
- Nuevo `app/utils/safe_path.py` con `safe_resolve_within` y `safe_optional_file`. Aplicado en `OBSIDIAN_VAULT_PATH` (bloquea `../../...` traversal con fallback al default) y `MT5_PATH` (rechaza paths no-absolutos o no-existentes).
- Nuevo `app/utils/log_redactor.py`: filter que enmascara tokens estilo Telegram (regex `\d{9,12}:[A-Za-z0-9_-]{35,}`) y valores conocidos del .env. Instalado en root logger al startup desde main.py.
- Nuevo `app/utils/safe_http.py` con `safe_json(response, default)`. Aplicado en `dexscreener_collector._get_json` y `geckoterminal_collector.fetch_pool_ohlcv` (donde antes un JSON invalido crasheaba el ciclo).
- `app/scheduler/jobs.py:93` solo loguea el nombre del archivo de la DB (no path absoluto del filesystem del usuario).
- `app/database/db.py::init_db` envuelve `executescript` en try/except `sqlite3.DatabaseError` con mensaje claro (sin filesystem leak) si la DB esta corrupta.
- `app/assistant/command_handler.py::halt_message` clampa el argumento de `/halt` al rango [1, 168] horas. Previene `/halt -999` o `/halt 999999`.
- `app/risk/position_sizer.py::calculate_position_size` rechaza `risk_pct > 10` como safety cap. Defensa contra config rota (ej. `RISK_PER_TRADE_PCT=100`).
- `app/analyzers/token_score.py::_liquidity_points` trata `liquidity_usd < 0` como `None` en lugar de propagar valor invalido.
- `requirements.txt`: versiones pinneadas exactas (python-dotenv==1.2.2, requests==2.34.2, streamlit==1.57.0, pandas==3.0.3, pytest==9.0.3, MetaTrader5>=5.0.45,<6.0.0). Defensa contra cadena suministro maliciosa.
- 18 tests nuevos en `tests/test_security_hardening.py` (settings repr, safe_path, halt clamp, position cap, score sanitize, log redactor, safe_json). Total **135 tests verdes** (117 → 135).
- `APP_VERSION` bump a `v2.1.0`.

Hallazgos del audit confirmados como OK (no requirieron fix): .gitignore correcto, HTTPS-only, todos los requests.get con timeout, User-Agents genericos, no shell injection, no eval/exec/pickle, no logs a disco, Streamlit en localhost, /config no expone secretos, queries usan placeholders ? (54 de 56; los 2 con f-string ya mitigados por whitelist + parameterized).

Sigue read-only. NO order_send a brokers reales ni demo MT5 (Fase 5).

## Trading Alert AI v2.0.0

Fase 2.5: el bot pasa de "alerter" a "trader engine autonomo". Sigue read-only (sin order_send a brokers ni demo MT5 todavia; eso es Fase 5).

- Agrega `app/brokers/mt5_reader.py`: adapter MT5 read-only soft-fail. Si MetaTrader5 no esta instalado o initialize falla, retorna None silenciosamente y el bot sigue corriendo degradado con yfinance. Lee tick, rates y account_info. Credenciales (login/password/server) solo en .env real; nunca en logs.
- Agrega `app/portfolio/portfolio_manager.py`: track de posiciones abiertas, exposicion por categoria, P&L diario, equity curve, riesgo total. account_balance prioriza MT5 → bot_state → starting_balance.
- Agrega `app/risk/risk_manager.py`: kill-switch persistente en bot_state (manual + automatico por max drawdown diario), gates check_can_open_trade (max trades concurrentes total + por categoria + max riesgo agregado), force_close_all_open.
- Agrega `app/risk/position_sizer.py`: funcion pura `calculate_position_size` con formula `risk_amount = balance × risk_pct/100; size_units = risk_amount / |entry - stop|`. Maneja long y short.
- Agrega `app/strategies/` con base + 4 estrategias: breakout, mean_reversion, momentum, news_catalyst. Cada strategy implementa Protocol `Strategy.evaluate(ctx) -> StrategySignal | None`. StrategyRouter las filtra por min_confidence.
- Agrega `app/intelligence/macro_context.py`: sesiones FX (asian/london/ny) con flag is_high_liquidity.
- Agrega `app/learning/lifecycle_manager.py`: `manage_open_positions` refresca latest_price (MT5 si conectado), actualiza MFE/MAE/trailing, cierra trades por time_horizon_hours, hace partial close en TP1 con stop a breakeven. Soporta short.
- Agrega `app/alerts/trade_reporter.py`: mensajes Telegram automaticos al abrir/cerrar paper trades.
- Schema: tabla nueva `daily_pnl_log` (date PK + realized_pnl + trades_closed/opened + kill_switch_triggered). Paper trades gana 8 columnas: strategy_name, direction, time_horizon_hours, size_notional, size_units, risk_pct, partial_closed, account_balance_at_open.
- Bloqueo memecoins Telegram por default (`enable_memecoin_telegram=false`). Memecoins siguen alimentando strategy_lessons y outcomes por horizonte como lab de aprendizaje.
- Decision Engine en `app/scheduler/jobs.py`: gestiona posiciones abiertas al inicio de cada ciclo; en el loop, para snapshots stock/forex/gold pregunta al strategy router, evalua position_sizer + risk_manager, y crea paper_trade si pasa. Notifica apertura por Telegram (configurable).
- Telegram nuevos comandos: `/portfolio`, `/posiciones`, `/halt [horas]`, `/resume_trading`, `/strategies`.
- Dashboard Streamlit nueva seccion "Portfolio en vivo" con metrics (Balance, Posiciones, Riesgo total, P&L hoy), badge kill-switch, exposicion por categoria, historial daily_pnl_log.
- Agrega 28 settings nuevos. `requirements.txt` agrega `MetaTrader5` (Windows-only, comentario que soft-fail si no aplica). `.env.example` con bloque Fase 2.5 y MT5_LOGIN/PASSWORD/SERVER vacios (NUNCA con valores reales).
- Agrega 53 tests nuevos (mt5_reader, portfolio_manager, risk_manager, position_sizer, strategy_router, macro_context, trade_reporter, lifecycle_manager, telegram_phase25_commands, memecoin_telegram_block, decision_engine_phase25). Total 117 tests verdes.
- Bumpea `APP_VERSION` a `v2.0.0`.
- Sigue read-only: sin order_send a brokers ni demo MT5 todavia. Real-money trading sigue prohibido sin nueva autorizacion explicita.

## Trading Alert AI v1.7.0

- Agrega paper trades con tracking de MFE/MAE durante la vida del trade (`paper_trades.mfe_pct`, `paper_trades.mae_pct`).
- Agrega trailing stops simulados en paper trading (columnas `original_stop_loss`, `trailing_active`). El stop se eleva cuando la posicion supera el umbral de activacion y nunca baja.
- Agrega SL/TP basados en ATR (Average True Range) opcional en `build_trade_readiness`; ATR se calcula del OHLCV cuando esta disponible y se clampa al rango seguro por categoria.
- Agrega `app/analyzers/learned_weights.py`: ajusta el score base con `strategy_lessons` aprendidas (bonus/malus por feature, clamp duro). **OFF por default** hasta que el usuario active `ENABLE_LEARNED_WEIGHTS=true`.
- Agrega `app/analyzers/learning_gate.py`: bloquea envio de alerta si el backtest historico de la combinacion de features tiene win_rate bajo. **OFF por default** hasta que el usuario active `ENABLE_LEARNING_GATE=true`.
- Agrega `app/collectors/forex_collector.py`: collector de FX majors (`EURUSD=X, GBPUSD=X, USDJPY=X, USDCHF=X, AUDUSD=X, USDCAD=X, NZDUSD=X`) y oro (`GC=F`) via Yahoo Finance. Solo persiste snapshots y outcomes por horizonte; **no genera alertas Telegram en Fase 2** (las alertas forex/oro vendran en Fase 3 con analisis price-action especifico).
- Excluye forex/gold de `should_send_alert` y `candidate_for_security_check` (categoria nueva, fluye por snapshots y horizons sin notificar).
- Agrega 21 settings nuevos (ATR, trailing, learned weights, learning gate, forex collector). Variables nuevas en `.env.example` con bloque comentado.
- Agrega 26 tests nuevos (MFE/MAE, trailing, ATR SL/TP, learned weights, learning gate, forex collector). Total 64 tests verdes.
- Bumpea `APP_VERSION` a `v1.7.0`.
- Mantiene el sistema read-only: no compra, no vende y no ejecuta ordenes (ni a demo MT5 todavia; eso es Fase 5).

## Trading Alert AI v1.6.0

- Agrega persistencia historica de precios en `price_snapshots` con purga automatica.
- Crea tabla `alert_outcome_horizons` con outcomes por horizonte fijo (1h, 6h, 24h, 7d).
- Calcula MFE (max favorable excursion) y MAE (max adverse excursion) por ventana.
- Agrega modulo `app/learning/horizon_evaluator.py` integrado en `run_learning_cycle`.
- Agrega modulo `app/learning/backtester.py` con `backtest_strategy()` y `rank_top_strategies()`.
- Agrega comandos Telegram `/horizontes SIMBOLO` y `/backtest [Nh] [features...]`.
- Agrega seccion "Rendimiento por horizonte" en el dashboard Streamlit (tabla MFE/MAE, equity curve, ranking).
- Agrega reporte semanal automatico en `obsidian/tradingbot v.1/11 - Reporte Semanal.md`.
- Agrega 16 tests nuevos (snapshots, horizon evaluator, backtester, comandos Telegram, reporte semanal).
- Agrega 7 settings (`ENABLE_PRICE_SNAPSHOTS`, `SNAPSHOT_RETENTION_DAYS`, `HORIZON_MIN_SNAPSHOTS`, `ENABLE_HORIZON_EVALUATOR`, `BACKTEST_MIN_SAMPLES`, `BACKTEST_DEFAULT_HORIZON_HOURS`, `ENABLE_WEEKLY_OBSIDIAN_REPORT`).
- Bumpea `APP_VERSION` a `v1.6.0`.
- Mantiene el sistema read-only: no compra, no vende y no ejecuta ordenes.

## Trading Alert AI v1.5.2

- Agrega Learning Engine local.
- Crea tabla `signal_outcomes` para evaluar señales pasadas contra precios actuales.
- Crea tabla `strategy_lessons` para aprender que features ayudan o perjudican.
- Crea paper trading simulado en `paper_trades`, sin ordenes reales.
- Agrega readiness A/B/C/D/BLOCKED para preparar setups manuales.
- Agrega comandos `/aprendizaje`, `/paper` y `/entrenar`.
- Dashboard muestra outcomes, lecciones y paper trades.
- Mantiene el sistema read-only: no compra, no vende y no ejecuta ordenes.

## Trading Alert AI v1.5.1

- Agrega IA Pro read-only antes de MT5.
- Mejora analisis tecnico con MACD, Bollinger, ATR, volumen relativo, soporte/resistencia y sparkline.
- Agrega analisis de filings SEC recientes para acciones.
- Agrega comando `/pro SIMBOLO` con lectura profesional.
- Agrega comando `/filings SIMBOLO`.
- Mejora ranking con setup profesional, catalizadores, riesgos y checklist.
- Mantiene prohibido operar: sin compras, ventas, wallets, brokers ni ordenes.

## Trading Alert AI v1.5

- Agrega alertas agrupadas por categoria para reducir mensajes.
- Agrega comando `/cupos`.
- Agrega comando `/descartes`.
- Agrega filtro anti-hype para memecoins boosted/trending con baja liquidez, seguridad unknown o subidas ya exageradas.
- Agrega memoria automatica en Obsidian en `09 - Memoria Automatica.md`.

## Trading Alert AI v1.4

- Agrega inteligencia avanzada read-only de mercado.
- Analiza patrones tecnicos con velas OHLCV: tendencia, RSI, medias, ruptura y volumen.
- Usa OHLCV publico de GeckoTerminal para pools cuando hay `pair_address`.
- Usa velas publicas de Yahoo Finance para acciones configuradas.
- Agrega analisis basico de noticias/eventos por titulares: earnings, revenue, sales, guidance, conference, upgrades/downgrades.
- Agrega comandos Telegram `/noticias SIMBOLO` y `/patron SIMBOLO`.
- Suma patrones/noticias al ranking, sin ejecutar compras ni ventas.

## Trading Alert AI v1.3

- Agrega asistente basico por Telegram sin OpenAI API.
- Responde solo al `TELEGRAM_CHAT_ID` configurado.
- Agrega comandos `/status`, `/top`, `/top_memecoins`, `/top_stocks`, `/alertas`, `/analiza`, `/pausar`, `/reanudar`, `/config`.
- Permite pausar alertas automaticas sin detener el monitoreo ni el historial.
- Mantiene el sistema read-only: sin compras, ventas, wallets, brokers ni ordenes.

## Trading Alert AI v1.2

- Agrega categoria `stock` para alertas de bolsa de valores read-only.
- Agrega collector publico para simbolos configurados en `STOCK_SYMBOLS`.
- Agrega cupos duros por 24h: maximo 5 memecoins y 5 acciones por defecto.
- Agrega cupos por ciclo para evitar rafagas: 2 memecoins y 2 acciones por defecto.
- Cambia el envio a ranking: primero analiza, luego manda solo los mejores candidatos.
- Mantiene historial completo en SQLite aunque Telegram no envie.

## Trading Alert AI v1.1

- Reduce ruido de Telegram con modo high-conviction.
- Estima posible subida y posible caída con datos públicos.
- Telegram solo envía oportunidades con subida estimada mayor o igual a 500%.
- Guarda oportunidades descartadas en SQLite para revisión histórica.
- Agrega versión visible en alertas y configuración.

## Trading Alert AI v1.0

- MVP local con DEX Screener, GeckoTerminal, GoPlus, SQLite, Telegram y dashboard.
