---
tags: [guia, uso, manual]
version: v2.7.0
updated: 2026-05-30
---

# Guia de Uso — Trading Alert AI v2.7.0

> [!info] Para que es esto
> Manual practico para arrancar el bot, configurarlo, validarlo y usar los comandos cotidianos.

---

## Setup inicial (1 vez)

```powershell
# 1. Ir al proyecto
cd C:\Users\xxxv4\iCloudDrive\tradingalertaIA

# 2. Crear venv si no existe
python -m venv .venv

# 3. Activar venv
.\.venv\Scripts\Activate.ps1
# Si Windows bloquea: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force

# 4. Instalar deps
pip install -r requirements.txt

# 5. Configurar .env (copiar de .env.example y editar)
# Variables obligatorias: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SQLITE_PATH
```

---

## Arranque del dia

```powershell
# Activar venv si terminal nueva
cd C:\Users\xxxv4\iCloudDrive\tradingalertaIA
.\.venv\Scripts\Activate.ps1

# Asegurarse MT5 desktop esta abierto y logueado a MetaQuotes-Demo
# Sin MT5 abierto, el bot corre degradado (sin order_send, sin reconciler)

# Arrancar bot continuo
.\.venv\Scripts\python.exe main.py

# Alternativa: un solo ciclo (smoke test)
.\.venv\Scripts\python.exe main.py --once

# Alternativa: solo alertas (sin trader)
.\.venv\Scripts\python.exe main.py --mode alerts_only --once
```

> [!warning] Arrancar SIEMPRE desde la carpeta del proyecto
> Si arrancas desde otro lugar, no encuentra `SQLITE_PATH` y crearia DB vacia.

---

## Validacion post-arranque

Mandar por Telegram:

```
/health
```

Esperado:
- Version: **v2.7.0**
- Balance: ~$88,585 USD
- Kill switch: inactivo
- Demo trading halt: inactivo
- Scalping engine: ACTIVO
- Strategies activas: 4 swing + 2 scalping (sin momentum, sin forex_session_breakout si lo deshabilitaste)

```
/expectancy
```

Esperado: tabla con strategies + R neto + tags LIVE/SHADOW. Si esta vacia, esperar 1 ciclo de learning para poblarse.

```
/scalping_status
```

Esperado: estado del scalping engine (trades hoy, abiertos, simbolos).

---

## Logs a observar en consola

Buenos:
```
INFO | app.brokers.mt5_reader | MT5 reader connected (read-only)
INFO | app.scheduler.scalping_engine | ScalpingEngine thread started (interval=3s, symbols=['eurusd', 'gbpusd', 'usdjpy'])
INFO | app.scheduler.jobs | Trading Alert AI started. Database: trading_alert_ai.db
INFO | app.scheduler.jobs | Bot mode active: trader
INFO | app.scheduler.jobs | Lifecycle: {'managed': N, 'time_closed': X, ...}
INFO | app.scheduler.jobs | Collected N market snapshots
INFO | app.scheduler.jobs | Learning cycle complete. Evaluadas N senales; outcomes nuevos N; lecciones N
INFO | app.portfolio.mt5_reconciler | MT5Reconciler: checked=N closed=X sl_synced=Y
```

Sospechosos (investigar):
- `MT5Reconciler init failed`
- `MT5DemoTrader.send_prepared_request raised`
- `Auto-confirm DB persist failed`
- `realized_pnl_today` con valores ridiculos

Normales (soft-fail, no preocupar):
- `GeckoTerminal 429` (rate limit cripto)
- `Yahoo data failed for X: timed out` (red flaky)
- `Yahoo RSS 500` esporadicos
- `ScalpingEngine en rango` (waiting for breakout)

---

## Operacion diaria

### Por la manana

1. Abrir MT5 desktop (login MetaQuotes-Demo)
2. Verificar 0 posiciones abiertas (sino: cerrar manual o ver si reconciler las trackea)
3. `python main.py`
4. `/health` por Telegram

### Durante el dia

- Mirar alerts agrupadas en Telegram
- Cuando `Auto-orden demo enviada` aparece: verificar en MT5 desktop que la posicion exista
- Si kill switch dispara: investigar via `/expectancy` y logs

### Cierre del dia (opcional)

- `/scalping_off` si no queres scalping overnight
- Dejar bot corriendo o `Ctrl+C` para parar
- Si dejas corriendo: revisar logs por la manana

---

## Test suite

```powershell
# Correr todos los tests (~1.5min con DB local)
.\.venv\Scripts\python.exe -m pytest tests/ -q
# Esperado: 397 passed

# Tests especificos de v2.7.0
.\.venv\Scripts\python.exe -m pytest tests/test_trade_outcomes.py tests/test_strategy_promotion_gate.py tests/test_cost_model.py tests/test_expectancy_command.py tests/test_realized_learning.py -v
```

---

## Smoke test rapido

```powershell
.\.venv\Scripts\python.exe -c "from app.config.settings import load_settings; s=load_settings(); print('OK v', s.app_version, '| Demo:', s.enable_mt5_demo_trading, '| Real:', s.enable_real_trading, '| Gate:', s.enable_strategy_promotion_gate)"
```

Esperado:
```
OK v v2.7.0 | Demo: True | Real: False | Gate: True
```

---

## Dashboard Streamlit

```powershell
streamlit run app/dashboard/streamlit_app.py
```

Abre en browser. 9 secciones (paper trades, signal outcomes, equity curve, strategy lessons, etc.).

---

## Cuando algo sale mal

### Bot no arranca

1. Verificar `python --version` (debe ser 3.12.x)
2. Verificar `.venv\Scripts\python.exe -c "import MetaTrader5"` no falla
3. Verificar MT5 desktop abierto
4. Verificar `.env` existe y tiene `TELEGRAM_BOT_TOKEN`, `MT5_LOGIN`
5. Verificar SQLITE_PATH existe (`C:\Users\xxxv4\trading_data\` dir)

### Kill switch activo y no queres esperar

```python
# Script en raiz del proyecto
import sqlite3
conn = sqlite3.connect(r"C:\Users\xxxv4\trading_data\trading_alert_ai.db")
conn.execute("UPDATE bot_state SET value='' WHERE key='kill_switch_active_until'")
conn.execute("UPDATE bot_state SET value='' WHERE key='kill_switch_reason'")
conn.commit()
print("Kill switch limpio")
```

### `/health` muestra version vieja

`APP_VERSION` en `.env` mismatch con codigo. Bumpear linea en `.env`.

### Hay huerfanas en MT5 que el bot no ve

```
/demo_positions    ← cuantas posiciones MT5 reales
/demo_close_all    ← cierra todas
```

Despues investigar por que el reconciler no las trackea (probable: demo_order sin paper_trade matching).

### Posiciones MT5 acumulandose

- Verificar `DEMO_MAX_OPEN_TRADES` (deberia ser 15 max conservador)
- Verificar logs por `MT5Reconciler closed orphan` — si nunca aparece pero hay huerfanas, hay bug
- Verificar `STRATEGY_SYMBOL_COOLDOWN_MINUTES=15` activo

---

## Backup / restore

### Backup manual

```powershell
# Copiar DB
Copy-Item "C:\Users\xxxv4\trading_data\trading_alert_ai.db" "C:\Users\xxxv4\trading_data\backup_$(Get-Date -Format yyyyMMdd_HHmm).db"
```

### Restore

```powershell
# Reemplazar DB activa
Copy-Item "C:\Users\xxxv4\trading_data\backup_YYYYMMDD_HHMM.db" "C:\Users\xxxv4\trading_data\trading_alert_ai.db" -Force
```

---

## Comandos Telegram rapidos

| Para que | Comando |
|---|---|
| Estado general | `/health` |
| Strategies y R real | `/expectancy` |
| Lessons aprendidas | `/aprendizaje` |
| Cuotas restantes | `/cupos` |
| Paper trades abiertos | `/posiciones` |
| Posiciones MT5 reales | `/demo_positions` |
| Cerrar todo MT5 | `/demo_close_all` |
| Halt manual | `/halt` |
| Resume despues de halt | `/resume_trading` |
| Scalping ON/OFF | `/scalping_on` o `/scalping_off` |
| Preview gate | `/gate_preview` |

Para detalle de los 40+ comandos ver [[13 - Comandos Telegram]].

---

## Tips de operacion

> [!tip] Empezar conservador, ir liberando
> Tu `.env` actual ya es conservador post-sprint 27-may. Solo agregar caps si las stats mejoran consistentemente.

> [!tip] Validar reconciler con MT5 desktop
> Cada cierto tiempo, revisar MT5 desktop para confirmar que no hay posiciones huerfanas que el bot no este trackeando.

> [!tip] `/expectancy` es tu mejor amigo
> Te dice la verdad sobre cada strategy. Si una mejora a R+, sabes que esta funcionando. Si todas bajan, algo cambio.

> [!tip] No mezclar config en medio del trading
> Cambiar `.env` mientras el bot corre no surte efecto hasta restart. Hacer cambios y restartear.

---

## Links relacionados

- [[04 - Configuracion Operativa]] - todas las env vars
- [[22 - Setup y Operacion]] - comandos powershell detallados
- [[13 - Comandos Telegram]] - referencia completa
- [[14 - Estado Actual v2.7.0]] - estado al cierre
