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
