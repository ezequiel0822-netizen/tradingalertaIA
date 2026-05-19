# Changelog

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
