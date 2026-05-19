# Learning Engine

## Objetivo

Preparar a Trading Alert AI para pensar como un sistema de trading profesional. Hasta Phase 5 sigue read-only (paper trades + lecciones). Phase 5 lo conecta a demo MT5.

## Que aprende

- que tipos de alerta terminan mejor
- que features ayudan: IA Pro, patron tecnico, noticias, filings, volumen, liquidez
- que features castigan: anti-hype, baja liquidez, riesgo critico, catalizador negativo
- que setups merecen simulacion en papel
- (v1.6.0) que horizontes son mas confiables por categoria
- (v1.6.0) que combinaciones de features dan mejor sharpe en backtest
- (v1.7.0) si los pesos aprendidos mejoran el score base
- (v2.0.0) que strategies (breakout/mean_reversion/momentum/news_catalyst) funcionan mejor

## Tablas

- `signal_outcomes`: compara precio de alerta contra precio actual guardado.
- `strategy_lessons`: resume features ganadoras o peligrosas (con win_rate, sample_count, confidence).
- `alert_outcome_horizons` (v1.6.0): outcomes por horizonte 1h/6h/24h/7d con return_pct + MFE + MAE.
- `price_snapshots` (v1.6.0): historial de precios para calcular MFE/MAE durante la ventana.
- `paper_trades`: setups simulados — desde v2.0.0 tienen strategy_name, direction, size_notional, risk_pct, partial_closed.
- `daily_pnl_log` (v2.0.0): P&L diario, kill_switch triggers, equity inicial/final.
- `training_runs`: bitacora de entrenamientos.

## Comandos

```text
/aprendizaje
/paper
/entrenar
/horizontes SIMBOLO
/backtest [24h] [features]
/portfolio
/posiciones
/strategies
```

## Modulos clave

### Horizon evaluator (v1.6.0)

`app/learning/horizon_evaluator.py` evalua cada alerta a 1h/6h/24h/7d. Persiste en `alert_outcome_horizons` con `outcome_label`, `return_pct`, `mfe_pct`, `mae_pct`.

### Backtester (v1.6.0)

`app/learning/backtester.py` con dos modos:
- `backtest_strategy(features, horizon)` mide una combinacion AND.
- `rank_top_strategies(horizon)` enumera combinaciones (singletons + pares predefinidos), devuelve top por sharpe aproximado.

### Learned weights (v1.7.0, OFF por default)

`app/analyzers/learned_weights.py` ajusta el score base con `strategy_lessons`. Bonus/malus por feature con clamp duro ±10. Activar con `ENABLE_LEARNED_WEIGHTS=true` despues de revisar `/aprendizaje`.

### Learning gate (v1.7.0, OFF por default)

`app/analyzers/learning_gate.py` consulta al backtester antes de enviar alerta. Si win_rate historico < umbral con muestras suficientes, bloquea envio. Activar con `ENABLE_LEARNING_GATE=true`.

### Strategy router (v2.0.0)

`app/strategies/` con 4 estrategias nombradas + router. Cada strategy decide direction, entry, stop, targets, time horizon. El router filtra por `STRATEGY_MIN_CONFIDENCE`.

### Lifecycle manager (v2.0.0)

`app/learning/lifecycle_manager.py` gestiona posiciones abiertas:
- Refresca latest_price (MT5 si disponible).
- Actualiza MFE/MAE + trailing stop.
- Cierra trades por time horizon.
- Partial close en TP1 (50% size + stop a breakeven).
- Soporta short.

## Regla

El aprendizaje no compra, no vende y no ejecuta ordenes en cuenta real. Hasta Phase 5 todo es simulado. Phase 5 conecta a demo MT5 (no real-money).

## Criterio de readiness (legacy v1.5.2)

- `A`: setup fuerte para revisar manualmente
- `B`: setup interesante, necesita confirmacion
- `C`: watchlist
- `D`: bajo interes
- `BLOCKED`: no simular por riesgo o datos insuficientes

Desde v2.0.0 el readiness sigue como filtro inicial, pero el **strategy router** es el que decide si crear paper trade.

## Status values de paper_trades

- `open`
- `stopped_simulated`
- `target_2_simulated`
- `closed_by_time` (v2.0.0)
- `closed_by_invalidation` (v2.0.0)
- `closed_by_strategy_exit` (v2.0.0)
- `closed_by_kill_switch` (v2.0.0)
- `partial_tp1` (v2.0.0, transicional)

## Risk controls (v2.0.0)

Antes de cualquier paper trade nuevo:

1. Kill switch activo? → bloquea
2. `max_open_trades_total` alcanzado (default 5)? → bloquea
3. `max_open_trades_{category}` alcanzado (3 stock / 4 forex / 2 gold)? → bloquea
4. `max_total_risk_pct` excedido (default 6%)? → bloquea
5. `daily_pnl < -max_daily_drawdown_pct` (default 3%)? → activa kill switch automatico

Default `risk_per_trade_pct=1.0%`. Safety cap a 10% en `calculate_position_size` (v2.1.0).
