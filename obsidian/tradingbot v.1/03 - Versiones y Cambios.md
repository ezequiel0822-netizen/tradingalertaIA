---
tags: [versiones, historial, evolucion]
version: v3.9.1
updated: 2026-06-18
---

# Versiones y Cambios

> [!info] Trayectoria
> 2 semanas de evolucion desde un MVP read-only hasta un trader engine con learning honesto basado en P&L realizado neto de costos.

---

## Tabla maestra

| Version | Fecha | Hito |
|---|---|---|
| v1.0-v1.5 | 2026-05-16 | MVP read-only: DEX Screener + Telegram + SQLite + Streamlit |
| v1.5.2 | 2026-05-17 | Learning Engine (signal_outcomes, strategy_lessons, paper_trades) |
| v1.6.0 | 2026-05-18 | Phase 1: horizons 1h/6h/24h/7d + MFE/MAE + backtester |
| v1.7.0 | 2026-05-18 | Phase 2: paper trading++, trailing stops, ATR SL/TP, learning gate (OFF) |
| **v2.0.0** | **2026-05-18** | **PIVOT: alerter → trader engine.** Strategy router, portfolio, risk manager, MT5 reader read-only |
| v2.1.0 | 2026-05-19 | Phase 2.6: security hardening (Settings.repr mascarado, LogRedactor, safe_path) |
| v2.2.0 | 2026-05-19 | Phase 3+3.5: forex price-action + macro (VIX/DXY) + ForexFactory + Claude API |
| v2.3.0 | 2026-05-19 | Phase 4: MT5 ICMarkets validation, walk-forward, data quality |
| v2.4.0 | 2026-05-19 | Phase 4.5: Memecoin Hunter Pro + Bot Mode Toggle |
| **v2.5.0** | **2026-05-20** | **Phase 5: order_send a MT5 demo con confirmacion manual** |
| v2.5.1-v2.5.3 | 2026-05-20 | Patches demo + fallback pip-value + /demo_candidates validacion |
| v2.5.4 | 2026-05-20 | **Phase 5.5 Bloque A: auto-confirm opt-in** |
| v2.5.5 | 2026-05-22 | DEMO_MAX_TOTAL_RISK_PCT separado + /health |
| **v2.6.0** | **2026-05-22** | **Phase 5.5 Bloque B: Scalping Engine + Mode Toggle + Learning per-style** |
| v2.6.1 | 2026-05-22 | /demo_close_all + 8 stock symbols extra |
| v2.6.2 | 2026-05-25 | Diagnostic instrumentation scalping |
| v2.6.3 | 2026-05-25 | FIX: timeframe int no string |
| v2.6.4 | 2026-05-25 | FIX: numpy.void sin .get() |
| v2.6.5 | 2026-05-26 | FIX: realized_pnl_today + symbol_select + account_balance |
| **v2.6.6** | **2026-05-28** | **scalping_mean_reversion (BB+RSI) + ScalpingEngine multi-strategy** |
| **v2.6.7** | **2026-05-28** | **MT5Reconciler: cierra MT5 huerfanas + sync SL post-trailing** |
| **v2.6.8** | **2026-05-28** | **size_notional con MT5 real + per-symbol cooldown** |
| v2.6.9 | 2026-05-29 | /gate_preview Telegram command |
| **v2.7.0** | **2026-05-30** | **Realized-R honesto + promotion gate + cost model + Fase 2b learning + DB fuera iCloud** |
| **v2.7.1** | **2026-06-02** | **`realized_pnl_today` filtra paper-only trades (tapa kill switch falso de gold GC=F)** |
| **v2.8.0** | **2026-06-03** | **Edge Detection: `strategy_performance_sliced` por sesion/direccion + `/edge` + gate sliceado (opt-in OFF, solo restringe)** |
| **v2.9.0** | **2026-06-03** | **Hybrid ML layer (XGBoost): `ml_predictor` modula el gate SOLO hacia abajo, soft-fail, DORMIDO por default** |
| **v2.9.1** | **2026-06-04** | **Flag `ENABLE_STOCK_TELEGRAM`: analizar acciones sin alertarlas (avisos de trades intactos)** |
| **v2.10.0** | **2026-06-04** | **Proveedor LLM local via Ollama (gratis, sin API key): `OllamaProcessor` + factory; solo enriquece texto, no decide trades** |
| v2.11.0 | 2026-06-05 | Features `rsi/atr/macd` al entry + `TradingReasoner` (asesor LLM read-only, solo texto) |
| v2.12.0 | 2026-06-05 | Comandos Telegram `/market` + `/porque_perdi` |
| **v3.0.0** | **2026-06-06** | **Veto del ensemble LLM (Llama+Mistral) en el demo gate — downward-only** |
| v3.1.0 | 2026-06-06 | Resumen diario por Telegram al cierre NY (read-only) |
| **v3.2.0** | **2026-06-08** | **Fase C — ContinuousLearner: lección por trade → `trade_lessons`; agrupa y PROPONE** |
| **v3.3.0** | **2026-06-09** | **`/performance` (baseline limpio post-bug) + `/readiness` (gates real-money)** |
| v3.3.1 | 2026-06-09 | Caché + cooldown 429 para GeckoTerminal |
| **v3.4.0** | **2026-06-10** | **Exit shadow: mide si un trailing mejoraría las salidas + `/exit_analysis`** |
| **v3.5.0** | **2026-06-11** | **Calendar gate (conecta `is_safe_window` huérfano) + cap de exposición neta USD + `/exposicion`** |
| **v3.6.0** | **2026-06-14** | **Backtest Replay Harness (`app/backtest/`) + `regime_filter` + `trend_following_d1`. Offline, tablas `backtest_*`. Veredicto: sin edge en D1 (el +4.7R del trend fue un artefacto)** |
| **v3.7.0** | **2026-06-17** | **Refocus a la bolsa: `ENABLE_MEMECOIN_ENGINE` corta la colección de memecoins (bot aparte). Scalping off, stock alerts on. + ESPEC backtest acciones** |
| **v3.8.0** | **2026-06-17** | **Regime gate vivo (`ENABLE_REGIME_GATE`, opt-in, downward-only): longs contra-tendencia D1 → paper. Nace del diagnóstico (longs −0.57R/shorts +1.29R = régimen)** |
| backtest acciones | 2026-06-17 | S1 (`stock_historical_loader`, Yahoo D1 ajustado) + S2 (harness `category=stock` + banner survivorship). Run real pendiente (Yahoo 429; `stock_backtest_run.json` listo) + S3 |
| **v3.9.0** | **2026-06-18** | **COT collector (`app/collectors/cot_collector.py` + tabla `cot_snapshots` + `ENABLE_COT_COLLECTOR`): CFTC semanal, 9 mercados FX+oro, SOLO captura para research. Opt-in OFF. VIVO** |
| v3.9.1 | 2026-06-18 | Fix dashboard Streamlit (bootstrap `sys.path`, `ModuleNotFoundError 'app'`) + chore `.gitignore .env.bak*`. **Veredicto Fase D: gate de datos cruzado (403/400) pero ML sin señal forward (CV temporal 0.475 OOS) → NO construir** |

---

## Fases conceptuales

### Phase 1-2: Detection MVP

Detectar memecoins y stocks, scoring, alertas Telegram. Read-only puro.

### Phase 2.5: Trader Engine (v2.0)

PIVOT mayor. De "alerter" a "trader engine":
- Strategy router (5 swing)
- Portfolio manager + risk manager + position sizer
- Kill-switch automatico (drawdown) + manual
- Bot mode toggle
- MT5 reader (read-only)

### Phase 2.6: Security hardening (v2.1)

`Settings.__repr__` mascarado, `LogRedactor`, `safe_path`, `safe_json`.

### Phase 3 + 3.5: Macro + LLM (v2.2)

Forex price-action, macro context (VIX/DXY/SPY), economic calendar (ForexFactory), Claude API soft-fail.

### Phase 4: Validation (v2.3)

MT5 ICMarkets validation, walk-forward backtester, data quality monitor.

### Phase 4.5: Memecoin Pro + Modes (v2.4)

Memecoin Hunter Pro (volume_velocity, anti-rug multiplier), Bot Mode Toggle (trader / alerts_only / hybrid).

### Phase 5: order_send a demo MT5 (v2.5)

`MT5DemoTrader` (unico modulo con order_send). Confirmacion manual obligatoria. Validaciones demo-only. Real-money bloqueado.

### Phase 5.5 Bloque A: Auto-confirm (v2.5.4)

`ENABLE_AUTO_CONFIRM_DEMO` opt-in. Bypassa confirmacion manual Telegram.

### Phase 5.5 Bloque B: Scalping Engine (v2.6.0)

Thread dedicado, polling 3-5s. Strategy `scalping_breakout` M1. Force-exit timeout. Caps independientes. Kill-switch propio. Lessons separadas via sufijo `_scalping`.

### Sprint del 27-28 may (v2.6.6 → v2.6.9)

Tras perdida de $12k el 27-may, 4 bugs descubiertos + fixeados:

- v2.6.6: `scalping_mean_reversion` + multi-strategy engine
- v2.6.7: `MT5Reconciler` (cierra huerfanas + sync SL TIGHTEN)
- v2.6.8: `size_notional` con MT5 real + per-symbol cooldown
- v2.6.9: `/gate_preview` Telegram command

Ver [[16 - Bugs Resueltos]] para el detalle de la saga.

### v2.7.0: Realized-R honesto + promotion gate (2026-05-30)

Sesion de hallazgo raiz:
- `_update_paper_trades` long-only insta-killeaba shorts → 86% del historial paper_trades eran artifacts
- Aprendizaje (`signal_outcomes`) media drift de alerta a horizonte fijo (~99% neutral, gate ciego)

Fixes:
- **Fix A** (keystone): `_update_paper_trades` direction-aware
- **Fix C**: `lifecycle_manager._fresh_price` mapea Yahoo→MT5
- **Fix D**: nuevo `trade_outcomes.py` (realized-R, cost model, artifacts, gate) + tabla `strategy_performance` + comando `/expectancy`
- **Promotion gate** (`should_execute_live`): bloquea order_send de losers probados
- **Cost model**: round-trip por categoria, R neto en gate
- **Fase 2b**: learning loop honesto. `learned_weights` + `learning_gate` re-apuntados al realized-R via `realized_feature_lessons`

### Infra v2.7.0: DB fuera de iCloud

`SQLITE_PATH=C:/Users/xxxv4/trading_data/trading_alert_ai.db`. iCloud causaba contencion brutal (tests 1h42m, learning sin terminar).

---

## Commits clave (referencia rapida)

| Commit | Version | Que |
|---|---|---|
| `fd59478` | **v2.7.1** | **realized_pnl_today filtra paper-only trades** |
| `0cc27d6` | v2.7.0 | Fase 2b: learning honesto (realized-R) |
| `f32db0e` | v2.7.0 | Bump app_version default |
| `ba51599` | v2.7.0 | Cost model |
| `3f0b48e` | v2.7.0 | Realized-R + promotion gate |
| `9fc0575` | v2.6.9 | /gate_preview |
| `ac18442` | v2.6.8 | notional + cooldown |
| `14e5cbe` | v2.6.7 | MT5 Reconciler |
| `1a69630` | v2.6.6 | scalping_mean_reversion + multi-strategy |
| `cb01305` | v2.6.5 | 3 bugs overnight validation |

---

## Tests verdes por version

| Version | Tests | Delta |
|---|---|---|
| v2.6.5 | 307 | base |
| v2.6.6 | 323 | +16 |
| v2.6.7 | 338 | +15 |
| v2.6.8 | 352 | +14 |
| v2.6.9 | 357 | +5 |
| v2.7.0 | 397 | +40 |
| **v2.7.1** | **402** | **+5** |

---

## Links relacionados

- [[14 - Estado Actual v2.7.0]] - snapshot actual
- [[16 - Bugs Resueltos]] - saga de fixes
- [[17 - Promotion Gate y Cost Model]] - core de v2.7.0
- [[18 - Realized R y Aprendizaje Honesto]] - Fase 2b
