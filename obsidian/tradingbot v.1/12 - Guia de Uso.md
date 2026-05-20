# Guia de Uso — Trading Alert AI v2.4.0

Manual practico para arrancar el bot, configurarlo y usar todos los comandos.

---

## 1. Setup inicial (una sola vez)

### Crear venv e instalar dependencias

```powershell
cd C:\Users\xxxv4\iCloudDrive\tradingalertaIA
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Esto instala: python-dotenv, requests, streamlit, pandas, pytest, MetaTrader5 (Windows-only), anthropic.

### Configurar `.env` real

Copia `.env.example` a `.env` y completa los valores reales:

```env
# Telegram (BotFather)
TELEGRAM_BOT_TOKEN=tu_token_real
TELEGRAM_CHAT_ID=tu_chat_id

# Version (no tocar usualmente)
APP_VERSION=v2.4.0

# MT5 demo ICMarkets (Phase 4+)
ENABLE_MT5_READER=true
MT5_BROKER_PROFILE=icmarkets
MT5_LOGIN=tu_login_demo
MT5_PASSWORD=tu_password
MT5_SERVER=ICMarketsSC-Demo
MT5_PATH=

# Bot mode (Phase 4.5+): trader (default) | alerts_only | hybrid
BOT_MODE=trader

# Memecoin Hunter (Phase 4.5+)
ENABLE_EARLY_MEMECOIN_DETECTION=true
MAX_EARLY_POOL_AGE_HOURS=6
ENABLE_MEMECOIN_HUNTER=true
ENABLE_MEMECOIN_TELEGRAM=true
FORCE_LEARNING_GATE_FOR_MEMECOIN=true
MAX_EARLY_MEMECOIN_ALERTS_PER_24H=3
MAX_MATURE_MEMECOIN_ALERTS_PER_24H=2

# Claude API (Phase 3.5, opcional)
ENABLE_CLAUDE_INTEGRATION=true
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-haiku-4-5
CLAUDE_MAX_COST_PER_DAY_USD=2.0

# Trader engine (Phase 2.5+)
RISK_PER_TRADE_PCT=1.0
MAX_DAILY_DRAWDOWN_PCT=3.0
MAX_OPEN_TRADES_TOTAL=5
ACCOUNT_STARTING_BALANCE=10000

# Pesos aprendidos y gate (default OFF, activar despues de varios dias de data)
ENABLE_LEARNED_WEIGHTS=false
ENABLE_LEARNING_GATE=false
```

**Importante de seguridad:** NUNCA subas `.env` a git. NUNCA pegues `ANTHROPIC_API_KEY` o `MT5_PASSWORD` en notas Obsidian o Telegram.

### Preparar MT5 demo

1. Abrir MetaTrader 5 desktop.
2. Login con la cuenta demo ICMarkets.
3. Dejar la app abierta. El bot conecta por IPC, no por internet.

---

## 2. Correr el bot

### Modo continuo (produccion)

```powershell
.\.venv\Scripts\python.exe main.py
```

Corre cada `POLL_INTERVAL_SECONDS` (default 60s). Para detener: `Ctrl+C`.

### Modo un ciclo (testing)

```powershell
.\.venv\Scripts\python.exe main.py --once
```

Ejecuta un ciclo completo y termina. Util para verificar configuracion.

### Dashboard Streamlit

```powershell
streamlit run app/dashboard/streamlit_app.py
```

Abre `http://localhost:8501`. Secciones:
- Estado general (tokens, alertas, paper trades, outcomes).
- Aprendizaje (lessons, training runs).
- Rendimiento por horizonte (1h/6h/24h/7d) con MFE/MAE.
- Portfolio en vivo (posiciones abiertas, risk, equity curve).
- Analisis profundo (heatmaps, drilldown, macro panel, calendario).
- Walk-Forward Performance (degradacion train→test por strategy).
- Data Quality (gaps + stale + failures).

### Correr tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

Esperado: 197 verdes.

---

## 3. Comandos Telegram (categorizado)

Todos los comandos responden solo al `TELEGRAM_CHAT_ID` autorizado.

### Info y control basico

| Comando | Hace |
|---|---|
| `/help` | Lista de comandos disponibles |
| `/status` | Estado general del bot |
| `/cupos` | Alertas restantes por categoria en las ultimas 24h |
| `/config` | Configuracion visible (sin secretos) |
| `/pausar` | Suspender envio automatico de alertas Telegram |
| `/reanudar` | Reanudar envio automatico de alertas Telegram |

### Tokens y alertas

| Comando | Hace |
|---|---|
| `/top` | Tokens con mejor score actual (todas las categorias) |
| `/top_memecoins` | Top memecoins |
| `/top_stocks` | Top acciones US |
| `/alertas` | Ultimas 5 alertas guardadas |
| `/ultimas_alertas` | Idem |
| `/descartes` | Mejores candidatos que NO se enviaron (por dedup, gate, cupos, etc) |
| `/analiza SIMBOLO` | Resumen del token guardado en DB. Ej: `/analiza NVDA` |
| `/analiza 0x...` | Idem con direccion |

### Inteligencia (analiza nuevo, no DB)

| Comando | Hace |
|---|---|
| `/noticias SIMBOLO` | Titulares de noticias + sentimiento (Yahoo RSS) |
| `/filings SIMBOLO` | SEC filings recientes (acciones US) |
| `/patron SIMBOLO` | Patron tecnico (RSI, MACD, ATR, Bollinger, S/R) |
| `/pro SIMBOLO` | Lectura profesional completa (grafico + noticias + filings + setup) |

### Aprendizaje y backtesting

| Comando | Hace |
|---|---|
| `/aprendizaje` | Top lecciones aprendidas (features que funcionan/fallan) |
| `/paper` | Paper trades abiertos + ultimos cerrados |
| `/paper_trades` | Idem |
| `/entrenar` | Forzar ciclo de aprendizaje manualmente |
| `/horizontes SIMBOLO` | Outcomes por horizonte 1h/6h/24h/7d de la ultima alerta. Ej: `/horizontes NVDA` |
| `/backtest` | Top reglas por horizonte default (24h) |
| `/backtest 6h ia_pro,score:80-90` | Backtest combinacion features especifica |

### Trader engine (v2.0.0+)

| Comando | Hace |
|---|---|
| `/portfolio` | Posiciones abiertas + exposicion + risk pct + daily P&L + equity curve mini |
| `/portafolio` | Alias |
| `/posiciones` | Detalle trade por trade (entry/SL/TP/MFE/MAE/strategy) |
| `/positions` | Alias |
| `/halt` | Activar kill-switch con duracion default (24h) |
| `/halt 6` | Kill-switch por 6 horas |
| `/parar` | Alias `/halt` |
| `/resume_trading` | Liberar kill-switch (distinto de `/reanudar` que solo libera alertas Telegram) |
| `/reanudar_trading` | Alias |
| `/strategies` | Lista strategies habilitadas + señales generadas en ultimas 24h |
| `/estrategias` | Alias |

### Phase 4 (v2.3.0)

| Comando | Hace |
|---|---|
| `/mt5_status` | Estado MT5: broker + account + balance + symbol_info de EURUSD |
| `/mt5` | Alias |
| `/data_quality` | Stale symbols + gaps detectados + collector failures |
| `/dq` | Alias |
| `/calidad` | Alias |
| `/walk_forward breakout 30 stock` | Walk-forward sobre 1 strategy en ultimos 30 dias (degradacion train→test) |
| `/wf momentum 14` | Forma corta |
| `/export_csv outcomes` | Genera CSV de outcomes en `exports/` |
| `/export_csv trades` | CSV de paper trades |
| `/export_csv horizons` | CSV de horizons |
| `/export_csv walk_forward` | CSV de resultados walk-forward |

### Phase 4.5 (v2.4.0) — Bot Mode + Memecoin Hunter

| Comando | Hace |
|---|---|
| `/mode` | Muestra modo activo del bot (trader / alerts_only / hybrid) |
| `/mode alerts_only` | Bot solo alerta por Telegram, NO abre paper trades nuevos (lifecycle sigue) |
| `/mode trader` | Default. Strategy router activo, abre paper trades. |
| `/mode hybrid` | En v2.4.0 = trader. Phase 5+ requerirá confirmación manual. |

Notas Phase 4.5:
- **Memecoin Hunter Pro** ya está activo: detecta early pools (<6h) en GeckoTerminal `/new_pools`, agrega `early_bonus` al scoring y aplica `anti_rug_multiplier` que penaliza honeypot/risky contracts.
- **Alertas Telegram memecoin re-activadas** con caps separados (3 early/día + 2 mature/día). Learning gate FORZADO para memecoin (defensa anti-rug).
- **CLI flag `--mode`**: `python main.py --mode alerts_only` override por sesión. Prioridad: CLI > Telegram `/mode` persistido > `BOT_MODE` en `.env` > default `trader`.

### Preguntas naturales (Phase 3.5)

Si `ENABLE_CLAUDE_INTEGRATION=true` y hay API key, podes escribir preguntas sin slash:

- "que opinas de nvda" → Claude interpreta y manda `/pro NVDA`.
- "como esta el portfolio" → mapea a `/portfolio`.
- "por que no alertaste a tsla" → texto natural explicando el descarte.

---

## 4. Workflow tipico dia a dia

### Manana (5 min)

1. `/status` — bot vivo?
2. `/mt5_status` — MT5 conectado?
3. `/data_quality` — sin gaps?
4. `/portfolio` — posiciones abiertas + risk actual.
5. `/posiciones` — detalle MFE/MAE de cada trade.

### Durante el dia

- El bot manda alertas automaticas para stocks/forex/oro cuando una strategy firma + risk_manager OK.
- Cuando abre o cierra un paper trade, lo reporta solo por Telegram.
- Si querés bloquear nuevos trades temporalmente: `/halt 4` (4h) y despues `/resume_trading`.

### Fin del dia / semana

- `/aprendizaje` — que features estan funcionando.
- `/backtest` — top reglas historicas.
- `/walk_forward STRATEGY 30` — degradacion out-of-sample por strategy.
- `/export_csv outcomes` — bajar data para analisis externo.

### Reporte semanal automatico

Obsidian `11 - Reporte Semanal.md` se actualiza cada 7 dias con outcomes por horizonte, top 5 reglas y retornos medios.

---

## 5. Settings clave en `.env`

### Riesgo y portfolio
- `RISK_PER_TRADE_PCT=1.0` — % del balance arriesgado por trade.
- `MAX_TOTAL_RISK_PCT=6.0` — riesgo agregado maximo de todas las abiertas.
- `MAX_DAILY_DRAWDOWN_PCT=3.0` — si daily P&L cae mas, kill-switch automatico.
- `MAX_OPEN_TRADES_TOTAL=5` — limite global.
- `MAX_OPEN_TRADES_STOCK=3`, `MAX_OPEN_TRADES_FOREX=4`, `MAX_OPEN_TRADES_GOLD=2`.
- `ACCOUNT_STARTING_BALANCE=10000` — balance virtual (paper). MT5 sobreescribe con `account_info.equity`.

### Strategy router
- `ENABLE_STRATEGY_ROUTER=true`.
- `STRATEGY_MIN_CONFIDENCE=60` — descarta señales con confidence menor.
- `ENABLE_STRATEGY_BREAKOUT/MEAN_REVERSION/MOMENTUM/NEWS_CATALYST/FOREX_SESSION_BREAKOUT=true` (todas activas por default).

### Alertas Telegram
- `MEMECOIN_MAX_ALERTS_PER_24H=5`, `STOCK_MAX_ALERTS_PER_24H=5`.
- `MAX_FOREX_ALERTS_PER_24H=3`, `MAX_GOLD_ALERTS_PER_24H=2`.
- `ENABLE_MEMECOIN_TELEGRAM=false` — memecoins quedan en lab de aprendizaje, sin Telegram.
- `ENABLE_FOREX_ALERTS=true`, `ENABLE_GOLD_ALERTS=true`.

### Lifecycle
- `ENABLE_TRAILING_STOP=true`.
- `TRAILING_ACTIVATION_PCT_STOCK=5.0`, `_MEMECOIN=50.0`.
- `ENABLE_PARTIAL_CLOSE_AT_TP1=true`.
- `ENABLE_TIME_BASED_EXIT=true`, `DEFAULT_TIME_HORIZON_HOURS=48`.

### Aprendizaje (default OFF, opt-in)
- `ENABLE_LEARNED_WEIGHTS=false` — activar tras revisar `/aprendizaje`.
- `ENABLE_LEARNING_GATE=false` — activar tras tener N samples por estrategia.

### Phase 4
- `ENABLE_WALK_FORWARD_BACKTEST=true`.
- `WALK_FORWARD_TRAIN_DAYS=14`, `_TEST_DAYS=7`, `_SLIDE_DAYS=1`.
- `ENABLE_DATA_QUALITY_MONITOR=true`.
- `DATA_QUALITY_CHECK_EVERY_N_CYCLES=10`.

---

## 6. Troubleshooting

### Bot no levanta
- Verificar `.env` existe y tiene los valores criticos (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID si querés Telegram).
- Si MT5 no conecta: bot loguea warning y sigue degradado (yfinance). Para conectar, MT5 desktop debe estar abierto + login OK.
- Logs: stderr (no van a archivo). Para guardar: `python main.py 2>&1 | tee bot.log`.

### Tests fallan
- Si `Settings.__init__() missing kwargs` → algun setting nuevo no esta en `_settings()` de `test_score.py` y/o `test_alert_rules.py`.
- Si fallan tests de MT5/Claude → packages no instalados; reinstalar: `pip install MetaTrader5 anthropic`.

### Telegram no responde
- Bot debe estar corriendo.
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` correctos.
- Tu chat ID debe coincidir con `TELEGRAM_CHAT_ID`.
- Si nada llega: `ENABLE_TELEGRAM_ASSISTANT=true` en `.env`.

### MT5 conecta pero `/mt5_status` falla
- `ENABLE_MT5_READER=true`.
- Cuenta en `MT5_LOGIN/PASSWORD/SERVER` debe coincidir con la que esta logged in en MT5 desktop.
- Si MT5 desktop tiene la cuenta cerrada, conectar manualmente primero.

### Claude API soft-fail
- `ENABLE_CLAUDE_INTEGRATION=true`.
- `ANTHROPIC_API_KEY` valida y con credito.
- Si das limite diario: setting `CLAUDE_MAX_COST_PER_DAY_USD` bloquea hasta UTC midnight.

### DB corrupta
- `init_db` ahora maneja `sqlite3.DatabaseError` con mensaje claro. Si pasa, hacer backup de `trading_alert_ai.db` y borrarlo — se recrea vacio en proximo arranque (pierdes historial, no la config).

---

## 7. Archivos clave

| Archivo | Para que |
|---|---|
| `.env` | Configuracion real (con secretos). NUNCA subir a git. |
| `.env.example` | Template sin secretos. SI esta en git. |
| `trading_alert_ai.db` | SQLite con todo el historial. NUNCA en git. |
| `main.py` | Entry point del bot. |
| `app/config/settings.py` | Defaults de todos los settings. |
| `obsidian/tradingbot v.1/` | Memoria del proyecto (este Vault). |
| `requirements.txt` | Dependencias pinneadas. |
| `tests/` | 197 tests automaticos. |

---

## 8. Regla de oro

El bot sigue **read-only para ordenes reales**. Phase 5 (autorizada el 2026-05-19) habilita `order_send(action=demo)` a la cuenta ICMarkets demo. Real-money trading queda prohibido hasta nueva autorizacion explicita.

Para cualquier operacion sensible: confirmar primero. Si dudas, no toques.
