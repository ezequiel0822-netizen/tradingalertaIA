# PRÓXIMOS PASOS — Trading Alert AI (continuación post-migración)

> **Para retomar el desarrollo en Claude Code (Lenovo).** Dónde estamos, qué sigue, y
> cómo construir sin romper nada. Complementa:
> - `HANDOFF.md` — setup de la máquina + prompt de arranque.
> - `Trading Alert AI v3.1 Plan Arquitectura MEJORADO.md` — el plan/arquitectura completo.
> - `CHANGELOG.md` — historia detallada de cada versión.
> - `CONTEXTO_MAESTRO_v2.10.0.md` — arquitectura/schema exhaustivos (base histórica).

---

## 1. Estado actual

- **v3.3.0**, **532 tests verdes**.
- Corriendo en la Lenovo (`C:\Users\LENOVO\tradingalertaIA`, fuera de iCloud, con GPU →
  el LLM local responde rápido).
- Operativo: MT5 demo (auto-confirm ON), lifecycle, scalping, alertas, learning, y la
  **capa LLM asesora** (Ollama + `llama3.1`) verificada con `/market`.
- Balance demo ~$88,6xx. **Real-money BLOQUEADO (HARDCODED).**

## 2. Lo que YA construimos (serie v3 — toda pusheada)

| Versión | Qué |
|---|---|
| **v2.11.0** | `rsi/atr/macd` persistidos al entry (desbloquea features ML reales) + `app/intelligence/reasoner.py` `TradingReasoner` (asesor LLM read-only, solo texto) |
| **v2.12.0** | comandos Telegram `/market` + `/porque_perdi` |
| **v3.0.0** | veto del ensemble Llama+Mistral en el gate (`app/intelligence/ensemble_gate.py` + `jobs._llm_ensemble_gate`, downward-only) |
| **v3.1.0** | resumen diario por Telegram (`jobs._maybe_send_daily_summary`) |
| **v3.2.0** | **Fase C ContinuousLearner**: leccion por trade (`app/learning/continuous_learner.py` + tabla `trade_lessons` + `reasoner.analyze_win`); agrupa lecciones y PROPONE (no aplica) |
| **v3.3.0** | Performance desde baseline limpio (`app/portfolio/performance.py` + comando `/performance`); el −11% fue el bug de mayo, limpio queda ~plano |

(Detalle completo en `CHANGELOG.md`.)

## 3. ⚠️ LA VERDAD DE FONDO (leer antes de codear)

**El cuello de botella es DATA, no código.** Ninguna estrategia tiene edge PROBADO. La
única +R agregada (`forex_session_breakout`/forex, +0.378R) la carga **solo el lado short
en un régimen direccional** (shorts +1.81R n=28 vs longs −0.31R n=58; mismo patrón en gold)
— es artefacto de régimen, no edge durable. El LLM y el ML **filtran, explican y protegen
capital — NO crean edge.**

**Sobre el −11% (corregido en v3.3.0):** ese drawdown fue sobre todo el **bug de mayo**
(feedback-loop / instant-kill / huérfanas, ~746 artifacts 22–28 may, fixes v2.6.7–v2.7.1).
Limpio de artifacts, los trades ejecutados suman ~−2% desde el inicio; desde el baseline
`2026-06-03` la cuenta está **+0.17% (plana)** sobre 16 trades. O sea: **ni −11% ni
ganador — plano, con muestra chica.** El comando `/performance` lo mide honesto.

Lo más valioso AHORA sigue siendo **dejar correr el bot para juntar muestra limpia** con
los features técnicos (v2.11.0): hoy hay **~68/400** trades con features reales (gate Fase
D). Sin data, las fases de abajo no rinden. El edge sale de data + research, no de
sofisticación.

## 4. Lo que FALTA (roadmap, en orden de valor)

### ✅ Fase C — ContinuousLearner *(HECHO — v3.2.0)*
- **Qué:** al cerrar cada trade, el LLM extrae una lección razonada (por qué ganó/perdió);
  se guarda en tabla `trade_lessons`; agrupa lecciones repetidas; si 10+ dicen lo
  mismo, **propone** un ajuste por Telegram para que el user apruebe (no lo aplica solo).
- **Implementado como job de escaneo en `run_once`** (no hook inline — hay 4 sitios de
  cierre; un job desacoplado es más limpio), cap por ciclo, idempotente, soft-fail.
- **Archivos:** `app/learning/continuous_learner.py` + `db.py` (tabla `trade_lessons`) +
  `repository` helpers + `reasoner.analyze_win` + `jobs._maybe_run_continuous_learner`.
- **Flags:** `ENABLE_CONTINUOUS_LEARNER=false` + `STORE_TRADE_LESSONS=true` (requiere ambos).

### Fase D — AdvancedPredictor *(REQUIERE DATA — no antes)*
- **Qué:** sumar LightGBM + RandomForest al XGBoost existente, con `CalibratedClassifierCV`
  (que 70% signifique 70%). Umbral conservador (>0.72).
- **Archivos:** **EXTENDER** `app/learning/ml_predictor.py` (NO reemplazar — tiene 22 tests).
  Dep nueva `lightgbm` (pineada).
- **GATE DURO:** ≥400 trades limpios CON features técnicos reales (los de v2.11.0). Bajo eso
  sigue DORMIDO (idéntico a hoy). Hoy hay ~189 viejos sin features + los nuevos acumulándose.
- **Riesgo:** medio (dep nueva). Mantener soft-fail/modo degradado en TODOS los caminos.

### Fase E — StrategyMutator *(REQUIERE EDGE + 3 MESES DATA)*
- **Qué:** 1x/día toma la peor estrategia, el LLM propone UN cambio de parámetro, se crea
  variante, corre **paper-only ≥5 días**, se promueve solo si gana.
- **GATE DURO:** ≥1 estrategia con R+ neto + 3 meses de data. **HOY NO se cumple.**
- **Flags:** `ENABLE_STRATEGY_MUTATOR=false`, `REQUIRE_HUMAN_CONFIRM_FOR_MUTATION=true`.
- Es la *Phase 6 (Strategy Evolution)* del roadmap histórico.

### Diferidos *(nice-to-have, NO son el cuello de botella)*
- TickAnalyzer (micro-patrones en ticks), SentimentAnalyzer, AnomalyDetector,
  DynamicRiskAdjuster. Evaluar cuando C–E estén firmes y haya data.

### Opciones inmediatas *(sin código)*
- **Activar el veto:** en la Lenovo `ollama pull mistral` + `ENABLE_LLM_ENSEMBLE=true`.
  Solo *frena* trades (baja a paper), nunca abre.
- **Sacar gold** (`XAUUSD,GOLD`) de `DEMO_ALLOWED_SYMBOLS` — sigue tóxico (−2.79R, 0/12).
- **Dejar correr** para juntar data (lo más importante).

## 5. Cómo construir (convenciones INAMOVIBLES)

- **Read-only de mercado:** `ENABLE_REAL_TRADING=false` HARDCODED; `order_send` SOLO en
  `app/brokers/mt5_demo_trader.py`; el LLM y el ML son **SUBTRACTIVOS** (solo vetan/bajan
  a paper, JAMÁS fuerzan una orden). No tocar `mt5_demo_trader.py` ni `mt5_reconciler.py`.
- **Todo opt-in OFF + soft-fail:** cada capa nueva default `false`; si está apagada o algo
  falla, el bot corre EXACTAMENTE igual.
- **Mantener pytest verde (501).** Al tocar `Settings`: sincronizar
  `tests/test_score._settings()` Y `tests/test_alert_rules._settings()`.
- **Versionado:** serie **v3.x** (la próxima feature = v3.2.0). Bump `app_version` +
  `CHANGELOG.md` + `.env.example` al cerrar cada versión.
- **Cada módulo nuevo trae su test file.** No mergear sin todos los tests verdes.
- Nunca leer/mostrar el `.env` real ni secrets.

## 6. Prompt para arrancar Claude Code en la Lenovo

Abrí Claude Code en `C:\Users\LENOVO\tradingalertaIA` y pegá esto como primer mensaje:

```
Retomamos Trading Alert AI (bot de trading algorítmico LOCAL, Python 3.12, Windows).
Estado: v3.1.0, origin/main, 501 tests verdes, corriendo en esta máquina (Lenovo, GPU).

Leé en este orden ANTES de tocar nada: PROXIMOS_PASOS.md (qué sigue + reglas),
HANDOFF.md, CHANGELOG.md, y "Trading Alert AI v3.1 Plan Arquitectura MEJORADO.md".

Reglas inamovibles: real-money BLOQUEADO (ENABLE_REAL_TRADING=false HARDCODED);
order_send solo en mt5_demo_trader.py; LLM/ML SUBTRACTIVOS (solo vetan, nunca fuerzan);
todo opt-in OFF + soft-fail; mantener 501 tests verdes; al tocar Settings sincronizar
los _settings() de test_score y test_alert_rules.

La verdad de fondo: el cuello de botella es DATA, no código. Ninguna estrategia tiene
edge; dejar correr para juntar muestra. No empezar Fase D/E sin la data que piden.

Decime qué querés hacer: (A) Fase C ContinuousLearner; (B) activar el veto/ajustes de
config; (C) revisar la data acumulada (/expectancy, /edge, /ml_status); (D) otra cosa.
```
