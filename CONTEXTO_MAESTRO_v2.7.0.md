# CONTEXTO MAESTRO — Trading Alert AI v2.7.0

Documento de handoff completo. Cierre de sesión **2026-05-30**. Reemplaza `CONTEXTO_MAESTRO_v2.6.9.md` (que quedó desactualizado: describía v2.7.0 como "branch sin merge, 376 tests"; ahora v2.7.0 está **mergeado a main + pusheado a GitHub (commit `0cc27d6`), 397 tests**, incluye Fase 2b (learning honesto) y se movió la DB fuera de iCloud).

Para los apéndices estáticos (arquitectura, schema completo, por-qué de decisiones viejas) ver `CONTEXTO_MAESTRO_v2.6.9.md` — acá se documenta el estado actual + el delta v2.7.0.

---

## 1. RESUMEN GENERAL

**Trading Alert AI v2.7.0** — Bot de trading algorítmico **local** en Python 3.12 (Windows, PowerShell + venv). Detecta oportunidades en memecoins / acciones US / forex / oro, decide con un strategy router (5 swing + 2 scalping), opera paper trades simulados y envía órdenes a **MT5 demo (MetaQuotes-Demo)**. Real-money trading **bloqueado por design (HARDCODED)**.

**El cambio de identidad de v2.7.0:** el bot pasó de medir una métrica de aprendizaje **ficticia** (el "drift" de la alerta a horizonte fijo) a medir el **P&L realizado real, neto de costos, en R-multiples**, y a **no ejecutar a MT5 estrategias con edge negativo probado** (promotion gate / shadow mode). Objetivo sigue siendo: acumular 3+ meses de demo estable (sharpe>1, win_rate>50%, maxDD<10%) antes de considerar real-money con autorización nueva.

---

## 2. ESTADO ACTUAL EXACTO (2026-05-30)

### Versión y git
- **Versión código:** v2.7.0
- **Branch:** `main` (la branch `claude/xenodochial-taussig-4206c6` ya está 100% mergeada por fast-forward)
- **`origin/main`:** `0cc27d6` — **PUSHEADO a GitHub** (en sync, 0 commits pendientes)
- **Tests:** **397 verdes**
- Commits v2.7.0 sobre `9fc0575` (v2.6.9):
  - `3f0b48e` — realized-R honesto + promotion gate
  - `ba51599` — cost model (spread+comisión)
  - `f32db0e` — bump app_version default → v2.7.0
  - `0cc27d6` — Fase 2b: learning loop honesto (realized-R en weights + gate)

### CAMBIO DE INFRA CRÍTICO: la DB salió de iCloud
- **La DB ahora vive en path LOCAL:** `C:\Users\xxxv4\trading_data\trading_alert_ai.db`
- Se configuró con `SQLITE_PATH=C:/Users/xxxv4/trading_data/trading_alert_ai.db` en el `.env` real.
- **Por qué:** la DB estaba en `iCloudDrive`, lo que causaba contención de I/O brutal — los tests tardaban **1h42m** (vs ~60s) y el learning cycle del bot no llegaba a terminar, además del riesgo de corrupción documentado. Mover la DB a un path local resolvió todo eso.
- **El `.db` viejo en `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\trading_alert_ai.db` quedó como BACKUP CONGELADO** — no borrar todavía (dejar unos días con el bot andando bien primero). Data nueva va al path local.
- **IMPORTANTE: arrancar el bot SIEMPRE desde la carpeta del proyecto** (`C:\Users\xxxv4\iCloudDrive\tradingalertaIA`), que es donde está el `.env` — si no, no encuentra `SQLITE_PATH` y crearía una DB vacía.
- Data en el path nuevo: **901 paper_trades, 507.681 signal_outcomes** (copia idéntica de la histórica).
- (Dato menor: hay un `trading_alert_ai.db` suelto viejo en `C:\Users\xxxv4\` — leftover, NO es data real, ignorar/borrar cuando se quiera.)

### Cuenta MT5 del usuario
```
Login:    10010956946
Server:   MetaQuotes-Demo   (NO ICMarkets, a pesar de MT5_BROKER_PROFILE=icmarkets que solo controla symbol mapping)
Balance:  ~88,585 USD       (era 100,468 originalmente; sin cambio material esta sesión)
```

### Estado del bot al cierre
- **Proceso:** OFF. (En esta sesión se corrió `main.py --once` para smoke test; corrió limpio, cerró 16 trades viejos por tiempo, pero el learning cycle no llegó a persistir por la lentitud de iCloud — por eso se movió la DB.)
- `bot_state` flags: kill switch CLEAR, demo_trading_halted false, scalping_halted false, scalping_active true, bot_mode trader.

---

## 3. QUÉ TRAJO v2.7.0 (el delta vs v2.6.9)

### Hallazgo raíz (Fix A — keystone)
`training_engine._update_paper_trades` era **LONG-ONLY** (`if latest <= stop`). Para un SHORT el stop está POR ENCIMA del entry → cada short se marcaba `stopped_simulated` en el MISMO ciclo de creación (vida ~12s, precio congelado en entry). Corría junto a `lifecycle_manager.manage_open_positions` (direction-aware) = doble-management conflictivo. **Resultado: ~86% del historial de paper_trades eran artifacts del feedback-loop, no trades reales.** Ahora `_update_paper_trades` es direction-aware. Cascada: mata el instant-kill → los trades viven su horizonte → el dedup de posiciones abiertas frena el feedback-loop → los precios dejan de congelarse.

### Fix C — precio fresco real para forex/gold
`lifecycle_manager._fresh_price` pasaba el símbolo Yahoo crudo (`USDCHF=X`) a `get_tick`, que siempre fallaba → caía a precio stale. Ahora mapea Yahoo→MT5 (`yahoo_to_mt5`, ej. `USDCHF=X`→`USDCHF`, `GC=F`→`XAUUSD`) antes del tick.

### Fix D — señal de aprendizaje HONESTA (realized-R)
Nuevo módulo `app/learning/trade_outcomes.py`:
- `realized_return_pct` (direction-aware, con partial close, NETO de costos)
- `risk_at_entry_pct` (usa `original_stop_loss`, respeta el SL-to-breakeven)
- `r_multiple`, `is_artifact` (detecta precio congelado), `outcome_label`
- `build_strategy_performance` → agrupa por (strategy_name, category), excluye artifacts, calcula expectancy en R
- `should_execute_live` → el promotion gate

Tabla nueva `strategy_performance` (PK strategy_name+category), refrescada cada learning cycle vía `_refresh_strategy_performance` (training_engine.py línea ~57, dentro de `if enable_paper_trading`). Comando Telegram **`/expectancy`** (muestra R neto + tags LIVE/SHADOW por estrategia).

### Promotion gate (shadow mode) — protección de capital
`should_execute_live(strategy, category, perf_row, min_samples, min_expectancy_r)`. Filosofía "inocente hasta probarse culpable": permite ejecutar a MT5 salvo que la estrategia tenga **edge negativo PROBADO** (avg_r ≤ umbral con n ≥ min_samples). Las no probadas pasan (juntando data). Los losers probados quedan **paper-only (SHADOW)**. Hooks en `jobs._try_prepare_demo_order` (swing) y `scalping_engine._open_scalping_trade` (scalping). **NO toca la creación de paper_trades ni el real-money — solo decide si se manda el order_send a demo.** La data de aprendizaje se junta IGUAL esté LIVE o SHADOW (el gate solo controla el order_send a MT5).

### Cost model — hace confiable al gate
`build_strategy_performance` resta un costo round-trip por categoría del retorno bruto de cada trade (siempre resta). Sin esto el realized-R era optimista vs MT5 real y el gate podía promover estrategias positivas-en-bruto-pero-netas-negativas.

### Fase 2b — learning loop honesto (realized-R en weights + gate)
`learned_weights` y `learning_gate` aprendían del DRIFT de la alerta (umbrales absolutos → ~99% 'neutral', gate inútil que bloqueaba casi todo). Con `ENABLE_REALIZED_LEARNING` (default ON) ahora aprenden del **P&L realizado** de paper_trades: tabla nueva `realized_feature_lessons` (R por feature, NETO de costos, excluye artifacts), construida por `build_realized_feature_lessons` (junta cada paper_trade cerrado → su R → las features del alert linkeado desde signal_outcomes) y refrescada cada learning cycle (`_refresh_realized_feature_lessons`). `apply_learned_weights` y `evaluate_learning_gate` (nuevo `_evaluate_gate_realized`) consultan esa señal honesta. **El `learning_gate` ahora SÍ es activable** (bloquea por win_rate realizado probado con n≥min_samples, no por drift). El drift path queda como fallback reversible (flag off; los tests viejos lo cubren). Caveat honesto: data por-feature escasa (~120 trades) → el gate/weights realizados actúan poco hasta juntar más data limpia (testeado). +7 tests (`test_realized_learning.py`).

### Security review (esta sesión) — LIMPIO
Se corrió `security-review` sobre v2.7.0: **0 hallazgos HIGH/MEDIUM.** SQL todo parametrizado, el gate es estrictamente subtractivo (nunca puede causar un order_send, solo prevenirlo), real-money intacto, sin secrets logueados, sin injection/deserialization.

---

## 4. EXPECTANCY REAL (sobre los 901 paper_trades, NETA de costos)

Confirmado read-only esta sesión. **TODAS las estrategias dan R negativo** — la medición honesta aguanta: ninguna tiene edge todavía.

```
[SHADOW] unknown/stock:                n=32  avgR=-0.039  win=34%
[LIVE  ] forex_session_breakout/forex: n=24  avgR=-0.512  win=12%   (arts_excl=339)
[LIVE  ] momentum/forex:               n=22  avgR=-0.657  win=23%
[LIVE  ] momentum/stock:               n=20  avgR=-0.406  win=35%
[LIVE  ] unknown/memecoin:             n=16  avgR=-0.280  win=25%
[LIVE  ] mean_reversion/forex:         n=6   avgR=-0.156
[LIVE  ] mean_reversion/stock:         n=5   avgR=-0.259  (arts_excl=171)
[LIVE  ] momentum/gold:                n=3   avgR=-1.077
[LIVE  ] forex_session_breakout/gold:  n=2   avgR=-1.107  (arts_excl=208)
[LIVE  ] scalping_breakout/forex:      n=1   avgR=-0.362
```

- La quarantine excluyó **~770 artifacts**, quedando ~120 trades reales.
- Con `min_samples=30`, el gate hoy solo manda a SHADOW `unknown/stock` (que es paper-only igual). `momentum` ya está disabled en `.env`. `forex_session_breakout/forex` (-0.51R) sigue LIVE porque tiene n=24 (<30) — está a ~6 trades de auto-SHADOW. Para protegerlo ya: aplicar el flag manual (ver pendientes) o bajar `STRATEGY_PROMOTION_MIN_SAMPLES`.

**La verdad de fondo:** v2.7.0 hace que el bot (1) mida la verdad neta de costos y (2) no ejecute losers probados. NO crea edge — eso sigue siendo el problema difícil (datos + research).

---

## 5. CONFIGURACIÓN — settings nuevos v2.7.0 (defaults)

```bash
# DB fuera de iCloud (aplicado en el .env real esta sesión)
SQLITE_PATH=C:/Users/xxxv4/trading_data/trading_alert_ai.db

# Promotion gate
ENABLE_STRATEGY_PROMOTION_GATE=true        # default ON (gate restrictivo = reduce riesgo)
STRATEGY_PROMOTION_MIN_SAMPLES=30
STRATEGY_PROMOTION_MIN_EXPECTANCY_R=0.0

# Cost model (round-trip % por categoría, defaults conservadores MT5 demo)
ENABLE_COST_MODEL=true
COST_ROUNDTRIP_PCT_FOREX=0.02
COST_ROUNDTRIP_PCT_GOLD=0.03
COST_ROUNDTRIP_PCT_STOCK=0.05
COST_ROUNDTRIP_PCT_MEMECOIN=0.5

# Fase 2b — learning honesto (learned_weights + learning_gate sobre realized-R)
ENABLE_REALIZED_LEARNING=true

# Default de versión (settings.py) ahora v2.7.0
```

El resto del `.env` conservador del user sigue vigente (de v2.6.9): `DEMO_RISK_PER_TRADE_PCT=1.5`, `DEMO_MAX_OPEN_TRADES=15`, `STRATEGY_MIN_CONFIDENCE=65`, `MAX_OPEN_TRADES_TOTAL=25`, `ENABLE_STRATEGY_MOMENTUM=false`, `ENABLE_LEARNING_GATE=false`, etc.

---

## 6. PENDIENTES (lado del usuario)

1. **`.env` real** (`SQLITE_PATH` y `APP_VERSION=v2.7.0` ya aplicados por el user):
   - **Pendiente:** `ENABLE_STRATEGY_FOREX_SESSION_BREAKOUT=false` (loser claro, -0.51R; el gate lo agarra solo en ~6 trades, pero el disable manual lo mata ya).
2. **Validar el bot un ciclo completo** con la DB local — ahora el learning cycle debería terminar rápido y poblar `strategy_performance` (verificar con `/expectancy` en Telegram, con los tags LIVE/SHADOW).
3. **Borrar (eventualmente) el `.db` viejo de iCloud** tras unos días estables.
4. Cleanup cosmético: worktree `reverent-curie-7ccc75` corrupto + la branch `xenodochial-taussig-4206c6` ya mergeada (se puede podar).

---

## 7. PRÓXIMOS PASOS / ROADMAP

**Hecho en esta sesión (v2.7.0 COMPLETO):** Fix A/C/D + promotion gate + cost model + **Fase 2b** (learned_weights/learning_gate re-apuntados al realized-R → el `learning_gate` ya es activable) + DB fuera de iCloud. Todo mergeado a main y pusheado a GitHub.

**El cuello de botella ahora NO es código, es DATA.** Toda estrategia da R negativo neto; el bot mide la verdad y protege capital, pero no hay edge todavía. Lo más valioso de acá en adelante:

1. **Dejar correr el bot días/semanas** con la DB local → acumular trades limpios (post-Fix-A). Eso solo: el promotion gate manda más losers a SHADOW al llegar a n≥30, las `realized_feature_lessons` se densifican, y recién ahí tiene sentido activar el `learning_gate`.
2. **Búsqueda de edge (el objetivo real, honesto):** slicear `strategy_performance` por sesión (London/NY/Asian) y régimen (risk_on/off) para encontrar bolsillos donde alguna estrategia sea +R; calibrar el cost model con los fills reales de `demo_orders`.
3. **Observabilidad:** heartbeat diario a Telegram con expectancy + tags LIVE/SHADOW.
4. **Recalibrar** `OUTCOME_WIN_RETURN_*` y, con data suficiente, **activar el `learning_gate`** (`ENABLE_LEARNING_GATE=true`).
5. **Phase 6 Strategy Evolution** (post 3+ meses data + ≥1 strategy con R+ neto) — el promotion gate es su primer ladrillo.
6. Phase 7+ (blockchain RPC, multi-timeframe, news/sentiment), Phase 10 real-money (BLOQUEADO sin autorización nueva).

**Recomendación al cierre de esta sesión:** dejar de codear y **dejar correr** para juntar data; los próximos features rinden poco hasta tenerla.

---

## 8. RESTRICCIONES INAMOVIBLES (NO romper)

- `ENABLE_REAL_TRADING=false` HARDCODED. order_send solo a MT5 demo vía `mt5_demo_trader` (único módulo).
- Auto-confirm + scalping engine son opt-in flags. NO hardcodear.
- Memecoins NO se ejecutan a MT5 (solo paper/lab).
- Lifecycle SL-to-breakeven post-TP1 es correcto. NO "corregir".
- MT5Reconciler sync de SL solo TIGHTEN, nunca loosen.
- Lessons scalping separadas via sufijo `_scalping`.
- El promotion gate es subtractivo: solo PREVIENE order_send, nunca lo causa.
- **397 tests verdes** deben mantenerse.
- Nunca leer/modificar/mostrar el `.env` real ni secrets sin autorización. `_SECRET_FIELDS` enmascara credenciales en logs.

---

## 9. CONTEXTO OPERATIVO PARA CLAUDE CODE (próxima sesión)

1. Leer memoria: `project_roadmap_phases.md` (delta v2.7.0 actual) + `feedback_read_only_absolute.md` + este doc.
2. `git status` / `git log --oneline -5` en `C:\Users\xxxv4\iCloudDrive\tradingalertaIA` → `main` = `origin/main` debe estar en `0cc27d6` (o más).
3. `pytest tests/ -q` → 397+ verdes. (Ahora rápido: la DB de test usa `.test_dbs/`, y la DB real está fuera de iCloud.)
4. **La DB real está en `C:\Users\xxxv4\trading_data\trading_alert_ai.db`** (vía `SQLITE_PATH`). El bot se corre desde la carpeta del proyecto.
5. NO TOCAR sin permiso: `.env` real, la DB real (no DELETE/UPDATE histórico), `mt5_demo_trader.py`, `mt5_reconciler.py`, `db.py::_init_db_unsafe`.
6. Si tocás `Settings`: sincronizar `tests/test_score.py::_settings()` Y `tests/test_alert_rules.py::_settings()` (los dos únicos que construyen `Settings(...)` directo).
7. Comando para ver la señal honesta: `/expectancy` (Telegram).

---

## 10. ARCHIVOS NUEVOS / CLAVE v2.7.0

| Archivo | Qué |
|---|---|
| `app/learning/trade_outcomes.py` | NUEVO — realized-R, cost model, artifacts, `build_strategy_performance`, `should_execute_live` (gate) |
| `app/learning/training_engine.py` | `_update_paper_trades` direction-aware (Fix A) + `_refresh_strategy_performance` |
| `app/learning/lifecycle_manager.py` | `_fresh_price` mapea Yahoo→MT5 (Fix C) |
| `app/scheduler/jobs.py` | hook del gate en `_try_prepare_demo_order` |
| `app/scheduler/scalping_engine.py` | hook del gate en `_open_scalping_trade` |
| `app/database/db.py` | tabla `strategy_performance` |
| `app/database/repository.py` | `fetch_closed_paper_trades`, `upsert/fetch_strategy_performance[_for]` |
| `app/assistant/command_handler.py` | comando `/expectancy` |
| `app/config/settings.py` | 9 settings nuevos (gate + cost model + `enable_realized_learning`) + app_version v2.7.0 |
| `app/analyzers/learned_weights.py` + `learning_gate.py` (Fase 2b) | re-apuntados al realized-R (`_evaluate_gate_realized`), detrás de `enable_realized_learning`; drift path = fallback |
| `app/learning/trade_outcomes.py` (Fase 2b) | `build_realized_feature_lessons` (realized-R por feature) |
| `app/database/{db,repository}.py` (Fase 2b) | tabla `realized_feature_lessons` + `upsert/fetch_realized_feature_lessons` |
| tests | `test_trade_outcomes.py`, `test_strategy_promotion_gate.py`, `test_cost_model.py`, `test_expectancy_command.py`, `test_realized_learning.py` (+ regresiones en `test_paper_trade_tracking.py`, `test_lifecycle_manager.py`) |

---

## 11. DELTA v2.7.1 (2026-06-02) — Kill switch falso del 01-jun

### El bug

El 01-jun el kill switch disparó con `daily drawdown -3.20% < -3.0%` pero el balance MT5 real solo bajó **−$1.40 en todo el día**. Variante del bug del 27-may pero esta vez por **paper-only trades con sizing teórico inflado**, no por size_notional vs MT5 real (eso ya lo tapaba v2.6.8 para forex post-execute).

Paper_trades de gold con `symbol=GC=F` (formato Yahoo) nunca matcheaban `DEMO_ALLOWED_SYMBOLS` (que tiene `XAUUSD/GOLD` post-yahoo_to_mt5, no `GC=F`), entonces NO se ejecutaban a MT5. Su `size_notional` quedaba con el sizing TEÓRICO del position_sizer (~$184k para gold con balance teórico 1M). Dos trades gold con −1% cada uno → `realized_pnl_today` decía −3.20% drawdown → kill switch falso disparaba, cuando el daño real al balance MT5 era cero.

### El fix (commit `fd59478`)

- **`app/database/repository.py`** — nuevo `has_successful_demo_order(paper_trade_id) -> bool`: True si hay al menos un `demo_order` con `status='sent'` vinculado al paper_trade.
- **`app/portfolio/portfolio_manager.py`** — `realized_pnl_today()` agrega filtro `if not repository.has_successful_demo_order(t.id): continue`. Trades paper-only quedan excluidos del cálculo USD.

Semántica corregida: `realized_pnl_today` ahora representa correctamente "USD impact en balance MT5 demo" (no "suma de paper PnL teórico").

### Validación live el 02-jun

Con 25 paper_trades cerrados hoy con size_notional > 0:

```
v2.7.0 calc (TODOS):           n=25  USD=-$15,295  drawdown=-17.26%  ← hubiera disparado kill switch falso
v2.7.1 calc (con demo_order):  n=1   USD=-$4.80    drawdown=-0.005%  ← realidad
```

Balance MT5 confirma: $88,635 (−$1.40 vs $88,637 del día anterior). El daño real era casi cero.

**El fix funcionó exactamente como esperaba**: el bot operó todo el día, generó 34 paper_trades (15 forex + 9 gold + 7 stock + 3 memecoin), pero solo 1 llegó a MT5 demo (1 AUDUSD), el resto fue paper-only (mayoría por promotion gate en SHADOW para forex_session_breakout/forex, y todo gold por GC=F no matchea allowed symbols).

### Tests v2.7.1 (+5 → 402 verdes)

- `_seed_closed_trade` helper extendido con `executed_to_mt5: bool = True` (default seedea demo_order para preservar tests existentes).
- `test_realized_pnl_today_excludes_paper_only_trades` — gold $184k notional sin demo_order → 0% (era el bug).
- `test_realized_pnl_today_includes_executed_trades` — forex $10k con demo_order → -0.1% normal.
- `test_realized_pnl_today_mixed_executed_and_paper_only` — mix realista (gold paper-only excluido, forex contado).
- `test_has_successful_demo_order_returns_false_when_no_order`.
- `test_has_successful_demo_order_returns_true_when_order_sent`.

### Estado al cierre v2.7.1 (2026-06-03 03:06 UTC)

| Métrica | Valor |
|---|---|
| Código | v2.7.1 |
| Tests | 402 verdes (era 397) |
| Branch | `main = origin/main = fd59478` |
| Balance MT5 | $88,635.74 |
| Kill switch | CLEAR (limpiado tras fix) |
| Bot | Vivo, balance updated last 19:46 UTC |

### Strategy_performance al 03-jun

| Strategy / Categoría | n | avgR_net | Win | Decisión gate |
|---|---|---|---|---|
| forex_session_breakout/forex | 44 | −0.44 | 20% | SHADOW (n≥30, R<0) |
| unknown/stock | 42 | −0.049 | 38% | SHADOW |
| momentum/forex | 26 | −0.45 | 31% | LIVE (n<30) |
| unknown/memecoin | 24 | **+0.337** | 46% | LIVE (única R+ pero paper-only) |
| momentum/stock | 22 | −0.32 | 36% | LIVE (n<30) |
| forex_session_breakout/gold | 12 | **−2.79** | 0% | LIVE (n<30, pero 0/12 wins — tóxica) |
| mean_reversion/forex | 8 | −0.47 | 13% | LIVE |
| mean_reversion/stock | 6 | −0.42 | 0% | LIVE |
| momentum/gold | 3 | −1.08 | 0% | LIVE |
| scalping_breakout/forex | 1 | −0.36 | 0% | LIVE |
| mean_reversion/gold | 1 | −4.41 | 0% | LIVE |

**Sigue 0 strategies con R+ neto que vaya a MT5.** Memecoin paper-only es la única excepción.

### Pendiente user

- [ ] Bumpear `APP_VERSION=v2.7.1` en `.env` (default código ya es v2.7.1).
- [ ] Reiniciar bot para tomar código v2.7.1.
- [ ] Considerar `ENABLE_STRATEGY_FOREX_SESSION_BREAKOUT=false` (ahorra paper_trades inútiles aunque el gate ya bloquea ejecución MT5).
