---
tags: [setup, operacion, powershell, queries]
version: v2.7.0
updated: 2026-05-30
---

# Setup y Operacion

> [!info] Recetario de comandos
> Todo lo que necesitas ejecutar a nivel terminal: setup, arranque, validacion, debugging, queries SQL, backups.

---

## Setup inicial (1 vez)

### Pre-requisitos

- Windows 10/11
- Python 3.12.x
- Git
- MetaTrader 5 desktop instalado (cuenta MetaQuotes-Demo creada)
- Telegram Bot creado en BotFather (con TOKEN guardado)

### Clonar / preparar proyecto

```powershell
# Cd a iCloudDrive (o donde tengas el proyecto)
cd C:\Users\xxxv4\iCloudDrive\tradingalertaIA

# Crear venv
python -m venv .venv

# Activar venv
.\.venv\Scripts\Activate.ps1
# Si Windows bloquea: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force

# Instalar deps
pip install -r requirements.txt
```

### Crear `.env` real

```powershell
# Copiar template
Copy-Item .env.example .env

# Editar a mano con notepad o code
notepad .env
```

Variables minimas necesarias:
```
TELEGRAM_BOT_TOKEN=<de BotFather>
TELEGRAM_CHAT_ID=<tu chat id>
MT5_LOGIN=<tu MT5 demo login>
MT5_PASSWORD=<password>
MT5_SERVER=MetaQuotes-Demo
SQLITE_PATH=C:/Users/xxxv4/trading_data/trading_alert_ai.db
APP_VERSION=v2.7.0
```

### Crear path de DB local

```powershell
New-Item -ItemType Directory -Path "C:\Users\xxxv4\trading_data" -Force
```

### Setear BotFather menu

Ver [[13 - Comandos Telegram]] seccion "Setup en BotFather".

---

## Operacion diaria

### Arrancar

```powershell
cd C:\Users\xxxv4\iCloudDrive\tradingalertaIA
.\.venv\Scripts\Activate.ps1  # si terminal nueva
.\.venv\Scripts\python.exe main.py
```

> [!warning] MT5 desktop debe estar abierto
> Sino, bot corre degradado (sin order_send, sin reconciler).

### Modos alternativos

```powershell
# Un solo ciclo (smoke test)
.\.venv\Scripts\python.exe main.py --once

# Solo alertas, sin trader
.\.venv\Scripts\python.exe main.py --mode alerts_only --once
```

### Parar

`Ctrl+C` en la terminal donde corre. Espera ~5s a que el scalping thread cierre limpio.

### Background

Si queres en background (no recomendado para debugging):
```powershell
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "main.py" -RedirectStandardOutput "bot.log" -RedirectStandardError "bot.err.log" -NoNewWindow
```

---

## Tests

### Suite completo

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
# Esperado: 397 passed in ~60s con DB local (era 1h42m con iCloud)
```

### Tests verbose con setup

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v --tb=short
```

### Solo tests de un area

```powershell
# v2.7.0 specific
.\.venv\Scripts\python.exe -m pytest tests/test_trade_outcomes.py tests/test_strategy_promotion_gate.py tests/test_cost_model.py tests/test_expectancy_command.py tests/test_realized_learning.py -v

# v2.6.7 (reconciler)
.\.venv\Scripts\python.exe -m pytest tests/test_mt5_reconciler.py -v

# v2.6.8 (notional + cooldown)
.\.venv\Scripts\python.exe -m pytest tests/test_v268_v269.py -v

# Scalping
.\.venv\Scripts\python.exe -m pytest tests/test_scalping_*.py -v
```

### Test individual

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mt5_reconciler.py::test_reconciler_closes_orphan_when_paper_trade_closed -v
```

### Coverage

```powershell
pip install pytest-cov
.\.venv\Scripts\python.exe -m pytest tests/ --cov=app --cov-report=html
# Abrir htmlcov/index.html
```

---

## Validacion post-arranque

### Settings cargan OK

```powershell
.\.venv\Scripts\python.exe -c "from app.config.settings import load_settings; s=load_settings(); print('Version:', s.app_version); print('Real trading:', s.enable_real_trading); print('Demo:', s.enable_mt5_demo_trading); print('Scalping:', s.enable_scalping_engine); print('Gate:', s.enable_strategy_promotion_gate); print('Cost model:', s.enable_cost_model); print('Realized learning:', s.enable_realized_learning); print('DB path:', s.sqlite_path)"
```

Esperado v2.7.0:
```
Version: v2.7.0
Real trading: False
Demo: True
Scalping: True
Gate: True
Cost model: True
Realized learning: True
DB path: C:\Users\xxxv4\trading_data\trading_alert_ai.db
```

### MT5 conexion OK

```powershell
.\.venv\Scripts\python.exe -c "from app.config.settings import load_settings; from app.brokers.mt5_reader import MT5Reader; s = load_settings(); r = MT5Reader(s); r.connect(); info = r.get_account_info(); print('Login:', info.get('login')); print('Balance:', info.get('balance')); print('Server:', info.get('server')); r.disconnect()"
```

Esperado:
```
Login: 10010956946
Balance: 88585.74
Server: MetaQuotes-Demo
```

---

## Inspeccion DB

### sqlite3 CLI

```powershell
$DB = "C:\Users\xxxv4\trading_data\trading_alert_ai.db"

# Listar tablas
sqlite3 $DB ".tables"

# Schema de una tabla
sqlite3 $DB ".schema paper_trades"

# Counts por tabla
sqlite3 $DB ".mode column" ".headers on" "SELECT name, (SELECT COUNT(*) FROM sqlite_master WHERE type='table') as total FROM sqlite_master WHERE type='table'"

# bot_state actual
sqlite3 $DB ".mode column" ".headers on" "SELECT key, value, updated_at FROM bot_state ORDER BY key"
```

### Queries comunes

#### Stats por strategy ultimo dia

```powershell
sqlite3 $DB ".mode column" ".headers on" "SELECT strategy_name, category, COUNT(*) as n, ROUND(AVG(unrealized_return_pct), 2) as avg_ret, SUM(CASE WHEN unrealized_return_pct < 0 THEN 1 ELSE 0 END) as losers, SUM(CASE WHEN unrealized_return_pct > 0 THEN 1 ELSE 0 END) as winners FROM paper_trades WHERE substr(closed_at, 1, 10) = date('now') GROUP BY strategy_name, category ORDER BY avg_ret"
```

#### Strategy performance (v2.7.0)

```powershell
sqlite3 $DB ".mode column" ".headers on" "SELECT strategy_name, category, sample_count, ROUND(avg_r_net, 3) as avg_r, ROUND(win_rate * 100, 1) as win_pct, arts_excl FROM strategy_performance ORDER BY sample_count DESC"
```

#### Lessons aprendidas swing top 10

```powershell
sqlite3 $DB ".mode column" ".headers on" "SELECT feature, category, sample_count, ROUND(win_rate * 100, 1) as win_pct, ROUND(avg_return_pct, 2) as avg_ret FROM strategy_lessons WHERE category NOT LIKE '%_scalping' ORDER BY sample_count DESC LIMIT 10"
```

#### Worst trades hoy (USD)

```powershell
sqlite3 $DB ".mode column" ".headers on" "SELECT id, symbol, strategy_name, ROUND(unrealized_return_pct, 2) as ret_pct, ROUND(size_notional, 0) as notional, ROUND(size_notional * unrealized_return_pct / 100.0, 0) as pnl_usd FROM paper_trades WHERE substr(closed_at, 1, 10) = date('now') ORDER BY pnl_usd ASC LIMIT 10"
```

#### Best trades hoy

```powershell
sqlite3 $DB ".mode column" ".headers on" "SELECT id, symbol, strategy_name, ROUND(unrealized_return_pct, 2) as ret_pct, ROUND(size_notional, 0) as notional, ROUND(size_notional * unrealized_return_pct / 100.0, 0) as pnl_usd FROM paper_trades WHERE substr(closed_at, 1, 10) = date('now') ORDER BY pnl_usd DESC LIMIT 10"
```

#### Posiciones MT5 orphan-check

```powershell
sqlite3 $DB ".mode column" ".headers on" "SELECT d.symbol, COUNT(*) as n_orders, SUM(CASE WHEN p.status = 'open' THEN 1 ELSE 0 END) as paper_open FROM demo_orders d LEFT JOIN paper_trades p ON p.id = d.paper_trade_id WHERE d.status = 'sent' AND substr(d.sent_at, 1, 7) = strftime('%Y-%m', 'now') GROUP BY d.symbol HAVING n_orders > paper_open"
```

Si retorna filas, hay potenciales huerfanas (mas orders enviadas que paper_trades abiertos para ese simbolo).

---

## Limpiar kill switch manualmente

Si el kill switch dispara y necesitas operar antes de las 24h:

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; conn = sqlite3.connect(r'C:\Users\xxxv4\trading_data\trading_alert_ai.db'); conn.execute(\"UPDATE bot_state SET value='' WHERE key='kill_switch_active_until'\"); conn.execute(\"UPDATE bot_state SET value='' WHERE key='kill_switch_reason'\"); conn.commit(); print('Kill switch limpio')"
```

> [!warning] Verificar antes
> Antes de limpiar, asegurarse que `realized_pnl_today` no este excediendo `MAX_DAILY_DRAWDOWN_PCT` — sino se re-dispara inmediato.

---

## Backups

### Backup manual

```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmm"
Copy-Item "C:\Users\xxxv4\trading_data\trading_alert_ai.db" "C:\Users\xxxv4\trading_data\backup_$ts.db"
```

### Restore

```powershell
# DETENER bot primero
# Despues:
Copy-Item "C:\Users\xxxv4\trading_data\backup_YYYYMMDD_HHMM.db" "C:\Users\xxxv4\trading_data\trading_alert_ai.db" -Force
```

### Cron de backups (Task Scheduler)

Crear tarea programada que corra cada 6h:
```powershell
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-Command Copy-Item 'C:\Users\xxxv4\trading_data\trading_alert_ai.db' \"C:\Users\xxxv4\trading_data\backup_$(Get-Date -Format yyyyMMdd_HHmm).db\""
$trigger = New-ScheduledTaskTrigger -Daily -At 6AM
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "TradingAlertAI Backup"
```

---

## Git operations

### Status del proyecto

```powershell
cd C:\Users\xxxv4\iCloudDrive\tradingalertaIA
git status
git log --oneline -10
```

### Pull cambios

```powershell
git pull origin main
# Despues correr pytest para validar
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

### Branch local para experimentar

```powershell
git checkout -b experiment/mi-idea
# Hacer cambios
git add archivos
git commit -m "experimento: descripcion"

# Si funciona:
git checkout main
git merge experiment/mi-idea
# Si no:
git checkout main
git branch -D experiment/mi-idea
```

---

## Cleanup pendientes

### Worktree corrupto

```powershell
cd C:\Users\xxxv4\iCloudDrive\tradingalertaIA
Remove-Item -Force .claude\worktrees\reverent-curie-7ccc75
git worktree prune
```

### Branch ya mergeada

```powershell
git branch -d claude/xenodochial-taussig-4206c6
```

### DB vieja de iCloud (despues de dias estables)

```powershell
# Verificar primero que el bot lleva dias OK con la DB local
Remove-Item "C:\Users\xxxv4\iCloudDrive\tradingalertaIA\trading_alert_ai.db"
```

---

## Logs

### Ver logs en tiempo real (consola)

Cuando el bot corre con `python main.py`, logs van a stderr/stdout en la terminal directamente.

### Capturar logs a archivo

```powershell
.\.venv\Scripts\python.exe main.py 2>&1 | Tee-Object -FilePath bot.log -Append
```

### Tail tipo Unix

```powershell
Get-Content bot.log -Wait -Tail 50
```

### Buscar errores

```powershell
Select-String -Path bot.log -Pattern "ERROR|exception|Failed" | Select-Object -Last 20
```

### Buscar reconciler activity

```powershell
Select-String -Path bot.log -Pattern "MT5Reconciler|closed orphan|sl_synced"
```

---

## Dashboard Streamlit

```powershell
streamlit run app/dashboard/streamlit_app.py
```

Abre browser en `http://localhost:8501`. 9 secciones disponibles.

---

## Smoke tests rapidos

### Verificar v2.7.0 features

```powershell
# Promotion gate
.\.venv\Scripts\python.exe -c "from app.learning.trade_outcomes import should_execute_live; print(should_execute_live('test', 'forex', None, 30, 0.0))"

# Cost model
.\.venv\Scripts\python.exe -c "from app.config.settings import load_settings; s = load_settings(); print('Cost forex:', s.cost_roundtrip_pct_forex); print('Cost gold:', s.cost_roundtrip_pct_gold)"

# Realized learning
.\.venv\Scripts\python.exe -c "from app.config.settings import load_settings; print('Realized learning:', load_settings().enable_realized_learning)"
```

### Test imports basicos

```powershell
.\.venv\Scripts\python.exe -c "from app.brokers.mt5_demo_trader import MT5DemoTrader, DemoCloseResult, DemoSendResult; from app.portfolio.mt5_reconciler import MT5Reconciler; from app.learning.trade_outcomes import should_execute_live, r_multiple; from app.strategies.scalping_mean_reversion import ScalpingMeanReversionStrategy; print('All imports OK')"
```

---

## Cuando algo va mal — debugging steps

1. **Bot no arranca:** `pytest -q` primero. Si rompe, hay regresion. Si pasa, problema runtime.

2. **MT5 reader falla:** abrir MT5 desktop manualmente, validar login, validar Market Watch tiene los simbolos.

3. **Kill switch dispara raro:** query `realized_pnl_today` en tu DB:
   ```powershell
   sqlite3 "C:\Users\xxxv4\trading_data\trading_alert_ai.db" "SELECT key, value FROM bot_state WHERE key LIKE '%kill%'"
   ```

4. **Reconciler no cierra huerfanas:** abrir MT5 desktop, comparar posiciones con `/demo_positions`. Si MT5 tiene mas que el bot ve, log de reconciler probable.

5. **`/expectancy` vacio:** strategy_performance no se ha refrescado. Forzar `/entrenar`.

---

## Links relacionados

- [[12 - Guia de Uso]] - operacion diaria
- [[13 - Comandos Telegram]] - comandos por chat
- [[20 - Schema de Base de Datos]] - tablas y queries
- [[16 - Bugs Resueltos]] - debugging stories
