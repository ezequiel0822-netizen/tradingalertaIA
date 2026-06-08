---
tags: [configuracion, env, settings]
version: v2.7.0
updated: 2026-05-30
---

# Configuracion Operativa

> [!info] Donde viven las variables
> Variables van al `.env` real en `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\.env`. NO al `.env.example` (que es template publico). NUNCA poner secretos reales en `.env.example` ni en este vault.

---

## Variables obligatorias (sin esto el bot no funciona)

```bash
# Telegram (de BotFather)
TELEGRAM_BOT_TOKEN=<token-real>
TELEGRAM_CHAT_ID=<chat-id-real>

# MT5 (MetaQuotes-Demo)
MT5_LOGIN=10010956946
MT5_PASSWORD=<password>
MT5_SERVER=MetaQuotes-Demo
ENABLE_MT5_READER=true
MT5_BROKER_PROFILE=icmarkets
MT5_CONNECTION_TIMEOUT_MS=5000
```

> [!warning] MT5_BROKER_PROFILE
> Controla SOLO el mapeo de simbolos Yahoo<->MT5 (coincide con MetaQuotes-Demo porque usan mismos pares). El broker REAL esta en `MT5_SERVER`.

---

## Settings nuevos v2.7.0

```bash
# DB local (sale de iCloud)
SQLITE_PATH=C:/Users/xxxv4/trading_data/trading_alert_ai.db

# Promotion gate (default ON, restrictivo)
ENABLE_STRATEGY_PROMOTION_GATE=true
STRATEGY_PROMOTION_MIN_SAMPLES=30
STRATEGY_PROMOTION_MIN_EXPECTANCY_R=0.0

# Cost model (round-trip % por categoria, defaults conservadores)
ENABLE_COST_MODEL=true
COST_ROUNDTRIP_PCT_FOREX=0.02
COST_ROUNDTRIP_PCT_GOLD=0.03
COST_ROUNDTRIP_PCT_STOCK=0.05
COST_ROUNDTRIP_PCT_MEMECOIN=0.5

# Fase 2b — learning honesto
ENABLE_REALIZED_LEARNING=true
```

---

## Settings nuevos v2.6.6-v2.6.9

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

---

## `.env` actual del usuario (configuracion deliberada)

> [!info] Riesgo apretado post-sprint 27-may
> Tras la perdida de $12k del 27-may, el user endurecio significativamente los parametros de riesgo y caps. Los siguientes valores son DELIBERADOS.

```bash
APP_VERSION=v2.7.0
BOT_MODE=trader

# Real-money NUNCA se activa
ENABLE_REAL_TRADING=false

# Demo trading: conservador
ENABLE_MT5_DEMO_TRADING=true
DEMO_ORDER_REQUIRE_CONFIRMATION=true
ENABLE_AUTO_CONFIRM_DEMO=true
DEMO_MAX_OPEN_TRADES=15            # era 100 pre-sprint
DEMO_RISK_PER_TRADE_PCT=1.5        # era 5.26 pre-sprint
DEMO_MAX_TOTAL_RISK_PCT=6.0        # era 10.0 pre-sprint
DEMO_MAX_LOT=0.1
DEMO_ALLOWED_SYMBOLS=EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,NZDUSD,XAUUSD,GOLD
DEMO_TRADE_REQUEST_TTL_MINUTES=5

# Scalping engine
ENABLE_SCALPING_ENGINE=true
SCALPING_ALLOWED_SYMBOLS=EURUSD,GBPUSD,USDJPY
SCALPING_RISK_PER_TRADE_PCT=1.0
SCALPING_MAX_TRADES_PER_DAY=100
SCALPING_MAX_OPEN_TRADES=5
SCALPING_MAX_DAILY_LOSS_PCT=3.0
SCALPING_FORCE_EXIT_MINUTES=3
SCALPING_POLL_INTERVAL_SECONDS=3
SCALPING_HEARTBEAT_EVERY_N_TRADES=10
SCALPING_SL_PIPS=6
SCALPING_TP_PIPS=8
SCALPING_RANGE_LOOKBACK_BARS=5

# Trading/risk: caps apretados
MAX_OPEN_TRADES_TOTAL=25            # era 100
MAX_OPEN_TRADES_STOCK=10            # era 30
MAX_OPEN_TRADES_FOREX=15            # era 40
MAX_OPEN_TRADES_GOLD=5              # era 10
ACCOUNT_STARTING_BALANCE=1000000    # teorico fallback
RISK_PER_TRADE_PCT=0.5
MAX_TOTAL_RISK_PCT=10.0
MAX_DAILY_DRAWDOWN_PCT=3.0
KILL_SWITCH_COOLDOWN_HOURS=24
ENABLE_KILL_SWITCH_AUTO=true

# Strategies — thresholds subidos
ENABLE_STRATEGY_ROUTER=true
STRATEGY_MIN_CONFIDENCE=65           # era 55
ENABLE_STRATEGY_BREAKOUT=true
ENABLE_STRATEGY_MEAN_REVERSION=true
ENABLE_STRATEGY_MOMENTUM=false       # DESHABILITADA (77% loss rate, -$36k)
ENABLE_STRATEGY_NEWS_CATALYST=true
ENABLE_STRATEGY_FOREX_SESSION_BREAKOUT=true  # PENDIENTE deshabilitar (-0.51R)

# Lifecycle
ENABLE_PARTIAL_CLOSE_AT_TP1=true
PARTIAL_CLOSE_FRACTION=0.5
ENABLE_TIME_BASED_EXIT=true
DEFAULT_TIME_HORIZON_HOURS=48
ENABLE_INVALIDATION_EXIT=true
LIFECYCLE_REEVAL_EVERY_N_CYCLES=5

# Alertas/ciclos: volumen reducido
POLL_INTERVAL_SECONDS=60
MAX_ALERTS_PER_RUN=15                # era 30
DEDUP_WINDOW_MINUTES=360             # era 180
MAX_SNAPSHOTS_PER_RUN=120
MAX_SECURITY_CHECKS_PER_RUN=40
ALERT_CAP_WINDOW_HOURS=24

# Stock/ETF universe (22 simbolos)
ENABLE_STOCK_ALERTS=true
STOCK_SYMBOLS=AAPL,MSFT,NVDA,TSLA,AMD,META,AMZN,GOOGL,SPY,QQQ,COIN,MSTR,PLTR,SMCI,NFLX,GLD,XOM,CVX,BAC,SLV,USO,TNA
MIN_STOCK_ESTIMATED_GAIN_PCT=8       # era 6
MIN_STOCK_ESTIMATE_CONFIDENCE=60     # era 50
MAX_STOCK_ALERTS_PER_24H=20          # era 30
STOCK_MAX_ALERTS_PER_RUN=5           # era 10

# Memecoin
MIN_LIQUIDITY_USD=8000
MIN_VOLUME_5M_USD=4000
MIN_VOLUME_1H_USD=12000
ALERT_SCORE_THRESHOLD=65             # era 60
CRITICAL_RISK_ALERTS=true
MIN_ESTIMATED_GAIN_PCT=300
MIN_ESTIMATE_CONFIDENCE=40
ENABLE_MEMECOIN_TELEGRAM=true
ENABLE_EARLY_MEMECOIN_DETECTION=true
MAX_EARLY_POOL_AGE_HOURS=6
ENABLE_MEMECOIN_HUNTER=true
MEMECOIN_HUNTER_MIN_VOLUME_VELOCITY_RATIO=1.8
MAX_EARLY_MEMECOIN_ALERTS_PER_24H=10
MAX_MATURE_MEMECOIN_ALERTS_PER_24H=10
MAX_EARLY_MEMECOIN_ALERTS_PER_RUN=3
FORCE_LEARNING_GATE_FOR_MEMECOIN=true
CHAINS_TO_MONITOR=solana,ethereum,base,bsc

# Forex/gold
ENABLE_FOREX_COLLECTOR=true
FOREX_SYMBOLS=EURUSD=X,GBPUSD=X,USDJPY=X,USDCHF=X,AUDUSD=X,USDCAD=X,NZDUSD=X,GC=F
ENABLE_FOREX_ALERTS=true
ENABLE_GOLD_ALERTS=true
MAX_FOREX_ALERTS_PER_24H=30
MAX_GOLD_ALERTS_PER_24H=15           # era 50
MAX_FOREX_ALERTS_PER_RUN=5
MAX_GOLD_ALERTS_PER_RUN=2            # era 10

# Outcome thresholds recalibrados v2.6.5
OUTCOME_WIN_RETURN_MEMECOIN_PCT=30
OUTCOME_LOSS_RETURN_MEMECOIN_PCT=-15
OUTCOME_WIN_RETURN_STOCK_PCT=5
OUTCOME_LOSS_RETURN_STOCK_PCT=-3

# Learning
ENABLE_LEARNING_ENGINE=true
LEARNING_MIN_ALERT_AGE_MINUTES=30
LEARNING_MAX_ALERTS_PER_RUN=500
ENABLE_PAPER_TRADING=true
PAPER_TRADE_MAX_ACTIVE=150
READINESS_MIN_SCORE=72               # era 65
READINESS_MIN_CONFIDENCE=65          # era 55

# Learned weights ACTIVO desde v2.6.5
ENABLE_LEARNED_WEIGHTS=true
LEARNED_WEIGHTS_MIN_SAMPLES=5
LEARNED_WEIGHTS_MIN_CONFIDENCE=40
LEARNED_WEIGHTS_PER_FEATURE_MAX=3.0
LEARNED_WEIGHTS_MAX_ADJUSTMENT=10.0

# Learning gate todavia OFF (NO activar - mide casi todo como neutral)
ENABLE_LEARNING_GATE=false
LEARNING_GATE_MIN_WIN_RATE=0.45
LEARNING_GATE_MIN_SAMPLES=10
LEARNING_GATE_HORIZON_HOURS=24
LEARNING_GATE_SINCE_DAYS=30

# ATR-based SL/TP
ENABLE_ATR_BASED_SLTP=true
ATR_STOP_MULTIPLIER=2.0
ATR_TP1_MULTIPLIER=2.0
ATR_TP2_MULTIPLIER=4.0
ENABLE_TRAILING_STOP=true
TRAILING_ACTIVATION_PCT_STOCK=5.0
TRAILING_ACTIVATION_PCT_MEMECOIN=50.0
TRAILING_DISTANCE_PCT_STOCK=3.0
TRAILING_DISTANCE_PCT_MEMECOIN=25.0

# Snapshots + horizons
ENABLE_PRICE_SNAPSHOTS=true
SNAPSHOT_RETENTION_DAYS=30
HORIZON_MIN_SNAPSHOTS=2
ENABLE_HORIZON_EVALUATOR=true
BACKTEST_MIN_SAMPLES=5
BACKTEST_DEFAULT_HORIZON_HOURS=24
ENABLE_WEEKLY_OBSIDIAN_REPORT=true

# Walk-forward + data quality
ENABLE_WALK_FORWARD_BACKTEST=true
WALK_FORWARD_TRAIN_DAYS=14
WALK_FORWARD_TEST_DAYS=7
WALK_FORWARD_SLIDE_DAYS=1
WALK_FORWARD_MIN_TRAIN_SAMPLES=10
ENABLE_DATA_QUALITY_MONITOR=true
DATA_QUALITY_CHECK_EVERY_N_CYCLES=10
DATA_QUALITY_STALENESS_MAX_MINUTES=15
DATA_QUALITY_GAP_THRESHOLD_MULTIPLIER=2.0
ENABLE_CSV_EXPORT=true
CSV_EXPORT_PATH=exports

# Macro + calendar
ENABLE_MACRO_CONTEXT=true
ENABLE_MACRO_COLLECTOR=true
MACRO_COLLECTOR_INTERVAL_MINUTES=60
ENABLE_ECONOMIC_CALENDAR=true
CALENDAR_BUFFER_MINUTES=30
CALENDAR_REFRESH_HOURS=12

# Intelligence
ENABLE_ADVANCED_MARKET_INTEL=true
ENABLE_PRO_INTELLIGENCE=true
ENABLE_NEWS_INTEL=true
MAX_CHART_ANALYSES_PER_RUN=10
MAX_NEWS_PER_SYMBOL=5
ENABLE_SEC_FILINGS_INTEL=true
MAX_SEC_FILINGS_PER_RUN=10
MAX_SEC_FILINGS_PER_SYMBOL=5
SEC_RECENT_DAYS=14
SEC_USER_AGENT=TradingAlertAI/2.7.0 local-read-only j0h4n2203@gmail.com

# Telegram assistant
ENABLE_TELEGRAM_ASSISTANT=true
TELEGRAM_ASSISTANT_MAX_UPDATES=10

# Claude (opcional)
ANTHROPIC_API_KEY=
ENABLE_CLAUDE_INTEGRATION=false
CLAUDE_MODEL=claude-haiku-4-5
CLAUDE_MAX_TOKENS=1024
CLAUDE_CALLS_PER_CYCLE_CAP=6
CLAUDE_CACHE_TTL_SECONDS=3600
CLAUDE_MAX_COST_PER_DAY_USD=2.0

# Obsidian
ENABLE_OBSIDIAN_MEMORY=true
OBSIDIAN_VAULT_PATH=obsidian/tradingbot v.1
REQUEST_TIMEOUT_SECONDS=15
```

---

## Cambios vs master context v2.6.5 (resumen)

| Setting | Antes (v2.6.5) | Ahora (v2.7.0) | Por que |
|---|---|---|---|
| `DEMO_RISK_PER_TRADE_PCT` | 5.26 | 1.5 | Reducir USD por loss |
| `DEMO_MAX_OPEN_TRADES` | 100 | 15 | Evitar stack catastrofico (huerfanas) |
| `DEMO_MAX_TOTAL_RISK_PCT` | 10.0 | 6.0 | Tope exposicion |
| `STRATEGY_MIN_CONFIDENCE` | 55 | 65 | Filtrar signals debiles |
| `READINESS_MIN_SCORE` | 65 | 72 | Subir barrera |
| `MAX_OPEN_TRADES_TOTAL` | 100 | 25 | Menos correlacion entre perdidas |
| `MAX_OPEN_TRADES_STOCK/FOREX/GOLD` | 30/40/10 | 10/15/5 | Proporcional |
| `ENABLE_STRATEGY_MOMENTUM` | true | **false** | 77% loss rate, -$36k impact |
| `MAX_GOLD_ALERTS_PER_24H/RUN` | 50/10 | 15/2 | Limita gold |
| `DEDUP_WINDOW_MINUTES` | 180 | 360 | Mismo simbolo no re-alerta cada 3h |
| `APP_VERSION` | v2.6.5 | v2.7.0 | Bump |

---

## Paths importantes

| Path | Que |
|---|---|
| `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\.env` | `.env` real (NO en git) |
| `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\.venv\Scripts\python.exe` | Python 3.12.13 venv |
| `C:\Users\xxxv4\trading_data\trading_alert_ai.db` | DB activa post v2.7.0 |
| `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\trading_alert_ai.db` | Backup congelado |
| `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\obsidian\tradingbot v.1\` | Este vault |
| `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\exports\` | CSV exports |
| `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\CONTEXTO_MAESTRO_v2.7.0.md` | Mirror tecnico maestro |

---

## Smoke test - settings cargan correctamente

```powershell
.\.venv\Scripts\python.exe -c "from app.config.settings import load_settings; s=load_settings(); print('Version:', s.app_version); print('Real trading:', s.enable_real_trading); print('Demo:', s.enable_mt5_demo_trading); print('Scalping:', s.enable_scalping_engine); print('Gate:', s.enable_strategy_promotion_gate); print('Cost model:', s.enable_cost_model); print('Realized learning:', s.enable_realized_learning); print('DB path:', s.sqlite_path)"
```

Esperado v2.7.0:
- Version: v2.7.0
- Real trading: False
- Demo: True
- Scalping: True
- Gate: True
- Cost model: True
- Realized learning: True
- DB path: `C:\Users\xxxv4\trading_data\trading_alert_ai.db`

---

## Links relacionados

- [[02 - Reglas de Seguridad]] - lo inamovible
- [[12 - Guia de Uso]] - como operar
- [[17 - Promotion Gate y Cost Model]] - settings v2.7.0 explicados
