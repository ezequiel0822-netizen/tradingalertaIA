# CONTEXTO MAESTRO — Trading Alert AI v3.6.0

> Referencia de arquitectura/schema **vigente** (reemplaza a `CONTEXTO_MAESTRO_v3.5.0.md`,
> que queda como base histórica). Local, Python 3.12, Windows + PowerShell + venv.
> Para el roadmap y las reglas de cómo construir: `PROXIMOS_PASOS.md`. Para la historia
> versión por versión: `CHANGELOG.md`. Para retomar en otra máquina: `HANDOFF.md`.
> Para el camino a real-money: `GO_LIVE_RUNBOOK.md`. Todo-en-uno: `RESUMEN_COMPLETO.md`.
> Para el backtest: `ESPEC_BACKTEST_REPLAY_v1.md` (cómo) + `MAPA_DE_EDGE_Y_RUTA.md` (porqué).

---

## 1. Qué es

Bot de trading algorítmico **local y gratis**. Detecta oportunidades (memecoins / acciones
US / forex / oro), decide con un **strategy router** (5 swing + 2 scalping), hace **paper
trades** y manda órdenes a **MT5 demo** (MetaQuotes-Demo). Una **capa de IA local** (Ollama
+ llama3.1, opcional) asesora, vetea y aprende — siempre **subtractiva**. Real-money
**BLOQUEADO por diseño**. Desde v3.6.0 trae además un **Backtest Replay Harness** OFFLINE
(`app/backtest/`) que mide hipótesis sobre la historia D1 sin tocar el ciclo vivo.

## 2. Reglas inamovibles (seguridad)

- `ENABLE_REAL_TRADING=false` **HARDCODED**. Real-money prohibido sin autorización nueva,
  explícita y deliberada del user, y solo con edge probado + reconfiguración de sizing.
- `order_send` **SOLO** en `app/brokers/mt5_demo_trader.py` (validaciones demo-only).
  Ningún módulo nuevo lo llama directo. No tocar `mt5_demo_trader.py` ni `mt5_reconciler.py`.
- **El LLM y el ML son SUBTRACTIVOS:** solo vetan / bajan a paper / registran / proponen.
  **JAMÁS** fuerzan ni habilitan una orden.
- **Todo lo nuevo es opt-in OFF + soft-fail:** si está apagado o algo falla, el bot corre
  EXACTAMENTE igual.
- Memecoins: solo paper/lab, no ejecutan a MT5.
- **Backtest harness (`app/backtest/`):** OFFLINE; escribe SOLO en tablas `backtest_*`; NO
  importa `mt5_demo_trader`/`reconciler`; NO toca el ciclo vivo; NO cuenta para `/readiness`,
  `/expectancy`, `/edge` ni los 400 de Fase D. El backtest abre la puerta de **PAPER**, nunca
  la de MT5; prohibido ajustar una hipótesis hasta que pase (si no pasa, se documenta).
- Nunca leer/mostrar el `.env` real ni secrets. **Mantener pytest verde (hoy 657).**
- Al tocar `Settings`: sincronizar `tests/test_score._settings()` Y `tests/test_alert_rules._settings()`.
- **Auditoría de seguridad (2026-06-11): limpia.** Telegram autoriza por chat_id exacto;
  `.env` jamás commiteado; `LogRedactor` enmascara el token (valor + patrón); SQL
  parametrizado; sin eval/exec/shell=True; timeouts en toda la red; repo privado.
  Menores aceptados: email personal en un doc de obsidian; `pickle.load` de modelos locales.

## 3. Arquitectura por capas (módulos reales)

| Capa | Módulos | Rol |
|---|---|---|
| **Colectores** | `app/collectors/*` (dexscreener, forex, stock, macro, news, sec, economic_calendar, geckoterminal, goplus) | Traen data cruda de mercado/macro/noticias |
| **Analizadores** | `app/analyzers/*` (token_score, technical_patterns, alert_decision_engine, learned_weights, learning_gate, risk_analyzer, pro_intelligence, ...) | Puntúan, deciden si alertar, aplican aprendizaje |
| **Estrategias** | `app/strategies/*` — swing: `breakout`, `forex_session_breakout`, `mean_reversion`, `momentum`, `news_catalyst`; scalping: `scalping_breakout`, `scalping_mean_reversion`; **`trend_following_d1` (v3.6.0, Donchian D1 — SOLO backtest, OFF en vivo)**; `strategy_router` | Eligen el candidato de trade |
| **Riesgo** | `app/risk/` — `risk_manager` (can_open, cooldowns), `position_sizer` (sizing; hoy para ~$100k), `exposure` (v3.5.0, neto USD) | Gate de riesgo + tamaño + correlación |
| **Brokers** | `app/brokers/` — `mt5_demo_trader` (ÚNICO order_send), `mt5_reader`, `mt5_symbol_map`, `mt5_historical` | Ejecución demo + lectura MT5 |
| **Portfolio** | `app/portfolio/` — `portfolio_manager`, `mt5_reconciler` (huérfanas/SL), `performance` (v3.3.0, baseline limpio) | Estado de cuenta + reconciliación + medición |
| **IA local** | `app/intelligence/` — `ollama_processor`, `reasoner`, `ensemble_gate`, `macro_context`, `claude_processor`, **`regime_filter` (v3.6.0, clasificador puro de régimen)** | Asesora / vetea (subtractivo) + régimen |
| **Aprendizaje** | `app/learning/` — `trade_outcomes`, `training_engine`, `ml_predictor` (XGBoost), `ml_dataset_builder`, `lifecycle_manager`, `walk_forward`, `continuous_learner` (v3.2.0) | Mide P&L honesto, entrena, aprende lecciones |
| **Backtest (OFFLINE)** | **`app/backtest/` (v3.6.0)** — `historical_loader`, `context_builder`, `trade_simulator`, `replay_harness`, `report` | Reproduce la historia D1 con las estrategias REALES y mide R neto con pesimismo. NO corre en el ciclo vivo |
| **Scheduler** | `app/scheduler/` — `jobs` (`run_once`, orquesta todo), `scalping_engine` | Loop principal |
| **Asistente** | `app/assistant/command_handler` (`BasicTelegramAssistant`), `telegram_assistant`; `app/alerts/telegram_notifier` | Comandos Telegram + envío |
| **Infra** | `app/database/` (`db`, `repository`), `app/config/settings`, `app/utils/*` | Persistencia, settings, helpers |

## 4. Pipeline (`jobs.run_once`, simplificado)

1. Colectar → analizar → puntuar → decidir alertas → enviar (ranked).
2. Abrir paper_trades (swing) / `scalping_engine` (scalping). Al abrir swing live se
   persisten `rsi_entry`/`atr_value`/`macd_*` (v2.11.0 — features ML reales).
3. **Gate de promoción** antes del `order_send` a demo: reglas (`should_execute_live`) →
   ML gate (`_ml_gate`) → ensemble LLM veto (`_llm_ensemble_gate`) → calendar gate
   (v3.5.0) → cap de exposición USD (v3.5.0). **Todos downward-only.**
4. `lifecycle_manager.manage_open_positions` → `mt5_reconciler.reconcile` (huérfanas/SL).
5. Learning cycle (refresca `strategy_performance` + sliced + lessons) → retrain ML diario.
6. Resumen diario (v3.1.0) → ContinuousLearner (v3.2.0) → exit shadow (v3.4.0, solo registro).

> **El harness v3.6.0 NO está en este pipeline.** Es un CLI offline aparte
> (`python -m app.backtest.replay_harness --config <run.json> --report`).

## 5. Schema de DB (SQLite, tablas reales)

`tokens`, `alerts`, `signal_outcomes`, `alert_outcome_horizons`, `paper_trades`
(+ `rsi_entry`/`atr_value`/`macd_value`/`macd_signal_value` desde v2.11.0), `demo_orders`,
`demo_trade_requests`, `strategy_lessons`, `realized_feature_lessons`, `strategy_performance`,
`strategy_performance_sliced`, `training_runs`, `walk_forward_results`, `price_snapshots`,
`macro_snapshots`, `economic_events`, `mt5_historical_cache`, `data_quality_log`,
`security_checks`, `daily_pnl_log`, `bot_state`, `trade_lessons` (v3.2.0),
`trade_r_samples` (v3.4.0), **`backtest_runs` / `backtest_trades` / `backtest_walkforward` (v3.6.0)**.

- **`trade_lessons`** (v3.2.0): una lección por trade cerrado (LLM). Solo registro.
- **`trade_r_samples`** (v3.4.0): camino de R no-realizado de cada trade abierto. Insumo de `/exit_analysis`.
- **`backtest_*`** (v3.6.0): resultados del harness, **separados de toda tabla viva (cero FK
  hacia tablas vivas)**. `backtest_runs` (una fila por corrida: git_commit, mode, timeframe,
  symbols, data_ranges_json, config_json, cost_multiplier, n_configs_tested), `backtest_trades`
  (una fila por trade simulado: direction, entry/sl/tp, exit_reason, r_gross/cost_r/r_net,
  mfe_r/mae_r, session, regime_trend/regime_vol, year), `backtest_walkforward` (ventanas OOS
  del Modo B). NO cuentan para nada vivo.

## 6. Las capas de IA (todas subtractivas, opt-in OFF)

| Capa | Versión | Flag | Qué hace |
|---|---|---|---|
| LLM local (transporte) | v2.10.0 | `ENABLE_OLLAMA_INTEGRATION` | Habla con Ollama por HTTP (throttle + cache + soft-fail) |
| Asesor `TradingReasoner` | v2.11.0 | `ENABLE_LLM_ADVISOR` | Solo TEXTO: `assess_market`, `analyze_loss`, `analyze_win`, `explain_setup`, `daily_summary` |
| Ensemble veto | v3.0.0 | `ENABLE_LLM_ENSEMBLE` | Dos modelos buscan red flags; si alguno marca → baja a paper |
| Resumen diario | v3.1.0 | `ENABLE_DAILY_SUMMARY` | 1x/día por Telegram (números + lección) |
| ContinuousLearner | v3.2.0 | `ENABLE_CONTINUOUS_LEARNER` + `STORE_TRADE_LESSONS` | Lección por trade → `trade_lessons`; agrupa y **PROPONE** (no aplica) |
| ML predictor | v2.9.0 | `ENABLE_ML_PREDICTOR` | XGBoost; gate ML. Dormido hasta `ML_GATE_MIN_SAMPLES=400` |

## 7. Backtest Replay Harness (v3.6.0, OFFLINE)

Reproduce la historia D1 de MT5 barra por barra, le pregunta a las estrategias **REALES**
qué habrían hecho, simula cada trade con pesimismo y mide R neto de costos. Propósito:
**invertir el descubrimiento** — el backtest descarta en horas lo que el demo tardaría meses.

- **`historical_loader`**: trae la profundidad MÁXIMA de D1 (y H1 si hay) por símbolo y la
  cachea en `mt5_historical_cache`. Reporta el rango REAL (D1: décadas; H1: 50k barras, tope
  del broker). Avisa si sospecha truncamiento ("Max bars" del terminal).
- **`context_builder`**: arma el `StrategyContext` en la barra N con ventanas que TERMINAN en
  N (anti look-ahead). Campos sin historia (news/pro/macro) → `None` + completeness report (B11).
- **`regime_filter`** (`app/intelligence/`): función PURA. `regime_trend` (precio vs SMA200 +
  pendiente) y `regime_vol` (terciles de ATR14 vs 252 previos). Doble uso: gate de
  `trend_following_d1` + dimensión de slicing.
- **`trade_simulator`**: vida completa del trade con **B1–B13**: empate intrabar → SL (B3);
  gaps asimétricos (B4); trailing solo al close y tighten-only (B5); salida confirmada al
  close → ejecución al open siguiente (`close_exit_fn`, la Donchian de trend D1); time exit
  (B6); direction-aware (B7); costos (B8, mismo cost map que la medición viva); slippage (B9).
  Determinista y offline (B10). Números dorados calculados a mano en los tests.
- **`replay_harness`**: orquestador. Aplica el mismo `STRATEGY_MIN_CONFIDENCE` que el router
  vivo; B12 (una posición por símbolo/estrategia); escribe SOLO en `backtest_*`.
- **`report`**: slices por símbolo/sesión/dirección/año/régimen ([OK] solo n≥30), veredicto
  §11 criterio por criterio, stress de costos ×1.5, y **concentración** (mejor trade / top-10
  % del P&L → aviso ARTEFACTO). Genera `report.md` + `trades.csv` + `equity_r.csv` en
  `exports/backtest_<id>/` (gitignored).
- **Flag:** `ENABLE_BACKTEST_HARNESS=false` (opt-in). Params de estrategia NO van a Settings:
  viven en el `config_json` del run (cada corrida queda autodescrita).

## 8. La verdad de fondo

**El cuello de botella es DATA, no código.** No hay edge PROBADO. La única +R viva
(`forex_session_breakout` +0.378R) la carga el lado short de un régimen (no durable). Y el
**backtest v3.6.0 lo confirmó sobre décadas de D1:** ninguna estrategia pasa los criterios
§11. El `trend_following_d1` mostró un avg **+4.7R** que **era un ARTEFACTO** — un solo trade
de **+3724R** sobre data sintética pre-1999 de USDCHF cargaba el 80% del P&L bruto (mediana
real −1.03R; GBPUSD −0.26R). El veredicto §11 lo rechazó (drawdown 57.5R, consistencia 58%)
y la métrica de concentración lo gritó. **NADA se promovió** — el harness funcionó
exactamente para lo que existe. El LLM/ML **filtran, explican, protegen — NO crean edge.**

**El −11% del balance demo fue sobre todo el bug de mayo** (~746 artifacts 22–28 may,
corregidos en v2.6.7–v2.7.1). Limpio: ~plano desde el baseline `2026-06-03`. El edge sale de
**data + research** (próximo: COT, instrumentos descorrelacionados — `MAPA_DE_EDGE_Y_RUTA.md`).

## 9. Estado + gates de roadmap

- **Hoy:** v3.6.0, **657 tests**, demo ~$88.8k. Features-coverage **~70/400** (gate Fase D).
- **Harness (v3.7+):** collector de COT (CFTC, gratis), instrumentos descorrelacionados
  (índices/commodities D1), backfill macro VIX/DXY, granularidad H1. Cada pieza opt-in + tests.
- **Fase D** (AdvancedPredictor: LightGBM+RF+calibración): **GATE DURO ≥400 trades limpios
  con features**. Dormido. El backtest NO cuenta para este gate (son trades vivos).
- **Fase E** (StrategyMutator): **GATE DURO ≥1 estrategia R+ neto + 3 meses**. No se cumple.
- **Real-money:** edge probado fuera de régimen + sizing reconstruido (hoy ~$100k) + audit
  del camino real + decisión deliberada. `GO_LIVE_RUNBOOK.md` cuando `/readiness` esté verde.

## 10. Comandos Telegram (read-only / asesores)

`/health`, `/expectancy`, `/edge`, `/performance` (v3.3.0), `/readiness` (v3.3.0),
`/exit_analysis` (v3.4.0), `/exposicion` (v3.5.0), `/ml_status`, `/market`, `/porque_perdi`,
`/gate_preview`, `/demo_close_all`. *(El harness es CLI-only; no tiene comando Telegram en v1.)*

## 11. Correr / testear

- Correr el bot: `cd <ruta>\tradingalertaIA` + **`.\start_bot.ps1`** (arranque oficial; pide
  contraseña si `STARTUP_PASSWORD_SHA256` está en el `.env` — opt-in, SHA-256, ASCII puro por
  PS 5.1). UNA máquina a la vez contra la misma cuenta. Preflight: `python preflight.py`.
- Correr el harness (offline): `$env:ENABLE_BACKTEST_HARNESS='true'` +
  `python -m app.backtest.replay_harness --config <run.json> --report`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` (debe dar **657 verdes**). OJO: si se
  corre con `| tail`, el exit code es el del pipe — verificar el conteo, no el exit.
- IA local: Ollama + `llama3.2:3b` (Lenovo) o `llama3.1`. ⚠️ En la Lenovo el LLM corre
  mayormente en CPU (~50s/gen): el asesor es a-demanda; nada de LLM en el hot path.
