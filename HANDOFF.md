# HANDOFF — Trading Alert AI (continuidad entre máquinas)

> Documento para retomar el proyecto en otra computadora (o sesión nueva de Claude Code).
> **Pegá el bloque de abajo como primer mensaje** en el Claude Code de la máquina nueva.
> No contiene secrets (login/password/token viven solo en el `.env`, fuera de git).

---

## Prompt de arranque (copiá/pegá en Claude Code)

```
Sos Claude Code retomando el proyecto Trading Alert AI (sesión nueva / otra compu).

PROYECTO: bot de trading algorítmico LOCAL en Python 3.12 (Windows, PowerShell + venv).
REFOCUS v3.7.0: 100% LA BOLSA (acciones US + forex + oro). Las MEMECOINS se cortaron
(ENABLE_MEMECOIN_ENGINE=false; el user tiene un bot aparte para memecoins) y el SCALPING
se apagó. Decide con un strategy router (swing), hace paper trades y manda órdenes a MT5
demo (MetaQuotes-Demo, solo forex/oro ejecutan; acciones son paper). Real-money BLOQUEADO
por diseño (HARDCODED). Estado: v3.8.0, 676 tests verdes. Demo ~$88.6k (plano).

ANTES DE TOCAR NADA leé (en el repo, en este orden): RESUMEN_COMPLETO.md (todo en uno),
PROXIMOS_PASOS.md, CONTEXTO_MAESTRO_v3.8.0.md (arquitectura vigente), CHANGELOG.md
(historia hasta v3.8.0), GO_LIVE_RUNBOOK.md (camino a real-money), y para el backtest
ESPEC_BACKTEST_REPLAY_v1.md (forex) + ESPEC_BACKTEST_STOCKS_v1.md (acciones) +
MAPA_DE_EDGE_Y_RUTA.md (la ruta de edge). Y la carpeta de memoria de Claude.

REGLAS INAMOVIBLES (no romper nunca):
- ENABLE_REAL_TRADING=false HARDCODED. Real-money prohibido sin autorización nueva y
  explícita del user.
- order_send SOLO en app/brokers/mt5_demo_trader.py. Ningún módulo nuevo lo llama directo.
- El LLM y el ML son SUBTRACTIVOS: solo pueden vetar / bajar-a-paper, JAMÁS forzar una orden.
- Todo lo nuevo (Ollama, asesor, ensemble veto, resumen diario) es opt-in OFF + soft-fail:
  si está apagado, el bot corre idéntico a antes.
- Nunca leer/mostrar el .env real ni secrets. Mantener pytest verde (676). Al tocar
  Settings, sincronizar tests/test_score._settings() Y tests/test_alert_rules._settings().
- Versionado: patch para fixes, minor SOLO para features reales, sin saltar números.
- Real-money: el user ya lo pidió 3+ veces; la respuesta es GO_LIVE_RUNBOOK.md +
  /readiness, NO desbloquear el flag. Memoria de Claude lo documenta.
- Backtest harness (app/backtest/): offline, escribe SOLO en tablas backtest_*, NO toca
  el ciclo vivo ni mt5_demo_trader, NO cuenta para /readiness ni los 400 de Fase D. El
  backtest abre la puerta de PAPER, nunca la de MT5; prohibido ajustar una hipótesis hasta
  que pase (si no pasa, se documenta).
- NO inventar "edge artificial" (optimizar parámetros hasta que el backtest brille = curve-
  fitting = se funde en real). El edge se DESCUBRE (data + research, validado fuera de
  muestra), no se inyecta. El user lo pidió; la respuesta es esta.
- Los gates vivos (calendar, cap USD, regime) son DOWNWARD-ONLY: solo bajan a paper, jamás
  fuerzan una orden. Opt-in OFF + soft-fail.

QUÉ SE CONSTRUYÓ (serie v3, todo pusheado):
- v2.11.0: rsi/atr/macd persistidos al entry (desbloquea features ML reales) +
  app/intelligence/reasoner.py (TradingReasoner, asesor LLM read-only, solo texto).
- v2.12.0: comandos Telegram /market y /porque_perdi.
- v3.0.0: veto del ensemble Llama+Mistral en el gate (app/intelligence/ensemble_gate.py
  + jobs._llm_ensemble_gate, downward-only, opt-in OFF ENABLE_LLM_ENSEMBLE).
- v3.1.0: resumen diario por Telegram (jobs._maybe_send_daily_summary).
- v3.2.0: Fase C ContinuousLearner (leccion por trade -> tabla trade_lessons; agrupa y
  PROPONE, no aplica). reasoner.analyze_win. Opt-in OFF, soft-fail, read/registro.
- v3.3.0: comando /performance (rendimiento desde un baseline limpio post-bug de mayo;
  no altera el balance real). El -11% fue el bug; limpio queda ~plano (+0.17% desde 3-jun).
  + /readiness (gates honestos para real-money). v3.3.1: cache+cooldown 429 Gecko.
- v3.4.0: exit shadow (mide si un trailing mejoraria las salidas; forex/oro no tenian
  trailing efectivo). /exit_analysis. Read-only.
- v3.5.0: calendar gate (conecta is_safe_window que estaba HUERFANO — el 10-jun abrio
  USDCAD 18 min antes del BOC) + cap de exposicion neta USD (7 posiciones eran 1 sola
  apuesta long-USD). /exposicion. Ambos downward-only, opt-in OFF.
- v3.6.0: Backtest Replay Harness (app/backtest/: historical_loader, context_builder,
  trade_simulator, replay_harness, report) + app/intelligence/regime_filter.py +
  app/strategies/trend_following_d1.py (Donchian D1, hipotesis congelada). Reproduce la
  historia D1 con las estrategias REALES y mide R neto con pesimismo, OFFLINE, en tablas
  backtest_* separadas. Veredicto del primer run: ninguna estrategia pasa §11 en D1; el
  +4.7R del trend D1 fue un ARTEFACTO (1 trade sintetico de USDCHF = 80% del P&L). NADA
  se promovio. El harness existe para atrapar justo ese falso positivo.
- v3.7.0 (REFOCUS A LA BOLSA): flag ENABLE_MEMECOIN_ENGINE (default true; en false el ciclo
  NI COLECTA memecoins -> libera presupuesto para la bolsa). El user montó un bot aparte
  para memecoins y apagó el scalping. + ESPEC_BACKTEST_STOCKS_v1.md.
- v3.8.0 (REGIME GATE VIVO): jobs._regime_gate + ENABLE_REGIME_GATE=false (opt-in). Antes
  del order_send a demo, clasifica el regimen D1 del simbolo (regime_filter sobre el cache)
  y si el trade pelea la tendencia (long en down / short en up) lo deja paper-only.
  Downward-only, soft-fail. Defensivo (NO edge): cablea al vivo el regime_filter que vivia
  solo en el backtest. Nace del diagnostico: longs -0.57R vs shorts +1.29R = regimen.
- Serie backtest de ACCIONES: S1 (app/backtest/stock_historical_loader.py: Yahoo D1
  ajustado por splits/dividendos + anti-429) + S2 (replay_harness con category='stock' +
  banner de SURVIVORSHIP BIAS en el report). CODIGO HECHO + testeado; el run real con
  veredicto quedó PENDIENTE (Yahoo throttleo la IP en las pruebas; se completa cuando se
  libere). El backtest de acciones SOLO sirve para DESCARTAR (survivorship bias).
- GO_LIVE_RUNBOOK.md: el camino completo a real-money (gates, broker, codigo del dia-D,
  checklist). Real-money sigue HARDCODED bloqueado hasta que /readiness este verde.
- preflight.py (raiz del repo, NO commiteado): chequea config + secretos + MT5 + el refocus
  (memecoins off, scalping off, stock alerts on, v3.x mergeado) sin arrancar nada.

VERDAD DE FONDO: el cuello de botella es DATA (70/400 trades con features), no código.
No hay edge PROBADO, CONFIRMADO POR DOS VÍAS: (1) el backtest sobre décadas de D1 (ninguna
estrategia pasa §11; el +4.7R del trend_following_d1 fue un ARTEFACTO de 1 trade sintético
de USDCHF), y (2) el diagnóstico vivo del 16-jun (slicing por dirección: forex_session_
breakout pierde -0.57R en LONGS y gana +1.29R en SHORTS; oro longs -2.57R). Los longs
sangran porque pelean el régimen; el +R de shorts NO es edge durable, es coyuntura (gira
y sangra). NO es volatilidad (VIX ~16, calmo). El −11% del demo fue el bug de mayo; limpio
queda ~plano (~$88.6k). El LLM/ML filtran, explican, protegen — NO crean edge. Lo más
valioso: DEJAR CORRER el libro vivo. Hardware: la GPU no banca LLM local rápido (~50s/gen)
— nada de LLM en el hot path; ContinuousLearner OFF en la Lenovo (límite de hardware).

PRÓXIMOS PASOS: 1) dejar correr el libro vivo limpio (data 70→400 para Fase D); 2) probar
el regime gate en vivo (ENABLE_REGIME_GATE=true) — deja de tomar longs contra la tendencia;
3) completar el veredicto del backtest de ACCIONES (S2 hecho; falta el run real cuando
Yahoo no throttlee) y cerrar S3 (trend_following_d1 sobre acciones + v3.9.0); 4) COT
collector (información nueva = el lever de mejor chance real, MAPA §3.4); 5) Fase D (≥400
trades) / Fase E (edge + 3 meses); 6) real-money: GO_LIVE_RUNBOOK.md cuando /readiness verde.

PRIMERA TAREA AL RETOMAR:
1. python preflight.py (chequea todo: config, secretos, MT5, refocus). Debe decir LISTO.
2. correr: .\start_bot.ps1 (pide contraseña si STARTUP_PASSWORD_SHA256 está en .env).
3. verificar en Telegram: /health (debe decir v3.8.0) + /readiness + /exposicion.
   /market tarda ~50s en hardware chico — es normal, no es un bug.
4. si OK, dejar correr. (Ollama opcional: ollama pull llama3.2:3b / llama3.1.)
```

---

## Checklist de migración a una máquina nueva

Lo que **NO** viaja por GitHub (hay que copiarlo/instalarlo aparte):

| Qué | Por qué | Acción |
|---|---|---|
| `.env` | Secrets (Telegram, MT5) + config | Copiar de la máquina vieja; actualizar `SQLITE_PATH` y MT5 si el path cambia. |
| DB (`...\trading_data\trading_alert_ai.db`) | Historia: trades, outcomes, lecciones | Copiar si querés continuidad del aprendizaje (si no, arranca vacía). |
| Ollama + modelos | Es otra máquina | Instalar Ollama + `ollama pull llama3.1` (+ `mistral`). |
| MT5 logueado | El reader necesita la cuenta demo | Abrir MT5 + login a MetaQuotes-Demo. |
| `.venv` | Dependencias | `python -m venv .venv` + `pip install -r requirements.txt` (Python 3.12). |
| Docs de contexto + memoria de Claude | Continuidad para Claude Code | `CONTEXTO_MAESTRO_*.md` + carpeta `memory` de Claude (no están en git por tener el login demo). |

## ⚠️ Reglas operativas

- **El bot corre en UNA sola máquina a la vez.** Dos máquinas contra la misma cuenta MT5
  demo = órdenes dobles y DBs divergentes. Apagá una antes de prender la otra.
- Para correr: `cd <ruta>\tradingalertaIA` + **`.\start_bot.ps1`** (arranque oficial,
  con contraseña opt-in). Directo sin contraseña: `.\.venv\Scripts\python.exe main.py`.
- Verificar: `/health` (versión), `/expectancy`, `/edge`, `/performance`, `/readiness`, `/exit_analysis`, `/ml_status`, `/market`.
