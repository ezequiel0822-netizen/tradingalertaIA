# Changelog

## Trading Alert AI v3.9.0

**COT collector: el primer input informacional fuera del OHLCV.** La ventaja retail es ESTRUCTURAL e INFORMACIONAL, nunca cognitiva (MAPA_DE_EDGE_Y_RUTA §2): toda la comprensión posible sobre data pública (velas) ya está en el precio. El Commitments of Traders de la CFTC (semanal, gratis) es el candidato #1 de "información que el precio todavía no digirió" (MAPA §3.4, ESPEC_BACKTEST_REPLAY_v1 §17.2): el posicionamiento real de los large speculators y los commercials.

- **`app/collectors/cot_collector.py`** + flag **`ENABLE_COT_COLLECTOR=false`** (opt-in OFF). Baja el Legacy Futures-Only de la Socrata Open Data API de la CFTC (`publicreporting.cftc.gov`) para los 9 mercados que el bot opera, mapeados por `cftc_contract_market_code` (identificador ESTABLE, no por nombre de mercado frágil): EUR, GBP, JPY, AUD, CAD, CHF, NZD, US Dollar Index y Gold. Calcula la posición neta no-comercial y comercial y persiste por reporte.
- **Tabla `cot_snapshots`** (UNIQUE `report_date, market_code`) + `repository.insert_cot_snapshot` (idempotente, `INSERT OR IGNORE`) + `fetch_latest_cot_snapshot`. Cableado en `jobs.run_once` tras el bloque de macro: gateado por `cot_last_capture_iso` (la data es semanal → chequeo 2×/día, `COT_COLLECTOR_INTERVAL_MINUTES=720`), soft-fail por mercado (uno que falla la HTTP no tumba a los demás).
- `tests/test_cot_collector.py` (+16): nets puros, parseo defensivo (sin fecha → None; conteos ausentes → None; tolera strings/floats), collect mockeado (9 mercados), soft-fail por mercado, payload vacío, `should_run` (gating por intervalo) e idempotencia del repository. Settings sincronizados en `test_score`/`test_alert_rules`.

Honestidad (NO inventar edge): el collector **SOLO captura para research** — no genera señal ni gate. La maquinaria de edge (slicing por posicionamiento, COT index sobre la historia acumulada) se construye DESPUÉS, sobre data ya juntada; el edge se descubre, no se inyecta. Como todo lo nuevo: opt-in OFF + soft-fail → con el flag apagado el bot corre EXACTAMENTE igual. Real-money sigue HARDCODED OFF.

676 -> **692 verdes**. app_version -> v3.9.0. `.env.example`.

> El veredicto del backtest de ACCIONES (S2/S3, también slotado para esta serie) queda PENDIENTE: Yahoo throttlea (429 confirmado incluso en 1 request, probablemente porque el bot vivo ya consume la cuota de la IP). Quedan listos `stock_backtest_run.json` (22 símbolos, 4 estrategias, `category=stock`) y el comando — correr cuando Yahoo afloje, idealmente con el bot vivo pausado. Recordatorio §2: el backtest de acciones solo sirve para DESCARTAR (survivorship bias), nunca habilita paper solo.

## Trading Alert AI v3.8.0

**Regime gate vivo: dejar de pelear la tendencia.** Nace del diagnóstico del 16-jun: el slicing por dirección mostró que `forex_session_breakout`/forex pierde **−0.57R en longs** y gana **+1.29R en shorts** (oro: longs **−2.57R**). El bot tomaba ambos lados y los longs sangraban porque iban contra el régimen. No es volatilidad (VIX ~16, calmo) ni edge nuevo — es estructura.

- **`_regime_gate`** (`jobs.py`) + flag **`ENABLE_REGIME_GATE=false`** (opt-in OFF): antes del `order_send` a demo, clasifica el régimen D1 del símbolo con `regime_filter` (sobre el cache `mt5_historical_cache`) y, si el trade va **contra** la tendencia (long en régimen `down` / short en `up`), lo deja **paper-only**. Aligned / `flat` / sin historia suficiente → permite. **Downward-only** (como el calendar gate y el cap USD): solo degrada a paper, JAMÁS fuerza una orden. Soft-fail. Solo forex/gold (lo único que ejecuta a demo).
- Reusa `regime_filter` (v3.6.0, que vivía solo en el backtest) + `yahoo_to_mt5` para el símbolo (GC=F → XAUUSD). El cache D1 lo refresca el loader / walk-forward.
- `tests/test_regime_gate.py` (+6, patrón `_StubJob`): long vs down → paper, short vs up → paper, aligned → permite, gate off → permite, historia insuficiente → permite, mapeo de oro. Settings sincronizados.

Honestidad: es **defensivo, no edge**. Deja de tomar los longs perdedores contra la tendencia; no garantiza ganar (el régimen se identifica tarde). Por eso es opt-in y downward-only. Real-money sigue HARDCODED OFF.

666 -> **672 verdes**. app_version -> v3.8.0. `.env.example`.

## Trading Alert AI v3.7.0

**Refocus a la bolsa: corte del motor de memecoins.** El user montó un bot aparte para memecoins; este queda 100% mercados (acciones + forex + oro).

- **`ENABLE_MEMECOIN_ENGINE`** (NUEVO, default `true` para backward-compat): master del motor de memecoins. En `false`, `jobs._collect_snapshots` ni siquiera corre los collectors de DEX Screener / GeckoTerminal — el ciclo deja de gastar tiempo y red en memecoins y le queda más presupuesto a la bolsa. Hallazgo que lo motivó: esos collectors corrían SIEMPRE; los flags `ENABLE_MEMECOIN_TELEGRAM`/`_HUNTER`/`_DETECTION` solo silenciaban las alertas, no la colección.
- Recomendado para el refocus (en `.env`): `ENABLE_MEMECOIN_ENGINE=false`, `ENABLE_MEMECOIN_TELEGRAM=false`, `ENABLE_SCALPING_ENGINE=false` (scalping tenía 1 trade -0.36R y settings agresivos), y `ENABLE_STOCK_TELEGRAM=true` (las acciones estaban mudas en Telegram).
- `tests/test_memecoin_engine_gate.py` (+3, patrón `_StubJob`): con el motor off no se llaman los collectors de memecoins y SÍ los de bolsa; default on (backward-compat). Settings sincronizados en `test_score`/`test_alert_rules`.

Honestidad: esto mejora la EFICIENCIA del ciclo (analiza la bolsa más a fondo y rápido), NO el % de ganados — el edge sale de data + research, no de velocidad. El lever honesto para el win rate es el backtest de acciones (próxima serie) + mantener los filtros estrictos.

657 -> **660 verdes**. app_version -> v3.7.0. `.env.example`.

## Trading Alert AI v3.6.0

**Backtest Replay Harness** (offline, opt-in, soft-fail): reproduce la historia D1 de MT5 barra por barra con las estrategias REALES del bot y mide R neto de costos con pesimismo brutal, en tablas `backtest_*` separadas. Proposito: invertir el descubrimiento — el backtest descarta en horas lo que el demo tardaria meses; la data viva pasa a CONFIRMAR en vez de descubrir. NO toca el ciclo vivo (ni importa `mt5_demo_trader`/`reconciler`), NO cuenta para `/readiness` ni para los 400 de la Fase D, y `ENABLE_REAL_TRADING=false` sigue HARDCODED.

Construido en 5 sesiones con gate de verificacion cada una (ESPEC_BACKTEST_REPLAY_v1.md):
- **S1** — tablas `backtest_*` + repository CRUD + `historical_loader` (mide la profundidad REAL por simbolo: D1 con decadas, H1 topado en 50k barras por el broker).
- **S2** — `context_builder` (ventanas que terminan en N) + `regime_filter` (SMA200+pendiente / terciles de ATR) + canario anti-look-ahead (un spike en N+5 no cambia el contexto en N).
- **S3** — `trade_simulator`: vida completa del trade con B1-B13 (empate intrabar -> SL; gaps asimetricos; trailing solo al close y tighten-only; time exit al open siguiente; direction-aware; slippage). Numeros dorados calculados a mano. Costos (B8) con el cost map REAL de `training_engine`.
- **S4** — `replay_harness` (orquestador, paridad `STRATEGY_MIN_CONFIDENCE`, B12 una posicion por simbolo/estrategia) + `report` (slices por simbolo/sesion/direccion/año/regimen, veredicto §11 criterio por criterio, stress ×1.5, concentracion). Optimizacion: al regimen se le pasa solo su ventana de cola -> replay O(n).
- **S5** — `trend_following_d1`: estrategia Donchian D1 nueva, **hipotesis CONGELADA antes de mirar la data** (anti data-dredging). Salida trailing Donchian close-confirmada (extiende el simulador con `close_exit_fn`).

**Veredicto del run Modo A real (8 simbolos D1, decadas de historia):**
- Las 4 estrategias existentes **NO PASAN** §11: `mean_reversion` -0.123R, `momentum` -0.004R, `breakout` n=15. `forex_session_breakout` no dispara en D1 (`macro=None`, B11).
- `trend_following_d1`: avg +4.7R que **parece un edge enorme pero es un ARTEFACTO** — un solo trade de +3724R sobre data sintetica pre-1999 de USDCHF carga el 91% del P&L (mediana real -1.03R, GBPUSD -0.26R). El veredicto §11 lo rechaza correctamente (drawdown 57.5R > 25R, consistencia 58% < 60%), y la nueva metrica de **concentracion** del reporte lo grita. **NO PASA. NO se promueve a Modo B.** Exactamente para lo que existe el harness: atrapar el falso positivo seductor en vez de creerle.

Lo correcto cuando una hipotesis no pasa es documentarlo, no ajustar hasta que pase. El edge no esta en estas estrategias sobre D1; el camino sigue (COT, instrumentos descorrelacionados) en `MAPA_DE_EDGE_Y_RUTA.md`.

572 -> **657 verdes**. app_version -> v3.6.0. `.env.example` con el bloque del harness. El backtest abre la puerta de PAPER, nunca la de MT5.

## Trading Alert AI v3.5.0

Proteccion de capital: calendar gate + cap de exposicion USD. Las DOS lecciones del 10-jun-2026 (CPI 12:30 + BOC 13:45): el bot abrio USDCAD 18 min antes de un rate statement que estaba en su propia DB, y tenia 7 posiciones forex que eran UNA SOLA apuesta (long-USD) — un movimiento del dolar las stoppeo juntas (~-7R). Ambos gates son downward-only (solo bajan a paper-only, jamas habilitan), opt-in OFF, soft-fail total.

**Calendar gate (arregla un BUG de integracion).** `is_safe_window` (calendar_filter) existia y el colector llenaba `economic_events`, pero NADIE lo llamaba — `CALENDAR_BUFFER_MINUTES` no hacia nada. Ahora:
- `jobs._calendar_gate` + hook en `_try_prepare_demo_order` (tras el ensemble veto): no ejecuta a MT5 si hay un evento high-impact de la(s) moneda(s) del par dentro del buffer.
- Hook tambien en `scalping_engine._open_scalping_trade` (un spike de noticia mata un scalp de 6 pips al instante).
- `calendar_filter.currencies_for_symbol` ahora parsea pares genericos: `EURUSD` (formato MT5 del scalping) y `EURUSD=X` (Yahoo) -> {EUR, USD}. Antes el formato MT5 caia al default {USD} y perdia eventos de la otra moneda.
- Flag `ENABLE_CALENDAR_GATE=false`; requiere `ENABLE_ECONOMIC_CALENDAR=true` (la fuente).

**Cap de exposicion neta USD.** `app/risk/exposure.py` (NUEVO, puro): `usd_direction` (+1 long-USD / -1 short-USD / 0 sin pata USD), `net_usd_exposure`, `would_exceed_cap` (solo bloquea concentracion ADICIONAL: reducir el neto siempre pasa; en el cap exacto pasa).
- `jobs._usd_exposure_gate` + hook en `_try_prepare_demo_order`: bloquea ejecutar un candidato que deje |neto| > cap, contando solo abiertos forex YA ejecutados a MT5.
- Comando `/exposicion` (aliases `/exposure`, `/usd`): neto actual + detalle por posicion + estado del gate.
- Flags `ENABLE_USD_EXPOSURE_CAP=false`, `MAX_NET_USD_EXPOSURE=3`.

- Settings sincronizados en `test_score`/`test_alert_rules`. app_version -> v3.5.0. `.env.example`.
- `tests/test_exposure.py` (+17: direccion USD por tipo de par, neto, cap (bloquea concentracion / permite reducir / cap exacto / simetrico short / sin pata USD), parsing de simbolos MT5, gates de jobs (off-por-default, bloqueo, soft-fail), comando).

554 -> **572 verdes**. Ningun gate puede causar un order_send: solo prevenirlo. Real-money sigue HARDCODED bloqueado.

## Trading Alert AI v3.4.0

Exit shadow: mide HONESTO si un trailing stop mejoraria las salidas, sin tocar ninguna salida real. Motivado por un hallazgo concreto: en `lifecycle_manager`, los trades de forex/oro caen al `else` y usan los params de trailing de MEMECOIN (activacion +50%), que en forex NUNCA se alcanza -> forex/oro **no tienen trailing efectivo** y devuelven ganancia (capture ratio ~0.68; 24% de winners devuelven >=1R desde el pico).

En vez de adivinar una distancia (o creerle al "techo" optimista que con solo mfe/mae ignora recuperaciones), el shadow registra el camino REAL de R de cada trade abierto cada ciclo y simula el trailing sobre ese camino, exitando en el PRIMER giveback. Asi el numero es honesto (captura el downside de cortar runners). SOLO medicion / opt-in OFF / soft-fail.

- `app/learning/exit_shadow.py` (NUEVO): `simulate_trailing_exit(r_path, distance, activation)` (pura: exita en el primer giveback, maneja recuperaciones), `compare_trailing(paths, distances)` (actual vs trailing, con counts de mejora/empeora), `record_open_trade_samples` (captura por ciclo) y `analyze_closed_trades` (reconstruye caminos y compara).
- `db.py`: tabla `trade_r_samples` (+indice). `repository.py`: `insert_r_sample`, `fetch_r_path`, `prune_r_samples`.
- `jobs._maybe_record_exit_shadow` + hook en `run_once` (tras lifecycle, latest_price fresco) + poda diaria de muestras > 7 dias. `command_handler`: comando `/exit_analysis` (aliases `/salidas`, `/trailing`).
- Settings: `ENABLE_EXIT_SHADOW=false`. Sincronizado en `test_score`/`test_alert_rules`. app_version -> v3.4.0.
- `tests/test_exit_shadow.py` (+14: simulacion (giveback/runner/loser/activacion), compare, captura, analisis, comando on/off, y el fix de salida real).
- Fix pre-merge: `analyze_closed_trades` anexa el R realizado VERDADERO del trade al camino (la ultima muestra era del ultimo ciclo abierto; un stop intra-ciclo podia diferir y sesgaba la comparacion actual-vs-trailing).
- Fixes del code review (2 revisores independientes, pre-merge): (1) la poda ahora es por `closed_at` del trade (>7 dias cerrado) — podar por `recorded_at` decapitaba el camino (perdia el pico) de trades longevos, justo lo que el shadow mide; (2) `activation=1.0R` en el analisis — con activation=0 la simulacion "mejoraba" perdedores con un stop mas apretado inimplementable e inflaba el delta; (3) excluye scalps (3 min de vida, poblacion distinta) y partial-close (R blended a media pendiente = unidades mezcladas; ademas ya tienen breakeven); (4) excluye caminos que arrancan a mitad de vida (|primera muestra|>0.5R: pico previo no registrado); (5) el mensaje de /exit_analysis declara el metodo (activation, exclusiones, fill asumido en el trail — gaps reales pueden ser peores). En el collector Gecko (v3.3.1): tope de staleness 30 min para el stale (bajo 429 sostenido, mejor [] que reciclar precios congelados como frescos), cache key por (chain, network) (evita mislabel con alias de chain), y new_pools sirve stale ante payload vacio (simetria de soft-fail). +6 tests.

534 -> **554 verdes**. Shadow read-only: no cambia ninguna salida ni ejecucion; real-money sigue HARDCODED bloqueado.

## Trading Alert AI v3.3.1

Caché + cooldown 429 para las listas de GeckoTerminal (saca el spam de "Too Many Requests" y acelera el ciclo). El collector pegaba a la API de memecoins cada ciclo (4 chains x trending + new_pools = 8 llamadas), y las listas no tenian manejo de 429 (solo el OHLCV lo tenia) -> reintentaba cada ciclo y se comia el rate limit. Como las pools trending no cambian cada 2-3 min, ahora se cachean.

- `app/collectors/geckoterminal_collector.py`: caché TTL en memoria (`LIST_CACHE_TTL_SECONDS=300`) por (endpoint, network) para trending y new_pools -> dentro del TTL sirve del caché sin pegarle a la API. En 429, un cooldown corto (`LIST_429_COOLDOWN_SECONDS=120`) deja de reintentar y **sirve el ultimo valor conocido** (stale) en vez de `[]`, evitando el spam de warnings. Helpers `_fresh_cached_list`/`_stale_cached_list`/`_note_list_http_error`. Sin settings nuevos (constantes de modulo) ni deps nuevas.
- `tests/test_geckoterminal_new_pools.py` (+2: el 2do ciclo dentro del TTL no re-pega a la API; un 429 sirve el caché stale y arma cooldown). Los 4 tests previos del collector siguen verdes.

app_version -> v3.3.1. 532 -> **534 verdes**. Read-only sobre mercados; real-money sigue HARDCODED bloqueado.

## Trading Alert AI v3.3.0

Performance desde un baseline limpio + comando `/performance`. El balance demo cayo ~11% sobre todo por el periodo buggeado de mayo (feedback-loop / instant-kill / posiciones huerfanas, ~746 artifacts entre el 22 y 28 de mayo, corregidos en v2.6.7-v2.7.1). Esto NO altera ni falsea el balance real; agrega una metrica que mide el % REALIZADO de los trades que de verdad se ejecutaron a MT5 demo (con `demo_order='sent'`) y no son artifacts, desde una fecha baseline configurable -> para ver la cuenta limpia del bug. Honesto por diseño: el re-baseline solo recorta el periodo medido, NO inventa edge (el mensaje lo dice explicito).

Hallazgo (read-only sobre la DB viva): limpio de artifacts, los trades ejecutados suman ~-2% desde el inicio (no -11%); desde el baseline 2026-06-03 la cuenta esta +0.17% (plana, levemente positiva) sobre 16 trades. El R se ve fuerte (+16.7R, 69% WR) pero el impacto real es plano: lotes chicos + el mismo libro short de un regimen. Muestra chica: NO prueba edge.

- `app/portfolio/performance.py` (NUEVO): `performance_since(trades, baseline_iso, executed_ids, balance, cost_pct_by_category)` -> `PerformanceSummary`. Pura/testeable. Filtra: cerrados, ejecutados a MT5 (en `executed_ids`), no-artifact, `closed_at >= baseline`. `net_r`/win-loss usan R realizado NETO de costos; `account_pct` usa el retorno final almacenado * `size_notional` / balance (misma metodologia que `realized_pnl_today` v2.7.1).
- `app/database/repository.py`: `fetch_executed_paper_trade_ids()` (set de paper_trade_id con demo_order 'sent').
- `app/assistant/command_handler.py`: `performance_message()` + dispatch `/performance` (aliases `/rendimiento`). Reusa `_cost_map_from_settings`.
- Settings: `PERFORMANCE_BASELINE_DATE=2026-06-03` (default; ~4 dias post-correccion, configurable; vacio = desde el inicio). Sincronizado en `test_score`/`test_alert_rules`. app_version -> v3.3.0.
- `tests/test_performance.py` (+9: filtro por baseline, exclusion de no-ejecutados y artifacts, win/loss y R neto, account_pct USD, baseline vacio, costo reduce R, balance 0 seguro, dispatch + formato del comando).
- **Comando `/readiness`** (aliases `/listo`, `real money`): evaluacion HONESTA y read-only de cuanto falta para operar dinero real. Reporta 5 gates — edge probado, data >=400 con features, performance limpia, sizing para cuenta micro, camino de ejecucion real auditado — y da veredicto (hoy **NO LISTO**: lo que falta es EDGE + DATA, no codigo). NO habilita nada; real-money sigue HARDCODED bloqueado. `repository.count_closed_trades_with_features`. `tests/test_readiness.py` (+5).

515 -> **532 verdes** (incluye +3 de los fixes del code review: ContinuousLearner gateado tambien en enable_llm_advisor + cap por INTENTOS al LLM, y scratch_eps en /performance; +5 de /readiness). Solo medicion read-only; no toca ejecucion ni real-money (`ENABLE_REAL_TRADING=false` hardcoded).

## Trading Alert AI v3.2.0

ContinuousLearner: una leccion razonada por trade cerrado (Fase C del roadmap v3.1). Al cerrar trades, un job de escaneo en `run_once` le pide al LLM local una leccion (por que gano/perdio) y la registra en la tabla nueva `trade_lessons`; agrupa las lecciones por clave (estrategia|categoria|direccion|outcome) y, cuando 10+ comparten clave, **PROPONE** revisar esa combinacion por Telegram. NO aplica ningun cambio: el LLM sigue SUBTRACTIVO, lo mas que hace es proponer para que el humano decida. Read/registro: no toca ejecucion, ni el gate, ni `order_send`, ni real-money. Opt-in OFF + soft-fail total.

- `app/learning/continuous_learner.py` (NUEVO): `ContinuousLearner.run() -> ContinuousLearnerSummary`. Escaneo (no hook inline — hay 4 sitios de cierre distintos, un job desacoplado es mas limpio): toma cerrados no-artifact sin leccion, clasifica win/loss por R realizado, llama `analyze_win`/`analyze_loss`, persiste. Cap por ciclo (`DEFAULT_MAX_PER_CYCLE=3`) acota costo/latencia LLM. Idempotente (UNIQUE `paper_trade_id`). Propuesta deduplicada via `bot_state` (`cl_proposed::{key}`) para no repetir cada ciclo. Soft-fail por trade: uno que falla no descarta el resto.
- `app/intelligence/reasoner.py`: +`analyze_win(trade)` (espejo de `analyze_loss`, solo TEXTO; pide al modelo distinguir 'setup repetible' de 'suerte'). No rompe el invariante de seguridad (no expone metodos de decision).
- `app/database/db.py`: tabla `trade_lessons` (+ indice `idx_trade_lessons_key`) via el `CREATE TABLE IF NOT EXISTS` del schema. `app/database/repository.py`: `insert_trade_lesson` (idempotente), `fetch_trade_lesson_ids`, `count_trade_lessons_by_key`, `fetch_trade_lessons`.
- `app/scheduler/jobs.py`: `_maybe_run_continuous_learner` (espeja el wiring del processor del resumen diario) + hook en `run_once` tras el resumen diario. Soft-fail total.
- Settings: `ENABLE_CONTINUOUS_LEARNER=false` (default) + `STORE_TRADE_LESSONS=true`. Requieren AMBOS para correr (sin corpus persistido no hay agrupacion ni propuestas). La leccion requiere `enable_llm_advisor`. Sincronizados en `test_score`/`test_alert_rules`. app_version -> v3.2.0.
- `tests/test_continuous_learner.py` (+13: gating por los dos flags, win->analyze_win / loss->analyze_loss, exclusion de artifacts y ya-procesados, soft-fail sin texto, cap por ciclo, propuesta al umbral + dedupe, invariante sin ejecucion) + `test_reasoner.py` (+1: `analyze_win`).

501 -> **515 verdes**. Cierra la Fase C del roadmap v3.1. El LLM sigue subtractivo (solo registra/propone); real-money 100% bloqueado (`ENABLE_REAL_TRADING=false` hardcoded).

## Trading Alert AI v3.1.0

Resumen diario por Telegram al cierre NY (Fase B p3 — ultima pieza de Fase B). 1x/dia, tras la hora de corte (UTC), manda los trades del dia (cerrados no-artifact: ganados/perdidos/R neto) + una leccion via LLM local si el asesor esta on. Read-only, opt-in OFF, soft-fail; los numeros se mandan aunque Ollama este apagado.

- `app/scheduler/jobs.py`: `_maybe_send_daily_summary` (gate por fecha en bot_state, sobrevive reinicios) + `_today_trade_stats` + `_format_daily_summary`. Hook en `run_once`. No toca ninguna decision ni orden.
- `app/intelligence/reasoner.py`: +`daily_summary(stats)` (lectura del dia + 1 leccion; solo texto, requiere `enable_llm_advisor`).
- Settings: `ENABLE_DAILY_SUMMARY=false` (default) + `DAILY_SUMMARY_HOUR_UTC=21`. Sincronizados en `test_score`/`test_alert_rules`. app_version -> v3.1.0.
- `tests/test_daily_summary.py` (+9).

492 -> **501 verdes**. Cierra la Fase B del roadmap v3.1 (asesor + comandos + veto + resumen). Real-money 100% bloqueado.

## Trading Alert AI v3.0.0

Arranca la serie **v3** (salto deliberado desde v2.12.0): primera capa donde el LLM influye sobre el demo gate, siempre de forma SUBTRACTIVA. Veto del ensemble LLM en el gate (Fase B p2 del roadmap v3.1). Resuelve la contradiccion del plan v3.0 original (que tenia al LLM dando "luz verde"): aca el LLM **solo puede vetar**, jamas habilitar.

DOS modelos locales (primario + 2da opinion) evaluan si hay una RED FLAG en un trade que las reglas YA aprobaron. Si CUALQUIERA marca red flag -> el trade baja a paper-only (sin order_send a MT5). Subtractivo por construccion: se invoca DESPUES de reglas + promotion gate + ML gate, asi que solo puede bloquear.

- `app/intelligence/ensemble_gate.py` (NUEVO): `ensemble_veto(settings, context, processor) -> (veto, reason)`. Soft-fail total -> NO veta si el flag esta off, no hay processor LLM, o todos los modelos fallan/responden ambiguo. Cada modelo se evalua aislado (el error de uno no descarta el flag del otro); dedupe si primario==segundo.
- `app/scheduler/jobs.py`: `_llm_ensemble_gate(paper_trade)` (espejo del `_ml_gate`, downward-only, soft-fail) + hook en `_try_prepare_demo_order` DESPUES del ML gate. NO toca `mt5_demo_trader.py`.
- `app/intelligence/ollama_processor.py`: `_call`/`generate` aceptan `model` (override para la 2da opinion); el cache key ahora incluye el modelo.
- Settings: `ENABLE_LLM_ENSEMBLE=false` (default; requiere `ENABLE_OLLAMA_INTEGRATION`) + `OLLAMA_SECOND_MODEL=mistral`. Sincronizados en `test_score`/`test_alert_rules`. app_version -> v3.0.0 (salto de v2.12.0; arranca serie v3).
- `tests/test_ensemble_gate.py` (+15): parsing SI/NO, subtractivo, soft-fail, veto por cualquiera, aislamiento por modelo, dedupe, y el hook de jobs (allow/veto/soft-fail).

477 -> **492 verdes**. El LLM y el ML siguen subtractivos: jamas ejecutan nada. Real-money 100% bloqueado.

## Trading Alert AI v2.12.0

Comandos Telegram `/market` y `/porque_perdi`: la capa LLM asesora (v2.11.0) ahora es usable desde Telegram. Read-only, solo texto, gating por `ENABLE_LLM_ADVISOR`, soft-fail total (si Ollama esta off o no responde -> mensaje claro, el bot sigue igual). Parte read-only de la "Fase B" del roadmap v3.1.

- `/market` (mercado, /mercado): evaluacion honesta del mercado del dia via `TradingReasoner.assess_market`, con macro de `full_macro_context` (sesiones activas + vix/dxy del ultimo `macro_snapshot`).
- `/porque_perdi` (por que perdi): post-mortem del ultimo `paper_trade` cerrado no-artifact con R<0 via `analyze_loss`, incluyendo `rsi_entry`/`atr_value` del entry (capturados en v2.11.0).
- `BasicTelegramAssistant`: +param opcional `reasoner` (lazy `TradingReasoner`, inyectable en tests) + metodos `market_message`, `loss_review_message`, `_last_losing_trade`.
- `tests/test_market_commands.py` (+7): gating por flag, soft-fail (None -> mensaje), y que el contexto correcto (incl. features del entry) llega al reasoner.

470 -> **477 verdes**. El LLM sigue read-only: no decide ni ejecuta nada. Real-money 100% bloqueado.

## Trading Alert AI v2.11.0

Captura de features tecnicos al entry (desbloquea el ML) + capa LLM asesora (read-only). Dos pasos hacia la vision "v3" (IA local potente), ambos additivos, soft-fail y opt-in OFF; el sistema corre identico si estan apagados.

**Fase 0 — `rsi`/`atr`/`macd` persistidos al abrir el swing trade.** Hasta ahora el ML los recibia NaN (no se persistian); el `ml_dataset_builder` lo documentaba como "proximo paso de mayor valor".
- `app/database/db.py`: 4 columnas nuevas nullable en `paper_trades` (`rsi_entry`, `atr_value`, `macd_value`, `macd_signal_value`) via el patron idempotente `_ensure_column`. NULL para trades viejos (no retroactivo), scalping (su `ScalpingSignal` es frozen) y memecoins/alertas reconstruidas (sin velas).
- `app/database/repository.create_paper_trade`: persiste los 4 con `.get()` (backward-compatible con todos los callers/tests).
- `app/scheduler/jobs._try_open_paper_trades`: los llena desde el `TechnicalPattern` ya calculado (path live forex/gold/stock — la categoria que ejecuta al demo gate). `atr_value` = ATR en % (normalizado entre simbolos).
- `app/learning/ml_dataset_builder.py`: lee los valores reales y deriva un `macd_state` REAL (macd vs signal) con fallback al proxy del alert para trades viejos. +2 tests.

**Fase A — `TradingReasoner` (capa LLM asesora, read-only).** Construye sobre `OllamaProcessor`; solo produce TEXTO en lenguaje natural. NO decide ni ejecuta trades.
- `app/intelligence/reasoner.py` (NUEVO): `assess_market` (evaluacion del dia), `analyze_loss` (post-mortem de perdida), `explain_setup` (explica un setup). Todos devuelven `str | None`. Soft-fail total (advisor off / Ollama caido / respuesta invalida -> None).
- `app/intelligence/ollama_processor.py`: +`generate()` (primitiva publica de texto, reusa throttle/cache/soft-fail de `_call`).
- Setting `ENABLE_LLM_ADVISOR=false` (default; requiere `ENABLE_OLLAMA_INTEGRATION=true`). Sincronizado en `test_score`/`test_alert_rules` `_settings()`.
- `tests/test_reasoner.py` (+11), incluido `test_safety_invariant_advisor_exposes_no_decision` que falla si alguien le agrega un metodo de decision/ejecucion al asesor.

Total 457 -> **470 verdes**. El LLM y el ML siguen SUBTRACTIVOS: jamas ejecutan nada. Real-money sigue 100% bloqueado (`ENABLE_REAL_TRADING=false` hardcoded).

Roadmap completo en `Trading Alert AI v3.1 Plan Arquitectura MEJORADO.md` (resuelve la contradiccion del plan v3.0 original: LLM/ML = veto, nunca luz verde).

## Trading Alert AI v2.10.0

Proveedor LLM **local via Ollama** (gratis, sin API key) como alternativa a Claude.

El LLM del bot (resumen de noticias, expansion del analisis pro, interpretacion de free-text en Telegram) **solo enriquece TEXTO — NO toca ninguna decision de trading** (ni gate, ni router, ni ordenes). Hasta ahora era Claude API (opcional, default OFF). v2.10.0 agrega un proveedor local: gratis, privado, sin API key, sin costo diario.

**`app/intelligence/ollama_processor.py` (NUEVO).**
- `OllamaProcessor`: misma interfaz que `ClaudeProcessor` (`reset_cycle`, `is_available`, `summarize_news`, `expand_pro_analysis`, `interpret_free_text`, `estimated_cost_today`=0). Habla con Ollama por HTTP local (`POST /api/chat` en `OLLAMA_BASE_URL`, default `http://localhost:11434`). Throttle por ciclo + cache TTL. **Cero dependencias nuevas** (usa `requests`).
- Soft-fail total: si `enable_ollama_integration=False`, si Ollama no responde, o si la respuesta es invalida -> `None` (el bot se comporta igual que sin LLM). Reachability cacheada (ping a `/api/tags`, 60s).
- `build_llm_processor(settings, repo)`: factory que devuelve `OllamaProcessor` si `enable_ollama_integration`, sino `ClaudeProcessor`. Comparten interfaz (duck-typing); el resto del bot no cambia. Wire en `jobs.py` (un solo call site).

**Settings nuevos.** `ENABLE_OLLAMA_INTEGRATION=false`, `OLLAMA_MODEL=llama3.1`, `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_TIMEOUT_SECONDS=30`, `OLLAMA_CALLS_PER_CYCLE_CAP=6`. Sincronizados en `test_score`/`test_alert_rules` `_settings()`.

**Para usarlo** (lado del user): instalar Ollama (ollama.com), `ollama pull llama3.1`, dejar el servicio corriendo, y poner `ENABLE_OLLAMA_INTEGRATION=true` en el `.env`. Sin eso, soft-fail = bot igual que antes. Nota honesta: un modelo local chico da menor calidad que Claude y corre mas lento en CPU; esto es UX/comodidad, no edge.

**Tests (`tests/test_ollama_processor.py`, +10).** flag off -> no disponible; reachable -> disponible; Ollama caido -> soft-fail; `_call` OK; soft-fail por excepcion/HTTP error; throttle cap; costo=0; factory elige proveedor. Mock de `requests` (no necesita Ollama corriendo).

Total 447 -> **457 verdes**. Read-only para mercados: el LLM jamas ejecuta nada. Real-money sigue 100% bloqueado.

## Trading Alert AI v2.9.1

Toggle para analizar acciones sin alertarlas (`ENABLE_STOCK_TELEGRAM`).

El user pidio dejar de recibir las alertas de "top 5 acciones" en Telegram pero que el bot las siga analizando y aprendiendo (era ruido, no plata: Claude API esta OFF por default). El flag existente `ENABLE_STOCK_ALERTS` no servia: controla la RECOLECCION (`stock_collector.collect` retorna `[]` si esta off → deja de analizar).

**Nuevo flag `ENABLE_STOCK_TELEGRAM` (default true)** que separa el envio del analisis:
- `app/analyzers/alert_decision_engine.should_send_alert`: para `category=="stock"`, si `not enable_stock_telegram` → `False` (no candidato a Telegram). El analisis y los paper_trades NO dependen de esto (ocurren siempre en `jobs.run_once`).
- `app/scheduler/jobs._send_ranked_candidates`: `"stock"` solo entra a `cats` si `enable_stock_telegram` (defensa en profundidad, mismo patron que `enable_memecoin_telegram`).
- NO toca `enable_trade_action_reports`: los avisos de apertura/cierre de trades siguen intactos.

Para el comportamiento pedido, en el `.env`: `ENABLE_STOCK_TELEGRAM=false` y `ENABLE_MEMECOIN_TELEGRAM=true`.

Tests: +2 (`test_stock_blocked_when_telegram_off`, `test_memecoin_unaffected_by_stock_telegram_flag`). Total 445 → **447 verdes**. Real-money sigue 100% bloqueado.

## Trading Alert AI v2.9.0

Capa ML hibrida (XGBoost) que COMPLEMENTA las reglas, no las reemplaza. Predice probabilidad de win de un trade y modula el promotion gate como señal adicional. Filosofia identica al gate: solo filtra HACIA ABAJO, nunca habilita lo que las reglas bloquearon. Soft-fail/degradado = comportamiento idéntico al sistema actual.

**Encuadre honesto.** Con 189 trades reales limpios el ML NO crea edge — es andamiaje listo para cuando haya data. Por eso nace DORMIDO: `ENABLE_ML_PREDICTOR=false` por default, y aun activo solo modula decisiones con n>=`ML_GATE_MIN_SAMPLES` (400). Ademas, verificado contra el schema: `rsi_entry`/`atr_value` NO se persisten hoy (quedan NaN); `macd_state` es un proxy categorico desde el alert. El modelo se apoya en macro (vix/dxy), temporales (sesion/hora/dia) y las features del alert (ia_pro, patrones, volumen). Para features tecnicas reales habria que capturarlas al crear el trade (cambio futuro, no retroactivo).

**ml_dataset_builder.py.** Lee paper_trades + macro_snapshots (join temporal vix/dxy via merge_asof) + alerts (feature_extractor). Reusa la quarantine de artifacts y el realized-R de v2.7.0, asi el target cuadra con /expectancy. Cada fila = un trade cerrado no-artifact con features al entry + win_loss (1 si r_multiple>0). Excluye scratch. Exporta exports/ml_dataset.csv y retorna DataFrame. `build_live_features` arma las features de un trade vivo (DRY). Solo depende de pandas.

**ml_predictor.py.** Clase `MLPredictor`: train (XGBClassifier max_depth=5, lr=0.1, n_estimators=100, subsample=0.8, eval_metric=auc; split temporal train-pasado/test-futuro sin look-ahead; AUC via sklearn.roc_auc_score), predict (0-1; 0.5 neutral en modo degradado), feature_importance (top5), save/load (pickle, models/xgboost_v1.pkl), get_status, retrain_if_needed (reentrena con >=20 trades nuevos; si el AUC cae >0.05 MANTIENE el modelo anterior). Modo degradado/soft-fail en todos los caminos: <100 muestras, sin modelo, libs ausentes o cualquier excepcion -> 0.5 sin crashear. `ml_gate_decision` (>0.65 pasa; 0.50-0.65 pasa con lot/2; <0.50 paper-only) y `should_consult_ml` (guard: solo modula con muestra suficiente).

**Integracion en el promotion gate (jobs._try_prepare_demo_order).** Tras el gate de reglas, si el ML esta activo y con muestra suficiente, consulta predict() y aplica ml_gate_decision: bloquea a paper-only, o reduce el lot a la mitad (modificando solo el draft, sin tocar mt5_demo_trader.py). Si esta dormido/degradado/falla: (allow, low)=(True, False) = sin cambios. Reentrenamiento diario en run_once (gate por fecha UTC). `/ml_status` muestra version, modo (activo/dormido), muestras, AUC, top5 features y la distribucion de decisiones del dia (passed/low/blocked, contadores en bot_state).

**Dependencias (aprobadas).** `xgboost==3.2.0`, `scikit-learn==1.9.0` (pinneadas). Soft-fail si no estan instaladas.

**Settings nuevos.** `ENABLE_ML_PREDICTOR=false`, `ML_MIN_TRAIN_SAMPLES=100`, `ML_GATE_MIN_SAMPLES=400`, `ML_RETRAIN_MIN_NEW_TRADES=20`, `ML_CONF_PASS=0.65`, `ML_CONF_LOW=0.50`. Sincronizados en test_score/_settings y test_alert_rules/_settings.

**Tests (+22).** `tests/test_ml_dataset_builder.py` (11: exclusion de artifacts, target, sesion/tiempo, join macro, proxy macd, rsi/atr NaN, scratch, CSV, coverage) y `tests/test_ml_predictor.py` (11: modo degradado <100, AUC valido, predict en rango, features faltantes, save/load identicas, feature_importance, soft-fail sin entrenar, revert por AUC, thresholds del gate, guard should_consult_ml, /ml_status desactivado). `models/` y `exports/` agregados a .gitignore.

Total 423 → **445 tests verdes**. Real-money trading sigue 100% bloqueado; el ML jamas puede causar un order_send, solo prevenirlo.

## Trading Alert AI v2.8.0

Edge Detection & Protection Layer: automatiza la búsqueda de edge por slice (sesión / dirección) y extiende el promotion gate a ese nivel. NO crea edge — construye la maquinaria que lo detecta de forma permanente y rigurosa, y protege capital cuando un slice prueba perder.

**El research que la motivó.**

Análisis read-only de los 189 paper_trades reales (post-Fix-A, excluyendo ~776 artifacts) sliceados por sesión y dirección: NINGÚN bolsillo +R es estadísticamente sólido (los positivos tienen n=4-17, por debajo del umbral de confianza). Hallazgos: forex_session_breakout ya opera 43/44 en la franja Londres-NY (filtrar sesión no le sirve, ya está concentrada) y tiene sesgo direccional fuerte (longs -0.55R n=40 vs shorts +0.64R n=4, este último ruido). Conclusión honesta: no hay filtro de edge para codificar hoy sin sobreajustar; el cuello de botella es muestra limpia. Por eso v2.8.0 no codifica un filtro adivinado, sino la herramienta que mide y deja decidir a la data.

**Componente A — medición sliceada (default ON, no toca ejecución).**

- `app/learning/trade_outcomes.py`: `session_of(opened_at)` (franjas UTC no solapadas: Asia 00-07, London 07-12, LDN-NY 12-16, NY 16-21, Off 21-00), `build_sliced_performance()` (una fila por estrategia×categoría×dimensión×bucket, reusando EXACTO el mismo realized-R neto de costos y la exclusión de artifacts que `build_strategy_performance`, así los números cuadran al re-agregar).
- Tabla nueva `strategy_performance_sliced` (PK strategy_name+category+dimension+bucket), refrescada cada learning cycle vía `_refresh_sliced_performance` (training_engine).
- Comando Telegram `/edge` (aliases `/borde`, `bolsillos`): muestra los slices por sesión y dirección, marca `[OK]` los confiables (n>=`EDGE_SLICE_MIN_SAMPLES`) y resalta `EDGE+` los que además son +R. Convierte el research manual en capacidad permanente.

**Componente B — promotion gate sliceado (default OFF, opt-in).**

`should_execute_live_sliced()` es estrictamente MÁS restrictivo que `should_execute_live`: bloquea (SHADOW) si el agregado O cualquier slice del trade en curso (su sesión y su dirección) prueba edge negativo (avg_r<=umbral con n>=min_samples). Hooks en `jobs._try_prepare_demo_order` (swing) y `scalping_engine._open_scalping_trade` (scalping), detrás de `ENABLE_SLICED_PROMOTION_GATE` (default OFF — el gate v2.7.0 sigue idéntico hasta activarlo).

**Regla anti-data-dredging (el rigor que evita el autoengaño).**

El slicing SOLO puede mover a SHADOW, NUNCA promover. Un slice +R jamás rescata a un agregado SHADOW. Cortar en muchos slices garantiza que alguno dé +R por azar (multiple comparisons); usar muchos tests para hallar PERDEDORES es conservador (protege capital), usarlos para hallar GANADORES invitaría falsos positivos. Por eso el gate sigue siendo estrictamente subtractivo: jamás causa un order_send, solo puede prevenirlo.

**Settings nuevos.**

- `ENABLE_EDGE_SLICING=true` (medición ON).
- `EDGE_SLICE_MIN_SAMPLES=30` (umbral de confiabilidad).
- `ENABLE_SLICED_PROMOTION_GATE=false` (gate sliceado opt-in).

**Tests (`tests/test_edge_slicing.py`, +21 casos).**

session_of (límites de franja, naive, inválido), build_sliced_performance (agrupación, exclusión de artifacts, costos, consistencia de re-agregación vs build_strategy_performance), should_execute_live_sliced (agregado SHADOW manda, slice perdedor con n>=min manda a SHADOW, slice chico respeta el agregado, slice +R no rescata, sin slices == gate base), repository upsert/fetch sliced, `_refresh_sliced_performance` (puebla + respeta el flag OFF), comando /edge (aliases, sin-datos, con-datos, soft-fail). Settings sincronizados en `tests/test_score.py` y `tests/test_alert_rules.py`.

Total 402 → **423 tests verdes**. Real-money trading sigue 100% bloqueado.

## Trading Alert AI v2.7.1

Tapa el kill switch falso del 2026-06-01: `realized_pnl_today` ahora filtra paper_trades que nunca se ejecutaron a MT5 demo.

**El bug.**

Paper trades de gold con `symbol=GC=F` (formato Yahoo) nunca matcheaban `DEMO_ALLOWED_SYMBOLS` (que tiene `XAUUSD`/`GOLD` post-yahoo_to_mt5, no `GC=F`), entonces NO se ejecutaban a MT5. Su `size_notional` quedaba con el sizing TEORICO del position_sizer (~$184k para gold con `ACCOUNT_STARTING_BALANCE=1M`). Dos trades gold con -1% cada uno → `realized_pnl_today` decia -3.20% drawdown → kill switch falso disparaba, cuando el daño real al balance MT5 era cero (nada habia ejecutado).

Variante del mismo patron que el bug del 27-may, pero esta vez con paper-only en vez de notional inflado teorico vs MT5 real. v2.6.8 tapaba el caso forex (POST-demo_order recalcula notional con MT5 real); v2.7.1 tapa el caso paper-only filtrandolos del calculo.

**Fix.**

- `Repository.has_successful_demo_order(paper_trade_id) -> bool`: True si hay al menos un demo_order con `status='sent'` vinculado al paper_trade.
- `PortfolioManager.realized_pnl_today()`: agrega filtro `if not repository.has_successful_demo_order(t.id): continue`. Trades paper-only quedan excluidos del calculo USD.

Semantica corregida: `realized_pnl_today` ahora representa correctamente "USD impact en el balance MT5 demo" (no "suma de paper PnL teorico").

**Tests (`tests/test_portfolio_manager.py`, +5 casos).**

- `_seed_closed_trade` helper extendido con `executed_to_mt5: bool = True` (default seedea demo_order para preservar tests existentes).
- `test_realized_pnl_today_excludes_paper_only_trades`: gold $184k notional sin demo_order → 0% (era el bug).
- `test_realized_pnl_today_includes_executed_trades`: forex $10k con demo_order → -0.1% normal.
- `test_realized_pnl_today_mixed_executed_and_paper_only`: mix realista (gold paper-only excluido, forex contado).
- `test_has_successful_demo_order_returns_false_when_no_order`.
- `test_has_successful_demo_order_returns_true_when_order_sent`.

Total 397 → **402 tests verdes**.

**Cambios menores.**

- `app/config/settings.py` + `.env.example`: bump v2.7.0 → v2.7.1.

Real-money trading sigue 100% bloqueado.

## Trading Alert AI v2.7.0 (branch claude/xenodochial-taussig-4206c6 — sin merge a main)

Medición honesta del P&L realizado + gate de promoción que protege capital. Surge del análisis cuantitativo de los paper_trades: el motor de aprendizaje medía la cosa equivocada y ~86% del historial eran artifacts del feedback-loop.

**Hallazgo raíz (Fix A).**

`training_engine._update_paper_trades` era LONG-ONLY (`if latest <= stop`). Para un SHORT el stop está POR ENCIMA del entry, así que la condición se cumplía apenas se creaba el trade → cada short se marcaba `stopped_simulated` en el MISMO ciclo (vida ~12s, precio congelado en entry). Corría junto a `lifecycle_manager.manage_open_positions` (direction-aware) = doble-management conflictivo. Resultado: 86% del historial (forex/gold shorts) eran artifacts, no trades reales. Ahora es direction-aware: mata el instant-kill → los trades viven su horizonte → el dedup de posiciones abiertas frena el feedback-loop → los precios dejan de congelarse.

**Fix C — precio fresco real para forex/gold.**

`lifecycle_manager._fresh_price` pasaba el símbolo Yahoo crudo (`USDCHF=X`) a `get_tick`, que siempre fallaba → precio stale. Ahora mapea Yahoo→MT5 (`yahoo_to_mt5`) antes del tick.

**Fix D — señal de aprendizaje HONESTA (realized-R).**

Nuevo `app/learning/trade_outcomes.py`: retorno realizado direction-aware (con partial close), riesgo al entry, R-multiple, detección de artifacts (precio congelado) y `build_strategy_performance`. Nueva tabla `strategy_performance` (PK strategy_name+category) refrescada cada ciclo de learning. Comando Telegram `/expectancy`. A diferencia de signal_outcomes (drift de la alerta a horizonte fijo con umbrales absolutos → ~99% 'neutral'), mide el P&L realizado normalizado por riesgo — la única métrica conectada con el crecimiento de la cuenta.

**Promotion gate (shadow mode) — protección de capital.**

Nuevo `should_execute_live()` + 3 settings (`ENABLE_STRATEGY_PROMOTION_GATE` default ON, `STRATEGY_PROMOTION_MIN_SAMPLES`=30, `STRATEGY_PROMOTION_MIN_EXPECTANCY_R`=0.0). Una estrategia NO manda `order_send` a MT5 si tiene expectancy realizada negativa PROBADA (avg_r<=umbral con n>=min_samples). Las no probadas pasan (juntando data); las que demostraron edge negativo quedan paper-only (SHADOW). Hooks en `jobs._try_prepare_demo_order` (swing) y `scalping_engine._open_scalping_trade` (scalping). Filosofía 'inocente hasta probarse culpable'. NO toca la creación de paper_trades ni el real-money (sigue HARDCODED bloqueado).

Default ON porque es un gate restrictivo (reduce riesgo), no una feature que lo agrega. Con la data actual deja `momentum` en SHADOW automáticamente (lo que el user ya hacía a mano) y deja al resto juntar muestra limpia. Visible en `/expectancy` como tag LIVE/SHADOW. Toggle: `ENABLE_STRATEGY_PROMOTION_GATE=false` revierte al comportamiento previo.

**Cost model (spread + comisión) — hace confiable al gate.**

El realized-R se calculaba sobre el movimiento de precio BRUTO, sin descontar costos → optimista vs MT5 real, y el promotion gate podía promover a LIVE una estrategia positiva en bruto pero negativa neta. Ahora `build_strategy_performance` resta un costo round-trip por categoría del retorno de cada trade (siempre resta, gane o pierda). Settings nuevos: `ENABLE_COST_MODEL` (default ON), `COST_ROUNDTRIP_PCT_FOREX`=0.02, `_GOLD`=0.03, `_STOCK`=0.05, `_MEMECOIN`=0.5. `trade_outcomes` se mantiene puro (recibe el costo como parámetro); `training_engine` arma el mapa desde settings. El R en `/expectancy` y en el promotion gate ahora es NETO de costos.

**Fase 2b — learning loop honesto (realized-R en weights + gate).**

`learned_weights` y `learning_gate` aprendían del DRIFT de la alerta a horizonte fijo con umbrales absolutos → ~99% 'neutral', y el gate era inútil (bloqueaba casi todo). Ahora, con `ENABLE_REALIZED_LEARNING` (default ON), aprenden del **P&L realizado** de paper_trades: nueva tabla `realized_feature_lessons` (R por feature, NETO de costos, excluye artifacts) refrescada en cada learning cycle vía `build_realized_feature_lessons` (junta cada paper_trade cerrado → su R → las features del alert linkeado). `apply_learned_weights` y `evaluate_learning_gate` consultan esa señal honesta. **El `learning_gate` ahora SÍ es activable** (bloquea por win_rate realizado probado con n≥min_samples, no por el drift que bloqueaba todo). El drift path queda como fallback reversible (flag off; los tests viejos lo siguen ejercitando). Caveat honesto: con ~120 trades reales repartidos en muchas features, pocas llegan a min_samples → el gate/weights realizados actúan poco hasta que entre más data limpia (testeado explícitamente).

Tests: 357 → 397 (+40). Data histórica NO mutada (la quarantine de artifacts es a query-time).

## Trading Alert AI v2.6.9

Telegram command `/gate_preview` para visualizar qué features bloquearia `ENABLE_LEARNING_GATE=true` antes de flipear el toggle. Permite monitorear evolución de data desde el celular, sin necesidad de scripts ad-hoc.

**Por qué.**

Tras el audit del 2026-05-28 con `.env` conservador, surgió la pregunta de si activar el learning gate (filtro automático de signals con win_rate histórico bajo). El preview reveló que con la data actual (1-2 semanas), el gate bloquearía CASI TODAS las features porque los `OUTCOME_WIN_RETURN_*_PCT` son tan estrictos (memecoin +30%, stock +5%) que muy pocos outcomes cuentan como "wins", incluso features con avg_return positivo.

Ej: `score:80-90` con 10 samples tiene win_rate=0% pero avg_return=+6.70% — la rule es profitable pero el gate la filtraria. Activar el gate ahora destruye el bot.

El comando ayuda a:
1. Verificar el balance bloqueados/pasa antes de activar.
2. Detectar si el set de features pierde diversidad con el tiempo.
3. Validar cuando hay suficiente data para activar con confianza.

**`app/assistant/command_handler.py` — método nuevo.**

`gate_preview_message()` corre `rank_top_strategies()` con los thresholds actuales y para cada feature decide PASS/BLOCK según `enable_learning_gate` semántica:
- `samples < min_samples` → PASS (insuf).
- `win_rate < min_wr` → BLOCK.
- Sino → PASS.

Output incluye: settings actuales, top 15 features con sample/wr/avg_ret/decision, resumen aggregado, warning si bloqueados > pasa.

Aliases: `/gate_preview`, `/preview_gate`, `/learning_gate`, `preview gate`.

Soft-fail: si `rank_top_strategies` tira excepción, devuelve mensaje con clase de error en vez de crashear el assistant.

**Tests (`tests/test_gate_preview_command.py`, 5 casos).**

- Responde a los 4 aliases.
- Muestra settings actuales (transparencia).
- DB vacía → mensaje "no filtraria nada" claro.
- Incluye disclaimer estándar.
- Soft-fail con repository error.

**Cambios menores.**

- `app/config/settings.py` + `.env.example`: bump v2.6.8 → v2.6.9.

Total 352 → **357 tests verdes**. Real-money trading sigue 100% bloqueado.

## Trading Alert AI v2.6.8

Dos fixes adicionales descubiertos en el audit del 2026-05-28 (segundo día con `.env` conservador y reconciler v2.6.7 activo). Balance solo bajó −$114 (vs −$12k del día anterior), pero el audit reveló dos issues estructurales.

**Fix #1 — `size_notional` inflado por sizing teórico (resuelve también el "v2.6.10" bug del realized_pnl_today).**

El `position_sizer.calculate_position_size` usa `ACCOUNT_STARTING_BALANCE=1,000,000` (teórico) cuando MT5 no entrega balance live, y computa notional según `risk_pct × balance / (entry − stop)`. Para una entrada mean_reversion con SL de 7 pips en EURUSD, esto da notional de 10-16 MILLONES de USD. Pero MT5 ejecuta sólo `DEMO_MAX_LOT=0.1` que son ~$11,600 reales.

Esa discrepancia inflaba 100-1000× tres cosas críticas:
- `paper_trade.size_notional` (almacenado en DB).
- `/aprendizaje` y `total_exposure_by_category` (stats agregadas).
- `realized_pnl_today` USD-based: con notional 16M × −0.09% return = −$15k "calculado", cuando el daño REAL fue −$9. Esto disparó kill switch falsos: el 2026-05-28 con balance bajando solo −0.13% el kill switch fired con "−3.18% drawdown".

**Solución (`app/brokers/mt5_demo_trader.py` + hooks en jobs y scalping).**

Después de cada `demo_order` exitoso, recalcula y persiste:
- `size_notional` = volume × contract_size × (entry_price si USD es QUOTE, sino 1).
- `size_units` = volume × contract_size.

Nuevos métodos `MT5DemoTrader.compute_actual_notional_usd()` y `actual_units()` consultan `symbol_info.trade_contract_size` y `currency_base`. El hook `_correct_paper_trade_notional()` está en `TradingAlertJob` (swing auto-confirm) y `ScalpingEngine` (scalping path), llamado inmediatamente tras `create_demo_order`.

Resultado: stats refleja exposure REAL de MT5 (0.1 lot × contract_size × price), no la teórica. `realized_pnl_today` ya no infla kill switches.

**Fix #2 — Per-symbol cooldown anti-feedback-loop.**

El 2026-05-28 el bot abrió **159 USDCHF demo orders en 20 minutos** (~8/min) porque `forex_session_breakout` re-detectaba el mismo setup tras cada SL hit. El `DEDUP_WINDOW_MINUTES=360` protege alertas Telegram pero NO los trades.

**Solución (`app/risk/risk_manager.py` + `app/database/repository.py`).**

- Nuevo setting `STRATEGY_SYMBOL_COOLDOWN_MINUTES` (default `15`). Bajar a `0` para deshabilitar.
- `RiskManager.check_can_open_trade(category, risk_pct, symbol=...)` ahora rechaza si existe un `paper_trade` del mismo símbolo abierto en los últimos N minutos.
- Nueva query `Repository.has_recent_paper_trade_for_symbol(symbol, after_iso)`.
- Caller actualizado en `app/scheduler/jobs.py` para pasar `symbol`.

Scalping no necesita este check porque ya tiene cooldown propio (60s) en `ScalpingBreakoutStrategy` / `ScalpingMeanReversionStrategy`.

**Tests (`tests/test_v268_v269.py`, 14 casos).**

- v2.6.8 (5): `compute_actual_notional_usd` para USD-quote (EURUSD, XAUUSD), USD-base (USDJPY), inputs inválidos; `actual_units` correcto.
- v2.6.9 (9): `has_recent_paper_trade_for_symbol` con/sin match, símbolo vacío, fuera de ventana; `RiskManager` bloquea cooldown activo, permite cooldown=0, permite sin symbol, permite símbolo distinto, permite tras expiración.

**Cambios menores.**

- `app/config/settings.py` + `.env.example`: bump v2.6.7 → v2.6.8.
- `tests/test_score.py` + `tests/test_alert_rules.py`: nuevo kwarg `strategy_symbol_cooldown_minutes=15`.

Total 338 → **352 tests verdes**. Real-money trading sigue 100% bloqueado.

## Trading Alert AI v2.6.7

Tapa el bug arquitectónico de posiciones MT5 demo huérfanas descubierto el 2026-05-27 (gap de −$9,606 entre paper PnL trackeado y balance MT5 real). Cada ciclo del bot, después del lifecycle, un reconciler limpia las posiciones MT5 cuyo paper_trade ya cerró y sincroniza los SL cuando el bot mueve el SL del paper_trade (trailing / breakeven post-TP1).

**El bug.**

Cuando el bot abre una orden a MT5 demo, crea un paper_trade vinculado. Si después el paper_trade cierra por una razón distinta a SL/TP real de MT5 (`closed_by_time`, `closed_force_exit_timeout` scalping, `stopped_simulated` cuando el bot movió SL a breakeven post-TP1 y el precio retrocedió, invalidation exit, etc), la posición MT5 sigue abierta con su SL ORIGINAL. El bot la "olvida" y sigue perdiendo dinero hasta que MT5 mismo hit SL real o intervención manual.

El 2026-05-27 había 117+ órdenes USDCHF/XAUUSD enviadas a MT5 con sus paper_trades ya cerrados. El usuario las descubrió manualmente en MT5 desktop, las cerró, y reveló un gap de ~$9.6k que el bot no trackeaba.

**`app/portfolio/mt5_reconciler.py` (NUEVO).**

`MT5Reconciler.reconcile()` corre cada ciclo. Pipeline:
1. `trader.positions()` — todas las posiciones MT5 abiertas.
2. `repository.fetch_demo_orders_by_tickets()` — bulk lookup de demo_orders por ticket.
3. Para cada posición:
   - Sin `demo_order` matching → ignorar (puede ser trade manual del usuario).
   - Con `demo_order` pero `paper_trade.status != 'open'` → **cerrar posición MT5 (huérfana)**.
   - Con `paper_trade` abierto y SL diferente → **sincronizar SL (sólo TIGHTENING)**.
4. Soft-fail por posición; error en una no afecta el resto. Devuelve `ReconcileSummary` con counts.

Tolerancia SL: `SL_SYNC_TOLERANCE_PIPS=0.5` (no actualiza si diff < 0.5 pip — evita spam de updates por ruido de floating-point).

Reglas de seguridad:
- LONG: sólo actualiza SL si nuevo SL > MT5.sl (tighten arriba). Nunca relaja hacia abajo.
- SHORT: sólo actualiza SL si nuevo SL < MT5.sl (tighten abajo). Nunca relaja hacia arriba.

**`app/brokers/mt5_demo_trader.py` — 2 métodos nuevos.**

- `close_position_by_ticket(ticket: int) -> DemoCloseResult` — cierra UNA posición por ticket. Reutiliza `_close_position()` interno. Validaciones demo-only intactas.
- `update_position_sl(ticket, new_sl, new_tp=None) -> DemoSendResult` — `TRADE_ACTION_SLTP`. Si `new_tp=None`, preserva el TP actual de la posición (MT5 requiere ambos valores). Soft-fail con `order_send` raised.

**`app/database/repository.py` — 3 helpers nuevos.**

- `fetch_demo_orders_by_tickets(tickets) -> dict[ticket -> order_row]` — bulk lookup.
- `fetch_latest_demo_order_for_paper_trade(paper_trade_id) -> order_row | None`.
- `fetch_paper_trade_by_id(trade_id) -> trade_row | None`.

**`app/scheduler/jobs.py` — hook.**

`TradingAlertJob.__init__` construye `self._mt5_reconciler` si `enable_mt5_demo_trading=true`. `run_once()` llama `reconciler.reconcile()` después de `manage_open_positions()` (lifecycle decisions se reflejan en MT5 en el mismo ciclo). Soft-fail.

**Tests (`tests/test_mt5_reconciler.py`, 15 casos).**

- `close_position_by_ticket`: success, not_found, demo off (3 tests).
- `update_position_sl`: success con `TRADE_ACTION_SLTP` correcto y preservación de TP, not_found (2 tests).
- `MT5Reconciler`: demo disabled no-op, no positions, cierra huérfana, sincroniza SL tightening, no relaja LONG, no relaja SHORT, ignora unmatched (manual), soft-fail trader error, no-op cuando SL en sync, dataclass defaults (10 tests).

**Cambios menores.**

- `app/config/settings.py` + `.env.example`: bump v2.6.6 → v2.6.7.

Total 323 → **338 tests verdes**. Real-money trading sigue 100% bloqueado.

## Trading Alert AI v2.6.6

Segunda strategy scalping + refactor del engine a multi-strategy. Cubre el escenario complementario al breakout (mean reversion en rangos laterales) para acumular outcomes scalping en condiciones de mercado donde el breakout fallaría.

**Nueva strategy `scalping_mean_reversion` (`app/strategies/scalping_mean_reversion.py`).**

Counter-trend basada en Bollinger Bands + RSI extremos sobre M1.
- LONG cuando `current_bid <= BB_lower` Y `RSI <= rsi_oversold`.
- SHORT cuando `current_ask >= BB_upper` Y `RSI >= rsi_overbought`.
- BB period=20, std multiplier=2.0 (defaults estándar).
- RSI period=14, SMA-based (sin Wilder smoothing — más simple, suficiente para M1).
- SL/TP en pips fijos reutilizando `SCALPING_SL_PIPS` y `SCALPING_TP_PIPS`. Misma escala de riesgo que breakout permite comparar win rates honestamente.
- Skip mercado plano: si `bb_upper - bb_lower < pip_size`, no opera (sin ventaja vs spread).
- Cooldown 60s post-signal igual que breakout.

**Refactor `ScalpingEngine` para multi-strategy (`app/scheduler/scalping_engine.py`).**

Reemplaza el campo único `self.strategy` por `self.strategies: list` construida en `__init__` según los flags settings. `_evaluate_signal_for_symbol` itera la lista y emite el primer signal no-None (breakout primero, mean reversion como fallback).

- Nuevo helper `_compute_candle_lookback()` calcula el max entre lookback del breakout y `max(BB_period, RSI_period+1)` cuando MR está activo. Garantiza que se fetchean suficientes velas M1 para ambos indicadores en una sola llamada.
- Tests existentes del engine se mantienen verdes: con 11 velas mockeadas, MR(BB20) no tiene closes suficientes y devuelve None inmediato, dejando que breakout dispare como antes.

**7 nuevos settings (`app/config/settings.py` + `tests/test_score.py`).**

- `ENABLE_SCALPING_BREAKOUT` (default `true`) — kill-switch específico para la strategy original.
- `ENABLE_SCALPING_MEAN_REVERSION` (default `true`) — opt-out de la nueva strategy.
- `SCALPING_MR_BOLLINGER_PERIOD` (default `20`).
- `SCALPING_MR_BOLLINGER_STD` (default `2.0`).
- `SCALPING_MR_RSI_PERIOD` (default `14`).
- `SCALPING_MR_RSI_OVERBOUGHT` (default `70`).
- `SCALPING_MR_RSI_OVERSOLD` (default `30`).

`ENABLE_SCALPING_ENGINE` sigue siendo opt-in (default `false`). Los flags por-strategy solo aplican cuando el engine está activo.

**Tests.**

- `tests/test_scalping_mean_reversion.py` (13 tests): signal LONG/SHORT en extremos, no signal mid-band, no signal cuando AND falla, cooldown, candles insuficientes, mercado plano, pip_size inválido, helpers `_bollinger` y `_rsi` correctos.
- `tests/test_scalping_engine.py` (3 tests nuevos): `engine.strategies` registra ambas por default, deshabilita breakout via flag deja solo MR, deshabilitar ambas deja la lista vacía y no opens trades.

Total 307 → 323 tests verdes.

**Cambios.**

- `app/config/settings.py` + `.env.example`: bump v2.6.5 → v2.6.6.

Real-money trading sigue 100% bloqueado.

## Trading Alert AI v2.6.5

3 bug fixes descubiertos durante validacion live overnight 2026-05-25/26. Total 295 -> 307 tests verdes.

**Bug A FIX — `realized_pnl_today` mal calculado (CRITICO).**

ANTES: sumaba `unrealized_return_pct` per-trade directamente. Memecoin USWC -82% en notional chico daba "-82% portfolio drawdown" cuando la perdida real era <$1k de un balance $100k. Disparaba falsos kill switches.

AHORA: convierte cada trade a USD usando `size_notional`, suma USD ganados/perdidos, divide por balance actual. Trades sin notional (paper trades memecoin que no se ejecutan a MT5) se ignoran porque no afectan balance real.

- `app/portfolio/portfolio_manager.py`: `realized_pnl_today` refactor completo.
- 5 tests nuevos en `tests/test_portfolio_manager.py` incluyendo el escenario del bug.

**Bug B FIX — `mt5_reader.get_rates` necesitaba `symbol_select` defensive.**

Si un simbolo no esta en MT5 Market Watch, `copy_rates_from_pos` devuelve None silenciosamente. Pasaba al agregar USDJPY a SCALPING_ALLOWED_SYMBOLS sin tenerlo visible. Usuario tenia que agregarlo manualmente.

- `app/brokers/mt5_reader.py`: `get_rates` llama `symbol_select(symbol, True)` antes de `copy_rates_from_pos`. Auto-agrega al Market Watch.
- 2 tests nuevos: verifica symbol_select se llama; verifica que continua si falla.

**Bug C FIX — `account_balance` no refrescaba MT5 equity.**

Cuando bot corre horas, `get_account_info` puede devolver None silencioso (sesion stale). Caia al `ACCOUNT_STARTING_BALANCE` del .env. Resultado: `/health` mostraba 1M cuando MT5 real era 100k.

AHORA: si get_account_info devuelve None, hace disconnect + reconnect 1 vez y reintenta. Persiste el equity fresco en `bot_state.account_balance` para que proximo arranque tenga valor real, no starting.

- `app/portfolio/portfolio_manager.py`: nuevo `_fetch_mt5_equity()` con retry, `account_balance` persiste a bot_state.
- 5 tests nuevos cubriendo retry, persist, fallback chains.

**Cambios:**
- `app/config/settings.py` + `.env.example`: bump v2.6.4 -> v2.6.5.

Real-money trading sigue 100% bloqueado.

## Trading Alert AI v2.6.4

**BUG FIX — mt5_reader.get_rates crasheaba contra MT5 real con `AttributeError: 'numpy.void' object has no attribute 'get'`.**

`copy_rates_from_pos` devuelve un numpy structured array donde cada elemento es un `numpy.void`. Soporta bracket access (`r["tick_volume"]`) pero NO el método `.get()`. Mi código antiguo usaba `r.get("tick_volume", 0)` que tira AttributeError. Las otras 5 líneas (`r["time"]`, `r["open"]`, etc.) ya usaban bracket access, solo volume estaba mal.

**Detectado en producción** justo después del fix v2.6.3 (que destrabó el primer call real a `copy_rates_from_pos`). Antes de v2.6.3 nunca llegaba a esta línea (fallaba antes por el timeframe string).

**Cambios:**
- `app/brokers/mt5_reader.py`: nuevo helper `_safe_tick_volume(r)` al nivel del módulo. Usa bracket access con try/except, maneja numpy.void, dict, None, valores ausentes. Reemplaza 2 ocurrencias del bug (`get_rates` y `get_historical_range`).
- Test regression `test_safe_tick_volume_handles_numpy_void_like_objects` con 5 escenarios (dict, void-like con __getitem__ pero sin .get, campo ausente, None object, None field).
- Bump version v2.6.3 → v2.6.4.

Total tests 294 → 295 verdes.

Real-money sigue 100% bloqueado.

## Trading Alert AI v2.6.3

**BUG FIX — scalping engine no recibía candles M1.**

Caused by `_fetch_m1_candles` pasando `timeframe="M1"` (string) a `mt5_reader.get_rates()` que espera `timeframe: int` (MT5 constant `TIMEFRAME_M1 = 1`). El call a `copy_rates_from_pos` fallaba silenciosamente, devolvía None → mi código convertía a `[]` → strategy nunca veía data → 0 signals en 1909 cycles consecutivos.

Detectado en producción gracias al diagnostic instrumentation de v2.6.2:
```
WARNING | ScalpingEngine: 0 velas M1 para EURUSD (mt5_reader.get_rates devolvió vacío)
```

Sin esos warnings (pre-v2.6.2) el engine fallaba en silencio total.

**Cambios:**
- `app/scheduler/scalping_engine.py`: nueva constante `MT5_TIMEFRAME_M1 = 1` al tope del módulo (también M5=5 y M15=15 para uso futuro). `_fetch_m1_candles` ahora pasa `MT5_TIMEFRAME_M1` en lugar de `"M1"`.
- Nuevo test regression `test_fetch_m1_candles_uses_int_timeframe_not_string` que verifica explícitamente que `get_rates` recibe int en arg timeframe, no string. Previene re-introducción del bug.
- Bump version v2.6.2 → v2.6.3.

Total tests 293 → 294 verdes.

Real-money sigue 100% bloqueado.

## Trading Alert AI v2.6.2

Patch diagnóstico para el ScalpingEngine. Antes era "silent failure mode" —
corría pero no logueaba nada, imposible saber si estaba evaluando signals,
qué le faltaba, o por qué nunca disparaba. Después de 10 min de runtime en
producción confirmamos 0 logs del engine y 0 trades scalping.

**Nuevas instrumentaciones (`app/scheduler/scalping_engine.py`):**

- `_emit_log_heartbeat_if_due`: cada 60s loguea INFO con resumen:
  `ScalpingEngine heartbeat: cycles_total=N eval=K opened=X force_exited=Y cap_blocks=Z errors=E last_block=...`
- `_throttled_warning`: cada return-None path de `_evaluate_signal_for_symbol`
  loguea WARNING la primera vez y DEBUG las siguientes 60s (anti-spam).
  Cubre: mt5_disconnected, no_candles, no_tick, invalid_tick, no_pip_size.
- Diagnóstico "en rango": cuando strategy devuelve None pero todo lo demás
  está OK, loguea WARNING throttled con range_low, range_high, ask, bid y
  width en pips. Permite ver cuán cerca está el precio del breakout.

**Cómo usar:**
Después de reiniciar el bot, en los logs PowerShell aparecen líneas tipo:
```
INFO | app.scheduler.scalping_engine | ScalpingEngine heartbeat: cycles_total=12 eval=24 opened=0 force_exited=0 cap_blocks=0 errors=0
WARNING | app.scheduler.scalping_engine | ScalpingEngine EURUSD en rango: ask=1.10050 bid=1.10048 range=[1.10000, 1.10080] width=8.0pips (esperando ask>1.10086 o bid<1.09995)
```

Si después de 5 min ves `eval=0`, el problema es upstream (MT5 reader o caps).
Si ves `eval>0 opened=0` con warnings "en rango", el mercado está apretado y
hay que loosen el buffer del breakout.

**Bump version v2.6.1 → v2.6.2.**

Total tests 291 → 293 verdes (2 nuevos: throttled_warning + heartbeat behavior).

Real-money trading sigue 100% bloqueado.

## Trading Alert AI v2.6.1

Patch consolidando funcionalidad que estaba en working tree sin commitear desde antes de v2.6.0:

- `app/brokers/mt5_demo_trader.py`: nuevos `DemoCloseResult` dataclass + métodos `close_all_positions()` y `_close_position()`. Cierran todas las posiciones MT5 demo abiertas via `order_send` con tipo opuesto. Validaciones demo-only intactas. Refactor de `send_prepared_request` que extrae `_send_deal_request` (reuso interno).
- `app/assistant/command_handler.py`: comando `/demo_close_all` (con aliases `/cerrar_demo`, `/cerrar_demo_todo`) ya estaba registrado y ahora conecta a `mt5_demo_trader.close_all_positions()`.
- `app/config/settings.py` + `.env.example`: STOCK_SYMBOLS default expandido con `NFLX,GLD,XOM,CVX,BAC,SLV,USO,TNA` (8 nuevos, ampliacion del universo monitoreado).
- Tests nuevos en `test_mt5_demo_trader.py` (close_all_positions) y `test_telegram_demo_trading.py` (/demo_close_all command flow).
- Bump version v2.6.0 → v2.6.1.

Total tests 291 verdes (suite ya cubrira los nuevos tests al re-correr).

## Trading Alert AI v2.6.0

Phase 5.5 Bloque B: Scalping Engine en thread dedicado + Mode toggle + Learning per-style. Tres capacidades nuevas que conviven con el swing engine sin reemplazarlo. Real-money trading sigue 100% bloqueado.

**Architecture decision:** Dos flags orthogonal en lugar de un enum compuesto. `BOT_MODE` controla swing engine (como antes desde v2.4.0). Nuevo `ENABLE_SCALPING_ENGINE` controla scalping engine. Combinaciones libres: hybrid (ambos), swing_only, scalping_only, alerts_only.

**Scalping Engine (Commit 1+2):**
- `app/scheduler/scalping_engine.py` NUEVO: thread dedicado (`threading.Thread` con `stop_event`) que polea MT5 cada `SCALPING_POLL_INTERVAL_SECONDS` (default 5s). Por ciclo: kill-switch checks, force-exits, evaluacion de signal por simbolo permitido, auto-ejecucion.
- `app/strategies/scalping_breakout.py` NUEVO: M1 range breakout sobre N velas (default 10), SL/TP fijos en pips (default 8/12), cooldown 60s post-signal.
- `app/utils/scalping_state.py` NUEVO: `resolve_scalping_state` espejo de `bot_mode.resolve_bot_mode` (prioridad CLI > bot_state > setting > default False).
- 12 settings nuevos: `ENABLE_SCALPING_ENGINE`, `SCALPING_ALLOWED_SYMBOLS=EURUSD,GBPUSD`, `SCALPING_RISK_PER_TRADE_PCT=1.0`, `SCALPING_MAX_TRADES_PER_DAY=30`, `SCALPING_MAX_OPEN_TRADES=3`, `SCALPING_MAX_DAILY_LOSS_PCT=3.0`, `SCALPING_FORCE_EXIT_MINUTES=5`, `SCALPING_POLL_INTERVAL_SECONDS=5`, `SCALPING_HEARTBEAT_EVERY_N_TRADES=5`, `SCALPING_SL_PIPS=8`, `SCALPING_TP_PIPS=12`, `SCALPING_RANGE_LOOKBACK_BARS=10`.
- Schema migration: nueva columna `is_scalping INTEGER DEFAULT 0` en `paper_trades`, `demo_orders`, `signal_outcomes`, `strategy_lessons` via `_ensure_column` (backward-compat).
- `main.py` arranca el thread en startup cuando flag activo, y lo cierra limpio en KeyboardInterrupt.
- Reusa `mt5_demo_trader.send_prepared_request` con todas las validaciones demo-only intactas (cuenta demo + trade_allowed + mandatory SL + simbolo whitelist + riesgo cap).

**Mode Toggle (Commit 3):**
- 6 comandos Telegram nuevos: `/scalping_on`, `/scalping_off`, `/scalping_status`, `/scalping_halt`, `/scalping_resume`, `/scalping_stats` (con aliases en español).
- `/mode` extendido con MACROS que setean ambos flags simultaneamente:
  - `/mode swing_only` -> trader + scalping OFF
  - `/mode scalping_only` -> alerts_only + scalping ON
  - `/mode hybrid` -> trader + scalping ON
  - `/mode alerts_only` y `/mode trader`: comportamiento previo (solo bot_mode_active, no toca scalping)
- `/health` (v2.5.5) extendido con seccion "Scalping engine".

**Learning per-style (Commit 4):**
- `_build_lessons` ahora agrupa scalping outcomes en buckets separados (sufijo `_scalping` en category, ej. `forex_scalping`). Lessons swing vs scalping no se mezclan ni contaminan win-rate.
- `scalping_engine._close_scalping_trade` registra signal_outcome con is_scalping=1 al cerrar (force-exit, TP, SL). Usa alert_id negativo (`-paper_trade.id`) para no colisionar con outcomes swing.
- `/aprendizaje` muestra "== SWING LESSONS ==" y "== SCALPING LESSONS ==" en secciones separadas.
- `upsert_signal_outcome` persiste flag is_scalping.

**Safety stack intacto:**
- `ENABLE_REAL_TRADING=false` sigue hardcoded. Scalping no toca real-money.
- Kill-switch global respeta ambos engines.
- Kill-switch propio scalping (`/scalping_halt` -> `bot_state.scalping_halted`) bloquea solo scalping.
- Memecoins siguen como lab de aprendizaje (no MT5, ni swing ni scalping).
- Lifecycle SL-to-breakeven post-TP1 sin cambios.

**Tests:** 253 -> 291 verdes (+38). Distribuidos en:
- test_scalping_state.py (7 nuevos)
- test_scalping_breakout.py (6 nuevos)
- test_scalping_engine.py (7 nuevos)
- test_scalping_commands.py (10 nuevos)
- test_learning_per_style.py (4 nuevos)
- test_telegram_mode_command.py (3 actualizados para v2.6.0 strings)
- test_health_command.py (regression con seccion scalping)

**Out of scope (para v2.6.x posteriores):** mean-reversion scalping strategy, session-aware lessons (London/NY/Asian), auto-enable ENABLE_LEARNED_WEIGHTS, dashboard Streamlit scalping timeline widget.

## Trading Alert AI v2.5.5

Patches tacticos post-observacion overnight v2.5.4. Dos cambios focused: cap separado de riesgo para demo execution + nuevo comando `/health` en Telegram.

**Cambio A — DEMO_MAX_TOTAL_RISK_PCT (default 10.0):**
- Problema observado: `MAX_TOTAL_RISK_PCT=6.0` cuenta agregado de stocks paper + forex + gold. Si stocks paper consumen 5%, los signals forex/gold que SI ejecutan a MT5 demo via auto-confirm quedan bloqueados (5+1>6 → block).
- Fix: `app/risk/risk_manager.py::check_can_open_trade` ahora usa `demo_max_total_risk_pct` cuando la categoria es forex o gold AND `enable_mt5_demo_trading=True`. Stocks/memecoins siguen bajo el cap default.
- Settings nuevo `DEMO_MAX_TOTAL_RISK_PCT=10.0` (opt-out via bajarlo, opt-in via subirlo).
- Tests nuevos en `tests/test_risk_manager.py` (4 escenarios: forex con demo permite, forex con demo bloquea al exceder, stocks no afectados, demo disabled usa cap viejo).

**Cambio B — Comando `/health` (`/salud`) en Telegram:**
- Panel rapido de salud del sistema. Muestra version + bot mode, MT5 (reader, broker, demo trading, auto-confirm, real trading bloqueado), paper trades open por categoria con caps, riesgo agregado con ambos caps aplicables, balance demo, P&L hoy, kill-switch state, demo trading halt state, contadores de auto-orders demo (sent/failed) + ultima auto-order con ticket + retcode.
- Util para chequear el bot desde el celular sin abrir PowerShell ni SQL.
- Aliases: `/health`, `/salud`. (`/estado` ya estaba tomado por `/status`.)
- Tests nuevos en `tests/test_health_command.py` (4 tests).

**Safety stack intacto:** real-money sigue `ENABLE_REAL_TRADING=false` hardcoded. Demo trading validations sin cambios. Kill-switch operativo. /demo_halt sigue activo.

**Total tests:** 245 -> 253 verdes (+8).

## Trading Alert AI v2.5.4

Phase 5.5 Bloque A: auto-confirm opt-in para ordenes demo MT5. Cuando `ENABLE_AUTO_CONFIRM_DEMO=true`, las ordenes se ejecutan automaticamente sin esperar `/confirm_demo_trade` desde Telegram. Acelera el ciclo de aprendizaje. Real-money trading sigue bloqueado.

- Nuevo setting `ENABLE_AUTO_CONFIRM_DEMO=false` (default OFF, opt-in).
- `app/scheduler/jobs.py::_auto_execute_demo_request`: ejecuta `send_prepared_request` inmediato despues de crear la request en `demo_trade_requests`. Persiste status `sent` o `failed` y crea fila en `demo_orders` para auditoria.
- Notificacion Telegram diferenciada: "Auto-orden demo enviada #N" en exito o "Auto-orden demo FALLIDA #N" en rechazo. Permite distinguir ejecuciones automaticas de cualquier otra notificacion.
- Manual confirm (`/confirm_demo_trade`) sigue funcionando como fallback. Bajando el flag a `false` se vuelve al modo Phase 5 original sin redeploy.
- Safety stack intacto: `ENABLE_REAL_TRADING=false` (hardcoded), validaciones demo-only en `mt5_demo_trader` (cuenta demo, `trade_allowed`, `trade_expert`, mandatory SL, simbolos whitelist, volumen normalizado, riesgo cap), kill-switch `/demo_halt` sigue activo.
- Tests nuevos en `tests/test_auto_confirm_demo.py` (4 tests). Total **244 verdes** (240 -> 244).

Proximo (Bloque B, sesion separada): Scalping Engine en hilo dedicado con polling 5s + nueva strategy M1 + caps especificos (SCALPING_RISK_PER_TRADE_PCT, SCALPING_MAX_TRADES_PER_DAY, etc.).

## Trading Alert AI v2.5.3

Patch de candidatos demo: `/demo_candidates` ahora valida cada paper trade contra el precio actual de MT5 antes de mostrarlo. Los setups vencidos, por ejemplo longs cuyo TP ya quedo debajo del precio actual, se ocultan y se reportan como descartes en vez de dejar que fallen repetidamente en `/demo_prepare`.

## Trading Alert AI v2.5.2

Patch de compatibilidad MT5: si un broker no entrega `trade_tick_size` o `trade_tick_value` para un simbolo demo, el bot intenta calcular riesgo usando `point`, `trade_tick_value_profit/loss` o `trade_contract_size` antes de bloquear la orden. Trading real sigue bloqueado.

## Trading Alert AI v2.5.1

Patch de practica demo: el modo MT5 demo ahora permite hasta 10 operaciones abiertas y sube el limite de riesgo demo por trade a 5.26% (aprox. 1/19 de la cuenta). Trading real sigue bloqueado y la confirmacion manual por Telegram sigue siendo obligatoria.

## Trading Alert AI v2.5.0

Phase 5: órdenes reales en **cuenta demo MT5** con confirmación manual obligatoria. Real-money trading sigue bloqueado.

- Nuevo `app/brokers/mt5_demo_trader.py`: ejecutor separado del reader. Es el único módulo que puede llamar `order_send`.
- Valida antes de enviar: MT5 conectado, cuenta demo, `trade_allowed`, `trade_expert`, símbolo permitido, SL/TP obligatorio, volumen normalizado, riesgo máximo, kill-switch demo y máximo de posiciones demo.
- Nuevas tablas SQLite: `demo_trade_requests` y `demo_orders`.
- Nuevos comandos Telegram: `/demo_candidates`, `/demo_prepare ID`, `/confirm_demo_trade ID`, `/demo_positions`, `/demo_halt`.
- Nuevas variables seguras: `ENABLE_MT5_DEMO_TRADING=false`, `DEMO_ORDER_REQUIRE_CONFIRMATION=true`, `DEMO_MAX_OPEN_TRADES=1`, `DEMO_RISK_PER_TRADE_PCT=0.25`, `DEMO_MAX_LOT=0.01`, `DEMO_ALLOWED_SYMBOLS=EURUSD,XAUUSD`, `DEMO_TRADE_REQUEST_TTL_MINUTES=15`, `ENABLE_REAL_TRADING=false`.
- El scheduler puede crear una solicitud demo pendiente cuando abre un paper trade forex/oro, pero nunca envía la orden sin `/confirm_demo_trade`.
- Tests nuevos para el ejecutor MT5 demo y comandos Telegram.

## Trading Alert AI v2.4.0

Phase 4.5: Memecoin Hunter Pro (early detection + scoring refinado) + Bot Mode Toggle (alerts_only / trader / hybrid). Sigue read-only para órdenes reales.

**Memecoin Hunter Pro:**
- `app/collectors/geckoterminal_collector.py`: nuevo método `_collect_new_pools_for_network` que llama `/networks/{network}/new_pools`. Filtra pools con edad > `MAX_EARLY_POOL_AGE_HOURS=6`. Marca como `event_type="EARLY_MEMECOIN"`.
- `app/analyzers/memecoin_hunter.py`: `MemecoinHunterResult` dataclass + `analyze_memecoin()`. Calcula `early_bonus` (0-20 pts), `volume_velocity_ratio` (aceleración 5m vs 1h), `anti_rug_multiplier` (0.5-1.0 que penaliza honeypot/risky/liquidity_unlocked/holder_concentration).
- Integrado en `jobs.py` después de `score_token`. Para `category=memecoin and enable_memecoin_hunter`: `adjusted_score = int((base_score + early_bonus) * anti_rug_multiplier)`.
- Holder concentration y liquidity_locked quedan `None` en v2.4.0 (requieren RPC blockchain). Phase 5+ agregará collector RPC dedicado.
- ALERT_PRIORITY: `EARLY_MEMECOIN=90` (alta, justo bajo SECURITY_RISK).

**Telegram memecoins re-activadas con filtros estrictos:**
- **Default flip:** `ENABLE_MEMECOIN_TELEGRAM=true` (antes `false`). Quien quiera silencio: setear `false` en `.env`.
- Caps separados: `MAX_EARLY_MEMECOIN_ALERTS_PER_24H=3`, `MAX_MATURE_MEMECOIN_ALERTS_PER_24H=2`, `MAX_EARLY_MEMECOIN_ALERTS_PER_RUN=1`.
- `_send_ranked_candidates` distingue early vs mature por `alert_type` (`EARLY_MEMECOIN` vs `BOOSTED_TOKEN`/`TRENDING_POOL`).
- **Learning gate FORZADO** para memecoins: `FORCE_LEARNING_GATE_FOR_MEMECOIN=true`. Aunque `ENABLE_LEARNING_GATE=false` globalmente, memecoins siempre pasan por gate (defensa anti-rug).

**Bot Mode Toggle:**
- `app/utils/bot_mode.py`: `resolve_bot_mode()` con prioridad CLI > bot_state > setting > default trader.
- 3 modos: `trader` (default), `alerts_only` (skip strategy router, mantiene Telegram + lifecycle), `hybrid` (en v2.4.0 = trader; Phase 5+ agregará confirmación manual).
- Setting `BOT_MODE=trader|alerts_only|hybrid` en `.env`.
- Comando Telegram `/mode [trader|alerts_only|hybrid]` persiste en `bot_state.bot_mode_active`.
- CLI flag `python main.py --mode alerts_only` override por sesión.
- En `run_once`: log "Bot mode active: X". Si `alerts_only`, skip strategy router (no abre paper trades nuevos) pero mantiene Telegram alerts y lifecycle manager (no abandona posiciones).
- Dashboard Streamlit: nueva metric "Bot mode" en sección Portfolio.

**Settings nuevos (10):** `enable_early_memecoin_detection`, `max_early_pool_age_hours`, `enable_memecoin_hunter`, `memecoin_hunter_min_volume_velocity_ratio`, `max_early_memecoin_alerts_per_24h`, `max_mature_memecoin_alerts_per_24h`, `max_early_memecoin_alerts_per_run`, `force_learning_gate_for_memecoin`, `bot_mode`, + default flip de `enable_memecoin_telegram` → `true`.

**Tests nuevos (32 en 7 archivos):** bot_mode_toggle (9), geckoterminal_new_pools (4), memecoin_hunter (7), memecoin_alerts_phase4_5 (5), telegram_mode_command (5), cli_mode_flag (2). Total **229 verdes** (197 → 229).

- `APP_VERSION` bump a `v2.4.0`. SEC user agent a 2.4.0.

Sigue read-only para órdenes. `order_send` recién en Phase 5 (cuenta demo ICMarkets autorizada).

## Trading Alert AI v2.3.0

Phase 4: validación MT5 demo + walk-forward backtester + data quality monitor + CSV export. Sigue read-only para órdenes. Phase 5 (`order_send` a demo) ya es el siguiente paso autorizado.

**MT5 extensiones (broker ICMarkets default):**
- `app/brokers/mt5_symbol_map.py`: mapping bidireccional Yahoo↔MT5 por broker_profile (icmarkets, metaquotes). EURUSD=X → EURUSD, GC=F → XAUUSD, etc.
- `app/brokers/mt5_reader.py`: nuevos métodos `validate_symbol`, `symbol_info` (spread, point, digits, contract_size, volume_min/step, tick_value), `compute_pip_value` (pip value en moneda de cuenta para 1 lote), `get_historical_range` (wrapper sobre copy_rates_range). Constants `MT5Timeframe.M1/M5/M15/H1/H4/D1`.
- `app/brokers/mt5_historical.py`: `MT5HistoricalFetcher` con cache local en SQLite (`mt5_historical_cache`). Evita pedir el mismo bar dos veces al broker.

**Walk-forward backtester:**
- `app/learning/walk_forward.py`: `WalkForwardBacktester` con train/test split deslizante. NO tunea parámetros (eso queda para Phase 6).
- Detecta degradación entre in-sample y out-of-sample: `(train_sharpe - test_sharpe) / |train_sharpe| * 100`.
- Settings: `walk_forward_train_days=14`, `walk_forward_test_days=7`, `walk_forward_slide_days=1`, `walk_forward_min_train_samples=10`.
- Persiste resultados en nueva tabla `walk_forward_results`.

**Data quality monitor:**
- `app/intelligence/data_quality.py`: `gap_check`, `staleness_check`, `collector_failure_check`, `run_full_check`.
- Persiste en nueva tabla `data_quality_log`.
- Integrado en `jobs.run_once` cada N ciclos (`data_quality_check_every_n_cycles=10`).

**CSV export:**
- `app/utils/csv_export.py`: `export_outcomes_csv`, `export_paper_trades_csv`, `export_horizons_csv`, `export_walk_forward_csv`. Path saneado con `safe_resolve_within`.

**Telegram commands nuevos:**
- `/mt5_status`: estado conexión MT5 + broker + account + symbol_info de EURUSD.
- `/data_quality`: stale symbols + gaps + collector failures.
- `/walk_forward STRATEGY [días] [categoría]`: corre walk-forward sobre 1 strategy.
- `/export_csv [outcomes|trades|horizons|walk_forward]`: genera archivo en `exports/`.

**Dashboard expansion:**
- Nueva sección "Walk-Forward Performance" con resumen por strategy y top 20 ventanas.
- Nueva sección "Data Quality" con últimos 20 checks.

**Schema (v2.3.0):**
- Tabla `mt5_historical_cache` (symbol, timeframe, time UNIQUE, ohlcv).
- Tabla `walk_forward_results` (strategy_name, train/test windows, métricas, degradation, samples).
- Tabla `data_quality_log` (check_at, gaps, stale, failures, summary JSON).

**Settings nuevos (12):** mt5_broker_profile, walk_forward_* (5), data_quality_* (4), enable_csv_export, csv_export_path.

**Packages:** `MetaTrader5 5.0.5735` y `anthropic 0.103.1` instalados en `.venv`. Soft-fail si faltan.

**Tests:** 34 nuevos (mt5_symbol_map 5, mt5_reader_extensions 6, mt5_historical 3, data_quality 4, csv_export 4, walk_forward 6, telegram_phase4 6). Total **197 verdes** (163 → 197).

- `APP_VERSION` bump a `v2.3.0`.
- User-Agents en collectors bumpeados a 2.3 + SEC user agent a 2.3.0.

Sigue read-only. `order_send` autorizado para Phase 5 (cuenta demo ICMarkets ya disponible).

## Trading Alert AI v2.2.0

Phase 3 + 3.5: forex price-action profesional + LLM integration con Claude API. Sigue read-only para ordenes reales.

**Phase 3 — Forex price-action + dashboard avanzado:**

- Nuevo `app/collectors/macro_collector.py`: pull periodico de VIX, DXY, SPY via Yahoo. Calcula regime `risk_on` / `risk_off` / `neutral`. Persiste en nueva tabla `macro_snapshots`.
- Nuevo `app/collectors/economic_calendar_collector.py`: parser ForexFactory XML, filtra eventos high-impact en USD/EUR/GBP/JPY/CHF/AUD/CAD/NZD. Persiste en nueva tabla `economic_events`.
- Nuevo `app/intelligence/calendar_filter.py::is_safe_window`: bloquea apertura de trades ± 30 min alrededor de NFP/FOMC/CPI para la moneda relevante.
- `app/intelligence/macro_context.py`: agrega `current_regime()` y `full_macro_context()` que combina sesion + regime.
- Nuevo `app/analyzers/technical_patterns.py::analyze_multitf`: combina pattern M15 + H1 con flag `aligned` + `confluence_score`.
- Nueva strategy `app/strategies/forex_session_breakout.py`: opera solo durante London/NY overlap, busca breakouts del Asian range. Horizon 8h.
- Las 4 strategies existentes ahora **usan** `ctx.macro`: breakout penaliza low liquidity, mean_reversion penaliza risk_off, momentum bonifica risk_on, news_catalyst permite forex/gold.
- Alertas Telegram activadas para forex/gold con caps separados (`max_forex_alerts_per_24h=3`, `max_gold_alerts_per_24h=2`). Controladas por `enable_forex_alerts` y `enable_gold_alerts`.
- Nueva columna `alerts.strategy_name` — cuando una strategy abre paper trade, el alert lo registra para drilldown.
- Dashboard Streamlit: nueva sección "Análisis profundo" con heatmap horizonte × hora del día, macro context panel (VIX/DXY/SPY/regime), calendario económico próximas 24h, drilldown por alerta (selectbox + paper_trade + horizons).

**Phase 3.5 — LLM integration (Claude API):**

- Nuevo `app/intelligence/claude_processor.py`: cliente centralizado para Anthropic Claude API. **Soft-fail completo**: si `ENABLE_CLAUDE_INTEGRATION=false`, sin API key o paquete `anthropic` no instalado → todos los metodos retornan None silenciosamente. Sin crashes.
- Caracteristicas: throttle por ciclo (`claude_calls_per_cycle_cap=6`), cache SHA256 (TTL 1h), telemetria de costo por dia en `bot_state` (`claude_input_tokens_<date>`, `claude_output_tokens_<date>`), safety cap `claude_max_cost_per_day_usd=2.0`.
- Métodos: `summarize_news`, `expand_pro_analysis`, `interpret_free_text`.
- `jobs.py::_market_intelligence` ahora llama `claude_processor.expand_pro_analysis` despues de armar `ProfessionalAnalysis`. Si Claude responde, agrega "🤖 IA: ..." a reasons.
- `command_handler.py` fallback "no entendi" ahora usa Claude para interpretar preguntas naturales. Si Claude retorna un comando slash valido, lo ejecuta recursivamente; sino devuelve texto natural.
- `AlertRecord` gana campo opcional `ai_reasoning: list[str]` para futuro storage de razonamiento Claude.
- Modelo default: `claude-haiku-4-5` (~$1/M input, $5/M output). Cost cap de $2/dia previene factura inesperada.
- Settings `_SECRET_FIELDS` incluye `anthropic_api_key` — enmascarado en `repr(settings)` y por `LogRedactor`.

**Schema changes (v2.2.0):**

- Tabla `macro_snapshots` (id, captured_at UNIQUE, vix_value, dxy_value, spy_value, regime).
- Tabla `economic_events` (id, event_time, country, impact, title, captured_at, UNIQUE(event_time, country, title)).
- Columna `alerts.strategy_name TEXT` via `_ensure_column`.
- Indices: `idx_events_time`, `idx_macro_captured`.

**Settings nuevos (19):** macro_collector (2), economic_calendar (3), forex_alerts (5), strategy_forex_session_breakout (1), claude integration (8 — incluye `ANTHROPIC_API_KEY` secret).

**Tests:** 28 nuevos en 5 archivos (claude_processor 8, macro_collector 3, economic_calendar 4, calendar_filter 3, forex_session_breakout 6, forex_alerts_phase3 4). Total **163 verdes** (135 → 163).

- `requirements.txt`: agrega `anthropic>=0.40.0,<1.0.0`.
- `APP_VERSION` bump a `v2.2.0`.

Sigue read-only. NO order_send a brokers ni demo MT5 (Phase 5).

## Trading Alert AI v2.1.0

Fase 2.6: hardening de seguridad y privacidad. Sin nuevas features funcionales. Sin breaking changes en API publica.

- `Settings.__repr__` ahora enmascara `telegram_bot_token`, `telegram_chat_id`, `mt5_login`, `mt5_password`, `mt5_server` con `<redacted>` y muestra paths solo como basename. Defensa contra logs accidentales de `repr(settings)`.
- Nuevo `app/utils/safe_path.py` con `safe_resolve_within` y `safe_optional_file`. Aplicado en `OBSIDIAN_VAULT_PATH` (bloquea `../../...` traversal con fallback al default) y `MT5_PATH` (rechaza paths no-absolutos o no-existentes).
- Nuevo `app/utils/log_redactor.py`: filter que enmascara tokens estilo Telegram (regex `\d{9,12}:[A-Za-z0-9_-]{35,}`) y valores conocidos del .env. Instalado en root logger al startup desde main.py.
- Nuevo `app/utils/safe_http.py` con `safe_json(response, default)`. Aplicado en `dexscreener_collector._get_json` y `geckoterminal_collector.fetch_pool_ohlcv` (donde antes un JSON invalido crasheaba el ciclo).
- `app/scheduler/jobs.py:93` solo loguea el nombre del archivo de la DB (no path absoluto del filesystem del usuario).
- `app/database/db.py::init_db` envuelve `executescript` en try/except `sqlite3.DatabaseError` con mensaje claro (sin filesystem leak) si la DB esta corrupta.
- `app/assistant/command_handler.py::halt_message` clampa el argumento de `/halt` al rango [1, 168] horas. Previene `/halt -999` o `/halt 999999`.
- `app/risk/position_sizer.py::calculate_position_size` rechaza `risk_pct > 10` como safety cap. Defensa contra config rota (ej. `RISK_PER_TRADE_PCT=100`).
- `app/analyzers/token_score.py::_liquidity_points` trata `liquidity_usd < 0` como `None` en lugar de propagar valor invalido.
- `requirements.txt`: versiones pinneadas exactas (python-dotenv==1.2.2, requests==2.34.2, streamlit==1.57.0, pandas==3.0.3, pytest==9.0.3, MetaTrader5>=5.0.45,<6.0.0). Defensa contra cadena suministro maliciosa.
- 18 tests nuevos en `tests/test_security_hardening.py` (settings repr, safe_path, halt clamp, position cap, score sanitize, log redactor, safe_json). Total **135 tests verdes** (117 → 135).
- `APP_VERSION` bump a `v2.1.0`.

Hallazgos del audit confirmados como OK (no requirieron fix): .gitignore correcto, HTTPS-only, todos los requests.get con timeout, User-Agents genericos, no shell injection, no eval/exec/pickle, no logs a disco, Streamlit en localhost, /config no expone secretos, queries usan placeholders ? (54 de 56; los 2 con f-string ya mitigados por whitelist + parameterized).

Sigue read-only. NO order_send a brokers reales ni demo MT5 (Fase 5).

## Trading Alert AI v2.0.0

Fase 2.5: el bot pasa de "alerter" a "trader engine autonomo". Sigue read-only (sin order_send a brokers ni demo MT5 todavia; eso es Fase 5).

- Agrega `app/brokers/mt5_reader.py`: adapter MT5 read-only soft-fail. Si MetaTrader5 no esta instalado o initialize falla, retorna None silenciosamente y el bot sigue corriendo degradado con yfinance. Lee tick, rates y account_info. Credenciales (login/password/server) solo en .env real; nunca en logs.
- Agrega `app/portfolio/portfolio_manager.py`: track de posiciones abiertas, exposicion por categoria, P&L diario, equity curve, riesgo total. account_balance prioriza MT5 → bot_state → starting_balance.
- Agrega `app/risk/risk_manager.py`: kill-switch persistente en bot_state (manual + automatico por max drawdown diario), gates check_can_open_trade (max trades concurrentes total + por categoria + max riesgo agregado), force_close_all_open.
- Agrega `app/risk/position_sizer.py`: funcion pura `calculate_position_size` con formula `risk_amount = balance × risk_pct/100; size_units = risk_amount / |entry - stop|`. Maneja long y short.
- Agrega `app/strategies/` con base + 4 estrategias: breakout, mean_reversion, momentum, news_catalyst. Cada strategy implementa Protocol `Strategy.evaluate(ctx) -> StrategySignal | None`. StrategyRouter las filtra por min_confidence.
- Agrega `app/intelligence/macro_context.py`: sesiones FX (asian/london/ny) con flag is_high_liquidity.
- Agrega `app/learning/lifecycle_manager.py`: `manage_open_positions` refresca latest_price (MT5 si conectado), actualiza MFE/MAE/trailing, cierra trades por time_horizon_hours, hace partial close en TP1 con stop a breakeven. Soporta short.
- Agrega `app/alerts/trade_reporter.py`: mensajes Telegram automaticos al abrir/cerrar paper trades.
- Schema: tabla nueva `daily_pnl_log` (date PK + realized_pnl + trades_closed/opened + kill_switch_triggered). Paper trades gana 8 columnas: strategy_name, direction, time_horizon_hours, size_notional, size_units, risk_pct, partial_closed, account_balance_at_open.
- Bloqueo memecoins Telegram por default (`enable_memecoin_telegram=false`). Memecoins siguen alimentando strategy_lessons y outcomes por horizonte como lab de aprendizaje.
- Decision Engine en `app/scheduler/jobs.py`: gestiona posiciones abiertas al inicio de cada ciclo; en el loop, para snapshots stock/forex/gold pregunta al strategy router, evalua position_sizer + risk_manager, y crea paper_trade si pasa. Notifica apertura por Telegram (configurable).
- Telegram nuevos comandos: `/portfolio`, `/posiciones`, `/halt [horas]`, `/resume_trading`, `/strategies`.
- Dashboard Streamlit nueva seccion "Portfolio en vivo" con metrics (Balance, Posiciones, Riesgo total, P&L hoy), badge kill-switch, exposicion por categoria, historial daily_pnl_log.
- Agrega 28 settings nuevos. `requirements.txt` agrega `MetaTrader5` (Windows-only, comentario que soft-fail si no aplica). `.env.example` con bloque Fase 2.5 y MT5_LOGIN/PASSWORD/SERVER vacios (NUNCA con valores reales).
- Agrega 53 tests nuevos (mt5_reader, portfolio_manager, risk_manager, position_sizer, strategy_router, macro_context, trade_reporter, lifecycle_manager, telegram_phase25_commands, memecoin_telegram_block, decision_engine_phase25). Total 117 tests verdes.
- Bumpea `APP_VERSION` a `v2.0.0`.
- Sigue read-only: sin order_send a brokers ni demo MT5 todavia. Real-money trading sigue prohibido sin nueva autorizacion explicita.

## Trading Alert AI v1.7.0

- Agrega paper trades con tracking de MFE/MAE durante la vida del trade (`paper_trades.mfe_pct`, `paper_trades.mae_pct`).
- Agrega trailing stops simulados en paper trading (columnas `original_stop_loss`, `trailing_active`). El stop se eleva cuando la posicion supera el umbral de activacion y nunca baja.
- Agrega SL/TP basados en ATR (Average True Range) opcional en `build_trade_readiness`; ATR se calcula del OHLCV cuando esta disponible y se clampa al rango seguro por categoria.
- Agrega `app/analyzers/learned_weights.py`: ajusta el score base con `strategy_lessons` aprendidas (bonus/malus por feature, clamp duro). **OFF por default** hasta que el usuario active `ENABLE_LEARNED_WEIGHTS=true`.
- Agrega `app/analyzers/learning_gate.py`: bloquea envio de alerta si el backtest historico de la combinacion de features tiene win_rate bajo. **OFF por default** hasta que el usuario active `ENABLE_LEARNING_GATE=true`.
- Agrega `app/collectors/forex_collector.py`: collector de FX majors (`EURUSD=X, GBPUSD=X, USDJPY=X, USDCHF=X, AUDUSD=X, USDCAD=X, NZDUSD=X`) y oro (`GC=F`) via Yahoo Finance. Solo persiste snapshots y outcomes por horizonte; **no genera alertas Telegram en Fase 2** (las alertas forex/oro vendran en Fase 3 con analisis price-action especifico).
- Excluye forex/gold de `should_send_alert` y `candidate_for_security_check` (categoria nueva, fluye por snapshots y horizons sin notificar).
- Agrega 21 settings nuevos (ATR, trailing, learned weights, learning gate, forex collector). Variables nuevas en `.env.example` con bloque comentado.
- Agrega 26 tests nuevos (MFE/MAE, trailing, ATR SL/TP, learned weights, learning gate, forex collector). Total 64 tests verdes.
- Bumpea `APP_VERSION` a `v1.7.0`.
- Mantiene el sistema read-only: no compra, no vende y no ejecuta ordenes (ni a demo MT5 todavia; eso es Fase 5).

## Trading Alert AI v1.6.0

- Agrega persistencia historica de precios en `price_snapshots` con purga automatica.
- Crea tabla `alert_outcome_horizons` con outcomes por horizonte fijo (1h, 6h, 24h, 7d).
- Calcula MFE (max favorable excursion) y MAE (max adverse excursion) por ventana.
- Agrega modulo `app/learning/horizon_evaluator.py` integrado en `run_learning_cycle`.
- Agrega modulo `app/learning/backtester.py` con `backtest_strategy()` y `rank_top_strategies()`.
- Agrega comandos Telegram `/horizontes SIMBOLO` y `/backtest [Nh] [features...]`.
- Agrega seccion "Rendimiento por horizonte" en el dashboard Streamlit (tabla MFE/MAE, equity curve, ranking).
- Agrega reporte semanal automatico en `obsidian/tradingbot v.1/11 - Reporte Semanal.md`.
- Agrega 16 tests nuevos (snapshots, horizon evaluator, backtester, comandos Telegram, reporte semanal).
- Agrega 7 settings (`ENABLE_PRICE_SNAPSHOTS`, `SNAPSHOT_RETENTION_DAYS`, `HORIZON_MIN_SNAPSHOTS`, `ENABLE_HORIZON_EVALUATOR`, `BACKTEST_MIN_SAMPLES`, `BACKTEST_DEFAULT_HORIZON_HOURS`, `ENABLE_WEEKLY_OBSIDIAN_REPORT`).
- Bumpea `APP_VERSION` a `v1.6.0`.
- Mantiene el sistema read-only: no compra, no vende y no ejecuta ordenes.

## Trading Alert AI v1.5.2

- Agrega Learning Engine local.
- Crea tabla `signal_outcomes` para evaluar señales pasadas contra precios actuales.
- Crea tabla `strategy_lessons` para aprender que features ayudan o perjudican.
- Crea paper trading simulado en `paper_trades`, sin ordenes reales.
- Agrega readiness A/B/C/D/BLOCKED para preparar setups manuales.
- Agrega comandos `/aprendizaje`, `/paper` y `/entrenar`.
- Dashboard muestra outcomes, lecciones y paper trades.
- Mantiene el sistema read-only: no compra, no vende y no ejecuta ordenes.

## Trading Alert AI v1.5.1

- Agrega IA Pro read-only antes de MT5.
- Mejora analisis tecnico con MACD, Bollinger, ATR, volumen relativo, soporte/resistencia y sparkline.
- Agrega analisis de filings SEC recientes para acciones.
- Agrega comando `/pro SIMBOLO` con lectura profesional.
- Agrega comando `/filings SIMBOLO`.
- Mejora ranking con setup profesional, catalizadores, riesgos y checklist.
- Mantiene prohibido operar: sin compras, ventas, wallets, brokers ni ordenes.

## Trading Alert AI v1.5

- Agrega alertas agrupadas por categoria para reducir mensajes.
- Agrega comando `/cupos`.
- Agrega comando `/descartes`.
- Agrega filtro anti-hype para memecoins boosted/trending con baja liquidez, seguridad unknown o subidas ya exageradas.
- Agrega memoria automatica en Obsidian en `09 - Memoria Automatica.md`.

## Trading Alert AI v1.4

- Agrega inteligencia avanzada read-only de mercado.
- Analiza patrones tecnicos con velas OHLCV: tendencia, RSI, medias, ruptura y volumen.
- Usa OHLCV publico de GeckoTerminal para pools cuando hay `pair_address`.
- Usa velas publicas de Yahoo Finance para acciones configuradas.
- Agrega analisis basico de noticias/eventos por titulares: earnings, revenue, sales, guidance, conference, upgrades/downgrades.
- Agrega comandos Telegram `/noticias SIMBOLO` y `/patron SIMBOLO`.
- Suma patrones/noticias al ranking, sin ejecutar compras ni ventas.

## Trading Alert AI v1.3

- Agrega asistente basico por Telegram sin OpenAI API.
- Responde solo al `TELEGRAM_CHAT_ID` configurado.
- Agrega comandos `/status`, `/top`, `/top_memecoins`, `/top_stocks`, `/alertas`, `/analiza`, `/pausar`, `/reanudar`, `/config`.
- Permite pausar alertas automaticas sin detener el monitoreo ni el historial.
- Mantiene el sistema read-only: sin compras, ventas, wallets, brokers ni ordenes.

## Trading Alert AI v1.2

- Agrega categoria `stock` para alertas de bolsa de valores read-only.
- Agrega collector publico para simbolos configurados en `STOCK_SYMBOLS`.
- Agrega cupos duros por 24h: maximo 5 memecoins y 5 acciones por defecto.
- Agrega cupos por ciclo para evitar rafagas: 2 memecoins y 2 acciones por defecto.
- Cambia el envio a ranking: primero analiza, luego manda solo los mejores candidatos.
- Mantiene historial completo en SQLite aunque Telegram no envie.

## Trading Alert AI v1.1

- Reduce ruido de Telegram con modo high-conviction.
- Estima posible subida y posible caída con datos públicos.
- Telegram solo envía oportunidades con subida estimada mayor o igual a 500%.
- Guarda oportunidades descartadas en SQLite para revisión histórica.
- Agrega versión visible en alertas y configuración.

## Trading Alert AI v1.0

- MVP local con DEX Screener, GeckoTerminal, GoPlus, SQLite, Telegram y dashboard.
