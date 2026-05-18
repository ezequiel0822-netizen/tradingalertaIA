# Changelog

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
