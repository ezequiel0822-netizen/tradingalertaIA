# Trading Alert AI v2.3.0

Sistema local read-only para monitorear cripto, memecoins y bolsa. Observa datos publicos, guarda historial en SQLite, estima posible subida/caida, revisa riesgo, analiza patrones/noticias/filings SEC, aprende de resultados historicos por horizonte y simula setups en papel.

## Que hace

- Detecta tokens nuevos, boosted y pools trending.
- Analiza volumen, liquidez, precio, patrones, noticias y filings SEC.
- Calcula una lectura IA Pro con setup, sesgo, confianza, riesgos y checklist.
- Guarda snapshots historicos de precio para medir resultado por horizonte (1h, 6h, 24h, 7d).
- Calcula MFE (max favorable excursion) y MAE (max adverse excursion) por alerta.
- Aprende de sus señales pasadas con `signal_outcomes`, `strategy_lessons` y `alert_outcome_horizons`.
- Backtest local de reglas (combinaciones de features) con win rate, retorno medio y sharpe aproximado.
- Crea paper trades simulados para medir preparacion sin operar real.
- Estima subida, caida y confianza.
- Guarda tokens, alertas y seguridad en SQLite.
- Envia Telegram solo con los mejores candidatos.
- Responde comandos basicos por Telegram.
- Escribe memoria diaria y reporte semanal automatico en Obsidian.

## Que NO hace

- No compra ni vende.
- No conecta wallets ni brokers.
- No firma transacciones.
- No ejecuta ordenes.
- No pide seed phrase ni private keys.

## Instalar

```powershell
python -m pip install -r requirements.txt
```

## Configurar `.env`

Copia `.env.example` como referencia y pon los valores reales solo en `.env`.

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
APP_VERSION=v1.7.0
ENABLE_TELEGRAM_ASSISTANT=true
ENABLE_PRO_INTELLIGENCE=true
ENABLE_SEC_FILINGS_INTEL=true
ENABLE_LEARNING_ENGINE=true
ENABLE_PAPER_TRADING=true
ENABLE_OBSIDIAN_MEMORY=true
ENABLE_PRICE_SNAPSHOTS=true
ENABLE_HORIZON_EVALUATOR=true
ENABLE_WEEKLY_OBSIDIAN_REPORT=true
SNAPSHOT_RETENTION_DAYS=30
OBSIDIAN_VAULT_PATH=obsidian/tradingbot v.1
```

No subas `.env` a GitHub.

## Probar Telegram

```powershell
python test_telegram.py
```

## Correr el monitor

```powershell
python main.py
```

Para detenerlo: presiona `Ctrl + C` en la terminal donde esta corriendo.

## Abrir dashboard

```powershell
streamlit run app/dashboard/streamlit_app.py
```

## Comandos Telegram

```text
/help
/status
/cupos
/top
/top_memecoins
/top_stocks
/alertas
/descartes
/aprendizaje
/paper
/entrenar
/horizontes NVDA
/backtest
/backtest 6h ia_pro,score:80-90
/analiza NVDA
/noticias NVDA
/filings NVDA
/patron NVDA
/pro NVDA
/pausar
/reanudar
/config
```

## Control de ruido v1.5.1

- Memecoins: por defecto maximo 5 candidatos enviados por 24h.
- Bolsa: por defecto maximo 5 candidatos enviados por 24h.
- Por ciclo: maximo 2 memecoins y 2 acciones dentro de mensajes agrupados.
- Las memecoins necesitan subida estimada de 500% o mas y confianza minima.
- El filtro anti-hype penaliza boosts/trending con baja liquidez, seguridad unknown o subidas ya exageradas.

## IA Pro

- Indicadores: RSI, medias, MACD, Bollinger, ATR, volumen relativo, soporte y resistencia.
- Catalizadores: titulares de noticias, earnings, revenue, guidance, conferencias, upgrades/downgrades.
- SEC: filings recientes para acciones cuando la SEC tenga datos publicos disponibles.
- Visualizacion rapida: sparkline de precio en Telegram para `/pro`.
- Salida: setup, sesgo, score, confianza, razones, riesgos y checklist manual.

## Learning Engine v1.5.2

- Evalua señales anteriores contra el precio actual guardado.
- Clasifica outcomes como `win`, `neutral` o `loss`.
- Extrae features: IA Pro, patrones, noticias, filings, volumen, liquidez, riesgo y anti-hype.
- Genera lecciones locales por feature y categoria.
- Abre paper trades simulados solo para setups A/B.
- Nunca envia ordenes reales.

## Aprendizaje por horizonte v1.6.0

- Captura `price_snapshots` historicos en cada ciclo (chain + token + precio + volumen + liquidez + timestamp).
- Evalua cada alerta a horizontes fijos: 1h, 6h, 24h y 7d. Una fila por alerta x horizonte en `alert_outcome_horizons`.
- Calcula `return_pct`, MFE (max favorable excursion) y MAE (max adverse excursion) por ventana.
- Backtester local con dos modos:
  - `rank_top_strategies(horizon)` enumera combinaciones (features individuales + pares predefinidos) y devuelve top reglas por sharpe aproximado.
  - `backtest_strategy(features, horizon)` mide una combinacion AND de features.
- Dashboard Streamlit muestra promedios MFE/MAE por categoria x horizonte, equity curve simulada y ranking de reglas.
- Reporte semanal automatico en Obsidian (`11 - Reporte Semanal.md`).
- Comandos Telegram nuevos: `/horizontes SYMBOL` y `/backtest [Nh] [features...]`.

Notas importantes:

- Las alertas anteriores a v1.6.0 no tienen snapshots historicos. Sus outcomes por horizonte quedaran como `insufficient_data` hasta que se acumulen snapshots.
- El horizonte 7d necesita 7 dias reales de datos para entregar resultados finales.
- Retencion por defecto: 30 dias de snapshots. Ajustable con `SNAPSHOT_RETENTION_DAYS`.
- Sigue siendo simulacion: NO compra, NO vende, NO conecta brokers.

## Paper trading mejorado v1.7.0

- Cada paper trade ahora trackea **MFE/MAE durante toda la vida del trade** (no solo al cerrar).
- **Trailing stops simulados**: cuando una posicion supera el umbral de activacion (5% stock, 50% memecoin por default), el stop se eleva siguiendo el precio. Nunca baja.
- **SL/TP por ATR**: cuando hay OHLCV disponible, los stop y targets se calculan con el ATR del activo en lugar de % fijos (multiplicador 2x stop, 2x/4x targets), clampeados al rango seguro por categoria.

## Pesos aprendidos y learning gate v1.7.0 (OFF por default, opt-in)

- **Pesos aprendidos** (`ENABLE_LEARNED_WEIGHTS=true`): el score base se ajusta con las `strategy_lessons`. Cada feature ganadora con suficiente confianza suma puntos al score; cada feature perdedora resta. Clamp duro a ±10 puntos para evitar dominio. Las razones del ajuste se muestran en las reasons de la alerta.
- **Learning gate** (`ENABLE_LEARNING_GATE=true`): antes de mandar una alerta a Telegram, el bot consulta al backtester historico (`category + alert + score buckets`, horizonte 24h, ultimos 30 dias). Si el win_rate esta por debajo del umbral (45% por default) y hay al menos 10 muestras, la alerta se descarta y queda registrada con `sent_to_telegram=0` (visible en `/descartes`).

Ambos features estan **OFF por default**. Activar despues de revisar `/aprendizaje` y `/backtest` con varios dias de data acumulada.

## Forex y oro v1.7.0 (acumula data, no genera alertas todavia)

- Nuevo collector `app/collectors/forex_collector.py` que trae OHLCV via Yahoo Finance para:
  - Forex majors: `EURUSD=X, GBPUSD=X, USDJPY=X, USDCHF=X, AUDUSD=X, USDCAD=X, NZDUSD=X`.
  - Oro: `GC=F` (futuros) y `XAUUSD=X` (spot).
- Las categorias `forex` y `gold` fluyen por `price_snapshots` y `alert_outcome_horizons` para que el motor acumule patrones, pero **no generan alertas Telegram en Fase 2**.
- Fase 3 construira el modulo de analisis forex-especifico (price action, S/R, sesiones Londres/NY, calendario economico).

## Trader Engine v2.0.0 (Fase 2.5)

El bot ahora opera como **trader engine autonomo simulado**. Sigue read-only: no manda ordenes a brokers reales ni a demo MT5 (eso es Fase 5). Lo que SI hace:

- **Strategy router** con 4 estrategias nombradas (breakout, mean_reversion, momentum, news_catalyst). Cada una con sus reglas de entry/exit; la primera que firma con confidence >= `STRATEGY_MIN_CONFIDENCE` abre paper_trade.
- **Portfolio Manager**: track de posiciones abiertas, exposicion por categoria, P&L diario, equity curve.
- **Risk Manager**: kill-switch (manual con `/halt` o automatico por max drawdown diario), max trades concurrentes (5 total / 3 stock / 4 forex / 2 gold por default), max riesgo agregado de cuenta (6% por default).
- **Position Sizer**: tamano calculado por `(balance × risk_pct) / |entry - stop|`. Risk per trade default 1%.
- **Trade Lifecycle**: maneja posiciones vivas - actualiza MFE/MAE, mueve trailing stop, cierra por time horizon, hace partial close al TP1 con stop a breakeven.
- **MT5 Reader** (read-only, opcional): si tenes MetaTrader 5 con cuenta demo y completas `MT5_LOGIN/PASSWORD/SERVER` en `.env`, el bot usa precios reales de MT5 para gestionar posiciones forex/oro. Si MT5 no esta instalado, el bot sigue corriendo con yfinance (soft-fail).
- **Reportes Telegram automaticos**: el bot avisa cuando abre o cierra un trade ("🟢 Abri long EURUSD (breakout, conf 78)...").
- **Comandos Telegram nuevos**: `/portfolio`, `/posiciones`, `/halt [horas]`, `/resume_trading`, `/strategies`.
- **Memecoins en modo lab**: siguen alimentando `strategy_lessons` y outcomes por horizonte, pero NO van a Telegram ni se operan. Activar con `ENABLE_MEMECOIN_TELEGRAM=true` si queres recibir alertas memecoin como en v1.7.0.

Restriccion absoluta de seguridad: **sin order_send a brokers reales ni demo todavia**. Real money trading sigue prohibido sin nueva autorizacion explicita.

## Carpetas

- `app/collectors`: datos publicos.
- `app/analyzers`: score, riesgo, patrones, noticias y estimacion.
- `app/alerts`: formato y envio Telegram.
- `app/database`: SQLite y repositorio.
- `app/scheduler`: ciclo principal.
- `app/dashboard`: Streamlit.
- `app/assistant`: respuestas por Telegram.
- `obsidian/tradingbot v.1`: memoria del proyecto.
- `tests`: pruebas basicas.

## Advertencia

No es recomendacion financiera. El sistema solo ayuda a filtrar candidatos para revision manual.
