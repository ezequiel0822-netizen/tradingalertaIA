---
tags: [learning, engine, outcomes, lessons]
version: v2.7.0
updated: 2026-05-30
---

# Learning Engine

> [!info] Objetivo
> Aprender de outcomes historicos: que features ayudan, que strategies funcionan, ajustar scoring para futuros signals.

---

## Componentes

```
Alert (con features) 
    ↓
Espera horizon (1h, 6h, 24h, 7d)
    ↓
Calcula drift y realized return
    ↓
signal_outcomes (drift de alerta)        ← Path original (siempre activo)
paper_trades.realized_pnl                ← Path v2.7.0 (realized-R)
    ↓
Agregacion por feature + categoria
    ↓
strategy_lessons (drift)
strategy_performance (realized-R)        ← v2.7.0
realized_feature_lessons (realized-R)    ← Fase 2b
    ↓
learned_weights (ajusta score)
learning_gate (filtra signals - opt-in)
```

---

## Tablas

### `signal_outcomes`

Outcome por (alert_id) a horizonte fijo:
- `observed_return_pct` — drift de la alerta
- `outcome_label` — win/loss/neutral segun `OUTCOME_WIN_RETURN_*_PCT`
- `age_minutes`, `features`, `evaluated_at`
- **`is_scalping`** (v2.6.0)
- Para scalping: `alert_id = -paper_trade.id` (negativo para no colisionar)

### `strategy_lessons` (path drift)

Agregado por `(feature, category)`:
- `sample_count`, `win_rate`, `avg_return_pct`
- `avg_score`, `confidence`, `lesson` (texto humano)
- Categoria para scalping: `{cat}_scalping`

### `strategy_performance` (v2.7.0, path realized)

Agregado por `(strategy_name, category)`:
- `sample_count`, `avg_r`, `win_rate`
- `expectancy_r_net` (despues de cost model)
- `arts_excl` (artifacts excluidos)
- Refrescada cada learning cycle por `_refresh_strategy_performance`

### `realized_feature_lessons` (v2.7.0 Fase 2b)

Agregado por `feature` (similar a strategy_lessons pero con realized-R):
- `sample_count`, `avg_r_net`
- Construida por `build_realized_feature_lessons` (junta paper_trade cerrado → R → features del alert linkeado)
- Refrescada cada learning cycle

### `alert_outcome_horizons`

Outcome por horizonte (1h, 6h, 24h, 7d):
- `horizon_hours`, `entry_price`, `exit_price`, `return_pct`
- `mfe_pct`, `mae_pct`, `snapshots_used`
- `outcome_label`, `status`

---

## Learning cycle (en cada ciclo del bot)

1. Fetch alerts que cumplen `LEARNING_MIN_ALERT_AGE_MINUTES`
2. Para cada alert: calcula outcome (drift + horizontes)
3. Upsert `signal_outcomes`
4. Compute aggregates → upsert `strategy_lessons`
5. **v2.7.0:** refresca `strategy_performance` por paper_trades cerrados
6. **v2.7.0 Fase 2b:** refresca `realized_feature_lessons`
7. Si `ENABLE_LEARNED_WEIGHTS=true`: aplica weights a alerts futuros

Cap: `LEARNING_MAX_ALERTS_PER_RUN=500`.

---

## Outcome thresholds

Recalibrados v2.6.5 (user):
- `OUTCOME_WIN_RETURN_MEMECOIN_PCT=30` (era 100)
- `OUTCOME_LOSS_RETURN_MEMECOIN_PCT=-15` (era -40)
- `OUTCOME_WIN_RETURN_STOCK_PCT=5`
- `OUTCOME_LOSS_RETURN_STOCK_PCT=-3`

> [!warning] Siguen muy estrictos para el gate
> Casi nada hit eso → ~99% outcomes 'neutral'. Por eso el path drift es poco util. v2.7.0 Fase 2b re-apunta el learning al realized-R que es mas honesto.

---

## Learned weights

`ENABLE_LEARNED_WEIGHTS=true` (user activo desde v2.6.5).

Ajusta score base segun `(feature, category, win_rate)`:
- Sample >= `LEARNED_WEIGHTS_MIN_SAMPLES=5`
- Confidence >= `LEARNED_WEIGHTS_MIN_CONFIDENCE=40`
- Bump max por feature: `LEARNED_WEIGHTS_PER_FEATURE_MAX=3.0`
- Bump total max: `LEARNED_WEIGHTS_MAX_ADJUSTMENT=10.0`

**v2.7.0 Fase 2b:** con `ENABLE_REALIZED_LEARNING=true`, los weights leen de `realized_feature_lessons` (P&L real) en vez de `strategy_lessons` (drift). Fallback al drift si flag off.

---

## Learning gate

`ENABLE_LEARNING_GATE=false` (NO activar, ver [[05 - Alertas y Scoring]]).

Cuando se active: para cada signal nuevo, busca features `category:`, `alert:`, `score:` y backtest historico. Si `win_rate < LEARNING_GATE_MIN_WIN_RATE` con `N >= LEARNING_GATE_MIN_SAMPLES` en `LEARNING_GATE_SINCE_DAYS`, BLOQUEA.

**v2.7.0 Fase 2b:** `_evaluate_gate_realized` consulta `realized_feature_lessons` si `ENABLE_REALIZED_LEARNING=true`. Drift path queda como fallback.

`FORCE_LEARNING_GATE_FOR_MEMECOIN=true` — memecoin SIEMPRE pasa por el gate.

---

## Walk-forward backtest

`ENABLE_WALK_FORWARD_BACKTEST=true` (activo).

Settings:
- `WALK_FORWARD_TRAIN_DAYS=14`
- `WALK_FORWARD_TEST_DAYS=7`
- `WALK_FORWARD_SLIDE_DAYS=1`
- `WALK_FORWARD_MIN_TRAIN_SAMPLES=10`

Cada ciclo: entrena reglas en ventana de 14 dias, valida en siguientes 7, desliza 1 dia. Output en `walk_forward_results`.

Util para: detectar reglas que ganan in-sample pero no out-of-sample (overfitting).

---

## Backtester

`backtest_strategy(repository, filter_features, horizon_hours, since_days, category)` — backtest historico por features. Output: BacktestResult con `sample_count`, `win_rate`, `avg_return_pct`, `median_return_pct`, `avg_mfe_pct`, `avg_mae_pct`, `max_drawdown_pct`, `sharpe_approx`, `equity_curve`.

`rank_top_strategies(...)` — rankea features por sharpe + win_rate + sample_count.

Usado por `/backtest`, `/gate_preview`, scripts diagnostic.

---

## Horizon evaluator

`HORIZONS = (1, 6, 24, 168)` horas. Cada alert se evalua a esos horizonts.

Util para: detectar que strategies son momentum (mejor a 1-6h) vs swing (mejor a 24-168h).

---

## Lessons separadas swing vs scalping

Decision v2.6.0: scalping outcomes van a category `{cat}_scalping`:
- swing forex → `forex`
- scalping forex → `forex_scalping`

No mezclan. Porque:
- Scalping cierra al close del trade (no por horizon)
- Tiempo de vida 10s-3min vs swing 1-48h
- Aprenden distinto

---

## v2.7.0 - realized-R como senal principal

> [!success] Decision arquitectonica
> Antes el learning aprendia del **drift** (cambio de precio entre alerta y horizonte fijo). Ahora aprende del **P&L realizado** de paper_trades cerrados (con direccion correcta, partial close, neto de costos).

Ver [[18 - Realized R y Aprendizaje Honesto]] para detalle de la implementacion.

---

## Comandos relacionados

- `/aprendizaje` — lessons swing y scalping separadas
- `/horizontes SIMBOLO` — performance por horizonte
- `/backtest` — backtest historico
- `/gate_preview` — preview de impacto si activas gate
- `/expectancy` — strategy_performance (realized-R) con LIVE/SHADOW
- `/entrenar` — fuerza un learning cycle

---

## Links relacionados

- [[17 - Promotion Gate y Cost Model]] - como se conecta al trading
- [[18 - Realized R y Aprendizaje Honesto]] - Fase 2b detail
- [[05 - Alertas y Scoring]] - como impacta el scoring
- [[13 - Comandos Telegram]] - comandos de learning
- [[20 - Schema de Base de Datos]] - tablas
