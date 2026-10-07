# HANDOFF — Trading Alert AI (continuidad entre máquinas)

> Documento para retomar el proyecto en otra computadora (o sesión nueva de Claude Code).
> **Pegá el bloque de abajo como primer mensaje** en el Claude Code de la máquina nueva.
> No contiene secrets (login/password/token viven solo en el `.env`, fuera de git).

---

## Prompt VIGENTE para el chat nuevo (7-oct-2026) — usá ESTE

```
Retomamos Trading Alert AI (bot de trading LOCAL, Python 3.12, Windows, repo en
C:/Users/LENOVO/tradingalertaIA, venv en .venv). Respondé en español, claro y sin jerga
innecesaria. Estado al 7-oct-2026: v3.16.0 (v3.14.1 = precio de los paper trades, v3.15.0 =
agentes sombra, v3.16.0 = colector de options flow, solo captura), 938 tests verdes. Demo MT5 MetaQuotes-Demo (~2.990 USD). Research: 27 familias
de hipótesis probadas con pre-registro → 0 operables (la 27 = FVG/iFVG en H1, 7-oct: NO PASA).

Leé ANTES de tocar nada: la memoria de Claude (MEMORY.md; en especial v3-13-0-ai-agent,
gold-paper-futures-vs-spot, no-direct-mt5-trading, sesiones-paralelas-2026-10, mt5-server-time,
real-money-stays-blocked), research/AGENTE_IA_V2_PREREGISTRO_2026-10-06.md + sus adendas
(AGENTE_IA_V2_ADENDA_2026-10-07_oro.md, AGENTE_IA_V2_ADENDA2_2026-10-07_realismo.md),
research/AGENTE_IA_SOMBRAS_PREREGISTRO_2026-10-07.md, research/HIPOTESIS_2026-10-07_kronos.md
(H-KRON1 hacia adelante: corre aparte con .\start_kronos.ps1; no mirar antes del 2027-01-15),
research/OPCIONES_COLECTA_2026-10-07.md (no mirar options flow antes del pre-registro), research/LEDGER_FAMILIAS.md,
PROXIMOS_PASOS.md (bloque del 7-oct) y RESUMEN_COMPLETO.md §2.12-§2.13.

AGENTE IA: app/ai_agent/ decide EJECUTAR / EXPLORAR / NO OPERAR cada candidato forex/oro en MT5
DEMO y aprende de todos (Thompson sampling, información completa: ejecutar más NO acelera el
aprendizaje). v2 (AI_AGENT_VERSION=2, AI_AGENT_EXPLORE_PCT=0.20). El 7-oct se encontró que el
oro de papel abría con el futuro de Yahoo (GC=F) y se marcaba con el spot de MT5 (~$21 abajo) y
que en forex la orden real heredaba el SL/TP del paper sobre otra entrada (NZDUSD: stop real de
0.4 pips). Fix opt-in PAPER_PRICE_FROM_MT5 (una sola fuente por paper trade). Con el flag + el
modelo reconstruido (warm start --exclude-mixed-gold) el tag es
v2|eps0.20|xr0.10|r0.50|thr0.05|pv0.25|nv1.00|xmax3|xstop2.0|px1 = lo único que se evalúa
(desde el 2027-01-11 con ≥200; t NW ≥ 2.50; predicción NO PASA). |px0 = flag sin reconstruir
(no cuenta). El tag sin px es el viejo (se reporta aparte). Agentes sombra (codicioso, prudente,
simple): deciden sobre los mismos candidatos y NUNCA operan; pre-registro propio, misma fecha.
NO cambiar parámetros del agente. Ver cómo va: /agente, scripts/ai_agent_report.py (solo
lectura) y la tarea programada revision-semanal-agente-ia (lunes 09:04).

LO QUE SIGUE: (1) si el user todavía no lo hizo: merge+push, .env (PAPER_PRICE_FROM_MT5=true,
AI_AGENT_SHADOWS=true), warm start con el bot apagado (python scripts/ai_agent_warmstart.py
--version 2 --mt5-d1 --exclude-mixed-gold --apply --force) y reinicio; verificar en /agente el
tag |px1 y "modelo sin oro mezclado: sí"; (2) checkpoint COT el 2026-12-07 09:00 (tarea
checkpoint-cot-reexperimento); (3) pendiente del user: realized_pnl_today ignora la mitad
cobrada en TP1; (4) NO abrir familias nuevas por defecto ni re-cortar las cerradas.

PROTOCOLO (no negociable): pre-registro commiteado ANTES de bajar datos / del código; código
congelado y verificado con datos sintéticos ANTES de correr; k declarado, umbral t ≥ 2.50
(Newey-West); manifest con checksums; NUNCA usar como decisoria una ventana marcada como vista;
diagnósticos post-hoc rotulados; si no pasa, se cierra sin re-cortes; adendas ANTES del código.

REGLAS DEL PROYECTO: real-money BLOQUEADO (ENABLE_REAL_TRADING=false HARDCODED; el user lo
pide seguido, la respuesta es no); Claude NO opera MT5 (solo lee, con mt5.initialize() SIN
credenciales); order_send solo en app/brokers/mt5_demo_trader.py; LLM/ML solo restan SALVO el
agente IA en demo (excepción acotada); todo lo nuevo opt-in OFF + soft-fail; nunca leer/mostrar
el .env (cambios = darle al user comandos de PowerShell); al tocar Settings sincronizar
tests/test_score._settings() y tests/test_alert_rules._settings(); versionado patch/minor sin
saltos; el push a main lo hace el user; una sola instancia del bot (verificar que no haya dos
main.py).

Gotchas: MT5 da las épocas en hora del SERVIDOR (EET; UTC+3 hasta el 25-oct, después +2); para
resultados de posiciones usar history_deals_get(position=...) sin rango de fechas;
copy_rates_from_pos con count ≥ 100000 da 'Invalid params' (usar ≤ 99000); el cache D1 de MT5
está congelado desde el 2026-06-15; la DB viva pesa ~5.6 GB (mode=ro, no copiarla); consola
cp1252 → sys.stdout.reconfigure(encoding="utf-8"); trading_data/ NO está en .gitignore.
```

---

## Prompt del 6-oct-2026 (histórico: reemplazado por el de arriba)

```
Retomamos Trading Alert AI (bot de trading LOCAL, Python 3.12, Windows, repo en
C:/Users/LENOVO/tradingalertaIA, venv en .venv). Respondé en español rioplatense, claro y sin
jerga innecesaria. Estado al 6-oct-2026: v3.14.0 (agente IA v2; incluye v3.13.3 = hora del servidor MT5),
889 tests verdes. Demo MT5
MetaQuotes-Demo (~2.990 USD). Research: 26 familias de hipótesis probadas con pre-registro →
0 operables (la 26 = H-FADE1: operar el reverso de las señales del bot
NO PASA; bruto ≈ 0 en ambas direcciones, se pierde el costo).

Leé ANTES de tocar nada: la memoria de Claude (MEMORY.md; en especial v3-13-0-ai-agent,
no-direct-mt5-trading, sesiones-paralelas-2026-10, mt5-server-time, real-money-stays-blocked),
research/LEDGER_FAMILIAS.md (26 familias + "Lectura transversal" + ventanas ya vistas),
research/AGENTE_IA_V2_PREREGISTRO_2026-10-06.md, PROXIMOS_PASOS.md (bloque del 6-oct) y
RESUMEN_COMPLETO.md §2.10-§2.12.

AGENTE IA: app/ai_agent/ decide EJECUTAR / EXPLORAR / NO OPERAR cada candidato forex/oro en MT5
DEMO y aprende de todos (Thompson sampling). v1 (default) cerrado sin conclusiones (n = 11).
v2 opt-in (AI_AGENT_VERSION=2, AI_AGENT_EXPLORE_PCT=0.20): 24 features as-of, D1 de MT5 en vivo,
exploración a 0.10 % de riesgo (≤3/día, stop −2R), ajuste de realismo con el P&L real de MT5,
policy_tag por decisión. Evaluación pre-registrada desde el 2027-01-11 con ≥200 decisiones del
tag v2|eps0.20|xr0.10|r0.50|thr0.05|pv0.25|nv1.00|xmax3|xstop2.0 (t NW ≥ 2.50; predicción NO
PASA). NO cambiar parámetros del agente (cambia el tag; prior/ruido además DESCARTAN el modelo).
Ver cómo va: /agente, scripts/ai_agent_report.py (solo lectura) y la tarea programada
revision-semanal-agente-ia (lunes 09:04). Más actividad sin edge = más pérdida esperada.

LO QUE SIGUE: (1) si el user todavía no lo hizo: merge+push de v3.14.0, warm start v2 con el bot
apagado (python scripts/ai_agent_warmstart.py --version 2 --mt5-d1 --apply), .env y reinicio;
(2) checkpoint COT ya programado para el 2026-12-07 09:00 (tarea checkpoint-cot-reexperimento,
--cot-lag-days 4); (3) preguntarle al user qué quiere: NO abrir familias nuevas por defecto ni
re-cortar las cerradas (B4b, H-FND1 y H-FADE1 incluidas).

PROTOCOLO (no negociable): pre-registro commiteado ANTES de bajar datos; código congelado y
verificado con datos sintéticos ANTES de correr; k declarado, umbral t ≥ 2.50 (Newey-West
cuando hay autocorrelación o solapamiento); manifest con checksums; NUNCA usar como decisoria
una ventana marcada como vista en el ledger; diagnósticos post-hoc rotulados; si no pasa, la
familia se cierra sin re-cortes; adendas se commitean ANTES de volver a correr.

REGLAS DEL PROYECTO: real-money BLOQUEADO (ENABLE_REAL_TRADING=false HARDCODED; el user lo
pide seguido, la respuesta es no); Claude NO opera MT5 (solo lee, con mt5.initialize() SIN
credenciales; las órdenes las pone el bot/agente); order_send solo en
app/brokers/mt5_demo_trader.py; LLM/ML solo restan SALVO el agente IA en demo (excepción
acotada); todo lo nuevo opt-in OFF + soft-fail; nunca leer/mostrar el .env (cambios = darle al
user comandos de PowerShell); al tocar Settings sincronizar tests/test_score._settings() y
tests/test_alert_rules._settings(); versionado patch/minor sin saltos; el push a main lo hace
el user; una sola instancia del bot (verificar que no haya dos main.py).

Gotchas: las épocas de MT5 (deals, ticks, velas) están en hora del SERVIDOR (EET, UTC+2/+3),
no UTC — para resultados de posiciones usar history_deals_get(position=...) sin rango de
fechas; el cache D1 de MT5 (mt5_historical_cache) está congelado desde el 2026-06-15 (no lo
refresca el loop vivo); la DB viva pesa ~5.6 GB (no copiarla: extraer tablas con ATTACH en
mode=ro); consola cp1252 → sys.stdout.reconfigure(encoding="utf-8"); herramientas de
auditoría con pip --target fuera del venv; trading_data/ NO está en .gitignore (no hacer
git add -A con datos de research en el árbol); v3.13.3 (hora del servidor: MT5_SERVER_TZ=EET
opt-in + scripts/mt5_cache_tz_migrate.py para el cache H1; D1 no se convierte) ya está
integrada en la rama de v3.14.0.
```

---

## Prompt del 5-oct-2026 (histórico: reemplazado por el de arriba)

```
Retomamos Trading Alert AI (bot de trading LOCAL, Python 3.12, Windows, repo en
C:/Users/LENOVO/tradingalertaIA, venv en .venv). Estado al 6-oct-2026: v3.13.3, 863 tests
verdes. OJO: MT5 entrega las épocas en HORA DEL SERVIDOR (EET, UTC+2/+3), no UTC: ver
CHANGELOG v3.13.3 y MT5_SERVER_TZ. Demo MT5 NUEVA (MetaQuotes-Demo, ~3.000 USD). OJO: al 5-oct el bot estaba APAGADO
(DB cerrada el 4-oct 13:44): verificar que no haya ningún main.py y pedirle al user que lo
arranque con start_bot.ps1 (pide contraseña; no lo arranques vos).
Research: 25 familias de hipótesis probadas con pre-registro → 0 operables (la 25 = redes
neuronales H-NN1: peores que el boosting, no se integran).

Leé ANTES de tocar nada: research/LEDGER_FAMILIAS.md (las 25 familias, commits, ventanas
ya vistas y la "Lectura transversal"), PROXIMOS_PASOS.md (bloque del 5-oct), RESUMEN_COMPLETO.md
(§2.8-§2.10) y la memoria de Claude.

ESTADO: el plan del 4-oct (B4b, B11, B13, B12) se ejecutó COMPLETO el 5-oct; nada quedó
abierto. B4b NO PASÓ su chequeo secundario (solo por la t Newey-West: 2.34/2.46 < 2.50) →
el forward NO se corre y su colector NO se programa. Lo único cerca del umbral en 24
familias fueron primas de funding/carry que existieron y se arbitraron; las señales
direccionales sobre información pública no mostraron nada.

AGENTE IA (v3.13.0): app/ai_agent/ decide ejecutar o no operar cada candidato forex/gold en
MT5 demo y aprende de todos (Thompson sampling); opt-in ENABLE_AI_AGENT, magic 250501,
límites duros, comando /agente; evaluación pre-registrada en
research/AGENTE_IA_PREREGISTRO_2026-10-05.md (NO cambiar sus parámetros: reinicia la evaluación).

LO QUE SIGUE: (1) checkpoint COT ya programado para el 2026-12-07 09:00 (tarea
checkpoint-cot-reexperimento, --cot-lag-days 4); (2) preguntarle al user qué quiere: NO
abrir familias nuevas por defecto ni re-cortar las cerradas (B4b y H-FND1 fueron near-miss:
re-correrlas con otra t, otra ventana u otros parámetros sería dredging).

PROTOCOLO (no negociable): pre-registro commiteado ANTES de bajar datos; código congelado y
verificado con datos sintéticos ANTES de correr; k declarado, umbral t ≥ 2.50 (Newey-West
cuando hay autocorrelación o solapamiento); manifest con checksums; NUNCA usar como decisoria
una ventana marcada como vista en el ledger; diagnósticos post-hoc rotulados; si no pasa, la
familia se cierra sin re-cortes; adendas (bugs, formatos de la fuente) se commitean ANTES de
volver a correr y se reportan ambos resultados. Verificar sobre el dataset completo antes de
afirmar algo (ej. "sin huecos").

REGLAS DEL PROYECTO: real-money BLOQUEADO (ENABLE_REAL_TRADING=false HARDCODED; el user lo
pide seguido, la respuesta es no); order_send solo en app/brokers/mt5_demo_trader.py; LLM/ML
solo restan (vetar/bajar a paper) SALVO el agente IA en demo (excepción acotada,
v3.13.0); todo lo nuevo opt-in OFF + soft-fail; el research NO toca
el bot, flags, MT5 ni el .env; nunca leer/mostrar el .env ni secrets (cambios al .env = darle
al user comandos de PowerShell); al tocar Settings sincronizar tests/test_score._settings() y
tests/test_alert_rules._settings(); versionado patch/minor sin saltos; el push a main lo hace
el user; una sola instancia del bot a la vez (verificar que no haya dos main.py).

Gotchas: pandas 3 del venv usa datetime64[us]; klines de Binance mezclan archivos con y sin
encabezado (normalizar por archivo); spot 2025+ en µs; `metrics` de Binance trae vacías las
columnas de top traders en 2022 y registros con OI = 0; Hyperliquid liquidaba funding cada
8 h hasta 2023-06-08; FRED corta la conexión → EFFR del NY Fed; Yahoo 429 → UA Mozilla;
consola cp1252 → sys.stdout.reconfigure(encoding="utf-8"); herramientas de auditoría
(coverage, pyflakes) se instalan con pip --target en una carpeta aparte, NUNCA en el venv del
bot; tests/conftest.py vacía .test_dbs al terminar. Los scripts de
research/ramas_carry_scripts/ NO están revisados.
```

---

## Prompt del 4-oct-2026 (histórico: ese plan se ejecutó completo el 5-oct)

```
Retomamos Trading Alert AI (bot de trading LOCAL, Python 3.12, Windows, repo en
C:\Users\LENOVO\tradingalertaIA, venv en .venv). Estado al 4-oct-2026: v3.12.0, 808 tests
verdes, bot corriendo en demo MT5 NUEVA (MetaQuotes-Demo, ~3.000 USD) desde el 4-oct.
Research: 15 familias de hipótesis probadas con pre-registro → 0 operables.

Leé ANTES de tocar nada: research/LEDGER_FAMILIAS.md (las 15 familias, commits y ventanas
ya vistas), PROXIMOS_PASOS.md (bloque "PLAN PENDIENTE para el chat nuevo"), RESUMEN_COMPLETO.md
(§2.8-§2.10), los research/HIPOTESIS_2026-10-*.md y research/EVALUACION_RAMAS_CARRY_2026-10-04.md,
y la memoria de Claude.

LO QUE SIGUE (pedido del user, en este orden):
1. B4b paper hacia adelante: short Hyperliquid / long Binance, BTC+ETH. Pre-registro +
   colector scripts/b4b_forward_collector.py (datos en trading_data/b4b_forward/) +
   dejarlo programado. Evaluación ~abril 2027; chequeo secundario 2023-05 → 2024-09.
2. B11 resto: OI, top traders, taker buy/sell (k=3), ventana ~2021-12 → 2024-09.
3. B13 otros factores cruzados (reversión semanal, funding como predictor, OI),
   ventana 2020-01 → 2024-09.
4. B12 flujos de baja frecuencia (stablecoins, ETF, on-chain). El checkpoint COT ya está
   programado para el 2026-12-07 (--cot-lag-days 4).

PROTOCOLO (no negociable): pre-registro commiteado ANTES de bajar datos; código congelado y
verificado con datos sintéticos ANTES de correr; k declarado, umbral t ≥ 2.50; manifest con
checksums oficiales; NUNCA usar como decisoria una ventana marcada como vista en el ledger;
diagnósticos post-hoc rotulados como tales; si no pasa, la familia se cierra sin re-cortes.
Verificar sobre el dataset completo antes de afirmar algo (ej. "sin huecos").

REGLAS DEL PROYECTO: real-money BLOQUEADO (ENABLE_REAL_TRADING=false HARDCODED; el user lo
pide seguido, la respuesta es no); order_send solo en app/brokers/mt5_demo_trader.py; LLM/ML
solo restan (vetar/bajar a paper); todo lo nuevo opt-in OFF + soft-fail; el research NO toca
el bot, flags, MT5 ni el .env; nunca leer/mostrar el .env ni secrets (cambios al .env = darle
al user comandos de PowerShell); al tocar Settings sincronizar tests/test_score._settings() y
tests/test_alert_rules._settings(); versionado patch/minor sin saltos; el push a main lo hace
el user; una sola instancia del bot a la vez (verificar que no haya dos main.py).

Gotchas: pandas del venv usa datetime64[us]; klines de Binance mezclan archivos con y sin
encabezado (normalizar por archivo); spot 2025+ en µs; FRED corta la conexión → usar EFFR del
NY Fed; Yahoo 429 → UA Mozilla. Los scripts de research/ramas_carry_scripts/ NO están revisados.

Arrancá por el punto 1 (B4b): mostrame el borrador del pre-registro antes de commitearlo.
```

---

## Prompt de arranque histórico (setup de máquina; los datos de estado de abajo pueden estar viejos)

```
Sos Claude Code retomando el proyecto Trading Alert AI (sesión nueva / otra compu).

PROYECTO: bot de trading algorítmico LOCAL en Python 3.12 (Windows, PowerShell + venv).
REFOCUS v3.7.0: 100% LA BOLSA (acciones US + forex + oro). Las MEMECOINS se cortaron
(ENABLE_MEMECOIN_ENGINE=false; el user tiene un bot aparte para memecoins) y el SCALPING
se apagó. Decide con un strategy router (swing), hace paper trades y manda órdenes a MT5
demo (MetaQuotes-Demo, solo forex/oro ejecutan; acciones son paper). Real-money BLOQUEADO
por diseño (HARDCODED de verdad desde v3.9.3). Estado: v3.12.0, 808 tests verdes. Demo MT5 NUEVA desde 4-oct-2026 (~3.000 USD).
Research: 15 familias probadas con pre-registro, 0 operables (research/LEDGER_FAMILIAS.md).
El promotion gate tiene TODAS las estrategias en SHADOW → cero órdenes a MT5 (protección, no bug).

ANTES DE TOCAR NADA leé (en el repo, en este orden): RESUMEN_COMPLETO.md (todo en uno; §2.8 =
auditoría jul + búsqueda de edge), PROXIMOS_PASOS.md, CONTEXTO_MAESTRO_v3.8.0.md (arquitectura
vigente + addendum v3.9.4→v3.11.0 al final), CHANGELOG.md (historia hasta v3.11.0),
research/HIPOTESIS_*.md (los veredictos de edge, pre-registrados), GO_LIVE_RUNBOOK.md,
MAPA_DE_EDGE_Y_RUTA.md. Y la carpeta de memoria de Claude. Informe consolidado en
exports/INFORME_PROYECTO_2026-07.xlsx.

REGLAS INAMOVIBLES (no romper nunca):
- ENABLE_REAL_TRADING=false HARDCODED. Real-money prohibido sin autorización nueva y
  explícita del user.
- order_send SOLO en app/brokers/mt5_demo_trader.py. Ningún módulo nuevo lo llama directo.
- El LLM y el ML son SUBTRACTIVOS: solo pueden vetar / bajar-a-paper, JAMÁS forzar una orden.
- Todo lo nuevo (Ollama, asesor, ensemble veto, resumen diario) es opt-in OFF + soft-fail:
  si está apagado, el bot corre idéntico a antes.
- Nunca leer/mostrar el .env real ni secrets. Mantener pytest verde (808). Al tocar
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
  veredicto quedó PENDIENTE (Yahoo throttleo la IP — 429 confirmado incluso en 1 request;
  se completa cuando se libere). Queda listo stock_backtest_run.json (22 simbolos, 4 estrategias,
  category=stock) + el comando. El backtest de acciones SOLO sirve para DESCARTAR (survivorship).
- v3.9.0 (COT COLLECTOR): app/collectors/cot_collector.py + ENABLE_COT_COLLECTOR=false (opt-in).
  Baja Commitments of Traders de la CFTC (Socrata, 9 mercados FX+oro por cftc_contract_market_code)
  -> tabla cot_snapshots. SOLO captura para research (no señal ni gate). Primer input fuera del
  OHLCV (MAPA §3.4). YA VIVO en la Lenovo (ENABLE_COT_COLLECTOR=true; valida 9 mercados contra CFTC).
- v3.9.1 (FIX): bootstrap de sys.path en app/dashboard/streamlit_app.py (streamlit run tiraba
  ModuleNotFoundError 'app'). + chore: .gitignore cubre .env.bak* (backups del .env con secrets).
- v3.9.2 (FIXES auditoria): A1 -> forex_session_breakout calculaba el Asian range sobre velas de
  HACE 5 DIAS (tomaba las primeras 32 posicionales de un feed de 5d); ahora filtra por timestamp a
  la sesion 00:00-08:00 UTC de HOY. La estrategia MAS operada venia disparando contra niveles basura
  -> su -0.08R no testeaba la hipotesis real. + cambio 24h (closes[-97]) + guard de frescura del
  cache D1 del regime gate.
- v3.9.3 (FIXES auditoria): el calendar gate dejo de estar CIEGO (suma ff_calendar_nextweek.xml: el
  feed thisweek no rota hasta el finde -> 0 eventos futuros -> el gate era no-op, justo el caso
  USDCAD/BOC) + gap_check revivido + ENABLE_REAL_TRADING hardcodeado de verdad (se leia del env; la
  barrera real es _is_demo_account) + dashboard mode=ro + LogRedactor compartido + scripts/cot_backfill.py.
- COT backfill HECHO: 5 años de historia (2340 filas, 9 mercados, 2021-2026) -> habilita COT index a futuro.
- v3.10.0: forex_session_breakout REPLAYABLE (bar-time como reloj + guard de frescura anti-A1).
- v3.10.1: batch fixes auditoria total: A2 (scalping alert_id=0 -> ids negativos), M1 (mt5.shutdown
  global -> is_connected() re-valida), M2 (cooldown 429 Yahoo), M4 (dollar volumes), short trailing.
- v3.11.0: gold_friday_hold (regla congelada HARNESS-ONLY; el gate §11 dio NO PASA: tilt real,
  +0.040R < +0.10R -> real ≠ rentable; familia B cerrada).
- Research jul-2026 (todo NO-accionable, nada vivo): carry FRED cerrado (edge=interes, swap lo come),
  turn-of-month NO PASA, COT commercials NO PASA (familia COT cerrada), E2 OVERNIGHT pasa existencia
  (t~5, 1er pase del proyecto) pero NO accionable aca (US equities MOC/MOO, Sharpe 0.7, DD 40%).
- v3.12.0 (6-jul): paquete app/indicators/ (puros, replayables): VWAP (sesion/semana/mes, soft-fail
  sin volumen — Yahoo-forex da 0; el VWAP forex sale del cache D1 MT5), Hurst (escalado de varianza,
  ventanas 100/200/500, 3 regimenes) y footprint lite (anatomia velas, CLV, fuerza ATR, secuencias).
  Integrado INFORMATIVO (score/gates vivos intactos) + captura al entry -> ML dataset (ML sigue OFF)
  + VWAP gate downward-only (ENABLE_VWAP_GATE=false) + /claude_analyze (LLM a demanda, analista
  secundario; transporte Claude u Ollama).
- H-M1 (9-jul): trend multi-asset D1 via CFD (13 indices Yahoo 56yr + plata, financiamiento CFD
  modelado 5%/1% L/S): NO PASA (50% anios+, maxDD 166R; longs +0.21R/shorts -0.11R = drift, no edge).
  Era la ULTIMA familia abierta -> 10 familias con pre-registro, 0 tradeables: el espacio de
  hipotesis de ESTE vehiculo (CFD retail/MT5/D1) esta AGOTADO con evidencia. NO abrir mas.
  PROXIMO CHECKPOINT (unico pendiente): ~15-sep-2026 re-run scripts/cot_ml_experiment.py
  (barra pre-registrada: FX/oro OOS>=0.55 y delta COT>=+0.03). Mientras: DEJAR CORRER.
- EXPERIMENTO DE COT CORRIDO (21-jun, scripts/cot_ml_experiment.py, research-only, sin bump): features de
  COT + re-test temporal del ML. Veredicto SIN SEÑAL accionable (test primario OOS 0.533<0.55; corte FX/oro
  n=178 0.585->0.607 pero dentro del ruido en ~1 mes, COT semanal = ~4-5 lecturas distintas). ENABLE_ML_
  PREDICTOR sigue OFF; re-correr el script cuando el COT acumule mas meses. Detalle en RESUMEN_COMPLETO §2.7.
- AUDITORIA TOTAL + BUSQUEDA DE EDGE (jul-2026, v3.9.4->v3.11.0, RESUMEN §2.8): 3 agentes hallaron bugs ->
  v3.9.4 (A1 poison-message brickeaba el bot 24h + M3/M5), v3.9.5 (perf: indice, LLM fuera del hot path,
  WAL, poll 120, retencion), v3.10.0 (session_breakout replayable), v3.10.1 (A2/M1/M2/M4 + short trailing),
  v3.11.0 (gold_friday_hold harness-only). EDGE: 9 hipotesis con pre-registro/holdout/Bonferroni ->
  0 tradeables. COT (specs+commercials), carry, estacionalidad, session_breakout H1: MUERTOS. Viernes del
  oro y carry: REALES pero NO tradeables (costos/regimen). Overnight equities: REAL y sobrevive costos
  (~+7-10%/año) PERO fuera del scope del bot (US equities + MOC/MOO). Scripts en scripts/, veredictos en
  research/HIPOTESIS_*.md, data nueva en trading_data/research_rates.db. NO re-abrir familias cerradas.
- Scalping confirmado OFF (bot_state.scalping_active=false). OJO/gotcha: bot_state PISA al .env para
  scalping y bot_mode (prioridad CLI > bot_state > .env); si algo ignora el .env, revisa bot_state.
- GO_LIVE_RUNBOOK.md: el camino completo a real-money (gates, broker, codigo del dia-D,
  checklist). Real-money sigue HARDCODED bloqueado hasta que /readiness este verde.
- preflight.py (raiz del repo, NO commiteado): chequea config + secretos + MT5 + el refocus
  (memecoins off, scalping off, stock alerts on, v3.x mergeado) sin arrancar nada.

VERDAD DE FONDO: el cuello de DATA se CRUZÓ (403/400 trades con features al 18-jun), pero NO
destrabó edge. No hay edge PROBADO, CONFIRMADO POR CUATRO VÍAS: (1) el backtest sobre décadas
de D1 (ninguna estrategia pasa §11; el +4.7R del trend_following_d1 fue un ARTEFACTO de 1 trade
sintético de USDCHF); (2) el diagnóstico vivo del 16-jun (slicing por dirección: forex_session_
breakout pierde -0.57R en LONGS y gana +1.29R en SHORTS; oro longs -2.57R = régimen, no edge);
(3) AUC del ML sobre el set completo = 0.533 (ruido); (4) CV temporal del ML el 18-jun =
TimeSeriesSplit AUC 0.475 (PEOR que azar) OOS, aunque el k-fold con shuffle daba 0.69 y un split
simple 0.627 — la brecha es la firma de cero señal forward + overfitting in-sample. NO es
volatilidad (VIX ~16, calmo). El −11% del demo fue el bug de mayo; limpio queda ~plano (~$88.6k).
El LLM/ML filtran, explican, protegen — NO crean edge. **ACTUALIZACIÓN jul-2026: la búsqueda de
edge se CERRÓ con evidencia (RESUMEN §2.8): 9 hipótesis con rigor, 0 tradeables.** Familias muertas:
COT (specs+commercials, 40yr), carry, estacionalidad, session_breakout H1, ML. Reales-no-tradeables:
viernes del oro (+0.040R) y carry (2ª mitad neg + swap). Real-fuera-de-scope: overnight equities
(~+7-10%/año, sobrevive costos, PERO US equities + MOC/MOO, no el universo MT5-forex del bot).
Conclusión honesta: NO hay edge tradeable al alcance de este bot. Su valor es la infra + la disciplina.
Hardware: la GPU no banca LLM local rápido (~50s/gen) — nada de LLM en el hot path (v3.9.5 lo movió al
send-path); ContinuousLearner OFF en la Lenovo.

PRÓXIMOS PASOS (jul-2026): 1) CONSOLIDAR — dejar el bot corriendo en demo juntando data; es el camino
honesto. 2) NO ir a real-money (no hay edge que lo justifique; sigue HARDCODED bloqueado). 3) NO
re-abrir familias cerradas ni cherry-pickear (dredging); una hipótesis NUEVA requiere pre-registro nuevo
(research/HIPOTESIS_*.md). 4) NO más modelos/IA sobre los mismos datos (el mercado precia la info pública).
5) Si algún día se persigue el overnight en serio, es un PROYECTO APARTE (broker de acciones + infra
MOC/MOO), no este bot. Informe consolidado: exports/INFORME_PROYECTO_2026-07.xlsx.

PRIMERA TAREA AL RETOMAR:
1. python preflight.py (chequea todo: config, secretos, MT5, refocus). Debe decir LISTO.
2. correr: .\start_bot.ps1 (pide contraseña si STARTUP_PASSWORD_SHA256 está en .env).
3. verificar en Telegram: /health (debe decir v3.12.0) + /readiness + /exposicion + /scalping_status (inactivo).
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
