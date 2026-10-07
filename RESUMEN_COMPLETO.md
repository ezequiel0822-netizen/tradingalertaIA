# RESUMEN COMPLETO — Trading Alert AI (todo el proyecto en un documento)

> **Actualizado: 2026-10-06.** Este documento es autocontenido: leyéndolo, cualquier
> persona (o cualquier sesión nueva de Claude, con el modelo que sea) entiende QUÉ es
> el proyecto, DÓNDE está, POR QUÉ está así, y QUÉ sigue. Para profundizar:
> `CONTEXTO_MAESTRO_v3.8.0.md` (arquitectura vigente), `CHANGELOG.md` (historia por versión),
> `PROXIMOS_PASOS.md` (roadmap + reglas), `GO_LIVE_RUNBOOK.md` (camino a real-money),
> `HANDOFF.md` (migración de máquina), `MAPA_DE_EDGE_Y_RUTA.md` (la ruta de edge — el porqué).

---

## 1. Qué es

**Bot de trading algorítmico local y gratis** (Python 3.12, Windows, Lenovo del user).
Detecta oportunidades (memecoins / acciones US / forex / oro), decide con un **strategy
router** (5 estrategias swing + 2 scalping), hace **paper trades** y ejecuta órdenes a
**MT5 demo**. Tiene capas de IA local (Ollama, ML XGBoost) que son siempre
**SUBTRACTIVAS**: vetan, explican, registran, proponen — **jamás abren una orden**, con UNA
excepción acotada desde v3.13.0: el **agente IA en sandbox demo** (opt-in, ver §2.11).

**Real-money está BLOQUEADO por diseño (HARDCODED)** y así sigue hasta que los gates de
`/readiness` estén verdes. El user lo pidió varias veces (incluso "solo 300 MXN"); la
respuesta acordada es el `GO_LIVE_RUNBOOK.md`, no el flag. Razones: el dinero real no
entrena mejor que el demo (misma data, mismos outcomes), el apalancamiento hace que
"300 pesos" no sea la pérdida máxima, y no hay edge probado.

## 1.5 Qué hace, paso a paso (el ciclo, cada ~2-3 minutos)

1. **Recolecta**: precios y datos de memecoins (DexScreener/GeckoTerminal), acciones US,
   forex y oro (Yahoo/MT5), noticias, filings SEC, contexto macro (VIX/DXY) y el
   calendario económico (eventos high-impact).
2. **Analiza y puntúa**: cada candidato pasa por análisis técnico (RSI, ATR, MACD,
   patrones), scoring (0-100), chequeos de seguridad (para memecoins: honeypot, liquidez)
   y los pesos aprendidos de resultados pasados.
3. **Alerta**: lo mejor del ciclo te llega por Telegram (con caps por categoría y dedup
   para no spamear).
4. **Decide trades**: el strategy router elige la estrategia (breakout, mean reversion,
   session breakout, etc.) y abre **paper trades** (apuestas simuladas que registran
   todo: entrada, stop, target, features técnicos al momento de entrar).
5. **Ejecuta a MT5 demo** SOLO los paper trades de forex que sobreviven TODA la cadena
   de gates (§5). Memecoins y acciones quedan paper-only siempre.
6. **Gestiona lo abierto**: cada ciclo revisa las posiciones (trailing, breakeven
   post-TP1, salida por tiempo, por invalidación), reconcilia contra MT5 (cierra
   huérfanas, sincroniza stops) y registra el camino de R (exit shadow).
7. **Aprende**: al cerrar trades mide el R realizado neto de costos (excluyendo
   artifacts), refresca la expectancy por estrategia y por slice (sesión/dirección),
   ajusta pesos, y reentrenaría el ML si hubiera muestra (≥400).
8. **Reporta**: resumen diario al cierre NY, avisos de apertura/cierre, y responde
   tus comandos de Telegram en cualquier momento.

En una frase: **observa los mercados, apuesta en simulado, ejecuta a demo solo lo que
pasa todos los filtros, gestiona y mide cada posición con honestidad brutal, y aprende
de los resultados — sin tocar jamás dinero real.**

## 2. Estado EXACTO al 08-jul-2026

| Qué | Estado |
|---|---|
| Versión | **v3.13.3** (§2.11 = agente IA, auditoría de tests, alertas forex/oro y hora del servidor MT5; §2.9 = v3.12.0) |
| Tests | **801 verdes** |
| Foco | **100% LA BOLSA** (acciones US + forex + oro). Memecoins CORTADAS (bot aparte), scalping APAGADO |
| Bot | Corriendo en la Lenovo vía **`.\start_bot.ps1`**. Preflight: `python preflight.py` |
| Balance demo | ~$88,6xx (plano — el dinero real casi no se movió) |
| Protecciones activas | calendar gate ✓, cap USD \|3\| ✓, cooldown 60 min ✓, exit shadow ✓, regime gate ✓, COT collector ✓; **poll 120s** (v3.9.5) |
| Órdenes a MT5 | CERO desde el 17-jun: **el promotion gate tiene TODAS las estrategias en SHADOW** (todas con avg_r<0 probado). Es el gate protegiendo capital, no un bug |
| Búsqueda de edge | **CERRADA con evidencia (jul-2026): 9 hipótesis, 0 tradeables.** Ver §2.8. Informe consolidado en `exports/INFORME_PROYECTO_2026-07.xlsx` |
| Real-money | BLOQUEADO; `/readiness` = NO LISTO |
| Verdad de fondo | **No hay edge tradeable** en los mercados que el bot opera. 7 familias muertas; 2 señales reales-no-tradeables (oro-viernes, carry); 1 real-fuera-de-scope (overnight equities) |

## 2.5 Serie v3.6.0 — Backtest Replay Harness — EN CURSO (actualizado 2026-06-14)

> El 12-jun se decidió una rama nueva: el **Backtest Replay Harness** (reproduce
> la historia de MT5 barra por barra con las estrategias REALES, mide R neto con
> honestidad brutal — para que el backtest DESCUBRA y el demo CONFIRME). Fuente de
> verdad: `ESPEC_BACKTEST_REPLAY_v1.md` (el cómo, sesiones S1→S5) y
> `MAPA_DE_EDGE_Y_RUTA.md` (el porqué + la ruta v3.6→v3.8). Esto NO toca el bot
> vivo, NO cuenta para `/readiness` ni para los 400 de Fase D, y vive en tablas
> `backtest_*` separadas.

| Sesión | Qué | Estado |
|---|---|---|
| **S1** | Tablas `backtest_*` + repository CRUD + `historical_loader` + tests | **HECHA y en `main`** (commit `caff8c1`) |
| **S2** | `context_builder` + `regime_filter` + canario anti-look-ahead + tests | **HECHA y en `main`** (commit `c6efe6b`; +21 tests) |
| **S3** | `trade_simulator` (long/short/gaps/costos/slippage, B1–B13) + tests | **HECHA y en `main`** (commit `307f5d3`; +21 tests, números dorados a mano) |
| **S4** | `replay_harness` + `report` + primer run Modo A real + tests | **HECHA y en `main`** (commit `c03c26e`; +9 tests) |
| **S5** | `trend_following_d1` + veredicto §11 + bump **v3.6.0** + CHANGELOG/README/.env | **HECHA y en `main`** (commit `05f9731`; +13 tests) |

**Primer run Modo A real (S4, 14-jun)** — 4 estrategias existentes × 8 símbolos D1, **6.798 trades** simulados sobre décadas de historia en ~3 min. **Veredicto: las 3 que dispararon NO PASAN** (§11) — `mean_reversion` −0.123R (PF 0.60, n=1026), `momentum` −0.004R (~plano, n=5757), `breakout` +0.043R pero n=15. `forex_session_breakout` no disparó (en D1 `macro=None`, B11). Exactamente para lo que existe el harness: **descartó en minutos lo que el demo tardaría meses**, y confirmó que el edge no está en estas estrategias sobre D1. El reporte vive en `exports/backtest_1/` (gitignored).

**Profundidad histórica REAL medida el 14-jun** (loader corrido contra MT5 demo,
cache en SQLite): D1 con décadas — EURUSD/USDCHF/USDJPY **desde 1971**, AUDUSD/
GBPUSD/USDCAD/NZDUSD desde 1993-94, XAUUSD desde 2004 (5.654–14.300 barras). H1
**topado en 50.000 barras** por símbolo (~desde may-2018; es el límite del broker,
no truncamiento). **Caveat de honestidad:** el D1 pre-1999 de EUR es sintético
(el euro no existía); tratar esa franja con escepticismo (el ×1.25 de costos ya
empuja a lo conservador). El motor D1 (trend-following) tiene la profundidad que
necesita; el régimen-slicing va a poder responder si el +R del session breakout
era estructura o coyuntura.

**Veredicto S5 — `trend_following_d1` (hipótesis congelada Donchian D1):** avg **+4.7R**
que **parece edge enorme pero es un ARTEFACTO** — un solo trade de **+3724R** sobre data
sintética pre-1999 de USDCHF carga el **91% del P&L** (mediana real −1.03R; GBPUSD −0.26R).
El veredicto §11 lo **RECHAZA** bien (drawdown 57.5R > 25R; consistencia 58% < 60%) y la
nueva métrica de **concentración** del reporte lo grita. **NO PASA. NO va a Modo B.**
Es justo lo que el harness existe para hacer: atrapar el falso positivo seductor en vez
de creerle. Conclusión de la serie: **el edge no está en estas estrategias sobre D1.** El
camino sigue (COT, instrumentos descorrelacionados) en `MAPA_DE_EDGE_Y_RUTA.md`.

## 2.6 Post-v3.6.0 — refocus a la bolsa + regime gate + backtest acciones (17-jun)

**v3.7.0 — Refocus a LA BOLSA.** El user montó un bot APARTE para memecoins; este queda
100% mercados. Flag **`ENABLE_MEMECOIN_ENGINE`** (default true; en `false` el ciclo NI
COLECTA memecoins — los collectors DEX/Gecko corrían SIEMPRE, los flags `_TELEGRAM`/`_HUNTER`
solo silenciaban alertas). En el `.env` del user: memecoins off, **scalping off**, **stock
alerts on** (`ENABLE_STOCK_TELEGRAM=true`; antes las acciones eran mudas). Honestidad:
libera presupuesto del ciclo para la bolsa (eficiencia), **NO sube el win rate** (eso es edge).

**Diagnóstico del 16-jun (por qué pierde).** El slicing por dirección (`strategy_performance_
sliced`) lo gritó: `forex_session_breakout`/forex pierde **−0.57R en longs** y gana **+1.29R
en shorts**; oro longs **−2.57R**. **Los longs sangran porque pelean el régimen.** No es
volatilidad (VIX ~16, calmo, BAJÓ desde ~19). El balance demo está PLANO (~$88.6k); las
cifras rojas grandes que el user veía eran **memecoins en PAPEL** (no tocan dinero). El +R
de shorts NO es edge durable — es coyuntura (gira y sangra, como 9-jun ganó / 10-jun perdió).

**v3.8.0 — Regime gate vivo.** `jobs._regime_gate` + **`ENABLE_REGIME_GATE=false`** (opt-in):
antes del `order_send` a demo, clasifica el régimen D1 del símbolo (con `regime_filter` sobre
el cache) y si el trade va CONTRA la tendencia (long en `down` / short en `up`) lo deja
**paper-only**. **Downward-only** (como calendar gate y cap USD), soft-fail, solo forex/gold.
Cablea al vivo el `regime_filter` que vivía solo en el backtest. **Defensivo, NO edge**: deja
de pelear la tendencia; no garantiza ganar (el régimen se identifica tarde).

**Serie backtest de ACCIONES (`ESPEC_BACKTEST_STOCKS_v1.md`).**
- **S1** (HECHA): `app/backtest/stock_historical_loader.py` — Yahoo D1 ajustado por splits/
  dividendos (un split NO fabrica gap falso), `period1/period2` (no `range=max` que da
  mensual), anti-429. Validado: AAPL 11.469 barras (1980→2026), NVDA, SPY.
- **S2** (CÓDIGO HECHO): `replay_harness` con `RunConfig.category='stock'` + banner de
  **SURVIVORSHIP BIAS** en el report (las quebradas desaparecen de Yahoo → solo sirve para
  DESCARTAR, nunca confirmar). El run real con veredicto quedó PENDIENTE: Yahoo throttleó la
  IP (429) tras las pruebas; se completa cuando se libere o desde otra IP.
- **S3** (pendiente): `trend_following_d1` sobre acciones + veredicto (sin versión asignada aún).

**v3.9.0 — COT collector.** `app/collectors/cot_collector.py` + tabla `cot_snapshots` +
**`ENABLE_COT_COLLECTOR=false`** (opt-in). Baja Commitments of Traders de la CFTC (Socrata, 9
mercados FX+oro por `cftc_contract_market_code`) → SOLO captura para research (no señal ni gate).
Primer input fuera del OHLCV (`MAPA §3.4`). **YA VIVO** en la Lenovo (valida 9 mercados contra CFTC).

**v3.9.1 — Fix dashboard.** Bootstrap de `sys.path` en `app/dashboard/streamlit_app.py`
(`streamlit run` tiraba `ModuleNotFoundError 'app'`). + chore `.gitignore .env.bak*`.

**v3.9.1-v3.9.3 — fixes de la auditoría multi-agente.** v3.9.2: **bug A1** — `forex_session_breakout`
calculaba el Asian range sobre velas de hace ~5 días (32 primeras posicionales de un feed de 5d) →
ahora por timestamp a 00:00-08:00 UTC de hoy (la estrategia más operada disparaba contra niveles
basura); + cambio 24h + guard de frescura del cache D1. v3.9.3: calendar gate dejó de estar CIEGO
(`ff_calendar_nextweek.xml`) + gap_check revivido + **real-money hardcoded de verdad** (la barrera
real es `_is_demo_account`) + dashboard `mode=ro`/LogRedactor + `scripts/cot_backfill.py`. **COT
backfill HECHO: 5 años (2340 filas, 9 mercados).** Scalping confirmado OFF (`bot_state` pisa al `.env`).

**Lo que sigue (orden honesto):** dejar correr el libro vivo + que el COT acumule (lo más
valioso); completar el veredicto de acciones cuando Yahoo no throttlee (config listo); cuando el
COT tenga historia, re-correr el test temporal del ML con features de COT. **NO Fase D / más
modelos sobre los features actuales** — ya se probó (AUC 0.475 OOS) = sin señal. Lo aprendido vale
más que lo que el bot probablemente genere; el edge se DESCUBRE (info nueva), no se inyecta.

**Tests:** 657 (v3.6.0) → 660 (v3.7.0) → 672 (v3.8.0) → 676 (backtest acciones S1-S2) → 692 (v3.9.0 COT) → 694 (v3.9.2) → **697 (v3.9.3)**, todos verdes por conteo.

## 2.7 Experimento de COT — el experimento REAL de Fase D (CORRIDO el 21-jun-2026)

El handoff dejó como "próximo paso real": derivar features de COT (posicionamiento institucional
CFTC) y re-correr el test temporal del ML. El backfill de 5 años (2340 filas) lo habilitó YA, sin
esperar. Se hizo vía **`scripts/cot_ml_experiment.py`** (research-only: snapshot read-only de la DB
viva, anti-lookahead con lag de release CFTC de 3 días — el reporte del martes se publica el viernes;
mira SIEMPRE el TimeSeriesSplit OOS, nunca el k-fold).

**Dataset:** 642 trades cerrados no-artifact (374 feature-complete con rsi/atr), ventana **2026-05-20
→ 06-22 (~1 mes)**. COT: 2340 filas, 9 mercados.

| Test (AUC) | n | TimeSeriesSplit OOS |
|---|---|---|
| Baseline features actuales (set completo) | 642 | 0.483 |
| Baseline feature-complete | 374 | 0.509 |
| + COT (test primario) | 374 | **0.533** (Δ +0.024) |
| Solo trades FX/oro (sin COT) | 178 | 0.585 |
| Solo trades FX/oro **+ COT** | 178 | **0.607** |

**Veredicto: SIN SEÑAL accionable** — inconcluso-con-leve-indicio, NO un "no-edge" limpio. El baseline
reprodujo lo conocido (features actuales sin señal forward; el k-fold shuffle 0.63-0.67 es el espejismo
in-sample). El COT mete un empujón chico y, por 1ª vez, un corte (FX/oro, n=178) cruza 0.55 — PERO (a)
el lift propio del COT es solo +0.022 (0.585→0.607), bajo el umbral pre-registrado Δ≥0.03; (b) la ventana
es ~1 mes con COT semanal → solo ~4-5 lecturas distintas/mercado, así que el modelo agrupa por régimen,
no usa dinámica de posicionamiento; (c) n=178/5-fold = ~30 trades por fold test → CI del AUC ≈±0.10, así
que 0.585 vs 0.607 es indistinguible; (d) el gap in-sample/OOS persiste (k-fold 0.73 vs OOS 0.607).

**Decisión (MAPA §9, anti-autoengaño): NO promover, `ENABLE_ML_PREDICTOR` sigue OFF.** El umbral existe
justo para no perseguir un 0.607-sobre-178-trades-en-1-mes (misma forma del 0.627 que se desplomó a
0.475). **Re-correr el MISMO script cuando el COT acumule MÁS MESES** (que las features varíen entre
regímenes). Es el proyecto funcionando como fue diseñado: midió honesto y frenó antes de inyectar edge.

## 2.8 Auditoría total + búsqueda de edge exhaustiva (jul-2026) — v3.9.4→v3.11.0

**Auditoría de 3 agentes (2-jul)** encontró bugs reales y se arreglaron en cadena:
- **v3.9.4**: **A1 (ALTO)** — un comando de Telegram que crasheara brickeaba el bot hasta
  24h (offset no avanzaba → poison-message); + M3 (obsidian soft-fail) + M5 (límite 4096).
- **v3.9.5 — performance**: índice faltante (−11s/ciclo), **LLM fuera del hot path** (~30-50s/
  ciclo que decoraba alertas no enviadas), **WAL** (mata "database is locked"), poll 60→120s,
  retención 90d. Ciclo ~92s→~35-45s; suite de tests 4.5× más rápida.
- **v3.10.0**: `forex_session_breakout` **replayable** (bar-time en vez de `datetime.now()`;
  antes era irreplayable → cero validación histórica).
- **v3.10.1**: A2 (scalping alert_id), M1 (`mt5.shutdown` global dejaba el reader ciego),
  M2 (cooldown 429), M4 (dollar-volumes desalineados), short trailing + mark al ask.
- **v3.11.0**: `gold_friday_hold` (regla congelada del gate §11, harness-only).

**Búsqueda de edge — el cambio de paradigma que funcionó**: la unidad de análisis pasó de
"trade vivo" (meses de espera) a "barra/semana histórica" backfilleable (veredicto en horas).
Protocolo estricto: pre-registro commiteado ANTES de correr (`research/HIPOTESIS_*.md`),
holdout, Bonferroni. **9 hipótesis, 0 tradeables:**

| Familia | Muestra | Veredicto |
|---|---|---|
| ML features actuales / +COT | 374 / 178 trades | MUERTO (0.475 / 0.607 ruido) |
| COT × precio (specs, 40yr) | 12.689 sem | MUERTO (2ª mitad negativa) |
| COT commercials (smart money) | 12.689 sem | MUERTO (ruido) → **COT cerrado por ambos lados** |
| forex_session_breakout (H1, 8yr) | 14.213 trades | MUERTO (−0.16R, 0% años+) |
| Turn-of-month / estacionalidad | SPY 34yr | MUERTO/débil (t=1.3) |
| **Viernes del oro** (§11, 21yr) | 1.081 trades | **REAL pero NO tradeable** (+0.040R < 0.10) |
| **Carry trade** (FRED tasas, 31yr) | 6.524 trades | **REAL pero NO tradeable** (2ª mitad neg + swap) |
| **Overnight equities** (34yr) | SPY/QQQ/IWM | **REAL, sobrevive costos** (~+7-10%/año) PERO **fuera del scope del bot** (US equities + MOC/MOO) |

**Conclusión honesta**: no hay edge tradeable al alcance de este bot (forex/oro en MT5). Las
señales reales que aparecieron o no sobreviven costos, o están en un mercado que el bot no
opera. El valor del proyecto es la infraestructura + la disciplina de descartar rápido y no
autoengañarse — no una estrategia rentable. Más IA/modelos NO ayudan (el mercado precia la info
pública). Data nueva bajada: tasas FRED (`research_rates.db`), índices SPY/QQQ/IWM.

## 2.9 v3.12.0 (6-jul-2026) — VWAP + Hurst + footprint lite: la foto técnica se enriquece SIN tocar el score vivo

Detalle completo en CHANGELOG. Todo informativo + captura para research; ningún gate activo cambia:
- Paquete **`app/indicators/`** (puros, bar-time, replayables): **VWAP** (sesión/semana/mes, hlc3, soft-fail sin volumen — Yahoo-forex da 0), **Hurst** (escalado de varianza, ventanas 100/200/500, etiquetado honesto, 3 regímenes), **footprint lite** (anatomía de vela, CLV, fuerza por ATR, secuencias 1-3 velas, anomalía de volumen).
- Integración informativa: `TechnicalPattern` + IA Pro (score/confidence INTACTOS, con test) + alertas (textos sin needles del feature_extractor, test de regresión) + `/patron`/`/pro` + dashboard. El checklist de IA Pro (output muerto desde siempre) ahora se muestra en `/pro`.
- Captura al entry → ML dataset (`vwap_dist_pct`, `vwap_week_dist_pct`, `hurst_entry`, `clv_entry`, `candle_strength`); **`ml_predictor` congelado, ML sigue OFF** (captura para research, como el COT).
- **VWAP gate** (`ENABLE_VWAP_GATE=false`): downward-only, molde del regime gate, VWAP semanal del cache D1 MT5. Opt-in OFF.
- **`/claude_analyze SYMBOL`** (alias `/analisis_llm`): análisis técnico narrado por LLM (VWAP+velas+Hurst+noticias), a demanda, transporte Claude u Ollama, gated por `ENABLE_LLM_ADVISOR`. Analista secundario: jamás señales.

## 2.10 Research fuera del vehículo (9-jul → 5-oct-2026): 25 familias, 0 operables (la 26, H-FADE1, en §2.12)

Registro completo (fecha, datos, veredicto, commits, ventanas ya vistas): **`research/LEDGER_FAMILIAS.md`**.
- **H-M1** (9-jul): trend multi-asset D1 vía CFD → NO PASA; agota el vehículo CFD/MT5/D1.
- El bot estuvo **apagado 12-ago → 3-oct**; el checkpoint COT del 15-sep no corrió. Re-encendido el **4-oct** con una **demo MT5 nueva (~3.000 USD)** porque la vieja venció. COT rellenado; checkpoint reprogramado al **2026-12-07** con `--cot-lag-days 4` (se encontró y corrigió un leakage: con lag 3 se usaba el reporte del viernes antes de su publicación).
- **H-MS1** (3/4-oct): microestructura L1 BTCUSDT perp, a partir de una spec externa (auditada; su v5.0 adoptó la auditoría). Señal real (AUC 0.576) pero +0.42 bps brutos vs ~8 bps de costo → NO-GO formal. Rebates de market making verificados: inalcanzables a escala retail.
- **H-FC1** (4-oct): funding carry BTC/ETH → 3-3.5 %/año vs EFFR 4.04 % → NO PASA (prima arbitrada).
- **Tanda cripto k=3** (4-oct): H-FC2 carry altcoins (−12 % CAGR), H-XS1 momentum cruzado (crash en la 2ª mitad), H-POS1 posicionamiento (t 0.69) → las tres NO PASAN.
- **Ramas del carry** (agente, sin pre-registro): todo ≈ tasa libre; único candidato dudoso **B4b** short Hyperliquid / long Binance. Su ventana ya quedó vista → solo vale un test hacia adelante.
- **5-oct — plan B4b/B11/B13/B12 ejecutado completo (familias 16-24), las nueve NO PASAN:**
  - **B4b** short Hyperliquid / long Binance (3x): NO PASA la secundaria 2023-06 → 2024-09 solo por la t Newey-West (BTC 2.34, ETH 2.46 < 2.50) con exceso +9.1 %/año, DD ≤ 2.8 % y 0 liquidaciones. Near-miss; el spread ya se comprimió. El forward no se corre.
  - **B11** OI / top traders (H-TT1b) / flujo taker en BTC/ETH: |t| ≤ 1.3. La fuente no trae top traders en 2022; bug de OI = 0 corregido y declarado.
  - **B13** alts 2020-2024 (339 perps point-in-time): reversión semanal −34 %/año; funding como predictor +27 %/año pero t 2.26 y 2ª mitad negativa (+67 % en 2020 → −30 % en 2024).
  - **B12** stablecoins / flujo a exchanges / MVRV como predictores semanales: t ≤ 1.9. ETF flows no testeables honestamente hoy.
  - **Lectura transversal:** lo único cerca del umbral fueron primas de funding/carry que existieron y se arbitraron; las señales direccionales sobre información pública no muestran nada. Detalle: `research/LEDGER_FAMILIAS.md`.
- **H-NN1 (5-oct, redes neuronales):** en microestructura L1 de BTCUSDT, sobre 86 días nunca vistos, las redes (MLP-23 y MLP-SEQ con 30 s de historia) salieron PEORES que el boosting (ΔAUC −0.005 y −0.018, significativo) y la economía pierde ~−7.5 bps/trade. El HGB de H-MS1 replica su señal fuera de muestra (AUC 0.595/0.576): real, estable y ~13× menor que el costo. Más modelo no rescata poca señal → no integrar redes.
- **Sigue en pie:** checkpoint COT del **2026-12-07 09:00** (`--cot-lag-days 4`). El bot estaba APAGADO al 5-oct (DB cerrada el 4-oct 13:44): re-arrancar con `.\start_bot.ps1`.

## 2.11 v3.13.0 (5-oct-2026) — Agente IA en sandbox demo

El user pidió una IA que opere sola y aprenda practicando. Se construyó en DEMO: `app/ai_agent/`
(regresión bayesiana + Thompson sampling sobre 16 features) decide para cada candidato forex/gold
si EJECUTAR en MT5 demo o NO OPERAR, y aprende de TODOS los candidatos con el R realizado de su
paper trade. Reemplaza los filtros de edge (promotion/ML/LLM/régimen/VWAP) solo para sus
decisiones; mantiene los de riesgo (calendario, cap USD, halt) y suma límites propios (≤0.5 % por
trade con lote achicado, ≤3 abiertas, ≤6/día, stop diario −3R). Magic MT5 250501, `/agente`,
opt-in OFF, soft-fail, real-money bloqueado. **Excepción explícita a la regla "la IA solo
resta"**, acotada a la demo. Evaluación pre-registrada antes de encenderlo
(`research/AGENTE_IA_PREREGISTRO_2026-10-05.md`); predicción honesta: aprende a casi no operar.
Fix latente de paso: `draft.volume = x` sobre dataclass frozen en la rama ML (OFF).

**v3.13.1 (5-oct) — auditoría de tests desde cero** (cobertura por test, AST, aislamiento por
archivo, red bloqueada, pyflakes, revisión manual): 0 tests duplicados, 0 dependientes del
orden, 0 con red; 4 tests que no probaban nada, arreglados (uno no podía fallar nunca); bug
real en `lifecycle_manager` (el cierre parcial en TP1 aflojaba un trailing stop) arreglado;
`.test_dbs` ya no crece (~400 MB). Cobertura de `app/` 76 %. Pendiente de decisión del user:
`realized_pnl_today` no suma la mitad cobrada en TP1 (kill-switch algo más sensible). 829 tests.

**v3.13.2 (5-oct) — alertas forex/oro**: llegaban como "TOP MEMECOINS" con "caída est. 90 %" porque
forex/oro usaban el estimador y el score de memecoins, y `should_send_alert` dejaba pasar TODO snapshot
forex/oro. Ahora: estimador propio (movimiento observado, sin inventar subidas/caídas), envío solo con
movimiento notable, título por mercado y comandos de Telegram sin memecoins con el motor apagado. 838 tests.

**v3.13.3 (6-oct) — hora del servidor MT5**: MT5 entrega las épocas (velas, ticks, deals) en hora del
SERVIDOR (MetaQuotes-Demo: EET, UTC+2 invierno / UTC+3 verano, regla UE; medido). En vivo no pegaba (forex
viene de Yahoo); en el harness H1 `forex_session_breakout` corrió con las sesiones 2-3 h corridas (familia 5:
veredicto intacto, nota en el ledger). Fix opt-in `MT5_SERVER_TZ=EET` (convierte ticks e intradía; D1 queda
como fecha de trading) + `mt5_cache_meta` + `scripts/mt5_cache_tz_migrate.py` para el cache H1. 863 tests.

## 2.12 v3.14.0 (6-oct-2026) — Agente IA v2 + H-FADE1

El user pidió "el agente más activo y mejorado" (antes había pedido que Claude operara su demo
para "generar el 10 %": se declinó; Claude solo LEE MT5 y no se usan metas de ganancia).

- **Cierre de v1 sin conclusiones** (n = 11; agente −1.08R, ejecutar todo −9.83R) y **pre-registro
  v2 commiteado antes del código**. Evaluación v2 desde el 2027-01-11 con ≥ 200 decisiones del tag
  `v2|eps0.20|xr0.10|r0.50|thr0.05|pv0.25|nv1.00|xmax3|xstop2.0`, t NW ≥ 2.50; predicción NO PASA.
- **v2 (opt-in `AI_AGENT_VERSION=2`)**: 24 features as-of (evento high a ±2 h, COT index con lag 4
  días, costo/riesgo del trade, lunes/viernes, hora, racha de la estrategia); régimen/VWAP con el
  D1 de MT5 en vivo (el cache D1 está congelado desde el 15-jun y v1 los tuvo en 0); exploración
  `AI_AGENT_EXPLORE_PCT` a 0.10 % de riesgo con presupuesto propio; ajuste de realismo con el
  P&L REAL de MT5 de sus órdenes (`closed_position_outcome`, solo lectura); `policy_tag` por fila.
- **Honestidad**: el agente aprende del paper de TODOS los candidatos (información completa), así
  que ejecutar más NO acelera el aprendizaje; sin edge, la exploración cuesta ~0.2-0.3 % del equity
  por día de mercado. Lo que sí suma candidatos: subir `MAX_OPEN_TRADES_TOTAL` (lleno el 96 % del
  tiempo desde el 1-sep porque cuenta acciones que duran ~7 días).
- **Herramientas**: warm start v2 (`--version 2 --mt5-d1`), `scripts/ai_agent_report.py` (mode=ro,
  `--evaluate` bloqueado hasta 2027-01-11), tarea programada `revision-semanal-agente-ia`, línea
  del agente en el resumen diario de Telegram.
- **H-FADE1 (familia 26)**: NO PASA las tres estrategias (familia 26): el reverso pierde −0.37 / −0.21 / −0.19R por trade (t NW −18.8 / −23.7 / −12.4) en M15 2023-2025. El bruto es ≈ 0 en ambas direcciones y se pierde el costo de stops cortísimos (0.19-0.32R por trade): las señales son ruido y darlas vuelta vuelve a pagar el spread. Post-hoc: el −0.92R del paper vivo de mean_reversion no se reproduce (directo bruto −0.01R) → artefacto de la simulación paper. El agente NO suma acción "fade". `research/HIPOTESIS_2026-10-06_fade.md`.

## 2.13 v3.14.1 + v3.15.0 (7-oct-2026) — precio mezclado del oro y agentes sombra

El user preguntó "¿cómo va el agente? ¿se pueden agregar más?" y después pidió "haz todo ya".

- **Bug de datos (v3.14.1, opt-in `PAPER_PRICE_FROM_MT5`)**:
  - Los paper trades de oro se abrían con el futuro de Yahoo (GC=F) y se marcaban con el spot de MT5 (XAUUSD). Desfase mediano de **+$21**; en el **53 %** de 311 trades, mayor o igual a un stop entero.
  - Longs −1.68R y shorts +0.64R, casi todo artefacto. Dos trades del agente "tocaron" el stop al minuto (−3.5R / −5.1R).
  - En forex el desfase medio es chico (+0.03R), pero con stops de 2-3 pips rompe la orden REAL: NZDUSD #26 entró en MT5 2.1 pips bajo Yahoo con el SL/TP del paper (stop real de 0.4 pips). Dio **+10.95R real** contra +1.69R paper y dejó el ajuste de realismo ĝ clavado en +0.25R.
  - **Fix**: los niveles se trasladan al precio de MT5 al abrir (mismas distancias) y cada trade se marca solo con su fuente. El agente no aprende del "oro mezclado" y ĝ solo usa ejecuciones de fuente única.
  - **Protocolo**: adendas 1 y 2 al pre-registro v2, commiteadas ANTES del código. Se evalúa el tag `...|px1` (flag + modelo reconstruido con `--exclude-mixed-gold`). El tag original se reporta aparte. Fechas, criterios y predicción sin cambios.
- **Agentes sombra (v3.15.0)**:
  - Más agentes operando la misma cuenta no suman: mismos candidatos, mismo aprendizaje (información completa), mismos topes, y ensucian la evaluación.
  - Se armaron 3 sombras que deciden sobre los MISMOS candidatos y NUNCA operan: `codicioso`, `prudente` y `simple`.
  - Pre-registro propio commiteado antes del código (k = 3, t NW ≥ 2.50, desde el 2027-01-11 sobre `px1`). Predicción: NO PASA ninguna.
  - Las muestra el reporte; `/agente`, solo con `AI_AGENT_SHADOWS=true`.
- **Post-hoc (rotulado)**: la mezcla de fuentes NO explica el −0.93R del paper de mean_reversion (el "artefacto" de H-FADE1).
  - En forex, el desfase medio a la apertura es +0.09R y la media sigue en −0.99R sin oro.
  - El oro mezclado es 38 de 195 trades, con media −0.68R.
  - Queda abierto, sin investigar: el cierre del paper al precio sondeado (no en el stop) con stops cortísimos.

**H-FVG1 / H-IFVG1 (familia 27, 7-oct)**: el user pidió "leer todas las posibilidades" (noticias,
estrategias, flujo, FVG/iFVG, volumen, patrones). Todo eso ya estaba probado o dentro del agente, salvo los
FVG/iFVG. Se probaron con pre-registro en H1 de MT5 (2011-2017, no vista) → NO PASAN: −0.24 / −0.27R por
trade, bruto ya negativo (el TP de 2R sale el 31 %), costo ~0.19R. 27 familias, 0 operables.

## 3. La verdad de fondo (la filosofía del proyecto)

1. **El cuello de botella es DATA, no código.** No hay edge probado: el único +R agregado
   (`forex_session_breakout` +0.38R, n=86) lo carga **el lado short de un régimen** (shorts
   +1.81R vs longs −0.31R) — se da vuelta cuando el mercado gira. Quedó demostrado en vivo:
   el 9-jun ganó +$312 y el 10-jun el mismo libro perdió.
2. **El −11% histórico del demo fue un BUG, no estrategia**: el feedback-loop/instant-kill
   de mayo (~746 artifacts, corregidos en v2.6.7–v2.7.1). Limpio de artifacts: ~−2% desde
   el inicio; desde el baseline 2026-06-03, **~plano** (≈−0.004% sobre 105 trades ejecutados al 18-jun). `/performance` lo mide.
3. **El LLM/ML no crean edge** — filtran, explican y protegen. La "potencia" tipo
   IA-grande no compra rentabilidad: un bot simple CON edge le gana siempre a un bot
   genio SIN edge. El edge sale de data + research, validado fuera de muestra. **Probado
   18-jun:** con el gate de datos cumplido (403/400), el ML sobre los features actuales dio
   **AUC temporal 0.475 OOS (peor que azar)** — el k-fold 0.69 era peeking in-sample. Sin señal
   forward; `ENABLE_ML_PREDICTOR` queda OFF. **Probado de nuevo el 21-jun con features de COT** (§2.7):
   el corte FX/oro nudgea a 0.607 OOS pero dentro del ruido (n=178, ~1 mes) y bajo el umbral → ML sigue
   OFF; re-correr cuando el COT acumule meses. El edge sale de INFORMACIÓN nueva con muestra, no de modelos.
4. **Todo se mide antes de creerse** (anti-autoengaño): gates que solo degradan a paper,
   shadow modes que simulan antes de activar, exclusión de artifacts a query-time.

## 4. Qué se construyó (serie v3 — sesiones 8 al 11 de junio de 2026)

| Versión | Qué | Estado |
|---|---|---|
| v3.2.0 | **Fase C — ContinuousLearner**: lección LLM por trade cerrado → tabla `trade_lessons`; agrupa repetidas y PROPONE por Telegram (no aplica) | Código sano; **OFF en la Lenovo por hardware** |
| v3.3.0 | **`/performance`** (rendimiento desde baseline limpio post-bug, no falsea el balance) + **`/readiness`** (los 5 gates hacia real-money, veredicto honesto) | Activo |
| v3.3.1 | Caché TTL + cooldown 429 para GeckoTerminal (mata el spam de rate-limit) | Activo |
| v3.4.0 | **Exit shadow**: registra el camino de R de cada trade abierto (`trade_r_samples`) y **`/exit_analysis`** simula un trailing sobre el camino REAL (arma en +1R, excluye scalps/partial/mid-life) vs la salida real. Hallazgo: forex/oro NO tienen trailing efectivo (usan params de memecoin, activación +50% inalcanzable) | **Registrando** (~6k muestras) |
| v3.5.0 | **Calendar gate** (conecta `is_safe_window` que estaba HUÉRFANO — bug real: el 10-jun abrió USDCAD 18 min antes del BOC que estaba en su propia DB) + **cap de exposición USD** (`/exposicion`; el 10-jun 7 posiciones eran UNA apuesta long-USD y un movimiento las barrió juntas) | **Activos** |
| — | `GO_LIVE_RUNBOOK.md` (camino a real-money) + `start_bot.ps1` (contraseña de arranque) + auditoría de seguridad | Hecho |

Antes de esta serie (resumen): v2.7.0 midió honesto (realized-R + promotion gate),
v2.8.0 edge slicing, v2.9.0 capa ML XGBoost (dormida hasta 400 trades), v2.10–v3.1
la capa LLM local completa (asesor, veto ensemble, resumen diario).

## 5. Cadena de seguridad de una orden (cómo NO se pierde plata por un bug)

Una orden a MT5 demo solo sale si pasa TODO esto (cada gate solo puede DEGRADAR a paper):
```
reglas de estrategia → risk manager (caps, cooldown 60min) → promotion gate
(expectancy probada) → ML gate (dormido <400) → ensemble LLM veto (off) →
calendar gate (evento high-impact cerca → paper) → cap USD (concentración → paper)
→ mt5_demo_trader (ÚNICO archivo con order_send, validaciones demo-only)
```
Más: kill-switch diario, reconciler de huérfanas, dedup, y real-money hardcoded OFF.

## 6. Operación diaria (lo que hace el user)

- **Arrancar**: `cd C:\Users\LENOVO\tradingalertaIA` → `.\start_bot.ps1` (pide contraseña).
- **Una sola máquina a la vez** contra la cuenta MT5 demo.
- **Comandos Telegram**: `/health` (versión), `/performance` (cuenta limpia),
  `/readiness` (gates a real-money), `/exit_analysis` (¿trailing ayuda?), `/exposicion`
  (apuestas al dólar abiertas), `/expectancy`, `/edge`, `/market` (LLM, ~50s), `/porque_perdi`.
- **El LLM local es LENTO en esta máquina** (~50s/respuesta, corre en CPU): es normal,
  no es un bug. Por eso ContinuousLearner está OFF acá.

## 7. Seguridad (auditoría 2026-06-11)

✅ Telegram autoriza por chat_id exacto (nadie más puede dar comandos) · `.env` JAMÁS
commiteado · `LogRedactor` enmascara el token en logs · SQL 100% parametrizado · sin
eval/exec/shell=True · timeouts en toda la red · repo privado · contraseña de arranque
(SHA-256 en `.env`, opt-in). Menores aceptados: email personal en un doc de obsidian
(repo privado); `pickle.load` de modelos locales. La protección real de los secretos:
contraseña de Windows + BitLocker.

## 8. Roadmap — qué sigue y sus GATES (no negociables)

1. **AHORA:** **dejar correr** el libro vivo + que el **COT acumule MÁS MESES** — es lo que
   destraba el próximo experimento real (el re-test del COT del 21-jun salió sin señal por
   ventana de ~1 mes; necesita más lecturas distintas). El gate de data de Fase D ya se cruzó
   (403/400). El Backtest Replay Harness (v3.6.0) ya está HECHO y cubre forex + acciones; se usa
   para descartar hipótesis offline, no toca el ciclo vivo.
2. **En días**: `/exit_analysis` con muestra → si delta +R robusto, activar trailing de
   forex CON evidencia (cambiar los params de `lifecycle_manager` para forex).
3. **Fase D — AdvancedPredictor**: gate de data CRUZADO (403/400) PERO probada y descartada sobre los
   features actuales (CV temporal 0.475 OOS) y con features de COT (21-jun, §2.7: 0.607 OOS pero dentro
   del ruido). **NO construir el ensemble LightGBM/RF; `ENABLE_ML_PREDICTOR` sigue OFF.** Re-evaluar SOLO
   cuando cambien los INPUTS con muestra (re-correr `scripts/cot_ml_experiment.py` con más meses de COT,
   mirando TimeSeriesSplit). Si algún día aplica: EXTENDER `ml_predictor.py`, no reemplazar.
4. **Fase E — StrategyMutator** (auto-evolución: propone variante, paper ≥5 días,
   promueve solo si gana): GATE ≥1 estrategia R+ neto + 3 meses de data.
5. **Real-money**: `GO_LIVE_RUNBOOK.md` — 5 gates verdes en `/readiness` + broker
   micro + sizing reconstruido + audit del camino real + decisión explícita del user.

## 9. Reglas inamovibles (para cualquier sesión futura)

- `ENABLE_REAL_TRADING=false` **HARDCODED**. No desbloquear aunque el user lo pida
  directo — mostrar `/readiness` y el runbook. (Ya lo pidió 3+ veces; está en la
  memoria de Claude con el razonamiento completo.)
- `order_send` SOLO en `mt5_demo_trader.py`. No tocar ese archivo ni `mt5_reconciler.py`.
- LLM/ML **SUBTRACTIVOS**: vetan/degradan, jamás fuerzan ni habilitan.
- Todo lo nuevo: **opt-in OFF + soft-fail** (apagado o roto = bot idéntico).
- **721 tests verdes siempre**. Settings nuevos → sincronizar `_settings()` de
  `test_score` Y `test_alert_rules`. Cada módulo nuevo trae su test file.
- **Versionado**: patch (v3.5.1) para fixes, minor (v3.6.0) solo features reales,
  sin saltar números.
- Nunca leer/mostrar el `.env` real. Nada de LLM en el hot path del ciclo (hardware).

## 10. Lecciones de proceso de esta sesión (para no repetir errores)

- PowerShell 5.1 lee `.ps1` sin BOM como ANSI → scripts en **ASCII puro** (sin ñ/—).
- `pytest | tail` enmascara el exit code → verificar el **conteo**, no el exit.
- Archivos de mensaje de commit van **FUERA** del repo (`$TEMP`) — `git add -A` los coló 2 veces.
- El user mergea con `git merge claude/<branch>` + `git push origin main` (no usa PRs web).
- Los "techos optimistas" (mfe/mae) mienten: simular sobre el camino real, con activación
  y exclusiones, o el análisis recomienda cambios equivocados.
- **Para ML de trading, el k-fold con shuffle MIENTE** (espía entre épocas): usar SIEMPRE
  TimeSeriesSplit (train pasado → test futuro). El 18-jun el k-fold daba 0.69 y el temporal 0.475 OOS.
- Los backups del `.env` (`.env.bak*`) tienen secrets → cubiertos en `.gitignore` (v3.9.1).

## 11. Prompt para arrancar un chat nuevo (copiá/pegá)

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

*Construido entre el user y Claude, con una regla por encima de todas: medir antes de
creer, proteger antes de arriesgar, y decir la verdad aunque no sea la respuesta que
se quiere escuchar.*
