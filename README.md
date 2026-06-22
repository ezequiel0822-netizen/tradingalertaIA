# Trading Alert AI v3.9.3

Trader engine algoritmico **local** (Python 3.12, Windows) enfocado **100% a LA BOLSA** (acciones US + forex + oro). Observa datos publicos, guarda historial en SQLite, decide entradas/salidas con un strategy router swing, opera paper trades simulados, aprende del P&L realizado neto de costos, y puede enviar ordenes **solo a cuenta MT5 demo** (con confirmacion manual o auto-confirmacion opt-in).

**Real-money trading sigue bloqueado por design.** `enable_real_trading` es `False` HARDCODED en `settings.py` (ya no se lee del env), y la barrera real es `_is_demo_account()` en `mt5_demo_trader.py` (rechaza cualquier cuenta no-demo). El sistema no es recomendacion financiera: filtra candidatos, simula y aprende para revision manual.

## Estado actual (v3.9.3, jun-2026)

- **697 tests verdes.** Corriendo en la Lenovo contra MT5 demo via `.\start_bot.ps1`.
- **REFOCUS v3.7.0 — 100% LA BOLSA.** Las **memecoins se cortaron** (`ENABLE_MEMECOIN_ENGINE=false`; el user tiene un bot aparte) y el **scalping se apago**. Acciones son paper-only; solo forex/oro ejecutan a MT5 demo.
- **Protecciones vivas (todas downward-only, solo bajan a paper):** calendar gate, cap de exposicion neta USD, cooldown por simbolo, exit shadow (registrando), **regime gate** (`ENABLE_REGIME_GATE`) y **COT collector** (`ENABLE_COT_COLLECTOR`, + backfill de 5 años / 2340 filas en `cot_snapshots`).
- **NO hay edge probado** — confirmado por multiples vias independientes (backtest D1, diagnostico vivo = regimen, ML AUC 0.533, CV temporal 0.475 OOS, walk-forward por slice). El gate de data de Fase D se cruzo (403/400) pero NO destrabo edge.
- **Experimento de COT (2026-06-21, `scripts/cot_ml_experiment.py`):** se derivaron features de COT sobre los 5 anios de historia y se re-corrio el test temporal del ML. Veredicto: **sin senial accionable** (test primario TimeSeriesSplit OOS 0.533 < 0.55; corte FX/oro 0.585→0.607 pero dentro del ruido en n=178 sobre ~1 mes). `ENABLE_ML_PREDICTOR` sigue OFF; re-correr el script cuando el COT acumule mas meses.
- Lo mas valioso ahora: **dejar correr el libro vivo + que el COT acumule** (es lo que destraba el proximo experimento real). El edge se DESCUBRE (informacion nueva), no se inyecta.

## Que hace

- Detecta tokens nuevos, boosted y pools trending (DEX Screener + GeckoTerminal + GoPlus).
- Monitorea acciones US (Yahoo), forex majors y oro (Yahoo + MT5).
- Analiza volumen, liquidez, precio, patrones, noticias y filings SEC.
- Calcula una lectura IA Pro con setup, sesgo, confianza, riesgos y checklist.
- LLM opcional para enriquecer texto (resumen de noticias, explicacion de setups, free-text en Telegram): Claude API o **Ollama local gratis** (`ENABLE_OLLAMA_INTEGRATION`). Solo texto, NO decide trades.
- Decide con un strategy router: breakout, mean_reversion, momentum, news_catalyst, forex_session_breakout (swing) + scalping_breakout y scalping_mean_reversion (scalping en thread aparte).
- Dimensiona posiciones por riesgo (`balance x risk% / |entry - stop|`) y gestiona el ciclo de vida (trailing stop, SL a breakeven post-TP1, partial close, salida por tiempo).
- Risk manager con kill-switch (manual o automatico por max drawdown diario), caps por categoria y cooldown por simbolo.
- **Backtest Replay Harness (v3.6.0, offline)**: reproduce la historia D1 de MT5 barra por barra con las estrategias REALES y mide R neto de costos con pesimismo (anti look-ahead), en tablas `backtest_*` separadas. NO toca el ciclo vivo, NO cuenta para `/readiness` ni para la Fase D. Opt-in (`ENABLE_BACKTEST_HARNESS=false`). CLI: `python -m app.backtest.replay_harness --config <run.json> --report`.
- Guarda snapshots historicos de precio y mide resultado por horizonte (1h, 6h, 24h, 7d) con MFE/MAE.
- Aprende del **P&L realizado en R-multiples, neto de costos** (spread + comision), no de una metrica de drift ficticia.
- Promotion gate: no ejecuta a MT5 las estrategias con edge negativo probado (quedan paper-only / SHADOW).
- Edge detection: slicea la expectancy realizada por sesion y direccion para cazar bolsillos de edge (comando `/edge`).
- Capa ML hibrida (XGBoost, opt-in): predice prob. de win y modula el gate como señal adicional, solo hacia abajo (comando `/ml_status`).
- Reconciler MT5: cierra posiciones demo huerfanas y sincroniza SL (solo tightening).
- Envia Telegram solo con los mejores candidatos y responde 40+ comandos.
- Escribe memoria diaria y reporte semanal automatico en Obsidian.
- Prepara y ejecuta ordenes demo MT5 con SL/TP obligatorio.

## Que NO hace

- **No opera con dinero real.** `ENABLE_REAL_TRADING=false` esta hardcoded; ningun flag lo destraba.
- El unico `order_send` permitido es a **cuenta MT5 demo** (`mt5_demo_trader` es el unico modulo que lo llama).
- No conecta wallets cripto ni firma transacciones on-chain.
- No compra/vende memecoins ni acciones: cripto y acciones son solo analisis + paper trading (no hay broker para ellas; solo forex/oro llegan a MT5 demo).
- No pide seed phrase ni private keys.

## Instalar

```powershell
python -m pip install -r requirements.txt
```

Opcional para forex/oro y demo trading: `MetaTrader5` (Windows) con una cuenta demo. Soft-fail si no esta instalado: el bot sigue corriendo con yfinance.

## Configurar `.env`

Copia `.env.example` como referencia y pon los valores reales solo en `.env`. Variables clave (la lista completa esta en `.env.example`):

```env
# Obligatorias
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
# APP_VERSION: NO pinear (el default vive en settings.py = v3.9.3). Si se pinea, pisa al codigo.

# MT5 (read + demo). Credenciales reales SOLO en tu .env.
ENABLE_MT5_READER=true
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
MT5_BROKER_PROFILE=icmarkets

# Ubicacion de la DB. Mantenela FUERA de iCloud/OneDrive: la contencion de I/O
# de la sync ralentiza el bot y los tests, y puede corromper el archivo.
# Default: trading_alert_ai.db (raiz del proyecto).
SQLITE_PATH=C:/ruta/local/trading_data/trading_alert_ai.db

# Demo trading (solo cuenta demo). Real-money sigue bloqueado.
ENABLE_MT5_DEMO_TRADING=false
DEMO_ORDER_REQUIRE_CONFIRMATION=true
ENABLE_AUTO_CONFIRM_DEMO=false
ENABLE_REAL_TRADING=false
DEMO_ALLOWED_SYMBOLS=EURUSD,XAUUSD

# Scalping engine (thread dedicado, opt-in) — APAGADO en el refocus
ENABLE_SCALPING_ENGINE=false
SCALPING_ALLOWED_SYMBOLS=EURUSD,GBPUSD

# Refocus v3.7.0: 100% LA BOLSA (memecoins cortadas, stock alerts on)
ENABLE_MEMECOIN_ENGINE=false
ENABLE_STOCK_TELEGRAM=true

# Protecciones v3.5.0/v3.8.0 (downward-only, opt-in) + COT collector v3.9.0
ENABLE_CALENDAR_GATE=true
ENABLE_USD_EXPOSURE_CAP=true
STRATEGY_SYMBOL_COOLDOWN_MINUTES=60
ENABLE_EXIT_SHADOW=true
ENABLE_REGIME_GATE=true
ENABLE_COT_COLLECTOR=true

# Aprendizaje honesto v2.7.0 (defaults ON)
ENABLE_STRATEGY_PROMOTION_GATE=true
STRATEGY_PROMOTION_MIN_SAMPLES=30
STRATEGY_PROMOTION_MIN_EXPECTANCY_R=0.0
ENABLE_COST_MODEL=true
ENABLE_REALIZED_LEARNING=true

# Edge detection v2.8.0 (medicion ON; gate sliceado opt-in OFF)
ENABLE_EDGE_SLICING=true
EDGE_SLICE_MIN_SAMPLES=30
ENABLE_SLICED_PROMOTION_GATE=false

# Capa ML hibrida v2.9.0 (OFF por default; dormida hasta ML_GATE_MIN_SAMPLES)
ENABLE_ML_PREDICTOR=false
ML_MIN_TRAIN_SAMPLES=100
ML_GATE_MIN_SAMPLES=400

# Pesos aprendidos / learning gate (OFF por default; activar con data acumulada)
ENABLE_LEARNED_WEIGHTS=false
ENABLE_LEARNING_GATE=false

OBSIDIAN_VAULT_PATH=obsidian/tradingbot v.1
```

No subas `.env` a GitHub.

## Probar Telegram

```powershell
python test_telegram.py
```

## Correr el monitor

```powershell
python main.py                      # loop continuo
python main.py --once               # un solo ciclo y sale
python main.py --mode alerts_only   # override de modo para esta corrida
```

- `--mode`: `trader` | `alerts_only` | `hybrid`. Prioridad: CLI > `/mode` persistido en Telegram > `.env BOT_MODE` > default `trader`.
- Si `ENABLE_SCALPING_ENGINE=true`, `main.py` arranca el scalping engine en un thread separado y lo cierra limpio con `Ctrl + C`.
- Arranca SIEMPRE desde la carpeta del proyecto (donde esta el `.env`), si no, no encuentra `SQLITE_PATH`.

## Abrir dashboard

```powershell
streamlit run app/dashboard/streamlit_app.py
```

## Comandos Telegram

```text
# Estado e info
/help            /status          /health          /cupos
/top             /top_memecoins   /top_stocks
/alertas         /descartes       /paper           /config

# Analisis por simbolo
/analiza NVDA    /noticias NVDA   /filings NVDA    /patron NVDA    /pro NVDA

# Trader engine
/portfolio       /posiciones      /strategies
/halt [horas]    /resume_trading  /pausar          /reanudar       /mode

# Aprendizaje
/aprendizaje     /entrenar        /expectancy      /edge            /gate_preview
/horizontes NVDA /backtest [Nh] [features...]      /walk_forward STRATEGY    /ml_status

# MT5 demo
/mt5_status      /demo_candidates /demo_prepare ID /confirm_demo_trade ID
/demo_positions  /demo_close_all  /demo_halt

# Scalping
/scalping_on     /scalping_off    /scalping_status
/scalping_halt   /scalping_resume /scalping_stats

# Datos
/data_quality    /export_csv [outcomes|trades|horizons|walk_forward]
```

## IA Pro

- Indicadores: RSI, medias, MACD, Bollinger, ATR, volumen relativo, soporte y resistencia.
- Catalizadores: titulares de noticias, earnings, revenue, guidance, conferencias, upgrades/downgrades.
- SEC: filings recientes para acciones cuando hay datos publicos.
- Salida: setup, sesgo, score, confianza, razones, riesgos y checklist manual.

## Learning Engine

- Evalua señales pasadas contra el precio guardado y clasifica outcomes (win/neutral/loss).
- Extrae features (IA Pro, patrones, noticias, filings, volumen, liquidez, riesgo, anti-hype) y genera lecciones por feature.
- Aprendizaje por horizonte: snapshots historicos cada ciclo, evaluacion a 1h/6h/24h/7d con `return_pct`, MFE y MAE.
- Backtester local: `rank_top_strategies(horizon)` y `backtest_strategy(features, horizon)` con win rate y sharpe aproximado.
- Walk-forward out-of-sample para detectar curve-fitting.
- Reporte semanal automatico en Obsidian.

## Paper trading

- Cada paper trade trackea MFE/MAE durante toda su vida.
- Trailing stops simulados (suben con el precio, nunca bajan) y SL/TP por ATR cuando hay OHLCV (stop 2x, targets 2x/4x), clampeados por categoria.
- Partial close al TP1 con stop a breakeven.

## Pesos aprendidos y learning gate (OFF por default)

- **Pesos aprendidos** (`ENABLE_LEARNED_WEIGHTS=true`): ajustan el score base con las lecciones aprendidas (clamp +-10 puntos).
- **Learning gate** (`ENABLE_LEARNING_GATE=true`): descarta alertas con win_rate historico bajo antes de mandarlas a Telegram.
- Desde v2.7.0, con `ENABLE_REALIZED_LEARNING=true` ambos consultan el **P&L realizado** (tabla `realized_feature_lessons`), no el drift. Usa `/gate_preview` para ver que bloquearia el gate antes de activarlo.

## Forex y oro

- `app/collectors/forex_collector.py` trae OHLCV via Yahoo para majors (`EURUSD=X`, `GBPUSD=X`, ...) y oro (`GC=F`, `XAUUSD=X`).
- La estrategia `forex_session_breakout` opera sesiones Londres/NY con calendario economico como filtro.
- Symbol map Yahoo<->MT5 por broker profile (`mt5_symbol_map.py`): `EURUSD=X`->`EURUSD`, `GC=F`->`XAUUSD`, etc.

## Trader Engine v2.0.0

- **Strategy router** con 5 estrategias swing nombradas; la primera que firma con confianza >= `STRATEGY_MIN_CONFIDENCE` abre paper trade.
- **Portfolio Manager**: posiciones abiertas, exposicion por categoria, P&L diario, equity curve.
- **Risk Manager**: kill-switch (manual `/halt` o automatico por max drawdown), caps por categoria, riesgo agregado, cooldown por simbolo.
- **Position Sizer**: `(balance x risk_pct) / |entry - stop|`.
- **MT5 Reader** (read-only): precios reales de MT5 para gestionar posiciones forex/oro; soft-fail a yfinance si MT5 no esta.
- **Reportes Telegram** automaticos al abrir/cerrar trades.
- Memecoins **CORTADAS** desde el refocus v3.7.0 (`ENABLE_MEMECOIN_ENGINE=false`): el ciclo ni las colecta (el user tiene un bot aparte). El motor sigue en el código por si se reactiva.

## MT5 demo orders (Phase 5, v2.5.x)

`order_send` solo contra cuenta **MT5 demo**, solo forex/oro (`DEMO_ALLOWED_SYMBOLS`), con SL y TP obligatorios y lotaje conservador (`DEMO_MAX_LOT`).

- Flujo manual: `/demo_candidates` -> `/demo_prepare ID` -> `/confirm_demo_trade ID`.
- Auto-confirm opt-in (`ENABLE_AUTO_CONFIRM_DEMO=true`, v2.5.4): ejecuta sin pedir confirmacion por Telegram.
- Emergencia: `/demo_halt` bloquea nuevas ordenes demo; `/resume_trading` libera; `/demo_close_all` cierra todas.

## Scalping Engine (Phase 5.5, v2.6.0 / v2.6.6)

- Thread dedicado que polea MT5 cada `SCALPING_POLL_INTERVAL_SECONDS` sobre velas M1.
- Dos estrategias: `scalping_breakout` (range breakout) y `scalping_mean_reversion` (Bollinger + RSI counter-trend). Caps, force-exit y kill-switch independientes del swing engine.
- Auto-ejecuta a MT5 demo reusando las validaciones demo-only. Real-money sigue bloqueado.
- Comandos `/scalping_*` y macros de `/mode` (`swing_only`, `scalping_only`, `hybrid`).

## MT5 Position Reconciler (v2.6.7)

Cada ciclo, despues del lifecycle, el reconciler:

- Cierra posiciones MT5 demo huerfanas (cuyo paper_trade ya cerro).
- Sincroniza el SL cuando el bot lo movio (trailing / breakeven), **solo tightening, nunca loosen**.
- Soft-fail por posicion; ignora trades manuales del usuario.

Resuelve el gap historico entre el P&L de paper trades y el balance MT5 real.

## Aprendizaje honesto y proteccion de capital (v2.7.0)

- **Realized-R**: `app/learning/trade_outcomes.py` mide retorno realizado direction-aware (con partial close), riesgo al entry y R-multiple. Excluye artifacts (trades con precio congelado). Tabla `strategy_performance` por (estrategia, categoria), refrescada cada ciclo. Ver con `/expectancy`.
- **Cost model**: resta un costo round-trip por categoria (`COST_ROUNDTRIP_PCT_*`) del retorno de cada trade, asi el R es neto y el gate es confiable.
- **Promotion gate** (`should_execute_live`): una estrategia no manda `order_send` si tiene expectancy realizada negativa **probada** (`avg_r <= umbral` con `n >= min_samples`). "Inocente hasta probarse culpable": las no probadas juntan data (LIVE), las que demostraron edge negativo quedan paper-only (SHADOW). Es estrictamente subtractivo: solo previene un order_send, nunca lo causa.

Contexto honesto: hoy toda estrategia da R negativo neto; el bot mide la verdad y protege capital, pero el edge es trabajo de data + research pendiente.

## Fix kill switch falso (v2.7.1)

`realized_pnl_today` ahora filtra paper trades que nunca se ejecutaron a MT5 (`has_successful_demo_order`). Tapa un kill-switch falso: trades gold paper-only con `symbol=GC=F` (que no matchea `DEMO_ALLOWED_SYMBOLS`) inflaban el drawdown con su sizing teorico sin haber tocado el balance real. Ahora el calculo representa el impacto USD real en el balance MT5 demo.

## Edge Detection & Protection Layer (v2.8.0)

Automatiza la busqueda de edge por slice y extiende el promotion gate a ese nivel. NO crea edge: construye la maquinaria que lo detecta de forma permanente y protege capital cuando un slice prueba perder.

- **Medicion sliceada** (`ENABLE_EDGE_SLICING=true`, no toca ejecucion): la tabla `strategy_performance_sliced` mide la expectancy realizada en R por **sesion** (Asia/London/LDN-NY/NY/Off, hora UTC) y por **direccion** (long/short), refrescada cada ciclo. Reusa el mismo realized-R neto de costos que `/expectancy`, asi cuadra al re-agregar. Visible con **`/edge`**: marca `[OK]` los slices con muestra suficiente (`EDGE_SLICE_MIN_SAMPLES`, default 30) y resalta los que ademas son +R.
- **Gate sliceado** (`ENABLE_SLICED_PROMOTION_GATE=false`, opt-in): el promotion gate manda a SHADOW tambien por slice (la sesion y direccion del trade en curso), no solo por estrategia.
- **Regla anti-data-dredging**: el slicing SOLO puede mover a SHADOW, nunca promover. Un slice +R jamas rescata a un agregado SHADOW. Cortar en muchos slices garantiza algun +R por azar (multiple comparisons); por eso se usa solo para hallar perdedores (conservador), no ganadores. El gate sigue siendo estrictamente subtractivo.

Contexto honesto: el research que motivo esto (slicing de los 189 trades reales) no encontro ningun bolsillo +R solido todavia (los positivos tienen n=4-17, ruido). El cuello de botella sigue siendo muestra limpia; esta capa hace que, cuando un bolsillo cruce el umbral, lo veas con rigor en vez de adivinarlo.

## Capa ML hibrida — XGBoost (v2.9.0)

Capa de Machine Learning que COMPLEMENTA las reglas (no las reemplaza): predice la probabilidad de win de un trade y modula el promotion gate como señal adicional. Misma filosofia que el gate: solo filtra HACIA ABAJO, nunca habilita lo que las reglas bloquearon. Nace DORMIDA y segura.

- **Dataset** (`app/learning/ml_dataset_builder.py`): cada trade cerrado no-artifact con features al entry (macro vix/dxy, sesion/hora/dia, estrategia/categoria, features del alert) + outcome win/loss. Reusa la quarantine y el realized-R de v2.7.0. Exporta `exports/ml_dataset.csv`.
- **Predictor** (`app/learning/ml_predictor.py`): `MLPredictor` con XGBClassifier (max_depth=5, lr=0.1, n_estimators=100, subsample=0.8). Validacion temporal sin look-ahead, AUC en test, persistencia en `models/xgboost_v1.pkl`, reentrenamiento diario (revierte si el AUC cae >0.05).
- **Integracion**: con `ENABLE_ML_PREDICTOR=true` y muestra suficiente (`ML_GATE_MIN_SAMPLES`, default 400), el gate consulta la confianza: >0.65 pasa; 0.50-0.65 pasa con lot a la mitad; <0.50 queda paper-only. Comando **`/ml_status`**.
- **Salvaguardas (no romper nada)**: master switch OFF por default; modo degradado (sin modelo, <100 muestras, o xgboost ausente) devuelve 0.5 neutral y el sistema se comporta EXACTAMENTE igual que antes; el ML jamas causa un order_send, solo puede prevenirlo.

Encuadre honesto: el ML esta **DORMIDO** y `ENABLE_ML_PREDICTOR` sigue OFF — no toca ninguna decision. No crea edge; es andamiaje. **Actualizado (v3.x):** `rsi`/`atr` al entry SI se persisten desde v2.11.0; el gate de data de Fase D se cruzo (403/400), pero el ML sobre los features actuales NO mostro senial forward (CV temporal AUC 0.475 OOS) y el experimento de COT del 21-jun tampoco la levanto sobre la barra (`scripts/cot_ml_experiment.py`, ver "Estado actual"). Se re-evalua cuando el COT acumule mas meses. Requiere `xgboost` + `scikit-learn`.

## Base de datos

SQLite en `SQLITE_PATH` (default `trading_alert_ai.db` en la raiz). Mantenela en un disco local fuera de iCloud/OneDrive: la sync genera contencion de I/O que ralentiza el bot y los tests y arriesga corrupcion. El schema se crea/migra solo via `_ensure_column` (backward-compat).

## Carpetas

- `app/collectors`: datos publicos (DEX, GeckoTerminal, GoPlus, Yahoo, SEC, macro, calendario).
- `app/analyzers`: score, riesgo, patrones, noticias, IA Pro, memecoin hunter, learning gate.
- `app/strategies`: estrategias swing + scalping + router.
- `app/learning`: outcomes, horizontes, lifecycle, training engine, backtester, walk-forward.
- `app/risk` + `app/portfolio`: sizing, risk manager, portfolio, reconciler MT5.
- `app/brokers`: MT5 reader (read-only), demo trader (unico con order_send), symbol map, historico.
- `app/scheduler`: ciclo swing (`jobs.py`) + scalping engine.
- `app/alerts` + `app/assistant`: formato/envio Telegram y comandos.
- `app/dashboard`: Streamlit.
- `app/intelligence` + `app/config` + `app/utils`: Claude/macro/calidad, settings, utilidades.
- `obsidian/tradingbot v.1`: memoria del proyecto.
- `scripts`: herramientas manuales de research (`cot_backfill.py`, `cot_ml_experiment.py`).
- `tests`: 697 tests.

## Tests

```powershell
python -m pytest tests/ -q     # 697 verdes
```

## Advertencia

No es recomendacion financiera. El sistema solo ayuda a filtrar candidatos para revision manual. Real-money trading esta bloqueado por design.
