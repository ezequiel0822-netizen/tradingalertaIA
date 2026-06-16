---
tags: [arquitectura, estructura, modulos]
version: v3.6.0
updated: 2026-06-14
---

# Arquitectura del Sistema

> [!info] Vision general
> Aplicacion Python local con dos engines vivos (swing + scalping) que comparten infraestructura (DB, MT5 reader, learning engine, telegram, dashboard). Desde v3.6.0 hay además un **paquete offline `app/backtest/`** que NO corre en el ciclo vivo.

> [!warning] El Backtest Replay Harness (v3.6.0) NO está en el diagrama de abajo
> `app/backtest/` (`historical_loader`, `context_builder`, `trade_simulator`, `replay_harness`,
> `report`) + `app/intelligence/regime_filter.py` reproducen la historia D1 con las
> estrategias REALES, OFFLINE, vía CLI (`python -m app.backtest.replay_harness --config x.json`).
> Escribe SOLO en tablas `backtest_*`; no importa `mt5_demo_trader`/`reconciler`; no toca el
> ciclo de `jobs.run_once`. Ver `CONTEXTO_MAESTRO_v3.6.0.md` §7 y [[20 - Schema de Base de Datos]].

---

## Diagrama de alto nivel

```
                        +---------------------------+
                        |    MetaTrader 5 Desktop   |
                        |  (proceso separado, IPC)  |
                        +-----------+---------------+
                                    |
                                    | Python MetaTrader5 lib
                                    |
+-----------------------------------v---------------------------------------+
|                            main.py (entry point)                          |
|                                                                           |
|   +---------------------------------------------------------------+      |
|   |   TradingAlertJob (main thread, ciclos de ~60s)                |      |
|   |                                                                |      |
|   |   1. process_telegram_updates()                                |      |
|   |   2. lifecycle_manager.manage_open_positions()                 |      |
|   |   3. MT5Reconciler.reconcile()      <-- v2.6.7                 |      |
|   |   4. Collectors (9 paralelos)                                  |      |
|   |   5. strategies/strategy_router -> signals                     |      |
|   |   6. risk_manager.check_can_open_trade(symbol=)  <-- v2.6.8    |      |
|   |   7. position_sizer + paper_trade creation                     |      |
|   |   8. _try_prepare_demo_order()                                 |      |
|   |      * promotion_gate.should_execute_live()  <-- v2.7.0        |      |
|   |      * auto-confirm if enabled                                 |      |
|   |      * _correct_paper_trade_notional()  <-- v2.6.8             |      |
|   |   9. learning_cycle                                            |      |
|   |      * outcomes, lessons, weights                              |      |
|   |      * _refresh_strategy_performance()  <-- v2.7.0             |      |
|   |      * _refresh_realized_feature_lessons()  <-- v2.7.0         |      |
|   |  10. dashboard/CSV/Obsidian writes                             |      |
|   +---------------------------------------------------------------+      |
|                                                                           |
|   +---------------------------------------------------------------+      |
|   |  ScalpingEngine (DEDICATED THREAD, ciclos de ~3s)             |      |
|   |                                                                |      |
|   |   1. Check kill switches                                       |      |
|   |   2. _check_force_exits                                        |      |
|   |   3. _check_caps                                               |      |
|   |   4. Para cada simbolo:                                        |      |
|   |      * mt5_reader.get_rates(M1)                                |      |
|   |      * mt5_reader.get_tick                                     |      |
|   |      * iterate self.strategies (breakout + MR)  <-- v2.6.6     |      |
|   |   5. Si signal:                                                |      |
|   |      * promotion_gate check  <-- v2.7.0                        |      |
|   |      * create_paper_trade(is_scalping=1)                       |      |
|   |      * mt5_demo_trader.send_prepared_request                   |      |
|   |      * _correct_paper_trade_notional()  <-- v2.6.8             |      |
|   |   6. Heartbeat Telegram cada N trades                          |      |
|   +---------------------------------------------------------------+      |
|                                                                           |
|   +------------------------+  +------------------------+                 |
|   |     Telegram Bot       |  |       SQLite DB        |                 |
|   |   (40+ commands)       |  | C:\Users\xxxv4\        |                 |
|   |                        |  |   trading_data\        |                 |
|   |                        |  | trading_alert_ai.db    |                 |
|   +------------------------+  +------------------------+                 |
|                                                                           |
+---------------------------------------------------------------------------+
```

---

## Estructura de archivos

```
C:\Users\xxxv4\iCloudDrive\tradingalertaIA\
+-- .env                          # secretos reales (NO en git)
+-- .env.example                  # template publico v2.7.0
+-- .venv\                        # Python 3.12.13
+-- main.py                       # entry point
+-- pytest.ini
+-- requirements.txt
+-- CHANGELOG.md
+-- README.md
+-- CONTEXTO_MAESTRO_v2.7.0.md    # mirror tecnico
|
+-- app\
|   +-- alerts\                   # formatters + Telegram + trade reporter
|   +-- analyzers\                # scoring + memecoin hunter + technical + IA Pro + learning_gate
|   +-- assistant\
|   |   +-- command_handler.py    # 40+ comandos Telegram
|   |   +-- telegram_assistant.py
|   +-- brokers\
|   |   +-- mt5_reader.py         # read-only + v2.6.5 symbol_select defensive
|   |   +-- mt5_demo_trader.py    # UNICO con order_send. v2.6.7 close+update_sl. v2.6.8 compute_actual_notional_usd
|   |   +-- mt5_historical.py
|   |   +-- mt5_symbol_map.py     # Yahoo<->MT5 mapping
|   +-- collectors\               # 9 collectors
|   +-- config\
|   |   +-- settings.py           # dataclass Settings + load_settings
|   +-- dashboard\
|   |   +-- streamlit_app.py      # 9 secciones
|   +-- database\
|   |   +-- db.py                 # init_db + 18 tablas + _ensure_column
|   |   +-- models.py
|   |   +-- repository.py         # CRUD + v2.7.0 helpers
|   +-- intelligence\             # calendar + claude + data_quality + macro_context
|   +-- learning\
|   |   +-- backtester.py
|   |   +-- feature_extractor.py
|   |   +-- horizon_evaluator.py
|   |   +-- lifecycle_manager.py  # v2.7.0 _fresh_price con Yahoo->MT5
|   |   +-- training_engine.py    # v2.7.0 _update_paper_trades direction-aware
|   |   +-- trade_outcomes.py     # NUEVO v2.7.0: realized-R, gate, cost model
|   |   +-- walk_forward.py
|   +-- portfolio\
|   |   +-- portfolio_manager.py  # realized_pnl_today USD-based v2.6.5
|   |   +-- mt5_reconciler.py     # NUEVO v2.6.7
|   +-- risk\
|   |   +-- position_sizer.py
|   |   +-- risk_manager.py       # v2.6.8 check_can_open_trade(symbol=)
|   +-- scheduler\
|   |   +-- jobs.py               # TradingAlertJob v2.6.7 + v2.6.8 + v2.7.0 hooks
|   |   +-- scalping_engine.py    # multi-strategy v2.6.6
|   +-- strategies\
|   |   +-- base.py
|   |   +-- breakout.py
|   |   +-- forex_session_breakout.py
|   |   +-- mean_reversion.py
|   |   +-- momentum.py
|   |   +-- news_catalyst.py
|   |   +-- scalping_breakout.py
|   |   +-- scalping_mean_reversion.py  # NUEVO v2.6.6
|   |   +-- strategy_router.py
|   +-- utils\
|       +-- bot_mode.py
|       +-- scalping_state.py
|       +-- csv_export.py
|       +-- dedup.py
|       +-- log_redactor.py
|       +-- logging_config.py
|       +-- obsidian_memory.py
|       +-- rate_limiter.py
|       +-- safe_http.py
|       +-- safe_path.py
|       +-- time_utils.py
|
+-- obsidian\
|   +-- tradingbot v.1\           # este vault
|
+-- tests\                        # 397 tests
    +-- test_trade_outcomes.py        # v2.7.0
    +-- test_strategy_promotion_gate.py # v2.7.0
    +-- test_cost_model.py            # v2.7.0
    +-- test_expectancy_command.py    # v2.7.0
    +-- test_realized_learning.py     # v2.7.0 Fase 2b
    +-- test_mt5_reconciler.py        # v2.6.7
    +-- test_v268_v269.py             # v2.6.8 notional + cooldown
    +-- test_gate_preview_command.py  # v2.6.9
    +-- test_scalping_mean_reversion.py # v2.6.6
    +-- test_scalping_engine.py
    +-- ... (resto sin cambios)
```

---

## Archivos criticos (priorizado)

| Archivo | Por que critico |
|---|---|
| `main.py` | Entry point. Wraps `TradingAlertJob`, arranca scalping thread, signal handlers |
| `app/scheduler/jobs.py` | Orquestador swing ~1100 lineas. `run_once()` coordina todo |
| `app/scheduler/scalping_engine.py` | Thread scalping. Polling 3-5s. Multi-strategy v2.6.6 |
| `app/learning/trade_outcomes.py` | NUEVO v2.7.0 — realized-R, cost model, gate |
| `app/portfolio/mt5_reconciler.py` | NUEVO v2.6.7 — cierra MT5 huerfanas + sync SL |
| `app/brokers/mt5_demo_trader.py` | UNICO con `order_send`. Capa critica |
| `app/risk/risk_manager.py` | Per-symbol cooldown + kill switch + caps |
| `app/learning/training_engine.py` | `_update_paper_trades` direction-aware (Fix A v2.7.0) |
| `app/learning/lifecycle_manager.py` | `_fresh_price` con Yahoo->MT5 (Fix C v2.7.0) |
| `app/config/settings.py` | 160+ fields. Hardcoded restrictions |

---

## Modulos por responsabilidad

### Detection layer (collectors)

9 modulos en `app/collectors/`:
- `dexscreener_collector.py` — memecoins (boosts, trending, profiles)
- `geckoterminal_collector.py` — cripto trending + new pools
- `stock_collector.py` — 22 stocks via Yahoo
- `forex_collector.py` — 7 pares forex + GC=F
- `news_collector.py` — Yahoo RSS
- `sec_collector.py` — SEC EDGAR filings
- `goplus_collector.py` — security check cripto
- `macro_collector.py` — VIX/DXY/SPY
- `economic_calendar_collector.py` — ForexFactory

### Analysis layer

`app/analyzers/`:
- `token_score.py` — scoring base
- `pro_intelligence.py` — IA Pro setup
- `news_analyzer.py` — RSS keywords
- `filing_analyzer.py` — SEC filings
- `technical_patterns.py` — RSI, MACD, ATR, Bollinger, S/R
- `memecoin_hunter.py` — Pro multipliers (anti-rug, volume velocity)
- `move_estimator.py` — gain/loss/confidence
- `learning_gate.py` — feature filter (opt-in)
- `alert_decision_engine.py` — decision final

### Strategy layer

`app/strategies/`:
- 5 swing strategies + base.py
- 2 scalping strategies
- `strategy_router.py` — dispatch + multi-strategy iteration

### Execution layer

`app/risk/` + `app/portfolio/` + `app/brokers/`:
- `position_sizer.py` — calc notional
- `risk_manager.py` — gates pre-trade
- `portfolio_manager.py` — open positions + realized_pnl_today
- `mt5_reconciler.py` — huerfanas + SL sync (v2.6.7)
- `mt5_demo_trader.py` — order_send (unico)

### Learning layer

`app/learning/`:
- `training_engine.py` — coordina learning cycle
- `lifecycle_manager.py` — manage open positions
- `trade_outcomes.py` — realized-R + gate (v2.7.0)
- `backtester.py` + `walk_forward.py` — historical analysis
- `horizon_evaluator.py` — per-horizon outcomes
- `feature_extractor.py` — features para learning

### Persistence layer

`app/database/`:
- `db.py` — schema + migrations
- `models.py` — dataclasses
- `repository.py` — CRUD

### Interaction layer

`app/assistant/`:
- `command_handler.py` — 40+ comandos
- `telegram_assistant.py` — poll Telegram updates

`app/alerts/`:
- `telegram_notifier.py` — send messages
- `formatters.py` — message formatting
- `trade_action_reporter.py` — auto-reports

`app/dashboard/`:
- `streamlit_app.py` — UI 9 secciones

### Infrastructure

`app/utils/`:
- `bot_mode.py`, `scalping_state.py` — runtime state
- `safe_http.py`, `safe_path.py` — defense
- `log_redactor.py`, `logging_config.py` — observability
- `obsidian_memory.py` — vault writes
- `time_utils.py` — UTC handling
- `dedup.py` — alert dedup
- `csv_export.py` — exports
- `rate_limiter.py` — request rate limiting

---

## Threading model

### Main thread

`TradingAlertJob.run_forever()` → loop infinito de `run_once()` con sleep entre ciclos (`POLL_INTERVAL_SECONDS=60` - elapsed).

### Scalping thread

`ScalpingEngine._run_loop()` en thread separado, daemon=True. Polling `SCALPING_POLL_INTERVAL_SECONDS=3`. `_stop_event` para graceful shutdown.

### Telegram polling

Sub-method `process_telegram_updates()` se llama en cada `run_once()`. NO es thread separado.

### Concurrencia SQLite

Cada `repository.X()` abre conexion nueva via `get_connection`. SQLite stdlib es thread-safe asi.

---

## Data flow (ciclo swing)

1. `process_telegram_updates()` — comandos pendientes
2. `lifecycle_manager.manage_open_positions()` — refresca latest_price, MFE/MAE, trailing, partial close, time exit, SL/TP hit
3. `MT5Reconciler.reconcile()` — cierra huerfanas + sync SL **(v2.6.7)**
4. Collectors (9) corren en paralelo via threads/asyncio
5. Strategies emiten signals
6. `risk_manager.check_can_open_trade(symbol=)` valida **(v2.6.8 symbol param)**
7. `position_sizer.calculate_position_size` calcula
8. `repository.create_paper_trade` persiste
9. `_try_prepare_demo_order` (si forex/gold):
   - `should_execute_live` check **(v2.7.0)**
   - Create `demo_trade_request`
   - Si auto-confirm: `_auto_execute_demo_request`
   - `_correct_paper_trade_notional` post-send **(v2.6.8)**
10. `run_learning_cycle`:
    - Evaluate outcomes
    - Build lessons + weights
    - `_refresh_strategy_performance` **(v2.7.0)**
    - `_refresh_realized_feature_lessons` **(v2.7.0 Fase 2b)**
11. Dashboard / CSV / Obsidian writes

---

## Links relacionados

- [[20 - Schema de Base de Datos]] - tablas
- [[15 - Estrategias]] - strategy detail
- [[10 - Learning Engine]] - learning detail
- [[21 - Decisiones Arquitectonicas]] - por que esta estructura
