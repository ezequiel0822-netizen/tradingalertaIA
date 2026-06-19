# CONTEXTO MAESTRO — Trading Alert AI v3.8.0 (+ addendum v3.9.0–v3.9.1 al final)

> Referencia de arquitectura/schema **vigente** (reemplaza a `CONTEXTO_MAESTRO_v3.6.0.md`,
> que queda como base histórica). Local, Python 3.12, Windows + PowerShell + venv.
> Para el roadmap y las reglas de cómo construir: `PROXIMOS_PASOS.md`. Para la historia
> versión por versión: `CHANGELOG.md`. Para retomar en otra máquina: `HANDOFF.md`.
> Para el camino a real-money: `GO_LIVE_RUNBOOK.md`. Todo-en-uno: `RESUMEN_COMPLETO.md`.
> Backtest: `ESPEC_BACKTEST_REPLAY_v1.md` (forex) + `ESPEC_BACKTEST_STOCKS_v1.md` (acciones)
> + `MAPA_DE_EDGE_Y_RUTA.md` (la ruta de edge — el porqué).

---

## 1. Qué es

Bot de trading algorítmico **local y gratis**. **REFOCUS v3.7.0: 100% LA BOLSA** (acciones
US + forex + oro). Las **memecoins se cortaron** (`ENABLE_MEMECOIN_ENGINE=false`; el user
tiene un bot aparte) y el **scalping se apagó**. Decide con un **strategy router** (swing),
hace **paper trades** y manda órdenes a **MT5 demo** (MetaQuotes-Demo; solo forex/oro
ejecutan, acciones son paper). Una **capa de IA local** (Ollama, opcional) asesora, vetea
y aprende — siempre **subtractiva**. Real-money **BLOQUEADO por diseño**. Trae además un
**Backtest Replay Harness** OFFLINE (`app/backtest/`) que mide hipótesis sobre la historia
D1 (forex y acciones) sin tocar el ciclo vivo.

## 2. Reglas inamovibles (seguridad)

- `ENABLE_REAL_TRADING=false` **HARDCODED**. Real-money prohibido sin autorización nueva,
  explícita y deliberada del user, y solo con edge probado + reconfiguración de sizing.
- `order_send` **SOLO** en `app/brokers/mt5_demo_trader.py`. No tocar `mt5_demo_trader.py`
  ni `mt5_reconciler.py`. Ningún módulo nuevo lo llama directo.
- **LLM y ML son SUBTRACTIVOS:** solo vetan / bajan a paper / registran / proponen. JAMÁS
  fuerzan ni habilitan una orden.
- **Los gates vivos (calendar, cap USD, regime) son DOWNWARD-ONLY:** solo degradan a paper,
  jamás fuerzan. Opt-in OFF + soft-fail.
- **Todo lo nuevo es opt-in OFF + soft-fail:** apagado o roto = el bot corre idéntico.
- **NO inventar "edge artificial"** (optimizar parámetros hasta que el backtest brille =
  curve-fitting = se funde en real). El edge se DESCUBRE (data + research, validado fuera de
  muestra), no se inyecta. El user lo pidió; la respuesta es esta.
- **Backtest harness (`app/backtest/`):** OFFLINE; escribe SOLO en `backtest_*`; NO importa
  `mt5_demo_trader`/`reconciler`; NO toca el ciclo vivo; NO cuenta para `/readiness`,
  `/expectancy`, `/edge` ni los 400 de Fase D. Abre la puerta de **PAPER**, nunca la de MT5;
  prohibido ajustar una hipótesis hasta que pase.
- Nunca leer/mostrar el `.env` real ni secrets. **Mantener pytest verde (hoy 676).**
- Al tocar `Settings`: sincronizar `tests/test_score._settings()` Y `tests/test_alert_rules._settings()`.
- **Auditoría de seguridad (2026-06-11): limpia.** Telegram por chat_id exacto; `.env` jamás
  commiteado; `LogRedactor`; SQL parametrizado; sin eval/exec/shell=True; timeouts en la red.

## 3. Arquitectura por capas (módulos reales)

| Capa | Módulos | Rol |
|---|---|---|
| **Colectores** | `app/collectors/*` (forex, stock, macro, news, sec, economic_calendar; dexscreener/geckoterminal/goplus = memecoins, **gateados por `ENABLE_MEMECOIN_ENGINE`**) | Traen data cruda |
| **Analizadores** | `app/analyzers/*` (token_score, technical_patterns, learned_weights, learning_gate, risk_analyzer, pro_intelligence, ...) | Puntúan, deciden alertar, aprenden |
| **Estrategias** | `app/strategies/*` — swing: `breakout`, `forex_session_breakout`, `mean_reversion`, `momentum`, `news_catalyst`; scalping (APAGADO en vivo); `trend_following_d1` (Donchian D1 — SOLO backtest); `strategy_router` | Eligen el candidato |
| **Riesgo** | `app/risk/` — `risk_manager`, `position_sizer` (~$100k), `exposure` (v3.5.0, neto USD) | Gate de riesgo + tamaño + correlación |
| **Brokers** | `app/brokers/` — `mt5_demo_trader` (ÚNICO order_send), `mt5_reader`, `mt5_symbol_map`, `mt5_historical` | Ejecución demo + lectura MT5 |
| **Portfolio** | `app/portfolio/` — `portfolio_manager`, `mt5_reconciler`, `performance` (v3.3.0) | Cuenta + reconciliación + medición |
| **IA local** | `app/intelligence/` — `ollama_processor`, `reasoner`, `ensemble_gate`, `macro_context`, **`regime_filter` (v3.6.0; clasificador puro, lo usa el harness Y el regime gate vivo)** | Asesora / vetea + régimen |
| **Aprendizaje** | `app/learning/` — `trade_outcomes`, `training_engine`, `ml_predictor`, `lifecycle_manager`, `walk_forward`, `continuous_learner` | Mide P&L honesto, entrena, aprende |
| **Backtest (OFFLINE)** | `app/backtest/` — `historical_loader` (forex MT5), **`stock_historical_loader` (v3.9.0, acciones Yahoo D1 ajustado)**, `context_builder`, `trade_simulator`, `replay_harness`, `report` | Reproduce la historia con estrategias REALES. NO corre en el ciclo vivo |
| **Scheduler** | `app/scheduler/` — `jobs` (`run_once`, los gates vivos), `scalping_engine` (off) | Loop principal |
| **Asistente** | `app/assistant/command_handler`, `telegram_assistant`; `app/alerts/telegram_notifier` | Comandos Telegram + envío |
| **Infra** | `app/database/` (`db`, `repository`), `app/config/settings`, `app/utils/*`; `preflight.py` (raíz, no commiteado) | Persistencia, settings, helpers, chequeo de arranque |

## 4. Pipeline (`jobs.run_once`, simplificado)

1. Colectar → analizar → puntuar → decidir alertas → enviar (ranked). **Memecoins: solo si
   `ENABLE_MEMECOIN_ENGINE=true` (hoy false → ni se colectan).**
2. Abrir paper_trades (swing). Al abrir swing live se persisten `rsi_entry`/`atr_value`/`macd_*`.
3. **Gate de promoción** antes del `order_send` a demo (todos DOWNWARD-ONLY): reglas
   (`should_execute_live`) → ML gate → ensemble LLM veto → calendar gate (v3.5.0) → cap de
   exposición USD (v3.5.0) → **regime gate (v3.8.0): contra-tendencia → paper-only**.
4. `lifecycle_manager.manage_open_positions` → `mt5_reconciler.reconcile`.
5. Learning cycle (refresca `strategy_performance` + sliced + lessons) → retrain ML diario.
6. Resumen diario → ContinuousLearner → exit shadow (solo registro).

> **El harness NO está en este pipeline.** Es CLI offline aparte (`python -m
> app.backtest.replay_harness --config <run.json> --report`).

## 5. Schema de DB (SQLite, tablas reales)

Vivas: `tokens`, `alerts`, `signal_outcomes`, `alert_outcome_horizons`, `paper_trades`
(+ features al entry), `demo_orders`, `demo_trade_requests`, `strategy_lessons`,
`realized_feature_lessons`, `strategy_performance`, `strategy_performance_sliced` (slicing
por sesión/dirección — la fuente del DIAGNÓSTICO de §8), `training_runs`, `walk_forward_results`,
`price_snapshots`, `macro_snapshots` (VIX/DXY/regime), `economic_events`, `mt5_historical_cache`
(D1/H1 de forex Y D1 de acciones), `data_quality_log`, `security_checks`, `daily_pnl_log`,
`bot_state`, `trade_lessons` (v3.2.0), `trade_r_samples` (v3.4.0).
Backtest (OFFLINE, cero FK a tablas vivas): **`backtest_runs` / `backtest_trades` /
`backtest_walkforward`** (v3.6.0). NO cuentan para nada vivo.

## 6. Las capas de IA (subtractivas, opt-in OFF)

LLM local (`ENABLE_OLLAMA_INTEGRATION`) · asesor `TradingReasoner` (`ENABLE_LLM_ADVISOR`,
solo texto) · ensemble veto (`ENABLE_LLM_ENSEMBLE`, downward-only) · resumen diario
(`ENABLE_DAILY_SUMMARY`) · ContinuousLearner (`ENABLE_CONTINUOUS_LEARNER`, propone) · ML
predictor XGBoost (`ENABLE_ML_PREDICTOR`, dormido <400). En la Lenovo el LLM corre en CPU
(~50s/gen): nada de LLM en el hot path; ContinuousLearner OFF.

## 7. Backtest Replay Harness (OFFLINE)

Reproduce la historia D1 barra por barra, le pregunta a las estrategias **REALES** qué
habrían hecho, simula con pesimismo y mide R neto. **Invierte el descubrimiento:** descarta
en horas lo que el demo tardaría meses.

- **`historical_loader`** (forex/oro): D1 (y H1) máximo desde MT5 → `mt5_historical_cache`.
- **`stock_historical_loader`** (v3.9.0, acciones): D1 de Yahoo **ajustado por splits/
  dividendos** (`period1/period2`, no `range=max`; anti-429 con backoff + pacing).
- **`context_builder`**: `StrategyContext` en la barra N con ventanas que TERMINAN en N
  (anti look-ahead). Campos sin historia → `None` + completeness (B11).
- **`regime_filter`**: PURO. `regime_trend` (SMA200 + pendiente) y `regime_vol` (terciles
  ATR14). Lo usa el harness (slicing + gate de trend D1) Y el **regime gate vivo** (v3.8.0).
- **`trade_simulator`**: B1–B13 (empate→SL; gaps; trailing solo al close tighten-only;
  Donchian close-exit; time exit; direction-aware; costos B8; slippage B9). Determinista.
- **`replay_harness`**: orquestador. `RunConfig.category` (forex/gold auto, o `'stock'`
  forzado). Paridad `STRATEGY_MIN_CONFIDENCE`; B12; escribe SOLO en `backtest_*`.
- **`report`**: slices ([OK] n≥30), veredicto §11, stress ×1.5, **concentración** (aviso
  ARTEFACTO), y **banner de SURVIVORSHIP BIAS en runs de acciones** (solo DESCARTAR). Genera
  `report.md`/`trades.csv`/`equity_r.csv` en `exports/backtest_<id>/`.
- Flag: `ENABLE_BACKTEST_HARNESS=false`. Params de estrategia en el `config_json` del run.

## 8. La verdad de fondo (CONFIRMADA POR CUATRO VÍAS)

**El gate de DATA se cruzó (403/400) pero NO hay edge PROBADO:**
1. **Backtest (décadas de D1):** ninguna estrategia pasa §11. El `trend_following_d1` mostró
   +4.7R que **era un ARTEFACTO** (1 trade de +3724R sobre USDCHF sintético pre-1999 = 80%
   del P&L; mediana real −1.03R). La concentración + el drawdown lo atraparon. NADA se promovió.
2. **Diagnóstico vivo (16-jun, `strategy_performance_sliced`):** `forex_session_breakout`/forex
   pierde **−0.57R en LONGS** y gana **+1.29R en SHORTS** (oro longs −2.57R) = **régimen**, no
   edge. NO es volatilidad (VIX ~16). El demo está PLANO (~$88.6k); las cifras rojas grandes
   eran memecoins en PAPEL.
3. **ML sobre el set completo (18-jun):** AUC 0.533 = ruido.
4. **ML con CV temporal (18-jun):** `TimeSeriesSplit` AUC **0.475 (peor que azar)** OOS, aunque
   el k-fold con shuffle daba 0.69 y un split simple 0.627 — la brecha es la firma de cero señal
   forward + overfitting in-sample. → **NO construir Fase D / más modelos sobre los features
   actuales; `ENABLE_ML_PREDICTOR` queda OFF.**

El LLM/ML **filtran, explican, protegen — NO crean edge.** El regime gate (v3.8.0) es
DEFENSIVO. El edge se DESCUBRE con INFORMACIÓN nueva: el **COT** (v3.9.0) ya está VIVO juntando
data; cuando tenga historia se re-evalúa el ML con features de COT (mirando TimeSeriesSplit).

## 9. Estado + gates de roadmap

- **Hoy:** v3.9.1, **692 tests**, demo ~$88.6k (plano). Features-coverage **CRUZADO 403/400** —
  gate de Fase D cumplido, pero el ML resultó sin señal (ver §8).
- **Backtest de acciones:** S1 + S2 HECHOS; falta el run real (Yahoo 429; `stock_backtest_run.json`
  listo) + S3.
- **COT collector (v3.9.0): HECHO + VIVO.** Info nueva, primer input fuera del OHLCV (`MAPA §3.4`).
- **Fase D** (LightGBM+RF): gate de datos cumplido pero **PROBADO = callejón sin salida** (AUC
  0.475 OOS). NO construir sobre features actuales; el `ml_predictor` XGBoost existente sigue dormido.
- **Fase E** (StrategyMutator): GATE DURO ≥1 estrategia R+ neto + 3 meses. No se cumple.
- **Real-money:** edge probado fuera de régimen + sizing reconstruido + audit + decisión
  deliberada. `GO_LIVE_RUNBOOK.md` cuando `/readiness` esté verde.

## 10. Flags del refocus (en el `.env` del user)

`ENABLE_MEMECOIN_ENGINE=false` (corta colección de memecoins) · `ENABLE_MEMECOIN_TELEGRAM=false`
· `ENABLE_SCALPING_ENGINE=false` · `ENABLE_STOCK_TELEGRAM=true` (acciones alertan) ·
`ENABLE_REGIME_GATE=true` (longs contra-tendencia → paper) · `ENABLE_COT_COLLECTOR=true` (COT
semanal, captura para research) · `ENABLE_ML_PREDICTOR=false` (probado = sin señal; dejar OFF).
Comandos Telegram: `/health`, `/expectancy`, `/edge`, `/performance`, `/readiness`,
`/exit_analysis`, `/exposicion`, `/ml_status`, `/market`, `/porque_perdi`, `/gate_preview`.

## 11. Correr / testear

- Bot: `cd <ruta>\tradingalertaIA` + **`.\start_bot.ps1`**. Chequeo previo: **`python preflight.py`**.
- Harness forex: `$env:ENABLE_BACKTEST_HARNESS='true'` + `python -m app.backtest.replay_harness --config <run.json> --report`.
- Loader de acciones: `$env:ENABLE_BACKTEST_HARNESS='true'` + `python -m app.backtest.stock_historical_loader`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` (debe dar **692 verdes**). OJO: con `| tail`
  el exit code es del pipe — verificar el CONTEO, no el exit.
- Dashboard: `.\.venv\Scripts\streamlit run app/dashboard/streamlit_app.py --server.port 27333`
  → `localhost:27333` (abrir on-demand, cerrar al terminar — no dejarlo 24/7).

## 12. Addendum v3.9.0–v3.9.1

**v3.9.0 — COT collector** (`app/collectors/cot_collector.py`). Pull semanal del Commitments of
Traders de la CFTC vía la Socrata Open Data API (`publicreporting.cftc.gov/resource/6dca-aqww.json`,
Legacy Futures-Only). 9 mercados (EUR/GBP/JPY/AUD/CAD/CHF/NZD/US Dollar Index/Gold) mapeados por
`cftc_contract_market_code` (identificador estable). Calcula posición neta no-comercial y comercial.
- **Tabla `cot_snapshots`** (UNIQUE `report_date, market_code`) + `repository.insert_cot_snapshot`
  (idempotente, INSERT OR IGNORE) + `fetch_latest_cot_snapshot`.
- **Wiring:** `jobs.run_once` tras el bloque de macro, gateado por `cot_last_capture_iso` (2×/día,
  `COT_COLLECTOR_INTERVAL_MINUTES=720`); el cooldown se marca en CADA intento (no martillar CFTC).
  Soft-fail por mercado. Flag `ENABLE_COT_COLLECTOR` (default false).
- **SOLO captura para research** — no genera señal ni gate. La maquinaria de edge (slicing por
  posicionamiento, COT index) se construye DESPUÉS, sobre data acumulada. Validado: 9/9 mercados vs CFTC.

**v3.9.1 — Fix dashboard.** Bootstrap de `sys.path` al tope de `app/dashboard/streamlit_app.py`
(`streamlit run` ponía solo la carpeta del script en el path → `ModuleNotFoundError 'app'`).
+ chore: `.gitignore` cubre `.env.bak*` (los backups del `.env` tienen secrets).

**Fase D — veredicto (18-jun):** gate de datos cumplido (403/400) pero el ML sobre los features
actuales NO tiene señal forward (CV temporal AUC 0.475 OOS; ver §8). NO construir el ensemble
LightGBM/RF; re-evaluar solo cuando cambien los INPUTS (features de COT, mirando TimeSeriesSplit).
