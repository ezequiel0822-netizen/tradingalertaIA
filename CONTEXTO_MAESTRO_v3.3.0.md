# CONTEXTO MAESTRO — Trading Alert AI v3.3.0

> Referencia de arquitectura/schema **vigente** (reemplaza a `CONTEXTO_MAESTRO_v2.10.0.md`,
> que queda como base histórica). Local, Python 3.12, Windows + PowerShell + venv.
> Para el roadmap y las reglas de cómo construir: `PROXIMOS_PASOS.md`. Para la historia
> versión por versión: `CHANGELOG.md`. Para retomar en otra máquina: `HANDOFF.md`.

---

## 1. Qué es

Bot de trading algorítmico **local y gratis**. Detecta oportunidades (memecoins / acciones
US / forex / oro), decide con un **strategy router** (5 swing + 2 scalping), hace **paper
trades** y manda órdenes a **MT5 demo** (MetaQuotes-Demo). Una **capa de IA local** (Ollama
+ llama3.1, opcional) asesora, vetea y aprende — siempre **subtractiva**. Real-money
**BLOQUEADO por diseño**.

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
- Nunca leer/mostrar el `.env` real ni secrets. **Mantener pytest verde (hoy 527).**
- Al tocar `Settings`: sincronizar `tests/test_score._settings()` Y `tests/test_alert_rules._settings()`.

## 3. Arquitectura por capas (módulos reales)

| Capa | Módulos | Rol |
|---|---|---|
| **Colectores** | `app/collectors/*` (dexscreener, forex, stock, macro, news, sec, economic_calendar, geckoterminal, goplus) | Traen data cruda de mercado/macro/noticias |
| **Analizadores** | `app/analyzers/*` (token_score, technical_patterns, alert_decision_engine, learned_weights, learning_gate, risk_analyzer, pro_intelligence, ...) | Puntúan, deciden si alertar, aplican aprendizaje |
| **Estrategias** | `app/strategies/*` — swing: `breakout`, `forex_session_breakout`, `mean_reversion`, `momentum`, `news_catalyst`; scalping: `scalping_breakout`, `scalping_mean_reversion`; `strategy_router` | Eligen el candidato de trade |
| **Riesgo** | `app/risk/` — `risk_manager` (can_open, cooldowns), `position_sizer` (sizing; hoy para ~$100k) | Gate de riesgo + tamaño |
| **Brokers** | `app/brokers/` — `mt5_demo_trader` (ÚNICO order_send), `mt5_reader`, `mt5_symbol_map`, `mt5_historical` | Ejecución demo + lectura MT5 |
| **Portfolio** | `app/portfolio/` — `portfolio_manager` (balance, realized_pnl_today), `mt5_reconciler` (huérfanas/SL), **`performance` (v3.3.0, baseline limpio)** | Estado de cuenta + reconciliación + medición |
| **IA local** | `app/intelligence/` — `ollama_processor` (transporte HTTP), `reasoner` (asesor texto), `ensemble_gate` (veto), `macro_context`, `claude_processor` (alt) | Asesora / vetea (subtractivo) |
| **Aprendizaje** | `app/learning/` — `trade_outcomes` (realized-R, artifacts), `training_engine`, `ml_predictor` (XGBoost), `ml_dataset_builder`, `lifecycle_manager`, `walk_forward`, **`continuous_learner` (v3.2.0)** | Mide P&L honesto, entrena, aprende lecciones |
| **Scheduler** | `app/scheduler/` — `jobs` (`run_once`, orquesta todo), `scalping_engine` | Loop principal |
| **Asistente** | `app/assistant/command_handler` (`BasicTelegramAssistant`), `telegram_assistant`; `app/alerts/telegram_notifier` | Comandos Telegram + envío |
| **Infra** | `app/database/` (`db`, `repository`), `app/config/settings`, `app/utils/*` | Persistencia, settings, helpers |

## 4. Pipeline (`jobs.run_once`, simplificado)

1. Colectar → analizar → puntuar → decidir alertas → enviar (ranked).
2. Abrir paper_trades (swing) / `scalping_engine` (scalping). Al abrir swing live se
   persisten `rsi_entry`/`atr_value`/`macd_*` (v2.11.0 — features ML reales).
3. **Gate de promoción** antes del `order_send` a demo: reglas (`should_execute_live`) →
   ML gate (`_ml_gate`) → ensemble LLM veto (`_llm_ensemble_gate`). **Todos downward-only.**
4. `lifecycle_manager.manage_open_positions` → `mt5_reconciler.reconcile` (huérfanas/SL).
5. Learning cycle (refresca `strategy_performance` + sliced + lessons) → retrain ML diario.
6. Resumen diario (v3.1.0) → **ContinuousLearner** (v3.2.0, lecciones + propuestas).

## 5. Schema de DB (SQLite, tablas reales)

`tokens`, `alerts`, `signal_outcomes`, `alert_outcome_horizons`, `paper_trades`
(+ `rsi_entry`/`atr_value`/`macd_value`/`macd_signal_value` desde v2.11.0), `demo_orders`,
`demo_trade_requests`, `strategy_lessons`, `realized_feature_lessons`, `strategy_performance`,
`strategy_performance_sliced`, `training_runs`, `walk_forward_results`, `price_snapshots`,
`macro_snapshots`, `economic_events`, `mt5_historical_cache`, `data_quality_log`,
`security_checks`, `daily_pnl_log`, `bot_state`, **`trade_lessons` (v3.2.0)**.

- **`trade_lessons`** (v3.2.0): una lección por trade cerrado. PK `id`, `paper_trade_id`
  UNIQUE (idempotente), `outcome` (win/loss), `r_multiple`, `lesson` (texto LLM),
  `lesson_key` (`strategy|category|direction|outcome`, indexado), `created_at`. FK a
  `paper_trades(id)`. Solo registro; no afecta decisiones.

## 6. Las capas de IA (todas subtractivas, opt-in OFF)

| Capa | Versión | Flag | Qué hace |
|---|---|---|---|
| LLM local (transporte) | v2.10.0 | `ENABLE_OLLAMA_INTEGRATION` | Habla con Ollama por HTTP (throttle + cache + soft-fail) |
| Asesor `TradingReasoner` | v2.11.0 | `ENABLE_LLM_ADVISOR` | Solo TEXTO: `assess_market`, `analyze_loss`, **`analyze_win`** (v3.2.0), `explain_setup`, `daily_summary`. No decide |
| Ensemble veto | v3.0.0 | `ENABLE_LLM_ENSEMBLE` | Dos modelos buscan red flags; si alguno marca → baja a paper (downward-only) |
| Resumen diario | v3.1.0 | `ENABLE_DAILY_SUMMARY` | 1x/día por Telegram (números + lección) |
| **ContinuousLearner** | **v3.2.0** | `ENABLE_CONTINUOUS_LEARNER` + `STORE_TRADE_LESSONS` (+ requiere `ENABLE_LLM_ADVISOR`) | Lección por trade → `trade_lessons`; agrupa y **PROPONE** (no aplica). Cap por ciclo, idempotente |
| ML predictor | v2.9.0 | `ENABLE_ML_PREDICTOR` | XGBoost; gate ML (>0.65 pasa, <0.50 paper). Dormido hasta `ML_GATE_MIN_SAMPLES=400` |

## 7. Medición honesta (v2.7.0+ / v3.3.0)

- `trade_outcomes`: realized-R direction-aware **neto de costos**, detección de **artifacts**
  (precio congelado del feedback-loop) excluida a query-time (no muta data).
- `strategy_performance` / `_sliced`: expectancy por estrategia (× sesión/dirección).
- **`performance.performance_since` (v3.3.0):** % realizado de trades EJECUTADOS a MT5 y
  no-artifact desde `PERFORMANCE_BASELINE_DATE` (default `2026-06-03`). `net_r` y win/loss
  netos de costos con `scratch_eps`; `account_pct` = P&L crudo / balance (idem
  `realized_pnl_today`). **No altera el balance real.** Comando `/performance`.

## 8. La verdad de fondo

**El cuello de botella es DATA, no código.** No hay edge PROBADO: la única +R agregada
(`forex_session_breakout`/forex +0.378R) la carga el **lado short de un régimen** (no
durable). El LLM/ML **filtran, explican, protegen — NO crean edge.**

**El −11% del balance demo fue sobre todo el bug de mayo** (feedback-loop / instant-kill /
huérfanas, ~746 artifacts 22–28 may, corregidos en v2.6.7–v2.7.1). Limpio de artifacts:
~−2% desde el inicio; desde el baseline `2026-06-03` la cuenta está **+0.17% (plana)** sobre
16 trades — ni −11% ni ganador. El edge sale de **data + research**.

## 9. Estado + gates de roadmap

- **Hoy:** v3.3.0, 527 tests, demo ~$88.6k. Features-coverage **~68/400** (gate Fase D).
- **Fase D** (AdvancedPredictor: LightGBM+RF+calibración): **GATE DURO ≥400 trades limpios
  con features**. Dormido.
- **Fase E** (StrategyMutator: auto-evolución, paper ≥5d + confirmación humana): **GATE DURO
  ≥1 estrategia R+ neto + 3 meses**. No se cumple.
- **Real-money:** requiere edge probado fuera de régimen + reconstruir sizing para cuenta
  micro (hoy es para ~$100k) + audit del camino real (nunca ejecutado) + decisión deliberada.

## 10. Comandos Telegram (read-only / asesores)

`/health`, `/expectancy`, `/edge`, **`/performance`** (v3.3.0), `/ml_status`, `/market`,
`/porque_perdi`, `/gate_preview`, `/demo_close_all`.

## 11. Correr / testear

- Correr: `cd <ruta>\tradingalertaIA` + `.\.venv\Scripts\python.exe main.py` (UNA máquina a
  la vez contra la misma cuenta MT5 demo).
- Tests: `.\.venv\Scripts\python.exe -m pytest -q` (debe dar **527 verdes**).
- IA local: instalar Ollama + `ollama pull llama3.1` (+ `mistral` para el veto).
