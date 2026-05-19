# Versiones y Cambios

## v1.0

MVP local:

- DEX Screener
- GeckoTerminal
- GoPlus opcional
- SQLite
- Telegram alerts
- Dashboard

## v1.1

Reduccion de ruido:

- estimacion de subida
- estimacion de caida
- confianza
- Telegram solo para memecoins con subida estimada >= 500%

## v1.2

Ranking y bolsa:

- categoria `memecoin`
- categoria `stock`
- cupos por 24h
- cupos por ciclo
- collector publico de bolsa
- ranking antes de enviar

## v1.3

Asistente basico por Telegram:

- `/status`
- `/top`
- `/top_memecoins`
- `/top_stocks`
- `/alertas`
- `/analiza`
- `/pausar`
- `/reanudar`
- `/config`

No usa OpenAI API.

## v1.4

Market Intelligence read-only:

- patrones tecnicos con OHLCV
- RSI, medias, ruptura, volumen
- noticias y eventos por titulares
- comandos `/noticias SIMBOLO`
- comandos `/patron SIMBOLO`
- patrones/noticias suman al ranking

## v1.5

Signal Quality:

- alertas agrupadas
- comando `/cupos`
- comando `/descartes`
- filtro anti-hype
- memoria automatica en Obsidian

## v1.5.1

IA Pro read-only:

- comando `/pro SIMBOLO`
- comando `/filings SIMBOLO`
- MACD, Bollinger, ATR, volumen relativo, soporte/resistencia
- sparkline visual para lectura rapida
- catalizadores de noticias: earnings, revenue, guidance, conferencias, upgrades/downgrades
- filings SEC recientes para acciones
- setup profesional con sesgo, score, confianza, riesgos y checklist

Regla: sigue sin operar mercados.

## v1.5.2

Learning Engine:

- evalua señales pasadas contra precios actuales
- aprende features que funcionan o fallan
- guarda outcomes en `signal_outcomes`
- guarda lecciones en `strategy_lessons`
- simula setups en papel en `paper_trades`
- agrega readiness A/B/C/D/BLOCKED
- comandos `/aprendizaje`, `/paper`, `/entrenar`

Regla: paper trading no es trading real. No se envian ordenes.

## v1.6.0

Aprendizaje por horizonte (Fase 1 - Fundamentos):

- guarda snapshots historicos de precio en `price_snapshots` (purga 30 dias por defecto)
- evalua cada alerta a horizontes fijos 1h, 6h, 24h y 7d
- guarda outcomes en `alert_outcome_horizons` con `return_pct`, `mfe_pct`, `mae_pct` y `snapshots_used`
- nuevo modulo `app/learning/horizon_evaluator.py` integrado en `run_learning_cycle`
- nuevo modulo `app/learning/backtester.py` con `backtest_strategy()` y `rank_top_strategies()`
- comandos Telegram nuevos: `/horizontes SIMBOLO` y `/backtest [Nh] [features...]`
- dashboard Streamlit nueva seccion "Rendimiento por horizonte" con tabla MFE/MAE, equity curve simulada y ranking de reglas
- reporte semanal automatico en `11 - Reporte Semanal.md` cada 7 dias
- 16 tests nuevos en `tests/test_price_snapshots.py`, `test_horizon_evaluator.py`, `test_backtester.py`, `test_telegram_horizons_backtest.py`, `test_weekly_obsidian_report.py`

Nota: las alertas anteriores a v1.6.0 no tienen snapshots historicos, sus outcomes por horizonte aparecen como `insufficient_data` hasta que se acumulen snapshots.

Regla: sigue siendo read-only. No compra, no vende, no firma transacciones.

## v1.7.0

Fase 2 - paper trading++, pesos aprendidos, learning gate, foundation forex/oro:

- Paper trades guardan MFE y MAE durante toda la vida del trade (`paper_trades.mfe_pct`, `paper_trades.mae_pct`).
- Trailing stops simulados: cuando la posicion sube por encima del umbral (5% stock, 50% memecoin), el stop sigue al precio. Nunca baja. Se preserva el stop original en `original_stop_loss`.
- SL/TP por ATR opcional en `build_trade_readiness`. Si hay OHLCV, calcula ATR del activo y arma stop/targets con multiplicadores (2x stop, 2x/4x targets), clampeados al rango seguro por categoria.
- Pesos aprendidos en `app/analyzers/learned_weights.py`: ajusta score base con `strategy_lessons` aprendidas. Bonus/malus por feature con clamp duro ±10. OFF por default; activar con `ENABLE_LEARNED_WEIGHTS=true` despues de revisar `/aprendizaje`.
- Learning gate en `app/analyzers/learning_gate.py`: antes de mandar Telegram, consulta backtester historico de la combinacion (`category + alert + score buckets`, horizonte 24h, ultimos 30 dias). Si win_rate < 45% y hay >= 10 muestras, bloquea envio. La alerta queda con `sent_to_telegram=0`, visible en `/descartes`. OFF por default; activar con `ENABLE_LEARNING_GATE=true`.
- Nuevo collector `app/collectors/forex_collector.py` para FX majors (EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD) y oro (GC=F) via Yahoo Finance. Solo acumula snapshots y outcomes por horizonte; NO genera alertas Telegram. Fase 3 traera el analisis price-action especifico para forex/oro.
- 21 settings nuevos. 26 tests nuevos (64 verdes en total).

Regla: sigue siendo read-only. No compra, no vende, no firma transacciones. Demo MT5 trading autorizado para Fase 5; real sigue prohibido sin nueva autorizacion.

## v2.0.0

Fase 2.5 - trader engine autonomo (simulado + MT5 read-only). El bot pasa de "alerter" a "trader engine":

- Nuevo `app/brokers/mt5_reader.py`: adapter MT5 read-only soft-fail. Lee tick, rates y account_info. Credenciales solo en .env real, nunca en logs. NUNCA `order_send`.
- Nuevo `app/portfolio/portfolio_manager.py`: posiciones abiertas, exposicion por categoria, P&L diario, equity curve, riesgo total.
- Nuevo `app/risk/risk_manager.py`: kill-switch persistente (manual con `/halt` o automatico por max drawdown diario), gates de max trades concurrentes y max riesgo agregado.
- Nuevo `app/risk/position_sizer.py`: tamano calculado por % cuenta × distancia al stop. Soporta long y short.
- Nuevo `app/strategies/`: 4 estrategias nombradas (breakout, mean_reversion, momentum, news_catalyst) + router que filtra por min_confidence.
- Nuevo `app/intelligence/macro_context.py`: sesiones FX (asian/london/ny) con flag is_high_liquidity.
- Nuevo `app/learning/lifecycle_manager.py`: gestiona posiciones vivas - MFE/MAE, trailing, time exit, partial close en TP1 con stop a breakeven. Soporta short.
- Nuevo `app/alerts/trade_reporter.py`: mensajes Telegram al abrir/cerrar paper trades.
- Schema: tabla `daily_pnl_log` nueva + 8 columnas nuevas en `paper_trades` (strategy_name, direction, time_horizon_hours, size_notional, size_units, risk_pct, partial_closed, account_balance_at_open).
- Memecoins bloqueadas de Telegram por default (`enable_memecoin_telegram=false`); siguen alimentando `strategy_lessons` como lab de aprendizaje.
- Decision Engine continuo en `app/scheduler/jobs.py`: gestiona posiciones abiertas al inicio del ciclo, pregunta al strategy router para nuevos snapshots, aplica position_sizer + risk_manager antes de abrir paper trades.
- Dashboard Streamlit con seccion "Portfolio en vivo" (balance, posiciones, riesgo total, P&L hoy, kill-switch badge, exposicion por categoria, historial daily_pnl_log).
- Telegram comandos nuevos: `/portfolio`, `/posiciones`, `/halt [horas]`, `/resume_trading`, `/strategies`.
- 28 settings nuevos. 53 tests nuevos. **117 tests verdes en total**.

Regla: sigue siendo read-only. NO compra, NO vende, NO `order_send` ni a brokers reales ni a demo MT5 (eso es Fase 5). MT5 demo trading sigue autorizado para Fase 5; real-money trading sigue prohibido sin nueva autorizacion explicita.

## v2.1.0

Fase 2.6 - security & privacy hardening. Sin nuevas features funcionales. Cero breaking changes en API publica.

- `Settings.__repr__` enmascara `telegram_bot_token`, `telegram_chat_id`, `mt5_login`, `mt5_password`, `mt5_server` con `<redacted>` y paths solo como basename. Defensa contra logs accidentales de `repr(settings)`.
- Nuevo `app/utils/safe_path.py`: bloquea path traversal en `OBSIDIAN_VAULT_PATH` (fallback al default) y rechaza `MT5_PATH` invalido.
- Nuevo `app/utils/log_redactor.py`: filter del root logger que enmascara tokens estilo Telegram y valores conocidos del .env. Instalado al startup desde main.py.
- Nuevo `app/utils/safe_http.py`: `safe_json` para parsing defensivo. Aplicado en dexscreener + geckoterminal collectors.
- `init_db` ahora maneja DB corrupta con mensaje claro (sin filesystem leak).
- `/halt` clampa a [1, 168] horas. `calculate_position_size` rechaza `risk_pct > 10` como safety cap. `score_token` trata liquidez negativa como None.
- `requirements.txt`: versiones pinneadas exactas (python-dotenv, requests, streamlit, pandas, pytest, MetaTrader5). Defensa contra cadena suministro maliciosa.
- Log de inicio loguea solo nombre de archivo de DB, no path absoluto del usuario.
- 18 tests de seguridad nuevos. Total **135 tests verdes** (117 → 135).
- Bump a v2.1.0.

Hallazgos del audit confirmados como OK (no requirieron fix): .gitignore correcto, HTTPS-only, todos los `requests.get` con timeout, User-Agents genericos, no shell injection, no eval/exec/pickle, no logs a disco, Streamlit en localhost, `/config` no expone secretos.

Regla: sigue siendo read-only. NO order_send a brokers reales ni demo MT5 (Fase 5).

## v2.2.0

Phase 3 + 3.5: forex price-action profesional + LLM integration con Claude API. Sigue read-only.

**Phase 3:**
- Macro collector: VIX, DXY, SPY via Yahoo. Regime `risk_on`/`risk_off`/`neutral` en nueva tabla `macro_snapshots`.
- Economic calendar via ForexFactory XML. Eventos high-impact en USD/EUR/GBP/JPY/CHF/AUD/CAD/NZD en nueva tabla `economic_events`.
- `calendar_filter.is_safe_window`: bloquea trades ± 30 min alrededor de NFP/FOMC/CPI.
- `analyze_multitf`: combina pattern M15 + H1 con flag `aligned` + `confluence_score`.
- Nueva strategy `forex_session_breakout`: solo durante London/NY overlap, breakout del Asian range.
- 4 strategies existentes ahora **usan** `ctx.macro` (breakout penaliza low liquidity, mean_reversion penaliza risk_off, momentum bonifica risk_on, news_catalyst permite forex/gold).
- Alertas Telegram activadas para forex/gold con caps separados.
- Columna `alerts.strategy_name` para drilldown.
- Dashboard Streamlit: heatmap horizonte × hora, macro panel, calendario económico, drilldown por alerta.

**Phase 3.5:**
- `claude_processor.py`: cliente Claude API con throttle, cache TTL, telemetria de costo, safety cap diario. Soft-fail completo si la key falta o `anthropic` no está instalado.
- Modelo default Haiku 4.5 (~$1/M input, $5/M output).
- `_market_intelligence` llama `expand_pro_analysis` → reasons gana "🤖 IA: ...".
- Fallback "no entendi" en Telegram usa Claude para interpretar preguntas naturales.
- `AlertRecord.ai_reasoning` para storage futuro.
- `ANTHROPIC_API_KEY` enmascarado en `_SECRET_FIELDS` y `LogRedactor`.

Schema: 2 tablas nuevas (`macro_snapshots`, `economic_events`) + columna `alerts.strategy_name`.
Settings: 19 nuevos. Tests: 28 nuevos. Total **163 verdes** (135 → 163).
APP_VERSION bump a v2.2.0.

Regla: sigue siendo read-only. NO order_send a brokers reales ni demo MT5 (Fase 5).
