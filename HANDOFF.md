# HANDOFF — Trading Alert AI (continuidad entre máquinas)

> Documento para retomar el proyecto en otra computadora (o sesión nueva de Claude Code).
> **Pegá el bloque de abajo como primer mensaje** en el Claude Code de la máquina nueva.
> No contiene secrets (login/password/token viven solo en el `.env`, fuera de git).

---

## Prompt de arranque (copiá/pegá en Claude Code)

```
Sos Claude Code retomando el proyecto Trading Alert AI en una máquina nueva
(migración de hardware, NO se agregó código — solo cambió la compu).

PROYECTO: bot de trading algorítmico LOCAL en Python 3.12 (Windows, PowerShell + venv).
Detecta oportunidades (memecoins / acciones US / forex / oro), decide con un strategy
router (5 swing + 2 scalping), hace paper trades y manda órdenes a MT5 demo
(MetaQuotes-Demo). Real-money BLOQUEADO por diseño (HARDCODED).
Estado: v3.4.0, 547 tests verdes.

ANTES DE TOCAR NADA leé (en el repo): CHANGELOG.md (historia completa hasta v3.1.0).
Si los copiaste de la otra compu: CONTEXTO_MAESTRO_v2.10.0.md +
"Trading Alert AI v3.1 Plan Arquitectura MEJORADO.md" + la carpeta de memoria de Claude.

REGLAS INAMOVIBLES (no romper nunca):
- ENABLE_REAL_TRADING=false HARDCODED. Real-money prohibido sin autorización nueva y
  explícita del user.
- order_send SOLO en app/brokers/mt5_demo_trader.py. Ningún módulo nuevo lo llama directo.
- El LLM y el ML son SUBTRACTIVOS: solo pueden vetar / bajar-a-paper, JAMÁS forzar una orden.
- Todo lo nuevo (Ollama, asesor, ensemble veto, resumen diario) es opt-in OFF + soft-fail:
  si está apagado, el bot corre idéntico a antes.
- Nunca leer/mostrar el .env real ni secrets. Mantener pytest verde (501). Al tocar
  Settings, sincronizar tests/test_score._settings() Y tests/test_alert_rules._settings().

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

VERDAD DE FONDO: el cuello de botella es DATA, no código. Ninguna estrategia tiene edge
aún (todas R-negativo neto). El LLM/ML filtran, explican y protegen capital — NO crean
edge. Lo más valioso ahora: DEJAR CORRER para juntar muestra limpia con los features
técnicos que ya se persisten.

PRÓXIMOS PASOS (roadmap v3.1): Fase C = ContinuousLearner (tabla trade_lessons);
Fase D = AdvancedPredictor (sumar LightGBM/RF al XGBoost) SOLO con ≥400 trades + features
reales; Fase E = StrategyMutator SOLO con ≥1 estrategia R+ neto + 3 meses data.
Diferidos: tick analyzer, sentiment, anomaly.

PRIMERA TAREA EN ESTA COMPU:
1. ollama pull llama3.1 (+ mistral si vas a usar el veto). Con GPU va rápido.
2. correr: .\.venv\Scripts\python.exe main.py
3. verificar en Telegram: /health (debe decir v3.1.0) + /market (debería responder rápido).
4. si OK, dejar correr.
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
- Para correr: `cd <ruta>\tradingalertaIA` + `.\.venv\Scripts\python.exe main.py`.
- Verificar: `/health` (versión), `/expectancy`, `/edge`, `/performance`, `/readiness`, `/exit_analysis`, `/ml_status`, `/market`.
