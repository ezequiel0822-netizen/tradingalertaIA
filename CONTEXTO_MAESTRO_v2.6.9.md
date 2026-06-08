---
name: master-context-handoff-for-trading-alert-ai-v2-6-9
description: Onboarding doc EXHAUSTIVO del estado completo del proyecto al cierre de sesión 2026-05-28 nocturna / 2026-05-29 madrugada. Reemplaza master_context_v2_6_5 (desactualizado, no incluía v2.6.6-v2.6.9 ni los bugs descubiertos en validación live 27-may). Mirror plano en C:\Users\xxxv4\iCloudDrive\tradingalertaIA\CONTEXTO_MAESTRO_v2.6.9.md.
metadata:
  node_type: memory
  type: reference
  originSessionId: 80591436-8e63-4451-bd2a-0240f6f57ea2
---

# CONTEXTO MAESTRO — Trading Alert AI v2.6.9

Documento de handoff completo. Cierre de sesión 2026-05-29 madrugada (post-sprint 12h tras pérdida de $12k del 27-may).

---

## 1. RESUMEN GENERAL DEL PROYECTO ACTUAL

**Nombre:** Trading Alert AI v2.6.9

**Qué es:** Bot de trading algorítmico **local** en Python 3.12 (Windows, PowerShell + venv) que evolucionó de "alerter read-only" a **trader engine autónomo con auto-execute a MT5 demo + scalping engine en thread paralelo + reconciler de posiciones MT5**. Real-money trading sigue bloqueado por design.

**Objetivo:**
- Detectar oportunidades en 4 mercados: memecoins (DEX Screener + GeckoTerminal), acciones US (Yahoo), forex majors (Yahoo + MT5), oro (MT5).
- Decidir entradas/salidas con strategy router (5 swing + 2 scalping).
- Operar paper trades simulados Y enviar órdenes a cuenta demo MT5 MetaQuotes-Demo.
- Reconciler MT5 cierra automáticamente posiciones huérfanas y sincroniza SL post-trailing.
- Aprender de outcomes históricos (signal_outcomes, strategy_lessons, learned_weights, walk_forward_results).

**Resultado final esperado:** Después de 3+ meses de demo estable (sharpe > 1, win_rate > 50%, max drawdown < 10%), considerar real-money con autorización explícita nueva.

---

## 2. EVOLUCIÓN DEL PROYECTO

| Versión | Fecha aprox | Hito |
|---|---|---|
| v1.0-v1.5 | 2026-05-16 | MVP read-only DEX Screener + Telegram + SQLite |
| v1.5.2 | 2026-05-17 | Learning Engine (signal_outcomes, strategy_lessons, paper_trades) |
| v1.6.0-v1.7.0 | 2026-05-18 | Horizons + paper_trading++ + ATR SL/TP |
| v2.0.0 | 2026-05-18 | **PIVOT: alerter → trader engine.** Strategy router, portfolio, risk manager, MT5 reader read-only |
| v2.1.0-v2.2.0 | 2026-05-19 | Security hardening + forex price-action + macro + Claude API |
| v2.3.0-v2.4.0 | 2026-05-19 | MT5 ICMarkets validation + walk-forward + Memecoin Hunter Pro + Bot Mode Toggle |
| v2.5.0 | 2026-05-20 | **Phase 5: order_send a MT5 demo con confirmación manual obligatoria** |
| v2.5.1-v2.5.3 | 2026-05-20 | Patches: demo trades + fallback pip-value + /demo_candidates validación |
| v2.5.4 | 2026-05-20 | **Phase 5.5 Bloque A: auto-confirm opt-in (ENABLE_AUTO_CONFIRM_DEMO)** |
| v2.5.5 | 2026-05-22 | DEMO_MAX_TOTAL_RISK_PCT separado + /health |
| v2.6.0 | 2026-05-22 | **Phase 5.5 Bloque B: Scalping Engine + Mode Toggle + Learning per-style** |
| v2.6.1 | 2026-05-22 | /demo_close_all + 8 stock symbols extra |
| v2.6.2 | 2026-05-25 | Diagnostic instrumentation scalping |
| v2.6.3 | 2026-05-25 | FIX: timeframe int no string |
| v2.6.4 | 2026-05-25 | FIX: numpy.void sin .get() |
| v2.6.5 | 2026-05-26 | FIX: realized_pnl_today + symbol_select + account_balance |
| **v2.6.6** | **2026-05-28** | **scalping_mean_reversion (BB+RSI) + ScalpingEngine multi-strategy** |
| **v2.6.7** | **2026-05-28** | **MT5Reconciler: cierra MT5 huérfanas + sync SL post-trailing** |
| **v2.6.8** | **2026-05-28** | **size_notional con MT5 real + per-symbol cooldown** |
| **v2.6.9** | **2026-05-29** | **/gate_preview Telegram command** |

**Dirección actual:** acumular semanas/meses de demo trades reales (swing + scalping) con código más maduro post-sprint del 27-28 may. Aprendizaje + reconciler activos.

---

## 3. ESTADO ACTUAL EXACTO

### Versión y git
- **Versión código:** v2.6.9
- **Branch:** `main`
- **Último commit origin/main:** `9fc0575` (`feat(v2.6.9): /gate_preview Telegram command`)
- **Tests:** **357 verdes** (pytest)
- **Working tree:** Limpio del lado código. Obsidian docs dirty intencionalmente.

### Branch experimental v2.7.0 (NO mergeada)
Per MEMORY.md línea 2: existe branch `claude/xenodochial-taussig-4206c6` con 376 tests donde otra sesión Claude descubrió bug deeper:
- Root cause: `_update_paper_trades` long-only insta-killeaba shorts
- 86% del historial paper_trades son artifacts
- Fixes: updater direction-aware, MT5 symbol map en lifecycle, módulo realized-R + tabla strategy_performance + comando `/expectancy`
- learning_gate NO activar (mide drift no P&L)

Sin merge a main. Decisión de mergear pertenece al user.

### Cuenta MT5 REAL del usuario
```
Login:    10010956946
Server:   MetaQuotes-Demo       ← NO es ICMarkets a pesar de MT5_BROKER_PROFILE=icmarkets
Balance:  88,585.74 USD         ← REAL al 29-may madrugada. Era 100,468 originalmente.
```

`MT5_BROKER_PROFILE=icmarkets` controla SOLO mapeo símbolos Yahoo↔MT5 (coincide con MetaQuotes-Demo porque usan mismos pares). El broker real está en `MT5_SERVER`.

### Estado del bot al cierre

- **Proceso:** OFF (user cerró sesión madrugada 29-may)
- **bot_state flags:**
  - `account_balance`: `88585.74` (actualizado 29-may 01:33 UTC)
  - `kill_switch_active_until`: vacío (CLEAR — limpiado manualmente al cierre)
  - `kill_switch_reason`: vacío
  - `demo_trading_halted`: false
  - `scalping_halted`: false
  - `scalping_active`: true
  - `bot_mode_active`: trader
  - `alerts_paused`: false

### Sprint del 27-28 may (resumen del por qué se hicieron v2.6.6-v2.6.9)

El 27-may el user perdió **$12k en 1 día**. Análisis live reveló 4 bugs/issues:

1. **MT5 huérfanas (−$9.6k)**: 117+ órdenes USDCHF/XAUUSD enviadas a MT5 con sus paper_trades ya cerrados. El bot las "olvidó" — quedaban abiertas hasta hit SL real o intervención manual.
2. **size_notional inflado 100-1000×**: position_sizer usaba `ACCOUNT_STARTING_BALANCE=1M` teórico. MT5 ejecutaba 0.1 lot (~$10k real). Stats agregadas y `realized_pnl_today` inflados.
3. **Kill switch falso**: −3.18% reportado vs −0.13% real (consecuencia del #2).
4. **Feedback loop**: 159 USDCHF orders en 20 min sin dedup por símbolo.

Fixes desplegados en sprint: v2.6.6 (mean reversion), v2.6.7 (reconciler), v2.6.8 (notional + cooldown), v2.6.9 (gate preview).

### Data acumulada en DB
```
paper_trades:        500+ totales (significativamente más tras día 27-may)
signal_outcomes:     145,000+
strategy_lessons:    63+ (refrescados último ciclo)
demo_orders:         170+ sent a MT5 demo (varios huérfanos fueron cerrados manualmente por user el 27)
```

### Stats por strategy (paper trades closed, all history)

```
momentum:                53 trades, 33L/10W (77% loss), ~-$36k impact ← DESHABILITADA por user
forex_session_breakout:  386 trades, 9L/4W,            -$596 (forex pierde, gold gana)
mean_reversion:          180 trades, 5L/6W,            -$16,710 (2 outliers gigantes pre-v2.6.8)
scalping_breakout:       1 trade,   1L/0W,             $0
scalping_mean_reversion: 0 trades   (engine activo, sin signals significativos)
```

---

## 4. ESTRUCTURA ACTUAL DE ARCHIVOS Y CARPETAS

```
C:\Users\xxxv4\iCloudDrive\tradingalertaIA\
├── .env                            # secretos reales (NO en git)
├── .env.example                    # APP_VERSION=v2.6.9
├── .gitignore
├── .venv\                          # Python 3.12.13 venv
├── trading_alert_ai.db             # SQLite con todo el historial
├── main.py                         # entry point
├── pytest.ini
├── requirements.txt
├── CHANGELOG.md                    # historial versiones (hasta v2.6.9)
├── README.md
├── CONTEXTO_MAESTRO_v2.6.9.md     # mirror de este doc (NEW path)
│
├── app\
│   ├── alerts\
│   ├── analyzers\                  # scoring + IA Pro + technical + memecoin hunter + learning_gate
│   ├── assistant\
│   │   ├── command_handler.py      # 40+ comandos Telegram + /gate_preview (v2.6.9)
│   │   └── telegram_assistant.py
│   ├── brokers\
│   │   ├── mt5_reader.py           # read-only + symbol_select defensive (v2.6.5)
│   │   ├── mt5_demo_trader.py      # ÚNICO módulo con order_send. v2.6.7: close_position_by_ticket + update_position_sl. v2.6.8: compute_actual_notional_usd
│   │   ├── mt5_historical.py
│   │   └── mt5_symbol_map.py
│   ├── collectors\                 # 9 collectors
│   ├── config\
│   │   └── settings.py             # dataclass Settings + ~160 fields. v2.6.9: app_version="v2.6.9"
│   ├── dashboard\
│   ├── database\
│   │   ├── db.py                   # 17 tablas + _ensure_column migrations
│   │   ├── models.py
│   │   └── repository.py           # v2.6.7: fetch_demo_orders_by_tickets, fetch_paper_trade_by_id, fetch_latest_demo_order_for_paper_trade. v2.6.8: has_recent_paper_trade_for_symbol
│   ├── intelligence\
│   ├── learning\
│   │   ├── backtester.py
│   │   ├── feature_extractor.py
│   │   ├── horizon_evaluator.py
│   │   ├── lifecycle_manager.py    # gestión paper_trades open
│   │   ├── training_engine.py
│   │   └── walk_forward.py
│   ├── portfolio\
│   │   ├── portfolio_manager.py    # realized_pnl_today USD-based
│   │   └── mt5_reconciler.py       # NUEVO v2.6.7: cierra MT5 huérfanas + sync SL
│   ├── risk\
│   │   ├── position_sizer.py
│   │   └── risk_manager.py         # v2.6.8: check_can_open_trade(symbol=) con per-symbol cooldown
│   ├── scheduler\
│   │   ├── jobs.py                 # TradingAlertJob. v2.6.7: _mt5_reconciler.reconcile() en run_once. v2.6.8: _correct_paper_trade_notional()
│   │   └── scalping_engine.py      # multi-strategy v2.6.6
│   ├── strategies\
│   │   ├── base.py
│   │   ├── breakout.py
│   │   ├── forex_session_breakout.py
│   │   ├── mean_reversion.py
│   │   ├── momentum.py             ← DESHABILITADA por user en .env
│   │   ├── news_catalyst.py
│   │   ├── scalping_breakout.py    # v2.6.0
│   │   ├── scalping_mean_reversion.py  # NUEVO v2.6.6 (BB+RSI)
│   │   └── strategy_router.py
│   └── utils\
│       ├── bot_mode.py
│       ├── scalping_state.py
│       ├── csv_export.py
│       ├── dedup.py
│       ├── log_redactor.py
│       ├── logging_config.py
│       ├── obsidian_memory.py
│       ├── rate_limiter.py
│       ├── safe_http.py
│       ├── safe_path.py
│       └── time_utils.py
│
├── obsidian\
│   └── tradingbot v.1\             # Vault personal (NO tocar sin permiso)
│
└── tests\                          # 60+ archivos, 357 tests verdes
    ├── test_mt5_reconciler.py           # 15 tests v2.6.7
    ├── test_v268_v269.py                # 14 tests v2.6.8 (notional + cooldown)
    ├── test_gate_preview_command.py     # 5 tests v2.6.9
    ├── test_scalping_mean_reversion.py  # 13 tests v2.6.6
    ├── test_scalping_engine.py          # 13 tests (10 existentes + 3 v2.6.6 multi-strategy)
    └── ... (resto sin cambios desde v2.6.5)
```

### Archivos críticos a entender primero

| Archivo | Para qué |
|---|---|
| `main.py` | Entry point. CLI flags `--once`, `--mode`. Arranca scalping thread si flag activo. |
| `app/scheduler/jobs.py` | Orquestador swing. `run_once()` ~1100 líneas. v2.6.7: hook reconciler post-lifecycle. v2.6.8: _correct_paper_trade_notional() post-demo_order. |
| `app/scheduler/scalping_engine.py` | Thread scalping. Polling 3-5s. v2.6.6: multi-strategy list. v2.6.8: notional correction post-demo_order. |
| `app/strategies/scalping_breakout.py` | M1 range breakout. |
| `app/strategies/scalping_mean_reversion.py` | NUEVO v2.6.6: BB(20,2.0) + RSI(14) sobre M1. Counter-trend. |
| `app/portfolio/mt5_reconciler.py` | NUEVO v2.6.7: cierra MT5 huérfanas + sync SL (sólo TIGHTEN). |
| `app/brokers/mt5_demo_trader.py` | ÚNICO con order_send. v2.6.7: close_position_by_ticket + update_position_sl. v2.6.8: compute_actual_notional_usd + actual_units. |
| `app/risk/risk_manager.py` | v2.6.8: check_can_open_trade(symbol=) con per-symbol cooldown. |
| `app/assistant/command_handler.py` | 40+ comandos. v2.6.9: /gate_preview, /preview_gate, /learning_gate. |
| `app/portfolio/portfolio_manager.py` | realized_pnl_today USD-based + account_balance retry+persist (v2.6.5). |

---

## 5. CONFIGURACIÓN Y VARIABLES IMPORTANTES

### Variables OBLIGATORIAS
```bash
TELEGRAM_BOT_TOKEN=<token-real>
TELEGRAM_CHAT_ID=<chat-id-real>
MT5_LOGIN=10010956946
MT5_PASSWORD=<password>
MT5_SERVER=MetaQuotes-Demo
ENABLE_MT5_READER=true
MT5_BROKER_PROFILE=icmarkets
```

### `.env` actual del user (post-sprint 28-may, CONSERVADOR)

Cambios aplicados por user respecto del master context v2.6.5:

```bash
# Bumpeado pero pendiente actualizar a v2.6.9
APP_VERSION=v2.6.7              # user todavía no bumpeó a v2.6.9 (1 línea pendiente)

# Demo trading: agresivo → conservador
DEMO_RISK_PER_TRADE_PCT=1.5     # era 5.26
DEMO_MAX_OPEN_TRADES=15         # era 100
DEMO_MAX_TOTAL_RISK_PCT=6.0     # era 10.0

# Strategy thresholds subidos
STRATEGY_MIN_CONFIDENCE=65      # era 55
READINESS_MIN_SCORE=72          # era 65
READINESS_MIN_CONFIDENCE=65     # era 55
ALERT_SCORE_THRESHOLD=65        # era 60

# Caps por categoría apretados
MAX_OPEN_TRADES_TOTAL=25        # era 100
MAX_OPEN_TRADES_STOCK=10        # era 30
MAX_OPEN_TRADES_FOREX=15        # era 40
MAX_OPEN_TRADES_GOLD=5          # era 10
MAX_ALERTS_PER_RUN=15           # era 30
MAX_GOLD_ALERTS_PER_24H=15      # era 50
MAX_GOLD_ALERTS_PER_RUN=2       # era 10
DEDUP_WINDOW_MINUTES=360        # era 180

# Stock min más estrictos
MIN_STOCK_ESTIMATED_GAIN_PCT=8  # era 6
MIN_STOCK_ESTIMATE_CONFIDENCE=60 # era 50

# DESHABILITADA por 77% loss rate (-$36k)
ENABLE_STRATEGY_MOMENTUM=false

# Pendiente aplicar por user
# ENABLE_STRATEGY_FOREX_SESSION_BREAKOUT=false  ← 73% loss forex, 50% gold
```

### Settings nuevos en v2.6.6-v2.6.9 (defaults)

```bash
# v2.6.6 — Multi-strategy scalping
ENABLE_SCALPING_BREAKOUT=true
ENABLE_SCALPING_MEAN_REVERSION=true
SCALPING_MR_BOLLINGER_PERIOD=20
SCALPING_MR_BOLLINGER_STD=2.0
SCALPING_MR_RSI_PERIOD=14
SCALPING_MR_RSI_OVERBOUGHT=70
SCALPING_MR_RSI_OVERSOLD=30

# v2.6.8 — Per-symbol cooldown anti-feedback-loop
STRATEGY_SYMBOL_COOLDOWN_MINUTES=15
```

### Configuración persistida deliberada del user (NO "corregir")

```bash
ENABLE_REAL_TRADING=false                # HARDCODED
ENABLE_AUTO_CONFIRM_DEMO=true            # opt-in user
ENABLE_SCALPING_ENGINE=true
SCALPING_RISK_PER_TRADE_PCT=1.0
SCALPING_MAX_OPEN_TRADES=5
SCALPING_MAX_TRADES_PER_DAY=100
SCALPING_FORCE_EXIT_MINUTES=3
SCALPING_POLL_INTERVAL_SECONDS=3         # más agresivo que default 5
SCALPING_SL_PIPS=6                       # más tight que default 8
SCALPING_TP_PIPS=8                       # más tight que default 12
SCALPING_RANGE_LOOKBACK_BARS=5

ENABLE_LEARNED_WEIGHTS=true              # user activó early
ENABLE_LEARNING_GATE=false               # MANTENER OFF — preview reveló bloquearia ~todo
FORCE_LEARNING_GATE_FOR_MEMECOIN=true    # protección anti-rug

# Outcome thresholds recalibrados v2.6.5
OUTCOME_WIN_RETURN_MEMECOIN_PCT=30
OUTCOME_LOSS_RETURN_MEMECOIN_PCT=-15
OUTCOME_WIN_RETURN_STOCK_PCT=5
OUTCOME_LOSS_RETURN_STOCK_PCT=-3

ACCOUNT_STARTING_BALANCE=1000000         # Teórico fallback. MT5 real es ~88,585
```

### Paths importantes
- `.env` → `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\.env` (real, ignorado por git)
- `.venv` → `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\.venv\Scripts\python.exe` (Python 3.12.13)
- DB → `trading_alert_ai.db` (raíz proyecto)
- Obsidian vault → `obsidian/tradingbot v.1/`
- CSV exports → `exports/`
- Mirror master context → `CONTEXTO_MAESTRO_v2.6.9.md`

---

## 6. TECNOLOGÍAS, HERRAMIENTAS E INTEGRACIONES

(Sin cambios significativos desde v2.6.5)

- Python 3.12.13 en `.venv`
- SQLite3 (stdlib) thread-safe via `get_connection` per call
- Threading para scalping engine
- MetaTrader5 lib oficial
- Anthropic Claude API (Haiku 4.5, opcional, OFF default)
- Telegram Bot API
- DEX Screener + GeckoTerminal + GoPlus Labs APIs
- Yahoo Finance + RSS
- SEC EDGAR
- ForexFactory XML
- Streamlit dashboard
- Obsidian memory

---

## 7. COMANDOS IMPORTANTES

### Setup
```powershell
cd C:\Users\xxxv4\iCloudDrive\tradingalertaIA
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Tests
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
# Esperado: 357 passed
```

### Correr bot
```powershell
.\.venv\Scripts\python.exe main.py                  # continuo
.\.venv\Scripts\python.exe main.py --once           # un ciclo
.\.venv\Scripts\python.exe main.py --mode alerts_only --once
```

### Telegram commands (NUEVOS en v2.6.9)

- `/gate_preview`, `/preview_gate`, `/learning_gate`, `preview gate` — preview de qué features bloqueá learning_gate si se activa

Resto de comandos sin cambios desde v2.6.5: `/health`, `/status`, `/portfolio`, `/posiciones`, `/cupos`, `/demo_candidates`, `/demo_close_all`, `/scalping_*`, `/mode`, `/halt`, `/resume_trading`, `/analiza SIMBOLO`, `/aprendizaje`, `/backtest`, `/export_csv`, etc.

### Inspección DB

```powershell
sqlite3 trading_alert_ai.db ".tables"
sqlite3 trading_alert_ai.db "SELECT key, value FROM bot_state"
sqlite3 trading_alert_ai.db "SELECT category, COUNT(*) FROM strategy_lessons GROUP BY category"
```

Query useful para auditoría post-sprint:
```powershell
sqlite3 trading_alert_ai.db ".mode column" ".headers on" "SELECT strategy_name, category, COUNT(*) as n, ROUND(AVG(unrealized_return_pct),2) as avg_ret, ROUND(SUM(size_notional*unrealized_return_pct/100.0),2) as pnl_usd, SUM(CASE WHEN unrealized_return_pct<0 THEN 1 ELSE 0 END) as losers, SUM(CASE WHEN unrealized_return_pct>0 THEN 1 ELSE 0 END) as winners FROM paper_trades WHERE status != 'open' GROUP BY strategy_name, category ORDER BY avg_ret"
```

---

## 8. SCRIPTS, MÓDULOS, COMANDOS CREADOS (v2.5.0 → v2.6.9)

### Módulos nuevos en sprint v2.6.6-v2.6.9

| Archivo | Versión | Propósito |
|---|---|---|
| `app/strategies/scalping_mean_reversion.py` | v2.6.6 | Counter-trend BB+RSI sobre M1 |
| `app/portfolio/mt5_reconciler.py` | v2.6.7 | Cierra MT5 huérfanas + sync SL post-trailing |

### Métodos nuevos en módulos existentes

| Módulo | Método | Versión |
|---|---|---|
| `MT5DemoTrader` | `close_position_by_ticket(ticket)` | v2.6.7 |
| `MT5DemoTrader` | `update_position_sl(ticket, new_sl, new_tp=None)` | v2.6.7 |
| `MT5DemoTrader` | `compute_actual_notional_usd(symbol, volume, entry_price)` | v2.6.8 |
| `MT5DemoTrader` | `actual_units(symbol, volume)` | v2.6.8 |
| `Repository` | `fetch_demo_orders_by_tickets(tickets)` | v2.6.7 |
| `Repository` | `fetch_paper_trade_by_id(trade_id)` | v2.6.7 |
| `Repository` | `fetch_latest_demo_order_for_paper_trade(pt_id)` | v2.6.7 |
| `Repository` | `has_recent_paper_trade_for_symbol(symbol, after)` | v2.6.8 |
| `RiskManager.check_can_open_trade` | Param `symbol=None` con per-symbol cooldown | v2.6.8 |
| `TradingAlertJob._correct_paper_trade_notional` | Post-demo_order update | v2.6.8 |
| `ScalpingEngine._correct_paper_trade_notional` | Idem para scalping path | v2.6.8 |
| `BasicTelegramAssistant.gate_preview_message` | /gate_preview command | v2.6.9 |

### Settings nuevos

- v2.6.6: 7 settings (ENABLE_SCALPING_BREAKOUT/MEAN_REVERSION + 5 MR params)
- v2.6.8: 1 setting (STRATEGY_SYMBOL_COOLDOWN_MINUTES)

### Strategies activas

| Nombre | Archivo | Tipo |
|---|---|---|
| `breakout` | breakout.py | Swing |
| `mean_reversion` | mean_reversion.py | Swing |
| `momentum` | momentum.py | Swing (DESHABILITADA en .env user) |
| `news_catalyst` | news_catalyst.py | Swing |
| `forex_session_breakout` | forex_session_breakout.py | Swing (pendiente deshabilitar) |
| `scalping_breakout` | scalping_breakout.py | Scalping |
| **`scalping_mean_reversion`** | **scalping_mean_reversion.py** | **Scalping (NUEVO v2.6.6)** |

---

## 9. FUNCIONALIDADES COMPLETADAS

(Todas las de v2.5.0+ siguen + las nuevas)

### Nuevas v2.6.6-v2.6.9

- ✅ Strategy `scalping_mean_reversion` (BB+RSI counter-trend sobre M1)
- ✅ ScalpingEngine multi-strategy (lista `self.strategies` construida por flags, breakout primero, MR fallback)
- ✅ MT5Reconciler cierra posiciones MT5 huérfanas (paper_trade closed → MT5 close)
- ✅ MT5Reconciler sincroniza SL cuando paper_trade SL movió (trailing/breakeven) — solo TIGHTEN
- ✅ `MT5DemoTrader.close_position_by_ticket` + `update_position_sl` (TRADE_ACTION_SLTP)
- ✅ `paper_trade.size_notional` se updatea con MT5 actual post-demo_order (notional USD verdadero)
- ✅ Per-symbol cooldown en `RiskManager` (default 15 min, configurable)
- ✅ `/gate_preview` Telegram command (preview impacto si activas learning_gate)
- ✅ 50 tests nuevos (307 → 357)

---

## 10. FUNCIONALIDADES PENDIENTES

### Inmediato (al arrancar bot v2.6.9)
1. ⚠️ **User aplicar 2 cambios en `.env`:**
   - `APP_VERSION=v2.6.9` (era v2.6.7)
   - `ENABLE_STRATEGY_FOREX_SESSION_BREAKOUT=false` (73% loss forex)
2. ⚠️ Arrancar bot + observar primer ciclo limpio
3. ⚠️ Verificar `/health` muestra v2.6.9 + balance ~$88,585 + kill switch inactivo
4. ⚠️ Si MT5 acumula posiciones de nuevo, validar que reconciler las cierra (buscar log `MT5Reconciler: checked=N closed=X sl_synced=Y`)

### Cleanup post-sesión
- Limpiar worktree corrupto `.claude/worktrees/reverent-curie-7ccc75` (dir vacío, git ref roto):
  ```powershell
  cd C:\Users\xxxv4\iCloudDrive\tradingalertaIA
  Remove-Item -Force .claude\worktrees\reverent-curie-7ccc75
  git worktree prune
  ```

### Decisión usuario: v2.7.0 branch

Existe `claude/xenodochial-taussig-4206c6` (376 tests) sin merge, con fixes deeper que descubrió otra sesión Claude:
- `_update_paper_trades` long-only insta-killeaba shorts (86% del historial son artifacts)
- Módulo realized-R + tabla strategy_performance + comando `/expectancy`
- learning_gate NO activar (mide drift no P&L)

Pendiente decisión user de mergear o no.

### Próximos features
- Strategy `scalping_momentum_continuation` (futuro)
- Heartbeat Telegram con PnL agregado diario
- Auto-tune scalping params según observación
- Session-aware lessons (London/NY/Asian)
- Phase 6 Strategy Evolution (post 3+ meses data)
- Phase 7 Collector RPC blockchain
- Phase 10 Real-money — BLOQUEADO

---

## 11. ERRORES, PROBLEMAS Y SOLUCIONES

### Saga del 27-may al 29-may (sprint mayor)

| # | Bug | Síntoma | Fix | Versión |
|---|---|---|---|---|
| 1 | MT5 huérfanas | 117+ órdenes USDCHF/XAUUSD vivas en MT5 con paper_trades cerrados. User las descubrió manualmente y cerró → reveló gap $9.6k entre paper PnL trackeado (-$2.2k) y balance MT5 real (-$12.1k). | `MT5Reconciler.reconcile()` cada ciclo: cierra huérfanas + sync SL (TIGHTEN only). | v2.6.7 |
| 2 | size_notional inflado | position_sizer usaba ACCOUNT_STARTING_BALANCE=1M teórico. MT5 ejecutaba 0.1 lot (~$10k real). Discrepancia 100-1000×. | `MT5DemoTrader.compute_actual_notional_usd()` + UPDATE paper_trade post-demo_order. Considera USD-base (USDJPY → vol×contract) vs USD-quote (EURUSD/XAUUSD → vol×contract×price). | v2.6.8 |
| 3 | realized_pnl_today inflado | Kill switch falso disparó −3.18% cuando daño real era −0.13%. | Consecuencia de #2. Fix automático cuando size_notional refleja MT5 real. | v2.6.8 |
| 4 | Feedback loop sin dedup símbolo | 159 USDCHF orders en 20 min (~8/min). DEDUP_WINDOW_MINUTES protege alertas pero NO trades. | `RiskManager.check_can_open_trade(symbol=)` + `Repository.has_recent_paper_trade_for_symbol()` + nuevo `STRATEGY_SYMBOL_COOLDOWN_MINUTES=15`. | v2.6.8 |

### Bugs ya resueltos en versiones previas (siguen aplicando)

| Error | Solución | Versión |
|---|---|---|
| `macro_collector` y `economic_calendar_collector` no se ejecutaban | Wiring fix en `__init__` | v2.2.0 |
| Settings.__init__ missing kwargs al agregar settings | Política: actualizar `tests/test_score.py::_settings()` y `tests/test_alert_rules.py::_settings()` en MISMO commit | continuo |
| Logs filtraban `mt5_password` | `__repr__` mascarado + `LogRedactor` filter | v2.1.0 |
| MT5 demo no expone `tick_size`/`tick_value` para algún símbolo | Fallback a `point` + `trade_contract_size` | v2.5.2 |
| MAX_OPEN_TRADES_TOTAL=5 cap bloqueaba forex auto-execute | `DEMO_MAX_TOTAL_RISK_PCT` separado | v2.5.5 |
| Scalping engine silent failure 1909 cycles | `_throttled_warning` + heartbeat | v2.6.2 |
| `get_rates` con timeframe="M1" string | Pasar `MT5_TIMEFRAME_M1=1` int | v2.6.3 |
| `numpy.void` sin `.get()` | `_safe_tick_volume` con bracket access | v2.6.4 |
| `get_rates` símbolo no en Market Watch | `symbol_select(symbol, True)` defensive | v2.6.5 |
| `realized_pnl_today` sumaba % per-trade directamente | USD-based: sum(notional × return%) / balance | v2.6.5 |
| `account_balance` no refrescaba MT5 equity | Retry reconnect + persist a bot_state | v2.6.5 |

### Errores conocidos sin fixear (no críticos)
- **GeckoTerminal 429** rate limiting overnight (esperado, soft-fail)
- **Yahoo RSS 500** esporádicos (esperado, soft-fail)
- **Obsidian auto-gen** files dirty constantemente (intencional)
- **Worktree corrupto** `.claude/worktrees/reverent-curie-7ccc75` quedó vacío post-iCloud corrupción 28-may (inofensivo)

### Riesgos a tener en cuenta
- MT5 desktop debe estar abierto y logueado
- MT5 desktop sleep/computer sleep puede perder conexión
- iCloudDrive sync puede corrupir worktrees nested (como pasó 28-may)
- iCloud puede generar `.tmp.PID.HASH` files o duplicados

---

## 12. DECISIONES IMPORTANTES TOMADAS

### Pivots de identidad

| Versión | Decisión | Razón |
|---|---|---|
| v2.0.0 | alerter → trader engine | User quiere automatizar decisiones |
| v2.0.0 | Memecoins → lab aprendizaje | MT5 no tiene memecoins |
| v2.4.0 | Memecoin Telegram re-activado con learning gate FORZADO | Memecoin Hunter Pro + anti-rug |
| v2.5.0 | Phase 5: order_send a demo con confirmación manual | Cuenta demo lista |
| v2.5.4 | Manual confirm bypassable | Autorización user explícita |
| v2.6.0 | Phase 5.5 Bloque B: Scalping Engine thread dedicado | Acelerar acumulación outcomes |
| **v2.6.6** | **Multi-strategy ScalpingEngine con `self.strategies` list** | Cleanlier para agregar futuras strategies (vs single field) |
| **v2.6.6** | **scalping_mean_reversion como complemento de breakout** | Cubre rangebound markets donde breakout falla |
| **v2.6.7** | **MT5Reconciler como módulo separado, no en lifecycle** | Cleanlier separation of concerns. Lifecycle no necesita saber de MT5 close. |
| **v2.6.7** | **SL sync sólo TIGHTEN, nunca loosen** | Safety: nunca empeorar el risk de una posición ya abierta |
| **v2.6.8** | **size_notional update POST-demo_order, no PRE** | Pre requeriría conocer MT5 antes del sizing. Post es ground truth + simple. |
| **v2.6.8** | **Per-symbol cooldown en risk_manager, no en strategy_router** | Risk gate centralizado vs distribuido. Más simple, más auditable. |
| **v2.6.9** | **NO activar learning_gate** | Preview reveló que con data actual bloquearia ~todo (OUTCOME_WIN_RETURN_* muy estrictos). Esperar más data + recalibrar thresholds. |

### Decisiones técnicas (siguen vigentes)

- Soft-fail para todo lo opcional
- `_SECRET_FIELDS` + `LogRedactor`: doble defensa
- Memecoins con learning gate FORZADO
- Holder concentration / liquidity_locked = None (requieren RPC blockchain Phase 7)
- Bot mode resolution: CLI > bot_state > setting > default trader
- Scalping outcomes al CIERRE, no por horizon
- Alert_id negativo (`-paper_trade.id`) para scalping outcomes (no colisiona con swing)
- Lessons scalping separadas via sufijo `_scalping` en category

### Cosas decididas NO hacer
- ML profundo (LSTM, transformers)
- Reinforcement Learning
- Cifrado at-rest del SQLite
- TradingView integration
- Real-money trading (BLOQUEADO hasta nueva autorización)
- Webhooks externos
- Activar learning_gate con data actual

---

## 13. CONTEXTO OPERATIVO PARA CLAUDE CODE

Cuando retomes este proyecto:

### Qué revisar primero
1. **Leer memoria persistente automáticamente** (este doc + `feedback_read_only_absolute.md` + `project_roadmap_phases.md`)
2. `git status` y `git log --oneline -5`
3. `CHANGELOG.md` para confirmar versión user-facing
4. `app/config/settings.py` línea ~360: `app_version` default debe ser `"v2.6.9"`
5. Corré `pytest tests/ -q` → 357+ verdes
6. Si user menciona métricas:
   ```powershell
   sqlite3 trading_alert_ai.db "SELECT key, value FROM bot_state"
   sqlite3 trading_alert_ai.db "SELECT category, COUNT(*) FROM strategy_lessons GROUP BY category"
   ```

### Archivos críticos — NO TOCAR sin permiso explícito
- `.env` real — **NUNCA leas, modifiques, ni muestres su contenido sin autorización**
- `trading_alert_ai.db` — historial real (no DELETE/UPDATE sin permiso)
- `app/brokers/mt5_demo_trader.py` — código que envía órdenes
- `app/portfolio/mt5_reconciler.py` — cierra/modifica posiciones MT5
- `app/database/db.py::_init_db_unsafe` — schema (cambios via `_ensure_column`)

### Qué preservar SIEMPRE
- **Real-money stays blocked**: `ENABLE_REAL_TRADING=false` HARDCODED
- Auto-confirm + scalping engine son opt-in flags
- `_SECRET_FIELDS` set debe incluir todas las credenciales nuevas
- 357 tests verdes
- Memecoins NO se ejecutan a MT5
- Lifecycle SL-to-breakeven post-TP1 es comportamiento correcto
- Reconciler SL sync sólo TIGHTEN, nunca loosen
- Lessons scalping separadas via sufijo `_scalping`

### Pasos antes de modificar código
1. Leer archivo completo
2. Buscar tests existentes
3. Verificar `tests/test_score.py::_settings()` Y `tests/test_alert_rules.py::_settings()` sincronizados si tocás Settings
4. Correr `pytest tests/<archivo>.py` antes y después
5. Si tocás `jobs.run_once()`, verificar lifecycle + reconciler + collectors + strategy router + learning + dashboard
6. Si tocás `scalping_engine`, verificar thread + caps + force-exit + multi-strategy iteration

### Cómo validar cambios
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q                  # 357+ verdes
.\.venv\Scripts\python.exe main.py --once                       # smoke run
.\.venv\Scripts\python.exe -c "from app.config.settings import load_settings; print(load_settings())"
```

---

## 14. PLAN DE CONTINUACIÓN

### Paso 1 — User aplica 2 cambios en `.env`
```
APP_VERSION=v2.6.9
ENABLE_STRATEGY_FOREX_SESSION_BREAKOUT=false
```

### Paso 2 — Arrancar bot v2.6.9
```powershell
cd C:\Users\xxxv4\iCloudDrive\tradingalertaIA
.\.venv\Scripts\python.exe main.py
```

### Paso 3 — Verificar via Telegram
```
/health
```
Esperado:
- Version: **v2.6.9**
- Balance: ~$88,585
- Kill switch: inactivo
- Demo trading halt: inactivo
- Scalping engine: ACTIVO
- Strategies activas: 4 swing (sin momentum, sin forex_session_breakout) + 2 scalping

### Paso 4 — Observar primer ciclo limpio
Buscar en logs:
- `MT5Reconciler: checked=N closed=X sl_synced=Y` cuando haya posiciones MT5
- `v2.6.8: corrected paper_trade=N size_notional -> X.XX USD` cuando demo_order exitosa
- Lifecycle, learning_cycle, scalping heartbeat OK

### Paso 5 — Esperar 24-48h
- Si reconciler cierra huérfanas, NO debería haber gap entre paper PnL y balance MT5
- realized_pnl_today debería reflejar daño real
- Per-symbol cooldown debería evitar feedback loops

### Paso 6 — Próximas mejoras
1. **Decisión user**: mergear v2.7.0 branch o no
2. v2.7.x: scalping_momentum_continuation strategy
3. Auto-tune scalping params según observación
4. Cuando hay 30+ días lessons confiables: recalibrar OUTCOME_WIN_RETURN_* y considerar activar learning_gate
5. Phase 6 Strategy Evolution post-3-meses-data

---

## 15. CHECKLIST FINAL PARA RETOMAR EN NUEVO CHAT

- [ ] Master context (este doc) cargado automáticamente vía memoria
- [ ] Claude Code respondió confirmando qué entendió
- [ ] Claude Code corrió `git status` → main en `9fc0575`
- [ ] Claude Code corrió `pytest tests/ -q` → 357+ verdes
- [ ] Claude Code leyó `CHANGELOG.md` → última v2.6.9
- [ ] Claude Code confirmó `app_version` default en `settings.py` = `v2.6.9`
- [ ] Claude Code NO modificó `.env` ni `trading_alert_ai.db`
- [ ] Definiste con Claude Code próximo paso prioritario

---

## 16. RESUMEN EJECUTIVO (pegar al inicio del nuevo chat si no auto-carga memoria)

```
# CONTEXTO MAESTRO: Trading Alert AI v2.6.9

## Qué es
Bot de trading algorítmico local Python 3.12 (Windows). Phase 5.5 + sprint 27-28 may
COMPLETO: trader engine swing + scalping engine multi-strategy (breakout +
mean_reversion) + auto-confirm demo MT5 + MT5 Position Reconciler (cierra huérfanas)
+ size_notional accuracy fix + per-symbol cooldown. Real-money 100% bloqueado.

## Path
C:\Users\xxxv4\iCloudDrive\tradingalertaIA\
- Python 3.12.13 en .venv\Scripts\python.exe
- SQLite local trading_alert_ai.db
- Branch git: main
- origin/main: 9fc0575 (v2.6.9)

## Versión actual
v2.6.9 (sprint 27-28 may agregó v2.6.6, v2.6.7, v2.6.8, v2.6.9)
- Tests: 357 verdes
- Bugs descubiertos en validación live 27-may: MT5 huérfanas, size_notional inflado,
  realized_pnl_today falso, feedback loop. TODOS fixeados.
- Working tree limpio

## Cuenta MT5 del usuario
Login: 10010956946
Server: MetaQuotes-Demo
Balance: 88,585.74 USD (era 100,468 originalmente)

## Bot al cierre de sesión
OFF — user cerró madrugada 29-may post-sprint.
bot_state flags todos limpios (kill switch CLEAR, demo halt false, scalping halt false).
Próximo arranque: directo, sin necesidad de liberar flags.

## Configuración deliberada user (NO corregir)
.env conservador post-sprint:
- DEMO_RISK_PER_TRADE_PCT=1.5 (era 5.26)
- DEMO_MAX_OPEN_TRADES=15 (era 100)
- STRATEGY_MIN_CONFIDENCE=65 (era 55)
- ENABLE_STRATEGY_MOMENTUM=false (77% loss rate, -$36k)
- MAX_OPEN_TRADES_TOTAL=25 (era 100)
- APP_VERSION=v2.6.7 (user pendiente bumpear a v2.6.9)

## Pendiente user (2 líneas en .env)
- APP_VERSION=v2.6.9
- ENABLE_STRATEGY_FOREX_SESSION_BREAKOUT=false (73% loss forex)

## Funciona ya
- Phase 5.5 completa + sprint v2.6.6-v2.6.9
- MT5 Position Reconciler cierra huérfanas automático cada ciclo
- size_notional con MT5 real (no teórico inflado)
- Per-symbol cooldown previene feedback loops
- /gate_preview disponible
- 145k+ outcomes acumulados, 63+ lessons

## Decisión user pendiente
v2.7.0 branch sin merge (claude/xenodochial-taussig-4206c6, 376 tests)
con fixes deeper descubiertos por otra sesión Claude.

## Restricciones inamovibles
- ENABLE_REAL_TRADING=false HARDCODED
- order_send solo a MT5 demo via mt5_demo_trader
- Memecoins NO se ejecutan a MT5
- Reconciler SL sync sólo TIGHTEN nunca loosen
- _SECRET_FIELDS enmascarado en logs
- 357 tests verdes deben mantenerse
- NO activar learning_gate con data actual (preview reveló bloquearia ~todo)
```

---

## 17. PROMPT PARA NUEVO CHAT

```
Este es el contexto maestro v2.6.9. Léelo completo. Antes de hacer cualquier cambio:

1. `git status` en C:\Users\xxxv4\iCloudDrive\tradingalertaIA\ y `git log --oneline -10`
2. `.\.venv\Scripts\python.exe -m pytest tests/ -q` → 357+ verdes
3. CHANGELOG.md → confirmar v2.6.9
4. Resume en <200 palabras qué entendiste + próximo paso concreto

NO modifiques `.env`, `trading_alert_ai.db`, Obsidian sin permiso.
NO modifiques `app/brokers/mt5_demo_trader.py` ni `app/portfolio/mt5_reconciler.py` sin análisis profundo.
NO bajes `ENABLE_REAL_TRADING`.
NO hardcodees opt-in flags.
NO "corregís" lifecycle SL-to-breakeven.
NO actives learning_gate (preview reveló bloquearia ~todo).
NO mezcles lessons scalping con swing.
NO toques reconciler SL loosening logic.

Trabajá en español MX, sin emojis, commits descriptivos.

Roadmap futuro:
- v2.7.x: scalping_momentum_continuation + heartbeat agregado
- v2.7.0 branch existe (claude/xenodochial-taussig-4206c6) sin merge — decisión user
- Phase 6: Strategy Evolution (post 3+ meses data)
- Phase 7: Collector RPC blockchain
- Phase 8: Multi-timeframe (M5+H4+D1)
- Phase 9: News/sentiment real-time
- Phase 10: Real-money — BLOQUEADO sin autorización nueva

Confirmá ahora con resumen breve qué entendiste y desde dónde continuamos.
```
