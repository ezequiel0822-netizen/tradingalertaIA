# PRÓXIMOS PASOS — Trading Alert AI (continuación post-migración)

> **Para retomar el desarrollo en Claude Code (Lenovo).** Dónde estamos, qué sigue, y
> cómo construir sin romper nada. Complementa:
> - `HANDOFF.md` — setup de la máquina + prompt de arranque.
> - `Trading Alert AI v3.1 Plan Arquitectura MEJORADO.md` — el plan/arquitectura completo.
> - `CHANGELOG.md` — historia detallada de cada versión.
> - `CONTEXTO_MAESTRO_v3.8.0.md` — arquitectura/schema **vigentes** (el v3.6.0 queda histórico).
> - `GO_LIVE_RUNBOOK.md` — el camino completo a real-money (gates, broker, día-D).
> - `RESUMEN_COMPLETO.md` — TODO el proyecto en un solo documento (para arrancar un chat nuevo).
> - `ESPEC_BACKTEST_REPLAY_v1.md` + `MAPA_DE_EDGE_Y_RUTA.md` — el harness de backtest (cómo) y la ruta de edge (porqué).

---

## 1. Estado actual

- **v3.8.0**, **676 tests verdes** (main; +1 commit de S2-acciones pendiente de merge).
- **REFOCUS v3.7.0: 100% LA BOLSA** — memecoins CORTADAS (`ENABLE_MEMECOIN_ENGINE=false`; bot
  aparte), scalping APAGADO, stock alerts ON. **v3.8.0: regime gate vivo** (`ENABLE_REGIME_GATE`,
  opt-in): los longs contra-tendencia van a paper. Diagnóstico: longs −0.57R / shorts +1.29R
  = régimen, no edge. No es volatilidad (VIX ~16). Demo plano ~$88.6k.
- **Backtest Replay Harness** (v3.6.0, offline): paquete `app/backtest/` que reproduce
  la historia D1 de MT5 con las estrategias REALES y mide R neto con pesimismo, en tablas
  `backtest_*` separadas. **No toca el ciclo vivo, no cuenta para `/readiness` ni Fase D.**
  Opt-in (`ENABLE_BACKTEST_HARNESS=false`). Verdicto del primer run: **ninguna estrategia
  pasa §11 sobre D1** — el +4.7R de `trend_following_d1` era un artefacto (1 trade sintético
  de USDCHF = 80% del P&L). Detalle en `RESUMEN_COMPLETO.md` §2.5 y `MAPA_DE_EDGE_Y_RUTA.md`.
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
| **v3.6.0** | **Backtest Replay Harness** (`app/backtest/`: `historical_loader`, `context_builder`, `trade_simulator`, `replay_harness`, `report`) + `app/intelligence/regime_filter.py` + `app/strategies/trend_following_d1.py` (hipótesis Donchian congelada). Offline, opt-in OFF, tablas `backtest_*` separadas. Veredicto: sin edge en D1; el "+4.7R" de trend D1 fue un artefacto que el harness atrapó |
| **v3.7.0** | **Refocus a la bolsa**: `ENABLE_MEMECOIN_ENGINE` (corta colección de memecoins) + ESPEC del backtest de acciones. El user montó bot aparte para memecoins; scalping off, stock alerts on |
| **v3.8.0** | **Regime gate vivo** (`jobs._regime_gate` + `ENABLE_REGIME_GATE`): los longs contra-tendencia D1 van a paper. Downward-only, opt-in. Cablea al vivo el `regime_filter`. Nace del diagnóstico (longs −0.57R/shorts +1.29R) |
| **backtest acciones** | S1 (`stock_historical_loader`, Yahoo D1 ajustado) + S2 (harness `category=stock` + banner survivorship). Código hecho; run real PENDIENTE (Yahoo throttle). → v3.9.0 con S3 |

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

### Backtest Replay Harness — el motor de descubrimiento *(HECHO — v3.6.0)*
- **Qué:** `app/backtest/` reproduce la historia D1 con las estrategias REALES y descarta
  en horas lo que el demo tardaría meses. La data viva pasa a CONFIRMAR, no a descubrir.
- **Conclusión:** ninguna estrategia (existentes + `trend_following_d1` Donchian) pasa los
  criterios §11 sobre D1. El "+4.7R" de trend D1 fue un artefacto (1 trade sintético de
  USDCHF pre-1999). **No se promovió nada.** El pipeline correcto quedó construido:
  hipótesis → backtest con costos → walk-forward OOS → paper → demo → gates.
- **Lo que sigue del harness (v3.7+, diferido):** collector de **COT** (CFTC, gratis: info
  que el precio no contiene), **instrumentos descorrelacionados** (índices/commodities D1),
  backfill macro VIX/DXY, granularidad H1 para salidas. Orden completo en `MAPA_DE_EDGE_Y_RUTA.md`.

### Lo inmediato *(estado al 14-jun-2026)*
- **Dejar correr** el libro vivo para juntar data con features (lo más importante; 70→400
  es el cuello de botella de la Fase D — el backtest NO la reemplaza).
- **`/exit_analysis`** cuando haya días de muestra → si el trailing simulado da delta +R
  robusto, activar el trailing real de forex CON evidencia.
- Gold ya NO está en `DEMO_ALLOWED_SYMBOLS` (paper-only). Calendar gate + cap USD ya activos.
- El veto LLM (`ENABLE_LLM_ENSEMBLE`) queda OFF en esta máquina: agregaría llamadas de
  ~50s al gate (límite de hardware, ver §1).

## 5. Cómo construir (convenciones INAMOVIBLES)

- **Read-only de mercado:** `ENABLE_REAL_TRADING=false` HARDCODED; `order_send` SOLO en
  `app/brokers/mt5_demo_trader.py`; el LLM y el ML son **SUBTRACTIVOS** (solo vetan/bajan
  a paper, JAMÁS fuerzan una orden). No tocar `mt5_demo_trader.py` ni `mt5_reconciler.py`.
- **Todo opt-in OFF + soft-fail:** cada capa nueva default `false`; si está apagada o algo
  falla, el bot corre EXACTAMENTE igual.
- **Mantener pytest verde (657).** Al tocar `Settings`: sincronizar
  `tests/test_score._settings()` Y `tests/test_alert_rules._settings()`.
- **Versionado (regla del user):** patch (v3.6.1) para fixes; minor (v3.7.0) SOLO para
  features reales; nunca saltar números. Bump `app_version` + `CHANGELOG.md` +
  `.env.example` + docs al cerrar cada versión.
- **Backtest harness:** vive en `app/backtest/` y escribe SOLO en tablas `backtest_*`;
  NUNCA cuenta para `/readiness`, `/expectancy`, `/edge` ni los 400 de Fase D; el backtest
  abre la puerta de PAPER, nunca la de MT5; prohibido ajustar una hipótesis hasta que pase.
- **Cada módulo nuevo trae su test file.** No mergear sin todos los tests verdes.
- Nunca leer/mostrar el `.env` real ni secrets.

## 6. Prompt para arrancar Claude Code en la Lenovo

Abrí Claude Code en `C:\Users\LENOVO\tradingalertaIA` y pegá esto como primer mensaje:

```
Retomamos Trading Alert AI (bot de trading algorítmico LOCAL, Python 3.12, Windows).
Estado: v3.8.0, main, 676 tests verdes, corriendo en la Lenovo vía .\start_bot.ps1.
REFOCUS: 100% LA BOLSA (acciones+forex+oro); memecoins CORTADAS (bot aparte), scalping
APAGADO. Protecciones: calendar gate, cap USD, exit shadow; regime gate disponible (opt-in).

Leé en este orden ANTES de tocar nada: RESUMEN_COMPLETO.md (todo el proyecto en uno),
PROXIMOS_PASOS.md (qué sigue + reglas), CONTEXTO_MAESTRO_v3.8.0.md (arquitectura),
CHANGELOG.md, GO_LIVE_RUNBOOK.md (camino a real-money), y para el backtest
ESPEC_BACKTEST_REPLAY_v1.md (forex) + ESPEC_BACKTEST_STOCKS_v1.md (acciones) + MAPA_DE_EDGE_Y_RUTA.md.

Reglas inamovibles: real-money BLOQUEADO (ENABLE_REAL_TRADING=false HARDCODED) hasta
que /readiness esté verde — el user ya lo pidió 3+ veces, la respuesta es el runbook,
no el flag; order_send solo en mt5_demo_trader.py; LLM/ML SUBTRACTIVOS; los gates vivos
(calendar/cap USD/regime) son DOWNWARD-ONLY (solo bajan a paper); todo opt-in OFF +
soft-fail; mantener 676 tests verdes; al tocar Settings sincronizar los _settings() de
test_score y test_alert_rules; versionado patch/minor sin saltos. El backtest (app/backtest/)
escribe SOLO en backtest_*, NO cuenta para /readiness ni Fase D, no toca el ciclo vivo.
NO inventar edge artificial (curve-fitting): el edge se descubre, no se inyecta.

Límite de hardware: la GPU no banca LLM local rápido (~50s/gen) — nada de LLM en el
hot path del ciclo; ContinuousLearner queda OFF en esta máquina.

La verdad de fondo: el cuello de botella es DATA (70/400), no código. No hay edge
probado: el +4.7R del trend_following_d1 en el backtest fue un ARTEFACTO (1 trade
sintético de USDCHF). Dejar correr el libro vivo (Fase D); el backtest descarta/descubre.

Decime qué querés hacer: (A) revisar la data (/performance, /readiness, /exit_analysis,
/exposicion); (B) si /exit_analysis ya da delta +R robusto, activar el trailing de forex
con evidencia; (C) Fase D si la data llegó a 400; (D) avanzar el harness (COT / instrumentos
descorrelacionados, MAPA §8); (E) otra cosa.
```
