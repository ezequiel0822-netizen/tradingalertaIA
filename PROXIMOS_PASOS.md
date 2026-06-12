# PRÓXIMOS PASOS — Trading Alert AI (continuación post-migración)

> **Para retomar el desarrollo en Claude Code (Lenovo).** Dónde estamos, qué sigue, y
> cómo construir sin romper nada. Complementa:
> - `HANDOFF.md` — setup de la máquina + prompt de arranque.
> - `Trading Alert AI v3.1 Plan Arquitectura MEJORADO.md` — el plan/arquitectura completo.
> - `CHANGELOG.md` — historia detallada de cada versión.
> - `CONTEXTO_MAESTRO_v3.5.0.md` — arquitectura/schema **vigentes** (el v2.10.0 queda histórico).
> - `GO_LIVE_RUNBOOK.md` — el camino completo a real-money (gates, broker, día-D).
> - `RESUMEN_COMPLETO.md` — TODO el proyecto en un solo documento (para arrancar un chat nuevo).

---

## 1. Estado actual

- **v3.5.0**, **572 tests verdes**. Todo mergeado a `main` y deployado.
- Corriendo en la Lenovo (`C:\Users\LENOVO\tradingalertaIA`). Arranque oficial:
  **`.\start_bot.ps1`** (pide contraseña, opt-in, hash en `.env`).
- ⚠️ **Hardware**: la GPU NO banca un LLM local rápido (~50s/respuesta, corre en CPU).
  Por eso el asesor (`/market`) es a-demanda-con-paciencia, `ENABLE_CONTINUOUS_LEARNER=false`
  en esta máquina (el código v3.2.0 está sano; es límite de hardware), y el LLM jamás va
  en el hot path del ciclo.
- **Protecciones v3.5.0 ACTIVAS** en el `.env` del user: calendar gate, cap USD (|3|),
  cooldown 60 min, exit shadow registrando (~6k muestras al 11-jun).
- Balance demo ~$88,8xx. **Real-money BLOQUEADO (HARDCODED)** — camino en `GO_LIVE_RUNBOOK.md`.

## 2. Lo que YA construimos (serie v3 — toda pusheada)

| Versión | Qué |
|---|---|
| **v2.11.0** | `rsi/atr/macd` persistidos al entry (desbloquea features ML reales) + `app/intelligence/reasoner.py` `TradingReasoner` (asesor LLM read-only, solo texto) |
| **v2.12.0** | comandos Telegram `/market` + `/porque_perdi` |
| **v3.0.0** | veto del ensemble Llama+Mistral en el gate (`app/intelligence/ensemble_gate.py` + `jobs._llm_ensemble_gate`, downward-only) |
| **v3.1.0** | resumen diario por Telegram (`jobs._maybe_send_daily_summary`) |
| **v3.2.0** | **Fase C ContinuousLearner**: leccion por trade (`app/learning/continuous_learner.py` + tabla `trade_lessons` + `reasoner.analyze_win`); agrupa lecciones y PROPONE (no aplica) |
| **v3.3.0** | Performance desde baseline limpio (`app/portfolio/performance.py` + comando `/performance`); el −11% fue el bug de mayo, limpio queda ~plano. + comando `/readiness` (gates para dinero real) |
| **v3.3.1** | Caché + cooldown 429 para las listas de GeckoTerminal (`geckoterminal_collector.py`); saca el spam de "Too Many Requests" y acelera el ciclo |
| **v3.4.0** | Exit shadow (`exit_shadow.py` + tabla `trade_r_samples` + `/exit_analysis`): mide si un trailing mejoraria las salidas (forex/oro NO tienen trailing efectivo); read-only, no toca salidas |
| **v3.5.0** | Calendar gate (conecta `is_safe_window` que estaba huérfano) + cap de exposición neta USD (`app/risk/exposure.py` + `/exposicion`). Lecciones del 10-jun (CPI+BOC barrieron 7 posiciones que eran 1 apuesta). Downward-only, opt-in OFF |

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
los features técnicos (v2.11.0): hoy hay **~70/400** trades con features reales (gate Fase
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

### Lo inmediato *(estado al 11-jun-2026)*
- **Dejar correr** para juntar data (lo más importante; 70→400 es el cuello de botella).
- **En 3-5 días**: `/exit_analysis` → si el trailing simulado da delta +R robusto, activar
  el trailing real de forex CON evidencia (hoy forex/oro no tienen trailing efectivo).
- Gold ya NO está en `DEMO_ALLOWED_SYMBOLS` (paper-only). Calendar gate + cap USD ya activos.
- El veto LLM (`ENABLE_LLM_ENSEMBLE`) queda OFF en esta máquina: agregaría llamadas de
  ~50s al gate (límite de hardware, ver §1).

## 5. Cómo construir (convenciones INAMOVIBLES)

- **Read-only de mercado:** `ENABLE_REAL_TRADING=false` HARDCODED; `order_send` SOLO en
  `app/brokers/mt5_demo_trader.py`; el LLM y el ML son **SUBTRACTIVOS** (solo vetan/bajan
  a paper, JAMÁS fuerzan una orden). No tocar `mt5_demo_trader.py` ni `mt5_reconciler.py`.
- **Todo opt-in OFF + soft-fail:** cada capa nueva default `false`; si está apagada o algo
  falla, el bot corre EXACTAMENTE igual.
- **Mantener pytest verde (572).** Al tocar `Settings`: sincronizar
  `tests/test_score._settings()` Y `tests/test_alert_rules._settings()`.
- **Versionado (regla del user):** patch (v3.5.1) para fixes; minor (v3.6.0) SOLO para
  features reales; nunca saltar números. Bump `app_version` + `CHANGELOG.md` +
  `.env.example` + docs al cerrar cada versión.
- **Cada módulo nuevo trae su test file.** No mergear sin todos los tests verdes.
- Nunca leer/mostrar el `.env` real ni secrets.

## 6. Prompt para arrancar Claude Code en la Lenovo

Abrí Claude Code en `C:\Users\LENOVO\tradingalertaIA` y pegá esto como primer mensaje:

```
Retomamos Trading Alert AI (bot de trading algorítmico LOCAL, Python 3.12, Windows).
Estado: v3.5.0, main, 572 tests verdes, corriendo en esta máquina (Lenovo) vía
.\start_bot.ps1. Protecciones activas: calendar gate, cap USD, exit shadow registrando.

Leé en este orden ANTES de tocar nada: RESUMEN_COMPLETO.md (todo el proyecto en uno),
PROXIMOS_PASOS.md (qué sigue + reglas), CONTEXTO_MAESTRO_v3.5.0.md (arquitectura),
CHANGELOG.md, y GO_LIVE_RUNBOOK.md (camino a real-money).

Reglas inamovibles: real-money BLOQUEADO (ENABLE_REAL_TRADING=false HARDCODED) hasta
que /readiness esté verde — el user ya lo pidió 3+ veces, la respuesta es el runbook,
no el flag; order_send solo en mt5_demo_trader.py; LLM/ML SUBTRACTIVOS (solo vetan,
nunca fuerzan); todo opt-in OFF + soft-fail; mantener 572 tests verdes; al tocar
Settings sincronizar los _settings() de test_score y test_alert_rules; versionado:
patch para fixes, minor para features, sin saltos.

Límite de hardware: la GPU no banca LLM local rápido (~50s/gen) — nada de LLM en el
hot path del ciclo; ContinuousLearner queda OFF en esta máquina.

La verdad de fondo: el cuello de botella es DATA (70/400), no código. El único +R es
régimen-short (no edge durable). Dejar correr; no empezar Fase D/E sin sus gates.

Decime qué querés hacer: (A) revisar la data (/performance, /readiness, /exit_analysis,
/exposicion); (B) si /exit_analysis ya da delta +R robusto, activar el trailing de forex
con evidencia; (C) Fase D si la data llegó a 400; (D) otra cosa.
```
