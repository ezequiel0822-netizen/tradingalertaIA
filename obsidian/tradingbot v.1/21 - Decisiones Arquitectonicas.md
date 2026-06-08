---
tags: [decisiones, arquitectura, por-que]
version: v2.7.0
updated: 2026-05-30
---

# Decisiones Arquitectonicas

> [!info] Para que es esto
> Documenta el "por que" detras de las decisiones de diseño importantes. Util cuando alguien (vos o Claude futuro) considera cambiar algo y necesita entender el contexto historico.

---

## Pivots de identidad

### v2.0.0 — alerter → trader engine

User decidio que el bot pase de "alertar y dejar al humano operar" a "decidir entradas/salidas autonomamente". Implico:
- Strategy router (5 swing)
- Portfolio + risk + position sizer
- Kill-switch automatico
- Bot mode toggle (`trader/alerts_only/hybrid`)

**Por que:** El humano operando manual era cuello de botella + emocional. Bot autonomo en demo permite testear estrategias 24/7.

### v2.0.0 — Memecoins como lab de aprendizaje, no como mercado operable

MT5 no tiene memecoins. Decision: detectar memecoins igual, generar paper_trades + outcomes para alimentar el learning, pero NO intentar ejecutar a MT5.

**Por que:** Memecoins son ruidosos (rug pulls, manipulacion) pero generan mucho volumen de data → util para entrenar features (volume_strength, anti_hype, critical_security). Sin operar real, no hay riesgo.

### v2.5.0 — Phase 5: order_send a MT5 demo

Pivot desde "trader simulado" a "trader que ejecuta a MT5 demo".

**Por que:**
- Validar que las decisiones del bot se traduzcan en ordenes reales correctas
- Probar slippage, spread, retcode behavior contra broker real
- Sentir el feel de un trade bot en produccion sin riesgo real-money

**Decisiones de seguridad:**
- Modulo `mt5_demo_trader.py` separado de `mt5_reader.py`
- Validacion `account.trade_mode == ACCOUNT_TRADE_MODE_DEMO`
- Confirmacion manual obligatoria por default
- `ENABLE_REAL_TRADING=false` HARDCODED

### v2.5.4 — Auto-confirm opt-in

User autorizo bypassear la confirmacion manual via flag.

**Por que opt-in:**
- Confirmacion manual era cuello de botella (user no siempre disponible)
- Pero auto execute es decision de seguridad alta
- Default conservador (manual), user activa cuando esta listo

### v2.6.0 — Scalping engine en thread dedicado

Phase 5.5 Bloque B. Scalping requiere polling 3-5s vs swing 60s. Solucion: thread separado.

**Por que NO asyncio:**
- MT5 lib es sincronica
- Refactor a asyncio invasivo
- Threading + stop_event funciona bien para I/O-bound

**Decisiones:**
- Caps independientes (`SCALPING_MAX_*`)
- Kill switch propio (`scalping_halted`)
- Lessons separadas (sufijo `_scalping`)
- Outcomes al close (no por horizon)

---

## Decisiones del sprint 27-28 may

### v2.6.6 — Multi-strategy scalping con lista, no enum

`ScalpingEngine.strategies: list` construida por flags. NO un single enum field.

**Por que lista:**
- Permite agregar strategies sin breaking change
- Cada strategy independiente con su flag
- Iteracion clara, primer hit gana

**Orden:** breakout primero, mean_reversion fallback. Razon: momentum > rangebound como prior.

### v2.6.7 — MT5Reconciler como modulo separado, no en lifecycle

Pude haberlo metido en `lifecycle_manager`. NO lo hice.

**Por que separado:**
- Lifecycle ya complejo (~200 lineas)
- Reconciler tiene scope claro: MT5 vs paper_trade consistency
- Lifecycle no necesita saber de MT5 close
- Mas facil testear aisladamente

### v2.6.7 — SL sync solo TIGHTEN, nunca LOOSEN

`MT5Reconciler` sincroniza SL del paper_trade al MT5 SOLO si tightens el risk.

**Por que:**
- Loosen SL = empeorar el risk de una posicion abierta = peligroso
- Tighten SL = mejorar (reducir potential loss) = safe
- Cualquier divergencia en sentido loosen se ignora (probable bug en lifecycle)

### v2.6.8 — `size_notional` update POST-demo_order, no PRE

Alternativa considerada: clampear el `position_sizer` con MT5 max lot antes de calcular. Rechazada.

**Por que POST:**
- PRE requiere conocer MT5 contract_size antes del sizing (acopla layers)
- POST refleja ground truth de la ejecucion (notional real, no estimado)
- Mas simple: cambio en un solo lugar (hook post-send)

### v2.6.8 — Per-symbol cooldown en risk_manager, no strategy_router

Alternativa considerada: cooldown en cada strategy. Rechazada.

**Por que en risk_manager:**
- Risk gate centralizado vs distribuido
- Estado unico (no replicado en cada strategy)
- Mas auditable: 1 check para todas las strategies
- Strategy puede emitir signal, risk_manager decide si abrir

### v2.6.9 — `/gate_preview` como comando Telegram

Alternativa considerada: solo un script standalone. Decidi hacer ambas (script + command).

**Por que command:**
- User puede chequear desde el celular
- No requiere PowerShell
- Reutilizable cada N dias para monitorear evolution

---

## Decisiones de v2.7.0

### Realized-R como metrica principal (no drift)

Drift del alerta era ficcion (~99% neutral). Realized-R de paper_trades es la realidad.

**Por que no migrar TODO:**
- 145k+ outcomes historicos en path drift (data valiosa)
- Path drift sigue funcionando para `/aprendizaje` legacy
- Realized aprende sobre data nueva post-Fix A
- Flag `ENABLE_REALIZED_LEARNING` permite rollback transparente

### Promotion gate "inocente hasta probarse culpable"

Alternativa considerada: gate restrictivo por default (todo SHADOW hasta probarse). Rechazada.

**Por que inocente por default:**
- Strategies nuevas sin samples no pueden probar nada → quedarian SHADOW forever
- Junta data IGUAL en LIVE o SHADOW (paper_trade siempre se crea)
- Solo los losers PROBADOS se bloquean (con n >= min_samples y avg_R <= umbral)
- Menos friccion para iteracion

### `STRATEGY_PROMOTION_MIN_SAMPLES=30` conservador

Mas bajo (e.g. 10) = deteccion rapida pero alta variance. Mas alto (e.g. 50) = robustez pero loser quema mas USD demo.

**Por que 30:**
- Balance razonable entre velocidad y confianza estadistica
- User puede bajar a 20 para acelerar
- Compatible con caps demo conservadores (15 trades abiertos max)

### Cost model con defaults teoricos, no calibrados

Alternativa: scrape MT5 demo orders historicas para promediar el cost real. No hecho aun.

**Por que defaults:**
- Cost demo es proxy de cost real-money (que es lo que importa eventualmente)
- Calibracion fina requiere data + tooling
- Mejor cost teorico conservador ahora que nada
- Marcado en roadmap para v2.7.x

### DB fuera de iCloud

iCloud causaba contencion (tests 1h42m vs 60s). Movida a path local.

**Por que NO uso Postgres:**
- Single-user local
- SQLite stdlib es thread-safe via conexion per call
- File-based backup
- Performance suficiente (901 paper_trades, 507k outcomes, queries ms)

**Por que SQLITE_PATH absoluto:**
- iCloud sync interfiere con file locks
- iCloud genera `.tmp.PID.HASH` files cuando hay conflicts
- Performance terrible (medido)

### `.db` viejo se queda como backup

NO borrar el `.db` viejo de iCloud todavia.

**Por que:**
- Es backup zero-cost (ya esta ahi)
- Si la DB nueva se corrompe, recuperar from iCloud copy
- Dejarlo unos dias con bot operando bien primero

---

## Decisiones generales

### Soft-fail para todo lo opcional

MT5 reader, Claude API, anthropic package, geckoterminal collector, Yahoo RSS, SEC EDGAR, ForexFactory.

**Por que:**
- Bot corre siempre, aunque degradado
- Si Yahoo falla, otras categorias siguen
- Si Claude falla, scoring base sigue
- Usuario no se queda sin nada cuando algo externo falla

### Logs nunca filtran credenciales

Doble defensa:
1. `Settings.__repr__` mascarado via `_SECRET_FIELDS`
2. `LogRedactor` filter en logging_config

**Por que dos capas:**
- `__repr__` cubre `logger.info("Settings: %s", settings)`
- `LogRedactor` cubre cualquier otro log que mencione credenciales por error
- Defense in depth

### Bot mode resolution order

CLI `--mode` > `bot_state.bot_mode_active` > setting `BOT_MODE` > default `trader`.

**Por que esta order:**
- CLI override es explicito (debugging session)
- bot_state es runtime override (Telegram `/mode`)
- setting es config base
- default conservador (`trader` enabled)

### Scalping outcomes al CLOSE, no por horizon

Scalping trades duran 10s-3min. Horizonts 1h+ irrelevantes.

**Implementacion:**
- `alert_id = -paper_trade.id` (negativo) para no colisionar con swing outcomes
- Category con sufijo `_scalping`
- Insertado en `signal_outcomes` al cerrar el paper_trade

---

## Decisiones de NO hacer

### NO ML profundo

LSTM, transformers, etc. Rechazado.

**Por que:**
- Retail trading rara vez paga el overhead
- Strategies basadas en reglas son auditables
- Datos retail son pocos para entrenar bien
- Risk mas alto de overfit

### NO Reinforcement Learning

Fragil para trading. Reward signal noisy. Espacio de accion mal definido. Rechazado.

### NO cifrado at-rest del SQLite

Opcional. Para single-user local con `.env` que tampoco esta cifrado, no agrega seguridad significativa.

### NO logs a archivo con rotacion

Stderr suficiente para debugging interactivo. Si necesitas archivar, redirigir desde PowerShell: `python main.py 2>&1 | Tee-Object log.txt`.

### NO TradingView integration

Duplica data que ya tenemos via MT5/Yahoo. Costo de TradingView Premium injustificado.

### NO webhooks externos

Out of scope. El bot es self-contained.

### NO activar `learning_gate` con data actual

`/gate_preview` revelo que bloquearia ~todo. Esperar 1-2 semanas + recalibrar `OUTCOME_WIN_RETURN_*`.

---

## Lecciones meta sobre decisiones

> [!quote] Sobre lo defensivo vs agresivo
> En el sprint 27-may, el `.env` era agresivo (DEMO_RISK 5.26%, MAX_OPEN 100). Perdida de $12k. Post-sprint, conservador (DEMO_RISK 1.5%, MAX_OPEN 15). Conclusion: defaults conservadores son mas reversibles. Un user puede aflojar facil; no puede revertir una perdida grande.

> [!quote] Sobre features opt-in vs opt-out
> Cada feature de riesgo (auto-confirm, scalping, real-money) es opt-in por default. User da consent explicito. Esto previene que un upgrade accidental active algo critico.

> [!quote] Sobre tests como contrato
> 397 tests verdes baseline. Cada fix viene con tests del caso negativo (no solo happy path). Sin esto, los bugs arquitectonicos del sprint hubieran reaparecido en regresiones.

---

## Links relacionados

- [[02 - Reglas de Seguridad]] - lo que las decisiones protegen
- [[17 - Promotion Gate y Cost Model]] - decisiones v2.7.0
- [[16 - Bugs Resueltos]] - decisiones que vinieron de bugs
- [[07 - Ideas y Proximos Pasos]] - decisiones futuras pendientes
