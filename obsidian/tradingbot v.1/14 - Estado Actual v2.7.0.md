---
tags: [estado-actual, version, infra]
version: v2.9.1
updated: 2026-06-04
---

# Estado Actual - v2.9.1

> [!info] El nombre del archivo dice v2.7.0 por historia; el contenido es **v2.9.1** (renombrar rompe los links `[[14 - Estado Actual v2.7.0]]`, por eso se deja).

> [!success] Resumen ejecutivo
> **v2.9.1 en `main` + pushed.** 447 tests verdes. Balance MT5 ~$88,635. Sobre la base v2.7.1 (kill switch fix) se agregaron tres capas: **v2.8.0 Edge Detection** (expectancy sliceada por sesion/direccion + `/edge` + gate sliceado opt-in), **v2.9.0 Hybrid ML** (XGBoost que modula el gate solo hacia abajo, soft-fail, DORMIDO por default) y **v2.9.1** (flag `ENABLE_STOCK_TELEGRAM` para analizar acciones sin alertarlas). Todo subtractivo: el ML/gate jamas causan un order_send. Sigue: ninguna estrategia tiene edge — falta **DATA**, no codigo.

---

## Version y git

| Campo | Valor |
|---|---|
| **Codigo** | v2.10.0 |
| **Branch** | `main` |
| **Main local** | `0486df9` (v2.10.0; push a origin pendiente de OK — v2.9.1 `5a976b5` ya pusheado) |
| **Tests** | **457 verdes** (402 v2.7.1 → 423 v2.8.0 → 445 v2.9.0 → 447 v2.9.1 → 457 v2.10.0) |
| **`.env` APP_VERSION** | pendiente: v2.9.1 (+ `ENABLE_STOCK_TELEGRAM=false`, `ENABLE_MEMECOIN_TELEGRAM=true`) |

### Commits v2.7.0 + v2.7.1 sobre v2.6.9

| Commit | Cambio |
|---|---|
| `5a976b5` | **v2.9.1**: flag ENABLE_STOCK_TELEGRAM (analizar acciones sin alertar) |
| `80bb5db` | **v2.8.0 + v2.9.0**: edge detection sliceado + hybrid ML layer (XGBoost) |
| `fd59478` | **v2.7.1**: realized_pnl_today filtra paper-only trades (kill switch falso fix) |
| `0cc27d6` | Fase 2b: learning loop honesto (realized-R en weights + gate) |
| `f32db0e` | Bump app_version default -> v2.7.0 |
| `ba51599` | Cost model (spread + comision) |
| `3f0b48e` | Realized-R honesto + promotion gate |
| `0cc27d6` | Fase 2b: learning loop honesto (realized-R en weights + gate) |

---

## Lo nuevo v2.8.0 / v2.9.0 / v2.9.1

> [!abstract] Tres capas sobre v2.7.1, todas subtractivas
> Ninguna crea edge ni puede causar un order_send; solo miden y/o restringen.

### v2.8.0 — Edge Detection & Protection Layer
- `session_of` + `build_sliced_performance` → tabla `strategy_performance_sliced`: expectancy realizada en R neto por **estrategia × categoria × sesion × direccion**, refrescada cada learning cycle.
- Comando **`/edge`**: muestra los slices, marca `[OK]` los confiables (n>=`EDGE_SLICE_MIN_SAMPLES`=30) y resalta los +R.
- Gate sliceado (`should_execute_live_sliced`, `ENABLE_SLICED_PROMOTION_GATE` default OFF): **solo manda a SHADOW, nunca promueve** (anti data-dredging).
- Research: ningun slice +R solido aun (positivos con n=4-17 = ruido).

### v2.9.0 — Hybrid ML layer (XGBoost)
- `ml_dataset_builder.py` (dataset de trades cerrados no-artifact + `build_live_features`) + `ml_predictor.py` (`MLPredictor`: XGBClassifier max_depth=5/lr=0.1/n_est=100/subsample=0.8, validacion temporal, AUC sklearn, persistencia pickle `models/xgboost_v1.pkl`, retrain diario con revert si AUC cae >0.05, **modo degradado/soft-fail 0.5**).
- Integracion en el gate (`_ml_gate` en jobs): **downward-only**, doble umbral (`ENABLE_ML_PREDICTOR` default OFF; modula solo con n>=`ML_GATE_MIN_SAMPLES`=400), reduce lot/2 en conf 0.50-0.65, paper-only <0.50, **sin tocar `mt5_demo_trader.py`**. Reentrenamiento diario + comando **`/ml_status`**.
- **Con 189 trades el ML esta DORMIDO**: no toca ninguna decision (corre identico a sin-ML). deps `xgboost==3.2.0` + `scikit-learn==1.9.0` (en el `.venv`).
- **LIMITE de data: `rsi`/`atr` NO se persisten hoy** (quedan NaN); `macd_state` es proxy del alert. → proximo paso de mayor valor: capturarlos al crear el trade.

### v2.9.1 — Toggle de alertas de acciones
- Flag `ENABLE_STOCK_TELEGRAM` (default true): separa **analizar** de **alertar**. Con `false`, las acciones se siguen recolectando/scoreando/aprendiendo pero NO mandan alertas de candidatos a Telegram.
- **NO toca** los avisos de apertura/cierre de trades (`enable_trade_action_reports`).

> [!warning] Riesgo activo en el `.env` del user
> Gold sigue en `DEMO_ALLOWED_SYMBOLS` (XAUUSD,GOLD). Es la categoria mas toxica (-2.79R, 0/12 wins) y con n<30 el gate aun la deja ejecutar a demo. `DEMO_MAX_LOT` subido a 0.1.

---

## CAMBIO DE INFRA CRITICO - DB fuera de iCloud

> [!danger] Por que se movio la DB
> La DB en `iCloudDrive` causaba contencion de I/O brutal: tests tardaban **1h42m** (vs ~60s) y el learning cycle del bot no terminaba, ademas del riesgo de corrupcion.

### Path nuevo

```
SQLITE_PATH=C:/Users/xxxv4/trading_data/trading_alert_ai.db
```

### Reglas de operacion post-movida

> [!warning] Arrancar el bot SIEMPRE desde la carpeta del proyecto
> `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\` — donde esta el `.env`. Si arrancas desde otro lado, no encuentra `SQLITE_PATH` y crearia una DB vacia.

### Data en el path nuevo (verificada)

- 901 paper_trades
- 507.681 signal_outcomes
- 63+ strategy_lessons

### Backups

- `.db` viejo en iCloudDrive queda como **backup congelado** — NO borrar todavia (dejar unos dias con bot andando bien).
- Hay un `trading_alert_ai.db` suelto en `C:\Users\xxxv4\` que es leftover, NO es data real.

---

## Cuenta MT5 del usuario

```
Login:    10010956946
Server:   MetaQuotes-Demo
Balance:  $88,635.74 USD  (era 100,468 originalmente; -$1.40 vs ayer post v2.7.1)
```

> [!info] Sobre el broker
> `MT5_BROKER_PROFILE=icmarkets` controla SOLO el mapeo de simbolos Yahoo<->MT5 (coincide con MetaQuotes-Demo porque usan mismos pares). El broker REAL esta en `MT5_SERVER=MetaQuotes-Demo`.

---

## Estado del bot al cierre (2026-06-03 03:06 UTC)

- **Proceso:** Vivo, balance updated last 2026-06-02T19:46 UTC
- **Validacion v2.7.1 live:** 02-jun el bot operó todo el día tras el fix, 34 paper_trades creados (15 forex + 9 gold + 7 stock + 3 memecoin), solo 1 demo_order MT5 real (AUDUSD long sent OK), balance MT5 estable −$1.40 neto.

### bot_state flags actuales

| Key | Value |
|---|---|
| `account_balance` | 88635.74 |
| `kill_switch_active_until` | (vacio - CLEAR, limpiado post v2.7.1 fix) |
| `kill_switch_reason` | (vacio) |
| `demo_trading_halted` | false |
| `scalping_halted` | false |
| `scalping_active` | true |
| `bot_mode_active` | trader |
| `alerts_paused` | false |

### Validacion live del fix v2.7.1 (2026-06-02)

> [!success] El fix funcionó exactamente como esperaba
> Con 25 paper_trades cerrados ese dia con size_notional > 0:

```
v2.7.0 calc (TODOS los paper):     n=25  USD=-$15,295  drawdown=-17.26%  ← hubiera disparado kill switch
v2.7.1 calc (solo con demo_order): n=1   USD=-$4.80    drawdown=-0.005%  ← realidad MT5
```

9 paper_trades GC=F (gold) con notionals $147k-$246k cerraron stopped pero ningún demo_order para gold (GC=F no matchea allowed XAUUSD/GOLD post-yahoo_to_mt5). Paper PnL "imaginario": ~−$11,743. Real impact MT5: $0.

Esto confirma 100% que el filtro paper-only del v2.7.1 funciona y previene falsos kill switches.

---

## Expectancy real (snapshot 2026-06-03)

> [!warning] Toda estrategia que ejecuta a MT5 tiene R negativo neto
> El bot **mide la verdad** y frena losers, NO crea edge. La única R+ es `unknown/memecoin` pero memecoin no ejecuta a MT5 (solo paper/lab).

```
[SHADOW] forex_session_breakout/forex: n=44  avgR=-0.44   win=20%  (arts_excl=340)
[SHADOW] unknown/stock:                n=42  avgR=-0.049  win=38%
[LIVE  ] momentum/forex:               n=26  avgR=-0.45   win=31%
[LIVE  ] unknown/memecoin:             n=24  avgR=+0.337  win=46%  ← UNICA R+, paper-only
[LIVE  ] momentum/stock:               n=22  avgR=-0.32   win=36%
[LIVE  ] forex_session_breakout/gold:  n=12  avgR=-2.79   win=0%   ← TOXICA (0/12 wins)
[LIVE  ] mean_reversion/forex:         n=8   avgR=-0.47   win=13%
[LIVE  ] mean_reversion/stock:         n=6   avgR=-0.42   win=0%
[LIVE  ] momentum/gold:                n=3   avgR=-1.08   win=0%
[LIVE  ] scalping_breakout/forex:      n=1   avgR=-0.36
[LIVE  ] mean_reversion/gold:          n=1   avgR=-4.41
```

- `forex_session_breakout/forex` ahora SHADOW (n=44 ≥ 30, R<0).
- `unknown/stock` SHADOW.
- `forex_session_breakout/gold` con n=12 sigue LIVE pero **0/12 wins en gold** — clara toxicidad. Auto-SHADOW cuando llegue a n=30.
- `momentum/*` deshabilitado en `.env` user (no abrira nuevos).
- En 24h del 02-jun: 34 paper_trades creados, **solo 1 llego a MT5 demo** — gate funcionando perfectamente.

---

## Pendientes inmediatos del user

> [!todo] Lista corta (v2.9.1)
> - [ ] **Aplicar `.env`**: `APP_VERSION=v2.9.1` + `ENABLE_STOCK_TELEGRAM=false` + `ENABLE_MEMECOIN_TELEGRAM=true`
> - [ ] **Arrancar** con el python del venv (`.\.venv\Scripts\python.exe main.py`), MT5 abierto+logueado. Chequear `/health`, `/ml_status` (DORMIDO), `/edge`
> - [ ] **Considerar sacar gold** de `DEMO_ALLOWED_SYMBOLS` (toxica; el gate aun no la frena por n<30)
> - [ ] **Dejar correr** para juntar muestra limpia
> - [ ] (mayor valor futuro) capturar `rsi`/`atr` al crear el trade → features reales para el ML
> - [ ] Borrar `.db` viejo de iCloud (en unos dias)

---

## Links relacionados

- [[03 - Versiones y Cambios]] - historia completa
- [[16 - Bugs Resueltos]] - como llegamos aca
- [[17 - Promotion Gate y Cost Model]] - el alma de v2.7.0
- [[18 - Realized R y Aprendizaje Honesto]] - Fase 2b
- [[15 - Estrategias]] - detalle por strategy
