# CONTEXTO MAESTRO — Trading Alert AI v2.10.0

Documento de handoff. Cierre de sesión **2026-06-04**. Reemplaza `CONTEXTO_MAESTRO_v2.7.0.md` como el doc ACTUAL (que cubría hasta v2.7.1). Acá se documenta el delta **v2.8.0 + v2.9.0 + v2.9.1 + v2.10.0** (detalle de v2.10.0 en la sección 13).

Para apéndices estáticos (arquitectura, schema completo, historia de decisiones viejas) ver `CONTEXTO_MAESTRO_v2.7.0.md` (delta v2.7.x) y `CONTEXTO_MAESTRO_v2.6.9.md` (base exhaustiva). Acá: estado actual + lo nuevo.

---

## 1. RESUMEN GENERAL

**Trading Alert AI v2.10.0** — Bot de trading algorítmico **local** en Python 3.12 (Windows, PowerShell + venv). Detecta oportunidades en memecoins / acciones US / forex / oro, decide con un strategy router (5 swing + 2 scalping), opera paper trades simulados y envía órdenes a **MT5 demo (MetaQuotes-Demo)**. Real-money trading **bloqueado por design (HARDCODED)**.

**Lo nuevo de esta tanda (4 versiones):**
- **v2.8.0 — Edge Detection & Protection Layer:** mide expectancy realizada (R neto de costos) **sliceada por sesión y dirección**, para cazar bolsillos de edge. Comando `/edge`. Gate de promoción sliceado (opt-in).
- **v2.9.0 — Hybrid ML layer (XGBoost):** modelo que predice prob. de win y **modula el promotion gate solo hacia abajo**, con soft-fail/modo degradado. Nace **DORMIDO**. Comando `/ml_status`.
- **v2.9.1 — Toggle de alertas de acciones:** flag `ENABLE_STOCK_TELEGRAM` que separa *analizar* de *alertar* acciones.
- **v2.10.0 — Proveedor LLM local (Ollama):** alternativa gratis a Claude API para enriquecer texto (resúmenes/análisis/free-text). `OllamaProcessor` + `build_llm_processor` factory; soft-fail, read-only, **NO decide trades**, cero deps nuevas. Detalle en sección 13.

**La verdad de fondo (sin cambios):** con ~189 trades reales limpios **ninguna estrategia tiene edge** (todas R negativo neto salvo memecoin paper-only). El bot mide la verdad y protege capital, pero **el edge es trabajo de DATA + research, no de más código**. v2.8.0 da la herramienta para encontrarlo; v2.9.0 es andamiaje ML para cuando haya muestra.

---

## 2. ESTADO ACTUAL EXACTO (2026-06-04)

### Versión y git
- **Versión código:** v2.10.0 (`app_version` default ya en v2.10.0).
- **Branch:** `main`. `main` local = **`0486df9`** (v2.10.0). `origin/main` = **`5a976b5`** (v2.9.1) — el push de v2.10.0 a GitHub quedó **PENDIENTE de OK explícito del user**.
- **Tests:** **457 verdes** (`pytest tests/ -q`).
- Commits de la tanda sobre `fd59478` (v2.7.1):
  - `80bb5db` — v2.8.0 (edge detection) + v2.9.0 (hybrid ML), entrelazados en un commit. **Pusheado.**
  - `5a976b5` — v2.9.1 (flag ENABLE_STOCK_TELEGRAM). **Pusheado.**
  - `0486df9` — v2.10.0 (proveedor LLM local Ollama). **En main local; push a origin pendiente.**

### Infra
- **DB LOCAL fuera de iCloud:** `C:\Users\xxxv4\trading_data\trading_alert_ai.db` (vía `SQLITE_PATH`). Mantener así (iCloud causaba contención de I/O brutal).
- **Deps nuevas instaladas en el `.venv`:** `xgboost==3.2.0`, `scikit-learn==1.9.0` (aprobadas por el user). Soft-fail si faltan.
- **`models/` y `exports/`** agregados a `.gitignore` (modelos .pkl y datasets CSV no se versionan).

### Cuenta MT5 del usuario
```
Login:    10010956946
Server:   MetaQuotes-Demo
Balance:  ~88,635 USD
```

### Estado del bot al cierre
- **Proceso:** el user YA lo corrió (validado por log 2026-06-04): arrancó en v2.9.x, **no alerta acciones** (`ENABLE_STOCK_TELEGRAM=false` aplicado), **sí memecoins/forex/gold**, edge slicing poblando (45 slices), ML dormido. GeckoTerminal 429 frecuente (soft-fail; considerar subir `POLL_INTERVAL_SECONDS` para mejor cobertura de memecoins). Para tomar v2.10.0 (Ollama) habría que reiniciar, pero Ollama está OFF por default → sin diferencia operativa.
- **`.env` del user aplicado:** `ENABLE_STOCK_TELEGRAM=false`, `ENABLE_MEMECOIN_TELEGRAM=true`. **Riesgo activo:** gold sigue en `DEMO_ALLOWED_SYMBOLS` (tóxica −2.79R 0/12; el gate aún no la frena por n<30). `DEMO_MAX_LOT=0.1`.
- `bot_state`: kill switch CLEAR, demo_trading_halted false, scalping_active true, bot_mode trader.

---

## 3. QUÉ TRAJO v2.8.0 — Edge Detection & Protection Layer

Surge del research: slicear los 189 trades reales por sesión y dirección **no reveló ningún bolsillo +R sólido** (los positivos tienen n=4-17, ruido). Confirma que el cuello de botella es muestra. Por eso v2.8.0 NO codifica un filtro adivinado, sino la **maquinaria que mide el edge por slice** y deja decidir a la data.

- **`trade_outcomes.py`:** `session_of(opened_at)` (franjas UTC no solapadas: Asia 00-07, London 07-12, LDN-NY 12-16, NY 16-21, Off 21-00), `build_sliced_performance()` (una fila por estrategia×categoría×dimensión×bucket; reusa EXACTO el realized-R neto de costos y la exclusión de artifacts de v2.7.0).
- **Tabla `strategy_performance_sliced`** (PK strategy_name+category+dimension+bucket), refrescada cada learning cycle vía `_refresh_sliced_performance` (training_engine).
- **Comando `/edge`:** muestra slices por sesión y dirección, marca `[OK]` los confiables (n≥`EDGE_SLICE_MIN_SAMPLES`=30) y resalta los +R.
- **Gate sliceado** (`should_execute_live_sliced`, hooks en jobs/scalping detrás de `ENABLE_SLICED_PROMOTION_GATE`, **default OFF**): el slicing **SOLO puede mover a SHADOW, nunca promover** (anti data-dredging: usar muchos slices para hallar perdedores es conservador; para hallar ganadores invitaría falsos positivos). El gate sigue siendo estrictamente subtractivo.

---

## 4. QUÉ TRAJO v2.9.0 — Hybrid ML layer (XGBoost)

Capa ML que **COMPLEMENTA** las reglas (no las reemplaza). Misma filosofía que el gate: solo filtra hacia abajo, nunca habilita lo que las reglas bloquearon. **Nace dormida y segura.**

- **`ml_dataset_builder.py`:** dataset de paper_trades cerrados no-artifact (reusa quarantine + realized-R de v2.7.0) con features al entry + outcome win/loss. Exporta `exports/ml_dataset.csv`. `build_live_features` arma las features de un trade vivo (DRY). Solo pandas.
- **`ml_predictor.py`:** `MLPredictor` con XGBClassifier (max_depth=5, lr=0.1, n_estimators=100, subsample=0.8), validación temporal sin look-ahead, AUC (sklearn), persistencia pickle en `models/xgboost_v1.pkl`, `retrain_if_needed` con **revert si el AUC cae >0.05**. Modo degradado/soft-fail (0.5 neutral) en TODOS los caminos. `ml_gate_decision` (>0.65 pasa; 0.50-0.65 pasa con lot/2; <0.50 paper-only) y `should_consult_ml` (guard).
- **Integración en el promotion gate** (`jobs._try_prepare_demo_order`): downward-only, **doble umbral** (`ENABLE_ML_PREDICTOR` default OFF; modula solo con n≥`ML_GATE_MIN_SAMPLES`=400 — salvaguarda dura), reduce lot a la mitad en low-confidence (sobre el draft, **sin tocar `mt5_demo_trader.py`**), paper-only si <0.50. Soft-fail = comportamiento idéntico.
- **Reentrenamiento diario** en `run_once` (gate por fecha UTC, `_maybe_retrain_ml`). Comando **`/ml_status`** (versión, modo activo/dormido, muestras, AUC, top5 features, distribución de decisiones del día).

### LÍMITE HONESTO de la data (verificado contra el schema)
- `vix`/`dxy` (macro), sesión/hora/día, estrategia/categoría y features del alert (ia_pro, patrones, volumen) → **SÍ disponibles**.
- **`rsi_entry`, `atr_value` → NO se persisten hoy** (quedan NaN). `macd_state` es un proxy categórico desde el alert.
- **Próximo paso de mayor valor para el ML:** empezar a capturar rsi/macd/atr **al crear cada trade** (cambio futuro, no retroactivo — no recupera los 189 viejos). Sin features técnicas reales el modelo está casi ciego.
- **Con 189 trades el ML está DORMIDO** (189 < 400): no toca ninguna decisión. Corre idéntico a sin-ML.

---

## 5. QUÉ TRAJO v2.9.1 — Toggle de alertas de acciones

Pedido del user: que el bot **siga analizando acciones pero deje de mandar las alertas de "top 5 acciones"** a Telegram (era ruido, no plata: Claude API está OFF por default). Y que **NO** deje de avisar cuando abre/cierra trades.

- **Hallazgo:** `ENABLE_STOCK_ALERTS` controla la **recolección** (en `stock_collector.collect`, si false retorna `[]` → no analiza). No servía para "analizar sin alertar".
- **Fix (nuevo flag `ENABLE_STOCK_TELEGRAM`, default true):** separa el envío del análisis.
  - `app/analyzers/alert_decision_engine.should_send_alert`: para `category=="stock"`, si `not enable_stock_telegram` → `False` (no candidato a Telegram). El análisis/paper_trades NO dependen de esto (ocurren siempre en `jobs.run_once`, líneas ~395-419 y ~442-445).
  - `app/scheduler/jobs._send_ranked_candidates`: `"stock"` solo entra a `cats` si `enable_stock_telegram` (defensa en profundidad, mismo patrón que `enable_memecoin_telegram`).
  - **NO toca** `enable_trade_action_reports` (los avisos de apertura/cierre de trades son un flujo separado, siguen intactos).
- **Tests:** `test_stock_blocked_when_telegram_off` + `test_memecoin_unaffected_by_stock_telegram_flag` en `test_memecoin_telegram_block.py`; sync de `test_score`/`test_alert_rules` `_settings()`.

---

## 6. CONFIG QUE EL USER DEBE APLICAR EN SU `.env` REAL

Para lograr lo que pidió (solo memecoins en Telegram, acciones analizadas pero silenciadas, forex/oro y avisos de trades intactos):

```bash
ENABLE_STOCK_TELEGRAM=false     # acciones: analiza sí, NO alerta candidatos
ENABLE_MEMECOIN_TELEGRAM=true   # memecoins: SÍ alertar (default del código es false)
APP_VERSION=v2.9.1              # cosmético
```

(`ENABLE_STOCK_ALERTS` se queda en `true` — apagarlo dejaría de ANALIZAR acciones, que NO es lo que quiere. Forex/oro: `ENABLE_FOREX_ALERTS`/`ENABLE_GOLD_ALERTS` y `ENABLE_TRADE_ACTION_REPORTS` se quedan como están.)

---

## 7. SETTINGS NUEVOS DE LA TANDA (defaults)

```bash
# v2.8.0 — edge slicing
ENABLE_EDGE_SLICING=true            # medición ON (no toca ejecución)
EDGE_SLICE_MIN_SAMPLES=30
ENABLE_SLICED_PROMOTION_GATE=false  # gate sliceado opt-in

# v2.9.0 — ML layer (todo soft-fail / dormido)
ENABLE_ML_PREDICTOR=false           # master switch opt-in
ML_MIN_TRAIN_SAMPLES=100            # bajo esto, modo degradado (0.5)
ML_GATE_MIN_SAMPLES=400             # salvaguarda dura: modula gate solo con n>=400
ML_RETRAIN_MIN_NEW_TRADES=20
ML_CONF_PASS=0.65
ML_CONF_LOW=0.50

# v2.9.1 — toggle alertas acciones
ENABLE_STOCK_TELEGRAM=true          # user lo pone en false
```

---

## 8. PENDIENTES

1. **Commitear v2.9.1** (flag stock_telegram): bump `app_version`→v2.9.1, CHANGELOG, README/.env.example; commit; merge ff a `main`; push (con autorización del user).
2. **User aplica el `.env`** (sección 6) y **reinicia el bot** para tomar v2.9.0/v2.9.1.
3. **Validar pytest verde** tras el flag (≈447).
4. (Mayor valor a futuro) **capturar rsi/macd/atr al crear el trade** → recién ahí el ML tiene features técnicas reales (v2.9.x/v2.10).

---

## 9. PRÓXIMOS PASOS / ROADMAP

**El cuello de botella sigue siendo DATA, no código.** Lo más valioso:
1. **Dejar correr** para acumular muestra limpia (post-Fix-A). El gate manda más losers a SHADOW al llegar a n≥30; `/edge` empieza a tener señal por slice; el ML recién modula a n≥400.
2. **Capturar features técnicas al entry** (rsi/macd/atr) — habilita que el ML eventualmente aporte.
3. **Búsqueda de edge** vía `/edge`: vigilar si algún slice (sesión/dirección) cruza n≥30 con R+ sólido.
4. Phase 6 Strategy Evolution (post 3+ meses data + ≥1 strategy con R+ neto). Phase 10 real-money **BLOQUEADO sin autorización nueva**.

---

## 10. RESTRICCIONES INAMOVIBLES (NO romper)

- `ENABLE_REAL_TRADING=false` HARDCODED. `order_send` solo a MT5 demo vía `mt5_demo_trader` (único módulo).
- El **ML jamás causa un order_send, solo puede prevenirlo** (downward-only, subtractivo). El gate sliceado, ídem.
- En modo degradado/dormido el ML se comporta EXACTAMENTE igual que sin ML.
- Memecoins NO se ejecutan a MT5 (solo paper/lab).
- Auto-confirm + scalping engine + sliced gate + ml predictor = opt-in flags. NO hardcodear.
- Lifecycle SL-to-breakeven post-TP1 correcto. MT5Reconciler SL solo TIGHTEN. Lessons scalping con sufijo `_scalping`.
- Security review limpio (0 HIGH/MEDIUM) sobre v2.8.0+v2.9.0.
- Nunca leer/modificar/mostrar el `.env` real ni secrets sin autorización.
- **Mantener pytest verde.**

---

## 11. CONTEXTO OPERATIVO PARA CLAUDE CODE (próxima sesión)

1. Leer memoria + este doc + `CONTEXTO_MAESTRO_v2.7.0.md` (apéndices) + `feedback_read_only_absolute.md`.
2. `git -C C:/Users/xxxv4/iCloudDrive/tradingalertaIA log --oneline -3` → `main` debe estar en `80bb5db` (o el commit de v2.9.1 si ya se hizo).
3. `pytest tests/ -q` con el `.venv` → 445+ verdes.
4. DB real en `C:\Users\xxxv4\trading_data\trading_alert_ai.db`. El bot se corre desde el dir principal `C:\Users\xxxv4\iCloudDrive\tradingalertaIA` (donde está el `.env`).
5. NO TOCAR sin permiso: `.env` real, DB real, `mt5_demo_trader.py`, `mt5_reconciler.py`, `db.py::_init_db_unsafe`.
6. Si tocás `Settings`: sincronizar `tests/test_score.py::_settings()` Y `tests/test_alert_rules.py::_settings()`.
7. Comandos clave de observabilidad: `/expectancy`, `/edge`, `/ml_status`, `/health`.

---

## 12. ARCHIVOS NUEVOS / CLAVE DE LA TANDA

| Archivo | Qué |
|---|---|
| `app/learning/ml_dataset_builder.py` | NUEVO — dataset ML + `build_live_features` |
| `app/learning/ml_predictor.py` | NUEVO — `MLPredictor` (XGBoost), `ml_gate_decision`, `should_consult_ml` |
| `app/learning/trade_outcomes.py` | +`session_of`, `build_sliced_performance`, `should_execute_live_sliced` (v2.8.0) |
| `app/learning/training_engine.py` | +`_refresh_sliced_performance`, `_cost_map_from_settings` |
| `app/database/db.py` | +tabla `strategy_performance_sliced` |
| `app/database/repository.py` | +upsert/fetch sliced |
| `app/scheduler/jobs.py` | hooks ML (`_ml_gate`, `_maybe_retrain_ml`, `_record_ml_decision`) + gate sliceado + flag stock_telegram en `_send_ranked_candidates` |
| `app/scheduler/scalping_engine.py` | hook gate sliceado |
| `app/analyzers/alert_decision_engine.py` | `should_send_alert` respeta `enable_stock_telegram` (v2.9.1) |
| `app/assistant/command_handler.py` | comandos `/edge`, `/ml_status` |
| `app/config/settings.py` | settings v2.8.0 + v2.9.0 + `enable_stock_telegram`; app_version |
| `requirements.txt` | +xgboost, +scikit-learn |
| tests | `test_edge_slicing.py`, `test_ml_dataset_builder.py`, `test_ml_predictor.py` + regresiones |

---

## 13. DELTA v2.10.0 (2026-06-04) — Proveedor LLM local via Ollama

Pedido del user: usar un LLM **local y gratis** en vez de Claude API. Importante: el LLM del bot **solo enriquece TEXTO** (resumen de noticias, expansion del analisis pro, free-text en Telegram) — **NO toca ninguna decision de trading**. Es UX, no edge.

- **`app/intelligence/ollama_processor.py` (NUEVO):** `OllamaProcessor` con la MISMA interfaz que `ClaudeProcessor` (duck-typing). Habla con Ollama por HTTP local (`POST /api/chat`, default `http://localhost:11434`). Soft-fail total (Ollama caido / flag off / respuesta invalida -> None). Throttle + cache + reachability cacheada. **Cero deps nuevas** (usa `requests`).
- **`build_llm_processor(settings, repo)`:** factory — `OllamaProcessor` si `enable_ollama_integration`, sino `ClaudeProcessor`. Wire en `jobs.py` (un solo call site; el atributo sigue llamandose `claude_processor`).
- **Settings:** `ENABLE_OLLAMA_INTEGRATION=false`, `OLLAMA_MODEL=llama3.1`, `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_TIMEOUT_SECONDS=30`, `OLLAMA_CALLS_PER_CYCLE_CAP=6`. app_version -> v2.10.0.
- **Para usarlo el user debe:** instalar Ollama (ollama.com) + `ollama pull llama3.1` + dejar el servicio corriendo + `ENABLE_OLLAMA_INTEGRATION=true` en el `.env`. Ollama NO estaba instalado al cierre.
- **Tests:** `tests/test_ollama_processor.py` (+10, mock de `requests`). Total **457 verdes**.
- Estado git al cierre: commit de v2.10.0 PENDIENTE (en el worktree). Hay que commitear + merge ff a main + push (autorizacion explicita del user para el push).
