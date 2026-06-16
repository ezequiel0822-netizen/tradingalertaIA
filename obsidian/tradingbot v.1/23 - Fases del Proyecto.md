---
tags: [fases, roadmap, status, donde-estamos]
version: v3.6.0
updated: 2026-06-14
---

# Fases del Proyecto

> [!success] Donde estamos hoy — v3.6.0 (2026-06-14)
> Sobre la base v2.7.0 (medición honesta) se construyó la **serie v3**: capa LLM local
> subtractiva (asesor / ensemble veto / resumen diario / ContinuousLearner), `/performance`
> y `/readiness`, exit shadow, calendar gate + cap USD, y en **v3.6.0 el Backtest Replay
> Harness** (offline, `app/backtest/`). El harness corrió las estrategias REALES sobre
> décadas de D1 y confirmó: **ninguna pasa §11** (el +4.7R del `trend_following_d1` fue un
> artefacto). **657 tests verdes.** Real-money sigue bloqueado. **Siguiente: dejar correr
> el libro vivo (data Fase D) + el harness avanza con COT / instrumentos descorrelacionados.**

---

## Mapa visual de fases

```
COMPLETADAS                                  AQUI ESTAS              FUTURO
============================================================================

Phase 1     Phase 2     Phase 2.5    Phase 2.6   Phase 3+3.5   Phase 4
  v1.0       v1.5.2      v2.0.0       v2.1.0      v2.2.0       v2.3.0
[========]  [========]  [========]   [========]  [========]    [========]
Detection   Learning    Trader       Security    Macro+LLM     MT5+WF
 MVP        Engine      Engine       Hardening                 Validation

Phase 4.5    Phase 5      Phase 5.5A    Phase 5.5B
  v2.4.0      v2.5.0       v2.5.4        v2.6.0
[========]   [========]   [========]    [========]
Memecoin     order_send   Auto-confirm  Scalping
Hunter Pro   demo MT5     opt-in        Engine

Sprint 27-28 may          v2.7.0           v2.7.1
v2.6.6-v2.6.9             + Fase 2b        Paper-only filter
[========]                [========]       [#### ESTAS AQUI ####]
Bug fixes                 Realized-R       Kill switch falso fix
                          Promotion gate   (gold GC=F)
                          Cost model

                                                        Phase 6      Phase 7
                                                       Strategy     Collector
                                                       Evolution    RPC blockchain
                                                       [        ]   [        ]

                                                       Phase 8      Phase 9
                                                       Multi-       News/
                                                       timeframe    sentiment
                                                       [        ]   [        ]

                                                       Phase 10
                                                       Real-money
                                                       [LOCKED]
```

---

## Fases COMPLETADAS

### Phase 1 — Detection MVP (v1.0-v1.5)
- DEX Screener + Telegram + SQLite + Streamlit
- MVP read-only puro

### Phase 2 — Learning Engine (v1.5.2)
- `signal_outcomes`, `strategy_lessons`, `paper_trades`
- Aprendizaje sobre drift de alerta

### Phase 2.5 — Trader Engine (v2.0)
- Strategy router (5 swing)
- Portfolio + risk manager + position sizer
- Kill-switch + bot mode toggle
- PIVOT mayor: alerter → trader

### Phase 2.6 — Security Hardening (v2.1)
- `Settings.__repr__` mascarado
- `LogRedactor`, `safe_path`, `safe_json`

### Phase 3 + 3.5 — Macro + LLM (v2.2)
- Macro context (VIX/DXY/SPY)
- Economic calendar (ForexFactory)
- Claude API soft-fail

### Phase 4 — Validation (v2.3)
- MT5 ICMarkets validation
- Walk-forward backtester
- Data quality monitor

### Phase 4.5 — Memecoin Pro + Modes (v2.4)
- Memecoin Hunter Pro (anti-rug, volume velocity)
- Bot Mode Toggle (trader/alerts_only/hybrid)

### Phase 5 — order_send a demo MT5 (v2.5.0)
- `MT5DemoTrader` unico modulo con order_send
- Confirmacion manual obligatoria

### Phase 5.5 Bloque A — Auto-confirm (v2.5.4)
- `ENABLE_AUTO_CONFIRM_DEMO` opt-in

### Phase 5.5 Bloque B — Scalping Engine (v2.6.0)
- Thread dedicado polling 3-5s
- `scalping_breakout` M1
- Lessons separadas swing vs scalping

### Sprint del 27-28 may (v2.6.6-v2.6.9)

Bug fixes post-perdida de $12k:
- **v2.6.6**: scalping_mean_reversion + multi-strategy engine
- **v2.6.7**: MT5Reconciler (cierra huerfanas + sync SL)
- **v2.6.8**: size_notional MT5 real + per-symbol cooldown
- **v2.6.9**: `/gate_preview` Telegram command

---

## AQUI ESTAS - v2.7.0 (deployado 2026-05-30)

> [!success] v2.7.0 MERGEADO + PUSHEADO
> main = origin/main = `0cc27d6`. 397 tests verdes. DB movida fuera de iCloud.

### Que trajo v2.7.0

**Fix A (keystone):** `_update_paper_trades` direction-aware → 86% del historial eran artifacts pre-fix.

**Fix C:** `lifecycle_manager._fresh_price` mapea Yahoo→MT5 antes de `get_tick`.

**Fix D + Promotion Gate:** Nuevo `app/learning/trade_outcomes.py`:
- realized_return + R-multiple direction-aware
- artifact detection
- cost model (round-trip por categoria)
- `should_execute_live` gate
- tabla `strategy_performance`
- comando `/expectancy`

**Cost Model:** resta costo round-trip por categoria del realized-R. Confiable para gate.

**Fase 2b — Learning honesto:** `learned_weights` y `learning_gate` ahora aprenden del P&L realizado (no drift). Tabla nueva `realized_feature_lessons`. Refrescada cada learning cycle.

**Infra:** DB movida a `C:\Users\xxxv4\trading_data\trading_alert_ai.db` (fuera de iCloud).

### Estado actual (al cierre v2.7.0)

| Metrica | Valor |
|---|---|
| Codigo | v2.7.0 |
| Tests | 397 verdes |
| Branch | main pusheada |
| Balance MT5 | ~$88,585 |
| paper_trades | 901 totales (~120 reales post-quarantine) |
| signal_outcomes | 507.681 |
| Strategies con R+ | **0** |
| Strategies LIVE | 9 |
| Strategies SHADOW | 1 (`unknown/stock`) |

### Pendientes inmediatos (lado user)

- [ ] `ENABLE_STRATEGY_FOREX_SESSION_BREAKOUT=false` en `.env` (-0.51R)
- [ ] Validar primer ciclo completo con DB local
- [ ] Borrar `.db` viejo de iCloud (tras dias estables)
- [ ] Cleanup worktree corrupto + branch mergeada

### Que sigue ANTES de Phase 6

> [!warning] Pre-condicion Phase 6
> Phase 6 (Strategy Evolution) requiere **≥1 strategy con R positivo neto**. Hoy todas son negativas. Por eso lo siguiente es ACUMULAR + ENCONTRAR EDGE, no agregar features nuevas.

**v2.7.1 / v2.7.x (proximas semanas):**

1. **Heartbeat diario Telegram** con expectancy + tags LIVE/SHADOW
2. **Slice `strategy_performance` por sesion** (London/NY/Asian) y regimen (risk_on/off) — buscar bolsillos +R
3. **Calibrar cost model** con fills reales de `demo_orders` (no defaults teoricos)
4. **Session-aware lessons** — agregar `current_session` al feature set de scoring
5. **Auto-tune scalping params** segun observacion
6. **Decidir si bajar `STRATEGY_PROMOTION_MIN_SAMPLES`** de 30 → 20

**Recalibracion outcomes:**

- `OUTCOME_WIN_RETURN_MEMECOIN_PCT`: 30 → 10-15 (mas realista)
- `OUTCOME_WIN_RETURN_STOCK_PCT`: 5 → 1.5
- Permite mas trades cuenten como "wins" del threshold absoluto
- `signal_outcomes` original recupera utilidad

**Activacion learning_gate:**

- Hoy `ENABLE_LEARNING_GATE=false`
- Tras recalibrar outcome thresholds, chequear con `/gate_preview`
- Si balance bloqueados/pasa razonable, activar

---

## Fases FUTURAS

### Phase 6 — Strategy Evolution (post-data limpia)

> [!info] BLOQUEADA hasta ≥1 strategy R+

**Que hara:**
- Fitness por strategy (sharpe + win_rate + drawdown + R)
- Mutacion automatica de parametros con base teorica
- Evaluacion via walk-forward

**Pre-condiciones:**
- ≥3 meses de outcomes scalping limpios
- ≥1 strategy con R+ neto consistente
- Cost model calibrado con fills reales

### Phase 7 — Collector RPC blockchain

**Que agrega:**
- `holder_concentration` real (top 10 holders %)
- `liquidity_locked` (lock period, unlock date)
- Smart money tracking (wallets de alta performance)

**Costo:** $30-200/mes (Alchemy, QuickNode, etc).

**Que destrabea:**
- Filter anti-rug mas fuerte para memecoins
- Detection de pump and dump por whale activity

### Phase 8 — Multi-timeframe

**Hoy:** M1 scalping + 60s swing.

**Que agrega:**
- M5 para confirmar scalping entries
- H4 para context de swing
- D1 para regimen macro

**Cambios:**
- `mt5_reader.get_rates` multiple timeframes
- `pattern_analyzer` confluence multi-tf

### Phase 9 — News/sentiment real-time

**Hoy:** Yahoo RSS (lento, 500 esporadicos).

**Que agrega:**
- X (Twitter) API ($100/mes) — sentiment per ticker
- Reddit PRAW — sentiment de subreddits financieros
- Investing.com / Benzinga — earnings calendars + tier de noticias

### Phase 10 — Real-money trading

> [!danger] BLOQUEADO HARDCODED
> Requiere:
> - 3+ meses de demo estable (sharpe > 1, win_rate > 50%, maxDD < 10%)
> - Autorizacion explicita NUEVA del usuario
> - Auditoria de seguridad final
> - Pequeño capital de prueba primero ($500-1000)

`ENABLE_REAL_TRADING=false` HARDCODED en codigo, no solo `.env`.

---

## Quick reference: donde estoy AHORA

```
+----------------------------+
| FASE: v3.6.0 (backtest)    |
+----------------------------+
| TESTS: 657 verdes          |
| BALANCE: ~$88,744          |
| VERSION: v3.6.0           |
| BRANCH: main 05f9731       |
| BOT: listo (.\start_bot)   |
+----------------------------+
| PROXIMO MILESTONE:         |
| data Fase D (70->400) +    |
| edge real (COT/decorrel.)  |
+----------------------------+
| El backtest confirmo: sin  |
| edge en estas estrategias. |
+----------------------------+
```

---

## Resumen 3 lineas

1. **Hoy estamos en:** v3.6.0 (serie v3 completa + Backtest Replay Harness offline). 657 tests verdes. Bot mide la verdad neta de costos en vivo y en backtest.
2. **Siguiente paso:** dejar correr el libro vivo (data Fase D 70→400) + avanzar el harness con COT / instrumentos descorrelacionados (`MAPA_DE_EDGE_Y_RUTA.md`).
3. **Bloqueado:** Phase 6 / Fase E requiere ≥1 strategy con R+ neto + 3 meses. El backtest v3.6.0 confirmó que no hay edge en estas estrategias sobre D1. Real-money HARDCODED OFF.

---

## Links relacionados

- [[14 - Estado Actual v2.7.0]] - snapshot detallado
- [[03 - Versiones y Cambios]] - historia completa
- [[07 - Ideas y Proximos Pasos]] - roadmap detallado
- [[15 - Estrategias]] - stats por strategy
- [[17 - Promotion Gate y Cost Model]] - el cambio de v2.7.0
- [[18 - Realized R y Aprendizaje Honesto]] - Fase 2b detail
