# TRADING ALERT AI — Plan de Arquitectura v3.1 (MEJORADO)

> Versión revisada del `Trading Alert AI v3 Plan Arquitectura.docx`.
> Mantiene la **visión** (IA local potente, autónoma, que razona y se auto-evoluciona,
> costo $0, estilo "Mythos" pero para trading) y **corrige** los puntos que chocaban
> con las reglas inamovibles del proyecto, con la realidad de los datos, o con la
> estabilidad del `.venv`. Pensado para ejecutarse **incremental y siempre con
> tests verdes**, no en un "big bang" de 14 semanas.

Estado base: **v2.10.0**, 457 tests. Sobre eso ya se shippearon (en worktree) dos
piezas de este plan — ver §9.

---

## 1. Objetivo general (sin cambios respecto al v3.0)

Transformar Trading Alert AI en un sistema de trading **avanzado, local y gratis**:
detecta patrones que un humano no ve, razona sobre el contexto, explica sus
decisiones, ajusta riesgo y, eventualmente, evoluciona sus propias estrategias.
Todo en tu máquina, sin APIs de pago, privado.

Las 5 dimensiones de poder del v3.0 se mantienen como **norte**. Lo que cambia es
**cómo** se implementan para que sean potentes *sin* romper la seguridad.

---

## 2. EL CAMBIO #1 — Resolver la contradicción del v3.0

El v3.0 se contradice a sí mismo:

| El v3.0 dice (Sec. 5/6/16) | Pero también dice (Sec. 14) |
|---|---|
| "Llama decide SÍ → **auto-ejecuta** en MT5" | "el LLM SOLO puede **prevenir**, nunca forzar" |
| Ensemble: "se ejecuta si **AMBOS dicen SÍ**" (luz verde) | LLM/ML son **subtractivos** |

**Resolución (regla rectora de v3.1): siempre gana la Sección 14.**

- Las **reglas** (strategy router + risk manager + promotion gate) eligen el *candidato*.
- El **LLM, el ML y el ensemble** son capas de **VETO**: solo pueden **bajar a paper**
  (downward-only). **Nunca** producen un "ejecutá".
- La **autonomía** (operar sin `/confirm_demo_trade`) ya existe hoy vía
  `ENABLE_AUTO_CONFIRM_DEMO`. No la inventa el LLM; el LLM solo agrega vetos.
- `order_send` sigue **únicamente** en `mt5_demo_trader.py`. Ningún módulo nuevo lo llama.

Resultado: misma sensación de "autónomo + razonado", **cero riesgo nuevo**.

---

## 3. EL CAMBIO #2 — La verdad de fondo (expectativa honesta)

El v3.0 vende v3.0 como un salto enorme. Lo es en **inteligencia y autonomía**, pero
omite la frase que repite todo el contexto maestro del proyecto:

> **El cuello de botella es DATA, no código. Hoy ninguna estrategia tiene edge
> (todas R-negativo neto).**

Ni Llama, ni un ensemble de 3 modelos ML, ni los micro-patrones de ticks **crean**
edge donde no lo hay. Lo que hacen: **filtrar mejor, explicar, proteger capital y
acelerar el aprendizaje**. La edge se consigue con **data + research**. v3.1 hace al
sistema más inteligente y autónomo; **no** convierte R-negativo en R-positivo por sí
solo. Arrancamos con esa expectativa puesta.

---

## 4. EL CAMBIO #3 — Stack tecnológico (correcciones)

| El v3.0 propone | v3.1 lo corrige a |
|---|---|
| `pip install ... ` **`--break-system-packages`** | **Nunca** ese flag (es para system-Python; en un venv es un footgun). |
| `ollama==0.1.48` (paquete Python) | **No hace falta.** El `OllamaProcessor` ya habla con Ollama por HTTP usando `requests` (ya en requirements). **Cero deps nuevas.** |
| `diskcache==5.6.3` | **No hace falta.** `OllamaProcessor` ya cachea en memoria + throttle por ciclo. |
| `numpy==2.0.0` (pin nuevo) | **No tocar.** numpy 2.0 puede romper xgboost/sklearn/pandas. Dejar como está. |
| `lightgbm==4.4.0` | **Diferido** a la Fase D (solo cuando haya datos que justifiquen el ensemble). |
| `llama2:13b` (7.3 GB, 5–10 s/respuesta en CPU) | **`llama3.1`** (mejor y ya es el default del proyecto) + un modelo chico para la 2ª opinión. Mind: en CPU tarda segundos → **cap de llamadas + nunca bloquear el loop** (ya implementado). |
| Copiar el código de la "Sección 5" (`local_llm_reasoner.py`) | **No copiarlo.** Tiene bugs (`except:` desnudo, `requests.Timeout` mal referenciado, `datetime.utcnow()` deprecado, f-strings `:.0%` sobre `'N/A'` que crashean). Construir sobre el `OllamaProcessor` limpio. |

**Regla de oro de deps:** una dependencia nueva entra solo cuando una fase la
*necesita de verdad*, pineada y revisada. Nada de instalar las 6 de una.

---

## 5. EL CAMBIO #4 — Arquitectura: reutilizar, no duplicar

El v3.0 crea 12 módulos nuevos en paralelo a lo que ya existe. v3.1 **reusa**:

| El v3.0 crea/reemplaza | v3.1 |
|---|---|
| `local_llm_reasoner.py` (cliente Ollama nuevo) | Reusar `app/intelligence/ollama_processor.py` (transporte) + `reasoner.py` (prompts del dominio). |
| `local_llm_ensemble.py` que vota y **habilita** | Ensemble como **veto** enchufado al gate existente (`jobs._try_prepare_demo_order`). |
| `advanced_predictor.py` **reemplaza** `ml_predictor.py` | **Extender** `ml_predictor.py` (no tirar 22 tests). LightGBM/RF se suman dentro del mismo pipeline en la Fase D. |
| Modificar `mt5_demo_trader.py` ("razonar antes de ejecutar") | **No tocar.** El razonamiento/veto va en el gate, no en el ejecutor. |
| `tick_analyzer.py`, `sentiment_analyzer.py`, `anomaly_detector.py` | **Diferidos** (nice-to-have; no son el cuello de botella). |
| `dynamic_risk_adjuster.py`, `continuous_learner.py`, `strategy_mutator.py` | Mantener — en sus fases (C/E), con la data y los gates correctos. |

---

## 6. Roadmap por fases (incremental, tests-verdes, todo opt-in OFF)

Cada fase: **qué**, **archivos**, **flag**, **gate de datos**, **riesgo**.

### ✅ Fase 0 — Captura de features técnicos al entry (HECHO)
- **Qué:** persistir `rsi`/`atr`/`macd` al abrir cada swing trade → desbloquea el ML.
- **Archivos:** `db.py` (4 columnas nullable vía `_ensure_column`), `repository.py`,
  `jobs._try_open_paper_trades`, `ml_dataset_builder.py` (lee reales + `macd_state` real).
- **Riesgo:** nulo (additivo, NULL para trades viejos/scalping/memecoin). **Tests +2.**

### ✅ Fase A — Capa LLM asesora `TradingReasoner` (HECHO)
- **Qué:** `assess_market`, `analyze_loss`, `explain_setup` → **solo texto**.
- **Archivos:** `app/intelligence/reasoner.py`, `OllamaProcessor.generate()`,
  setting `enable_llm_advisor`.
- **Flag:** `ENABLE_LLM_ADVISOR=false` (default). Requiere `ENABLE_OLLAMA_INTEGRATION=true`.
- **Riesgo:** nulo. La clase, a propósito, **no** expone ningún método que devuelva
  decisión/bool (hay un test que lo verifica). **Tests +11.**

### Fase B — Ensemble como VETO + resumen diario
- **Qué:** Llama + Mistral evalúan el candidato de forma independiente; si **alguno**
  desconfía → baja a paper (downward-only). Resumen diario por Telegram al cierre NY.
- **Archivos:** `reasoner.py` (+`second_opinion`), hook en `jobs._try_prepare_demo_order`
  (junto al ML gate), comando `/market` y `/porque_perdi`.
- **Flags:** `ENABLE_LLM_ENSEMBLE=false`, `ENSEMBLE_VETO_REQUIRES_DISAGREEMENT` (cómo
  de estricto el veto). Soft-fail = comportamiento idéntico a hoy.
- **Gate de datos:** ninguno (es cualitativo), pero **solo veta, nunca promueve**.
- **Riesgo:** bajo (subtractivo). Cuidar latencia (cap de llamadas/ciclo).

### Fase C — ContinuousLearner (lección por trade)
- **Qué:** al cerrar cada trade, `analyze_loss`/`analyze_win` extrae una lección
  razonada; se guarda en tabla nueva `trade_lessons`; agrupa lecciones repetidas.
- **Archivos:** `app/learning/continuous_learner.py`, `db.py` (+`trade_lessons`),
  hook en el cierre de trades.
- **Flags:** `ENABLE_CONTINUOUS_LEARNER=false`, `STORE_TRADE_LESSONS`.
- **Riesgo:** bajo (lectura/registro; no toca ejecución). Es de lo más valioso del v3.0.

### Fase D — AdvancedPredictor (ensemble ML) — *requiere datos*
- **Qué:** sumar LightGBM + RandomForest al XGBoost existente, con
  `CalibratedClassifierCV` (que 70% signifique 70%). Umbral conservador (>0.72).
- **Archivos:** extender `ml_predictor.py` (no reemplazar); dep `lightgbm` (pineada).
- **Gate de datos (DURO):** **≥400 trades limpios CON features técnicos reales**
  (los de la Fase 0). Bajo eso, sigue **dormido** (idéntico a hoy).
- **Riesgo:** medio (dep nueva). Mantener soft-fail/modo degradado en todos los caminos.

### Fase E — StrategyMutator (auto-evolución) = Phase 6 del roadmap
- **Qué:** 1 vez/día, toma la peor estrategia, Llama propone **un** cambio de
  parámetro, se crea variante, corre **paper-only ≥5 días**, y se promueve solo si gana.
- **Archivos:** `app/learning/strategy_mutator.py`, `db.py` (+tabla de variantes).
- **Flags:** `ENABLE_STRATEGY_MUTATOR=false`, `REQUIRE_HUMAN_CONFIRM_FOR_MUTATION=true`.
- **Gate de datos (DURO):** **≥1 estrategia con R+ neto + 3 meses de data**. Hoy NO se
  cumple → la fase queda agendada, no activa.
- **Riesgo:** medio; mitigado por paper-only 5d + confirmación humana + 1 param/vez.

### Diferidas (post-roadmap, nice-to-have)
- **TickAnalyzer** (micro-patrones en ticks), **SentimentAnalyzer**, **AnomalyDetector**,
  **DynamicRiskAdjuster**. Interesantes, pero **no** son el cuello de botella (que es
  cantidad de muestra limpia, no features por trade). Se evalúan cuando B–E estén firmes.

---

## 7. Settings nuevos (corregidos, todos default OFF)

```bash
# Capa asesora (Fase A — YA creado)
ENABLE_LLM_ADVISOR=false            # requiere ENABLE_OLLAMA_INTEGRATION=true

# Transporte LLM local (ya existía en v2.10.0)
ENABLE_OLLAMA_INTEGRATION=false
OLLAMA_MODEL=llama3.1               # NO llama2:13b
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_TIMEOUT_SECONDS=30
OLLAMA_CALLS_PER_CYCLE_CAP=6

# Fase B (ensemble veto) — se agregan cuando llegue la fase
# ENABLE_LLM_ENSEMBLE=false
# Fase C (continuous learner)
# ENABLE_CONTINUOUS_LEARNER=false
# Fase D (advanced predictor) — reusa ML_GATE_MIN_SAMPLES=400 existente
# Fase E (strategy mutator)
# ENABLE_STRATEGY_MUTATOR=false / REQUIRE_HUMAN_CONFIRM_FOR_MUTATION=true
```

No agregar un flag hasta que su fase exista. Sincronizar siempre
`tests/test_score._settings()` y `tests/test_alert_rules._settings()` al tocar `Settings`.

---

## 8. Guardias de seguridad (la Sección 14 del v3.0, reafirmada)

Inamovibles, **idénticas** a todas las versiones anteriores:

- `ENABLE_REAL_TRADING=false` **HARDCODED**. Real-money bloqueado salvo autorización
  nueva y explícita.
- `order_send` **solo** en `mt5_demo_trader.py`. Ningún módulo nuevo lo llama directo.
- **El LLM y el ML solo PREVIENEN ejecución (subtractivos). NUNCA la fuerzan.**
- En modo degradado/dormido, el sistema se comporta **exactamente** igual que sin la capa.
- Memecoins: solo paper/lab, no ejecutan a MT5.
- Mutaciones: paper-only ≥5 días + confirmación humana antes de tocar demo.
- Nunca leer/modificar/mostrar el `.env` real ni secrets.
- **Mantener pytest verde** (hoy 470). No se mergea a main sin todos los tests verdes.

---

## 9. Estado actual real (qué ya está hecho de este plan)

En el worktree, sobre v2.10.0, **ya shippeado y verificado (470 tests verdes)**:

1. **Fase 0** — captura de `rsi`/`atr`/`macd` al entry (swing). El ML ya recibe
   features técnicos reales en vez de NaN. *(+2 tests)*
2. **Fase A** — `TradingReasoner` (capa asesora read-only) con `assess_market`,
   `analyze_loss`, `explain_setup`; `OllamaProcessor.generate()`; flag
   `ENABLE_LLM_ADVISOR`. *(+11 tests, incluido un test que prueba que el asesor NO
   expone ningún método de decisión)*.

Pendiente de commit/push (con tu OK): bump `app_version`→v3.1 + CHANGELOG + README/.env.example.

---

## 10. Próximos pasos inmediatos

1. (Tú) Instalar Ollama + `ollama pull llama3.1` (y un modelo chico tipo `mistral`
   o `llama3.2:3b` para la 2ª opinión de la Fase B). Dejar `ollama serve` corriendo.
2. (Tú) En el `.env`: `ENABLE_OLLAMA_INTEGRATION=true` + `ENABLE_LLM_ADVISOR=true`
   para activar la capa asesora ya construida.
3. (Nosotros) **Fase B**: wirear el ensemble-veto al gate + comandos `/market` y
   `/porque_perdi` + resumen diario.
4. (Nosotros) **Fase C**: `ContinuousLearner` + tabla `trade_lessons`.
5. **Dejar correr** para acumular muestra limpia CON features técnicos → recién ahí
   tienen sentido las Fases D y E.

---

*Trading Alert AI v3.1 — Plan de Arquitectura Local AI (mejorado).
Ollama + Llama 3.1 + (2ª opinión) + XGBoost — subtractivo, soft-fail, opt-in. Costo: $0.*
