---
tags: [database, schema, tablas, sqlite]
version: v2.7.0
updated: 2026-05-30
---

# Schema de Base de Datos

> [!info] SQLite local
> Path: `C:\Users\xxxv4\trading_data\trading_alert_ai.db` (post v2.7.0). Thread-safe via `get_connection` per call. Migraciones via `_ensure_column` (idempotente, backward-compat).

---

## 18 tablas (v2.7.0)

| Tabla | Que guarda | Volumen actual |
|---|---|---|
| `tokens` | Universo simbolos monitoreados, ultimo estado | ~500 |
| `alerts` | Cada vez que el bot decide alertar | ~700 |
| `price_snapshots` | Historico precios (retencion 30 dias) | ~50k |
| `signal_outcomes` | Outcome por alert_id a horizonte fijo | ~507k |
| `alert_outcome_horizons` | Outcomes por horizonte (1h/6h/24h/7d) | ~100k |
| `strategy_lessons` | Agregado por (feature, category) — path drift | ~63 |
| `paper_trades` | Trades simulados | ~901 |
| `demo_trade_requests` | Solicitudes pendientes orden demo | ~50 |
| `demo_orders` | Ordenes enviadas a MT5 demo | ~170+ |
| `bot_state` | Key-value para estados persistentes | ~15 keys |
| `daily_pnl_log` | Historial diario PnL realizado | ~10 |
| `macro_snapshots` | VIX/DXY/SPY/regime | ~200 |
| `economic_events` | Calendario ForexFactory | ~50 |
| `news_articles` | Headlines guardados | ~varies |
| `sec_filings` | SEC EDGAR | ~varies |
| `training_runs` | Log cada `run_learning_cycle` | ~varies |
| `data_quality_log` | Eventos data quality monitor | ~varies |
| **`strategy_performance`** | **Realized-R por (strategy_name, category)** — v2.7.0 | ~10 |
| **`realized_feature_lessons`** | **Realized-R por feature** — v2.7.0 Fase 2b | ~varies |
| `walk_forward_results` | Walk-forward backtests | ~varies |
| `mt5_historical_cache` | Cache OHLCV local | ~varies |
| `security_checks` | GoPlus checks cripto | ~varies |

---

## Tablas principales

### `paper_trades`

PK: `id` autoincrement.

Columnas clave:
- `alert_id` — link a `alerts` (0 si scalping)
- `token_id` — link a `tokens`
- `category` — memecoin/stock/forex/gold
- `chain`, `token_address`, `symbol`
- `entry_price`, `latest_price`
- `stop_loss`, `take_profit_1`, `take_profit_2`
- `original_stop_loss` — preservado para risk_at_entry calc
- `status` — `open` o `closed_*`
- `unrealized_return_pct`, `mfe_pct`, `mae_pct`
- `direction` — long/short
- `time_horizon_hours`, `size_notional`, `size_units`, `risk_pct`
- `strategy_name`
- `partial_closed`, `trailing_active`
- `account_balance_at_open`
- `opened_at`, `updated_at`, `closed_at`
- **`is_scalping`** (v2.6.0) — 0 swing, 1 scalping

Status posibles:
- `open`
- `stopped_simulated` (hit SL)
- `target_2_simulated` (hit TP2)
- `closed_by_time` (time exit)
- `closed_force_exit_timeout` (scalping force exit)
- `closed_invalidated`
- `closed_by_kill_switch`

### `signal_outcomes`

PK: `alert_id` (UNIQUE — permite scalping con `-paper_trade.id`).

- `token_id`, `category`, `symbol`
- `entry_price`, `latest_price`
- `observed_return_pct` — drift de alerta
- `score`, `confidence`
- `outcome_label` — win/loss/neutral por threshold absoluto
- `age_minutes`
- `features` (JSON)
- `evaluated_at`
- **`is_scalping`** (v2.6.0)

### `alert_outcome_horizons`

Outcomes por horizonte fijo:
- `alert_id` + `horizon_hours` PK
- `entry_price`, `exit_price`, `return_pct`
- `mfe_pct`, `mae_pct`
- `snapshots_used`
- `outcome_label`, `status`

### `strategy_lessons` (path drift)

PK: `(feature, category)` UNIQUE.

- `sample_count`, `win_rate`, `avg_return_pct`
- `avg_score`, `confidence`
- `lesson` (texto humano)
- `updated_at`
- **`is_scalping`** (v2.6.0)

Para scalping: `category = "{cat}_scalping"` (ej. `forex_scalping`).

### `strategy_performance` (v2.7.0)

PK: `(strategy_name, category)` UNIQUE.

- `sample_count` — trades no-artifact
- `avg_r_net` — expectancy neta costos
- `win_rate`, `loss_rate`, `scratch_rate`
- `arts_excl` — artifacts excluidos
- `updated_at`

Refrescada por `_refresh_strategy_performance` cada learning cycle.

### `realized_feature_lessons` (v2.7.0 Fase 2b)

PK: `feature`.

- `sample_count`
- `avg_r_net`
- `win_rate` (R > 0)
- `updated_at`

Construida por `build_realized_feature_lessons`: junta paper_trade cerrado → R → features del alert linkeado desde signal_outcomes.

---

## Tablas execution

### `demo_trade_requests`

- `id` PK
- `paper_trade_id` — link
- `symbol`, `direction`, `volume`
- `entry_price`, `stop_loss`, `take_profit`
- `risk_pct`, `strategy_name`
- `status` — pending/sent/failed/expired
- `reason`, `request_summary`
- `created_at`, `expires_at`, `confirmed_at`, `sent_at`
- `result_message`

### `demo_orders`

- `id` PK
- `demo_request_id` — link (0 si scalping)
- `paper_trade_id` — link
- `symbol`, `direction`, `volume`
- `price` (executed), `stop_loss`, `take_profit`
- `retcode`, `order_ticket`, `deal_ticket`
- `status` — sent/failed
- `strategy_name`, `result_summary`
- `sent_at`
- **`is_scalping`** (v2.6.0)

---

## `bot_state` (key-value)

Estados persistentes entre arranques.

Keys actuales:

| Key | Tipo | Que |
|---|---|---|
| `kill_switch_active_until` | ISO timestamp | Cuando expira el kill switch |
| `kill_switch_reason` | text | Razon humana |
| `demo_trading_halted` | bool string | Halt manual demo |
| `scalping_halted` | bool string | Halt manual scalping |
| `scalping_active` | bool string | Override del scalping flag |
| `bot_mode_active` | text | trader/alerts_only/hybrid |
| `account_balance` | float string | Ultimo equity MT5 cached |
| `alerts_paused` | bool string | Pausa alertas Telegram |
| `calendar_last_refresh_iso` | ISO timestamp | Ultimo refresh ForexFactory |
| `macro_last_capture_iso` | ISO timestamp | Ultimo macro snapshot |
| `obsidian_memory_last_date` | YYYY-MM-DD | Ultima escritura daily |
| `obsidian_weekly_last_date` | YYYY-MM-DD | Ultima escritura weekly |
| `snapshots_last_purge` | ISO timestamp | Ultimo purge price_snapshots |
| `telegram_last_update_id` | int string | Ultimo update Telegram procesado |

---

## Tablas auxiliares

### `daily_pnl_log`

PK: `date`. Para equity curve.
- `realized_pnl_pct`, `realized_pnl_usd`
- `trades_closed`, `trades_opened`
- `kill_switch_triggered`, `kill_switch_reason`
- `starting_equity`, `ending_equity`
- `updated_at`

### `macro_snapshots`

Cada hora: VIX/DXY/SPY/regime.

### `economic_events`

ForexFactory calendario: currency, event_name, impact, event_time, source, fetched_at.

### `training_runs`

Log de cada `run_learning_cycle`:
- `alerts_evaluated`, `outcomes_created`, `lessons_updated`
- `paper_trades_created`
- `horizons_created`, `horizons_updated`
- `summary`, `run_at`

---

## Indexes importantes

- `idx_alerts_token_created` ON `alerts(token_id, created_at)` — para fetch_alerts_for_learning
- `idx_signal_outcomes_alert_id` UNIQUE ON `signal_outcomes(alert_id)` — para upsert
- `idx_strategy_lessons_feature_cat` UNIQUE ON `strategy_lessons(feature, category)` — para upsert
- `idx_paper_trades_status` ON `paper_trades(status)` — queries open/closed
- `idx_strategy_performance` UNIQUE ON `strategy_performance(strategy_name, category)` — v2.7.0
- `idx_paper_trades_symbol_opened` ON `paper_trades(symbol, opened_at)` — para per-symbol cooldown v2.6.8

---

## Migraciones (backward-compat)

Todas las columnas nuevas se agregan via `_ensure_column(connection, table, col, type)` en `init_db`. Idempotente: si la columna existe, no hace nada. **Nunca DROP de columnas**.

Patrón:
```python
def _ensure_column(connection, table, column, sqltype):
    cols = [r[1] for r in connection.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sqltype}")
```

Tablas nuevas v2.7.0:
- `strategy_performance` — creada via `CREATE TABLE IF NOT EXISTS`
- `realized_feature_lessons` — creada via `CREATE TABLE IF NOT EXISTS`

Columnas nuevas v2.6.0:
- `paper_trades.is_scalping`
- `demo_orders.is_scalping`
- `signal_outcomes.is_scalping`
- `strategy_lessons.is_scalping`

---

## Queries utiles

### Stats por strategy hoy

```sql
SELECT strategy_name, category, COUNT(*) as n,
       ROUND(AVG(unrealized_return_pct), 2) as avg_ret,
       SUM(CASE WHEN unrealized_return_pct < 0 THEN 1 ELSE 0 END) as losers,
       SUM(CASE WHEN unrealized_return_pct > 0 THEN 1 ELSE 0 END) as winners
FROM paper_trades
WHERE substr(closed_at, 1, 10) = date('now')
GROUP BY strategy_name, category
ORDER BY avg_ret;
```

### bot_state actual

```sql
SELECT key, value, updated_at FROM bot_state ORDER BY key;
```

### Lessons aprendidas swing top 10

```sql
SELECT feature, category, sample_count, win_rate, avg_return_pct, lesson
FROM strategy_lessons
WHERE category NOT LIKE '%_scalping'
ORDER BY sample_count DESC
LIMIT 10;
```

### Strategy performance (v2.7.0)

```sql
SELECT strategy_name, category, sample_count, avg_r_net, win_rate, arts_excl
FROM strategy_performance
ORDER BY sample_count DESC;
```

### MT5 orders huerfanas (sospecha)

```sql
SELECT d.symbol, COUNT(*) as n_orders,
       SUM(CASE WHEN p.status = 'open' THEN 1 ELSE 0 END) as paper_open
FROM demo_orders d
LEFT JOIN paper_trades p ON p.id = d.paper_trade_id
WHERE d.status = 'sent' AND substr(d.sent_at, 1, 7) = '2026-05'
GROUP BY d.symbol
HAVING n_orders > paper_open;
```

---

## Inspeccion via sqlite3 CLI

```powershell
sqlite3 "C:\Users\xxxv4\trading_data\trading_alert_ai.db" ".tables"
sqlite3 "C:\Users\xxxv4\trading_data\trading_alert_ai.db" ".schema paper_trades"
sqlite3 "C:\Users\xxxv4\trading_data\trading_alert_ai.db" ".mode column" ".headers on" "SELECT * FROM bot_state"
```

---

## Backups

DB activa esta en `C:\Users\xxxv4\trading_data\trading_alert_ai.db`.

Backup pre-v2.7.0 congelado en `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\trading_alert_ai.db` (NO borrar todavia).

Para backups regulares:
```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmm"
Copy-Item "C:\Users\xxxv4\trading_data\trading_alert_ai.db" "C:\Users\xxxv4\trading_data\backup_$ts.db"
```

---

## Links relacionados

- [[19 - Arquitectura del Sistema]] - file structure
- [[10 - Learning Engine]] - como se usa
- [[17 - Promotion Gate y Cost Model]] - strategy_performance
- [[18 - Realized R y Aprendizaje Honesto]] - realized_feature_lessons
- [[22 - Setup y Operacion]] - queries practicos
