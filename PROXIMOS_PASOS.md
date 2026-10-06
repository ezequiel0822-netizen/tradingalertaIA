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

> **⚠️ ACTUALIZACIÓN 6-jul-2026: v3.12.0, 801 tests verdes.** Post-v3.9.3: v3.10.0
> (session breakout replayable, bar-time), v3.10.1 (fixes auditoría A2/M1/M2/M4 +
> short trailing), v3.11.0 (`gold_friday_hold` harness-only; §11 = NO PASA, tilt real
> pero no tradeable), research jul (carry/ToM/COT-commercials cerrados; overnight real
> pero NO accionable), y **v3.12.0**: `app/indicators/` (VWAP + Hurst + footprint lite,
> puros/replayables), integración INFORMATIVA (score/gates intactos), captura al entry
> → ML dataset (ML sigue OFF), VWAP gate downward-only (`ENABLE_VWAP_GATE=false`) y
> `/claude_analyze` (LLM a demanda, analista secundario). Detalle: CHANGELOG.md y
> RESUMEN_COMPLETO §2.8 (auditoría+edge) y §2.9 (v3.12.0). Lo de abajo sigue siendo la base histórica.
>
> **⚠️ 9-jul-2026 — H-M1 (trend multi-asset D1 vía CFD): NO PASA, familia CERRADA.**
> Era la ÚLTIMA familia abierta del MAPA §8. Con ella: **10 familias probadas con
> pre-registro → 0 tradeables. El espacio de hipótesis de ESTE VEHÍCULO (CFD retail/
> MT5/D1) está AGOTADO con evidencia.** 808 tests. Detalle: CHANGELOG (research) +
> `research/HIPOTESIS_2026-07-09_multiasset.md`. NO abrir hipótesis nuevas sobre
> este vehículo: no queda ninguna sin veredicto.
>
> **⚠️ 3-oct-2026 — estado del checkpoint COT y H-MS1.** El checkpoint del 15-sep NO corrió:
> la app estaba cerrada, la tarea arrancó recién el 3-oct y se cortó al medir la data, sin
> veredicto. Además el bot estuvo APAGADO del 12-ago al 3-oct: desde el run de junio hay solo
> ~7 semanas nuevas (416 trades cerrados, 4 lecturas COT) → por debajo de la barra de ~3
> meses del propio checkpoint. Decisión pendiente del user: prender el bot + rellenar COT
> con `scripts/cot_backfill.py` + reprogramar el checkpoint ~2 meses (recomendado). Aparte:
> **H-MS1 microestructura L1 (BTCUSDT perp) corrida y CERRADA**: señal real (AUC 0.576)
> pero +0.42 bps brutos contra ~8 bps de costo. Detalle en CHANGELOG.
>
> **⚠️ 4-oct-2026 — checkpoint COT reprogramado al 7-dic + corrección de leakage.** Bot
> re-encendido el 4-oct (demo MT5 nueva). COT rellenado hasta el reporte del 2026-09-29.
> Checkpoint (familia B12, horizonte días-semanas) reprogramado al **2026-12-07 09:00**.
> **Leakage encontrado y corregido ANTES de ver resultados:** `cot_ml_experiment.py` da por
> disponible el reporte del martes desde el viernes 00:00 UTC (lag 3 días), pero la CFTC lo
> publica el viernes 15:30 NY (~19:30-20:30 UTC): trades de viernes antes de esa hora usaban
> un reporte no publicado. El run oficial usa `--cot-lag-days 4` (sábado 00:00 UTC); lag 3
> solo para comparar con junio. Residual: semanas con feriado federal (publicación el lunes).
> El 4-oct se corrió una VISTA PREVIA no-decisoria a pedido del user (CHANGELOG).
>
> **⚠️ 4-oct-2026 (cierre de sesión) — 15 familias con pre-registro, 0 operables.** Tras
> H-MS1 se probó la tanda cripto: H-FC1 carry BTC/ETH, H-FC2 carry en altcoins, H-XS1
> momentum cruzado, H-POS1 posicionamiento → las cuatro NO PASAN. Un agente evaluó las
> ramas del carry: todo ≈ tasa libre; único candidato dudoso **B4b** (short Hyperliquid /
> long Binance). **Registro único con todas las familias, commits y ventanas ya vistas:
> `research/LEDGER_FAMILIAS.md`.** Main = origin/main en 13a3733 antes de este cierre.
>
> **🤖 6-oct-2026 — v3.14.0: agente IA v2 (864 tests) + H-FADE1 (familia 26).** Pedido del user:
> "hacé el agente más activo y mejoralo". Orden seguido: (1) evaluación v1 CERRADA sin conclusiones
> (n = 11: agente −1.08R vs ejecutar todo −9.83R) y pre-registro v2 commiteado ANTES del código
> (`research/AGENTE_IA_V2_PREREGISTRO_2026-10-06.md`, 2b0304d); (2) v2 opt-in: 24 features as-of
> (calendario, COT lag 4, costo/riesgo, día/hora, racha de la estrategia), D1 de MT5 en vivo (el
> cache D1 está congelado desde el 15-jun: régimen/VWAP valían 0 en v1), exploración ε 0.20 a
> 0.10 % de riesgo (≤ 3/día, stop −2R), ajuste de realismo con el P&L REAL de MT5 (solo lectura,
> verificado: −1.00R real vs −1.08R paper), `policy_tag`; (3) `scripts/ai_agent_report.py` (solo
> lectura) + tarea programada **`revision-semanal-agente-ia`** (lunes 09:04); (4) línea del agente
> en el resumen diario. **Dicho sin vueltas:** ejecutar más NO acelera el aprendizaje (aprende del
> paper de TODOS los candidatos) y sin edge cuesta (~0.2-0.3 % del equity por día de mercado).
> **Lo que más candidatos daría:** el tope `MAX_OPEN_TRADES_TOTAL` (5, cuenta también acciones)
> estuvo lleno el 96 % del tiempo desde el 1-sep → comando de `.env` en el cierre de sesión.
> **H-FADE1** (¿operar el reverso de las señales?): NO PASA las tres estrategias (familia 26): el reverso pierde −0.37 / −0.21 / −0.19R por trade (t NW −18.8 / −23.7 / −12.4) en M15 2023-2025. El bruto es ≈ 0 en ambas direcciones y se pierde el costo de stops cortísimos (0.19-0.32R por trade): las señales son ruido y darlas vuelta vuelve a pagar el spread. Post-hoc: el −0.92R del paper vivo de mean_reversion no se reproduce (directo bruto −0.01R) → artefacto de la simulación paper. El agente NO suma acción "fade". `research/HIPOTESIS_2026-10-06_fade.md`.
> **Pasos del user para encender v2** (en este orden, bot apagado): merge + push → warm start
> `python scripts/ai_agent_warmstart.py --version 2 --mt5-d1 --apply` → `.env`
> (`AI_AGENT_VERSION=2`, `AI_AGENT_EXPLORE_PCT=0.20`) → `.\start_bot.ps1`. Evaluación v2 desde el
> **2027-01-11** con ≥ 200 decisiones del tag pre-registrado; predicción: NO PASA.
>
> **📨 5-oct-2026 — v3.13.2 (838 tests): alertas forex/oro sin restos de memecoins.** Llegaban como
> "TOP MEMECOINS" con "caída est. 90 %" (estimador de memecoins aplicado a forex) y salían TODOS los
> snapshots forex (should_send devolvía True siempre). Ahora: título por mercado, movimiento observado,
> envío solo con movimiento notable; /status /cupos /help /top /config sin memecoins si el motor está apagado.
>
> **🧪 5-oct-2026 — v3.13.1 + H-NN1 (829 tests, 25 familias).** Auditoría de tests desde cero: sin
> duplicados, sin dependencia de orden ni de red; 4 tests vacíos arreglados; bug del cierre parcial
> que aflojaba el trailing (paper de acciones) arreglado; `.test_dbs` se vacía al terminar. Decisión
> pendiente del user: `realized_pnl_today` ignora la mitad cobrada en TP1. **H-NN1**: las redes
> neuronales salieron PEORES que el boosting en microestructura y ninguna cubre el costo → no se
> integran (`research/HIPOTESIS_2026-10-05_redes_neuronales.md`).
>
> **🤖 5-oct-2026 — v3.13.0: Agente IA en sandbox demo (827 tests).** Pedido del user: una IA
> que opere sola y aprenda practicando. `app/ai_agent/` (Thompson sampling sobre 16 features)
> decide EJECUTAR o NO OPERAR cada candidato forex/gold y aprende de todos con el R del paper
> trade. Opt-in OFF (`ENABLE_AI_AGENT`), magic MT5 propio 250501, límites duros (≤0.5 %/trade,
> ≤3 abiertas, ≤6/día, stop −3R/día), mantiene calendario/cap USD/halt. Comando `/agente`.
> Arranque en caliente opcional: `scripts/ai_agent_warmstart.py --apply`. Evaluación
> pre-registrada: `research/AGENTE_IA_PREREGISTRO_2026-10-05.md` (desde 2027-01-04 con ≥150
> decisiones; predicción: probable NO PASA). Real-money sigue bloqueado.
>
> **⚠️ 5-oct-2026 — plan B4b/B11/B13/B12 EJECUTADO COMPLETO: 24 familias con pre-registro, 0
> operables.** Cada tanda: pre-registro commiteado antes de bajar datos → código congelado y
> verificado con datos sintéticos → un tiro → veredicto + fila en el ledger.
> - **B4b** (short Hyperliquid / long Binance, 3x): NO PASA la secundaria 2023-06 → 2024-09
>   SOLO por la t Newey-West (BTC 2.34, ETH 2.46 < 2.50); exceso +9.1 %/año, DD ≤ 2.8 %, 0
>   liquidaciones. Near-miss honesto, y el spread ya se comprimió (~10.5 pp → ~2-4 pp). El
>   forward NO se corre; el colector `scripts/b4b_forward_collector.py` queda sin programar.
> - **B11** (OI, top traders, taker; BTC/ETH 2021-12 → 2024-09): las tres NO PASAN (|t| ≤ 1.3).
>   La fuente no trae top traders en 2022 (H-TT1 inválida → H-TT1b en 2022-12 → 2024-09).
>   Bug de OI = 0 encontrado, corregido y declarado (no cambió nada).
> - **B13** (alts 2020-01 → 2024-09, 339 perps point-in-time): reversión semanal −34 %/año;
>   funding como predictor +27 %/año pero t 2.26 y 2ª mitad negativa (+67 % 2020 → −30 % 2024).
> - **B12** (stablecoins, flujo a exchanges, MVRV; semanal): las tres NO PASAN (t ≤ 1.9). ETF
>   flows no probados (historia en ventana vista, sin API gratis).
> - Lectura transversal en `research/LEDGER_FAMILIAS.md`: lo único cerca del umbral fueron
>   primas de funding/carry que existieron y se arbitraron; lo direccional no mostró nada.
> - **Bot:** al 5-oct 00:20 local NO había ningún `main.py` corriendo; la DB se cerró limpia
>   el 4-oct 13:44. Re-arrancar con `.\start_bot.ps1` (verificar antes que no haya otro).
>
> **📅 CHECKPOINT COT: 2026-12-07 09:00** (tarea programada `checkpoint-cot-reexperimento`).
> Comando decisivo: `python scripts/cot_ml_experiment.py --cot-lag-days 4` (lag 3 solo como
> comparación con junio). Barra pre-registrada (sin mover): corte FX/oro TimeSeriesSplit
> OOS ≥ 0.55 robusto Y Δ del COT ≥ +0.03. Si no la cruza: ML sigue OFF.
>
> ### ✅ PLAN (4-oct) para el chat nuevo — EJECUTADO COMPLETO el 5-oct (ver bloque de arriba y el ledger)
>
> Se conserva como registro de lo que se pidió:
>
> #### (histórico) PLAN PENDIENTE (pedido del user: "sigue B11/B12/B13 y el paper de la rama")
>
> Reglas para TODO lo de abajo: research-only (no toca el bot, ni flags, ni MT5, ni .env);
> pre-registro commiteado ANTES de bajar datos; código congelado y verificado con datos
> sintéticos ANTES de correr; k declarado y umbral t ≥ 2.50; manifest con checksums;
> veredicto en el mismo archivo + fila en `research/LEDGER_FAMILIAS.md`. Si una ventana
> está en "Ventanas ya vistas" del ledger, NO puede ser la decisoria.
>
> **1. B4b — paper hacia adelante, short Hyperliquid / long Binance (BTC + ETH).**
> - Pre-registro `research/HIPOTESIS_<fecha>_B4b_forward.md`: patas perp-perp de igual
>   nocional; apalancamiento por pata FIJO elegido antes (2x o 3x; retorno sobre capital ≈
>   spread × L/2 con margen en ambos venues); costos taker de cada venue (verificar tabla
>   oficial; si no se puede, marcar UNVERIFIED y usar ×2 como estrés); regla de rebalanceo
>   de margen con demora y costo de puente USDC; chequeo de liquidación con máximo/mínimo
>   horario; ADL no modelable → se declara. Benchmark: EFFR del NY Fed sobre capital.
> - Ventana DECISORIA: desde el commit del pre-registro hasta ≥ 6 meses (~abril 2027).
>   Chequeo secundario NO visto: Hyperliquid 2023-05 → 2024-09 con la misma regla
>   (declarar antes si es requisito o solo confirmatorio; recomendado: requisito).
> - Datos: Hyperliquid `POST https://api.hyperliquid.xyz/info` con
>   `{"type":"fundingHistory","coin":"BTC","startTime":<ms>}` (paginado, horario) y
>   `{"type":"candleSnapshot",...}` para precios (según docs solo devuelve las ~5000 velas
>   más recientes → VERIFICAR y, si es así, bajar al menos mensual); Binance funding de
>   data.binance.vision (mensual) o `GET https://fapi.binance.com/fapi/v1/fundingRate`.
> - Colector: script nuevo `scripts/b4b_forward_collector.py`, idempotente, guarda en
>   `trading_data/b4b_forward/` (fuera de git) con checksum por corrida. Cadencia semanal;
>   dejarlo programado (Programador de tareas de Windows con comando para el user, o tarea
>   programada de Claude si la app queda abierta). El funding histórico es inmutable, así
>   que perder una corrida no rompe el test; las velas sí pueden perderse.
> - Expectativa declarada por el agente: BTC no pasa, ETH marginal. Riesgos no
>   modelables: contraparte DEX, ADL (10-oct-2025: ~35k cierres), puente, USDC vs USDT.
>
> **2. B11 resto — señales de posicionamiento no probadas (k = 3).** Columnas del `metrics`
> diario de Binance que H-POS1 NO probó: cambio de open interest, ratio long/short de
> top traders (cuentas y/o posiciones: elegir UNA a priori) y ratio taker buy/sell.
> Ventana decisoria NO vista: desde el inicio del `metrics` (~2021-12, verificar) hasta
> 2024-09. Misma mecánica que H-POS1 (z-score 90 d, umbral ±1.5, 3 días, BTC+ETH).
>
> **3. B13 otros factores cruzados (k = 2-3).** Reversión semanal (1 semana), funding como
> predictor de retorno (crowding: funding alto → retorno futuro bajo) y factor de OI.
> Ventana decisoria 2020-01 → 2024-09 (extender la descarga de alts hacia atrás con
> universo point-in-time, como `scripts/crypto_batch_download.py`). La ventana 2024-10 →
> 2026-09 está CONTAMINADA para señales de retornos cruzados (se vio el crash del momentum).
>
> **4. B12 flujos de baja frecuencia.** (a) Checkpoint COT del 7-dic (ya programado).
> (b) Supply de stablecoins (DefiLlama, API gratis), flujos de ETF de BTC/ETH (fuente gratis
> a verificar) y on-chain gratis (CoinMetrics community) como predictores semanales de
> BTC/ETH. Advertir antes: pocas observaciones independientes (~250 semanas) → poca
> potencia; un PASA así de chico se trata como exploración, no como edge.
>
> Orden recomendado: 1 (arranca el reloj del forward cuanto antes) → 2 → 3 → 4b.
> Los scripts del agente de ramas (`research/ramas_carry_scripts/`) NO están revisados:
> si se reutilizan, revisarlos primero.
>
> Mientras tanto el bot: DEJAR CORRER (v3.12.0, demo MT5 nueva ~3.000 USD desde 4-oct;
> no tocar flags, no agregar features, no re-abrir familias; verificar que no haya dos
> `main.py` corriendo).

- **v3.9.3**, **697 tests verdes** (main, pusheado). v3.9.0 = **COT collector** (CFTC semanal,
  opt-in OFF, **YA VIVO** + backfill 5yr hecho): posicionamiento institucional, primer input
  fuera del OHLCV. **v3.9.1-3 = fixes de la auditoría** (dashboard, **A1** forex_session_breakout,
  calendar lookahead, real-money hardcoded; ver §2). Scalping confirmado OFF. ⚠️ **Fase D: gate de data CRUZADO
  (403/400) pero el ML resultó CALLEJÓN SIN SALIDA** sobre los features actuales — ver §3.
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
| **backtest acciones** | S1 (`stock_historical_loader`, Yahoo D1 ajustado) + S2 (harness `category=stock` + banner survivorship). Código hecho; run real PENDIENTE (Yahoo 429). `stock_backtest_run.json` + comando listos. S3 pendiente |
| **v3.9.0** | **COT collector** (`app/collectors/cot_collector.py` + tabla `cot_snapshots` + `ENABLE_COT_COLLECTOR`): CFTC semanal, 9 mercados FX+oro por `cftc_contract_market_code`, SOLO captura para research. Opt-in OFF, soft-fail. **YA VIVO** en la Lenovo |
| **v3.9.1** | Fix dashboard Streamlit (bootstrap `sys.path`, tiraba `ModuleNotFoundError 'app'`) + chore `.gitignore .env.bak*` (backups del `.env` con secrets) |
| **v3.9.2** | **Bug A1**: `forex_session_breakout` calculaba el Asian range sobre velas de hace ~5 días (primeras 32 posicionales de un feed de 5d) → ahora por timestamp a 00:00-08:00 UTC de hoy + cambio 24h + guard de frescura del cache D1 del regime gate |
| **v3.9.3** | Auditoría: calendar gate dejó de estar CIEGO (suma `ff_calendar_nextweek.xml`) + gap_check revivido + real-money hardcoded de verdad (barrera real = `_is_demo_account`) + dashboard `mode=ro`/LogRedactor + `scripts/cot_backfill.py`. **COT backfill HECHO: 5 años (2340 filas)** |

(Detalle completo en `CHANGELOG.md`.)

## 3. ⚠️ LA VERDAD DE FONDO (leer antes de codear)

**El cuello de botella es DATA, no código.** Ninguna estrategia tiene edge PROBADO. La
única +R agregada (`forex_session_breakout`/forex, +0.378R) la carga **solo el lado short
en un régimen direccional** (shorts +1.81R n=28 vs longs −0.31R n=58; mismo patrón en gold)
— es artefacto de régimen, no edge durable. El LLM y el ML **filtran, explican y protegen
capital — NO crean edge.**

**Sobre el −11% (corregido en v3.3.0):** ese drawdown fue sobre todo el **bug de mayo**
(feedback-loop / instant-kill / huérfanas, ~746 artifacts 22–28 may, fixes v2.6.7–v2.7.1).
Limpio de artifacts, la cuenta queda **~plana** (≈−0.004% sobre 105 trades ejecutados desde el
baseline `2026-06-03`, al 18-jun). O sea: **ni −11% ni ganador — plano.** `/performance` lo mide honesto.

Lo más valioso AHORA sigue siendo **dejar correr el bot** + que el COT acumule. El gate de
features de Fase D se **CRUZÓ: 403/400** al 18-jun (`count_closed_trades_with_features`) — pero
cruzarlo **NO destrabó edge**. Se probó el `ml_predictor` (XGBoost) sobre la data viva y el
veredicto es **callejón sin salida**: set completo AUC 0.533; subset feature-complete (n=346)
AUC 0.627 y k-fold 0.69, PERO **CV temporal (TimeSeriesSplit, sin look-ahead) = 0.475, peor que
azar** — el k-fold/split simple eran peeking in-sample. Es la **4ª vía independiente** que
confirma que NO hay edge. → **NO construir Fase D / más modelos sobre los features actuales**
(`ENABLE_ML_PREDICTOR` queda en false). El edge se descubre con INFORMACIÓN nueva (COT), no con
sofisticación.

**ACTUALIZACIÓN 2026-06-21 — el experimento de COT YA se corrió** (`scripts/cot_ml_experiment.py`,
research-only, snapshot read-only + anti-lookahead con lag de release CFTC de 3 días). Dataset: 642
trades cerrados (374 feature-complete), ventana ~1 mes (2026-05-20→06-22). **Veredicto: SIN SEÑAL
accionable, pero inconcluso-con-leve-indicio** (NO un "no-edge" limpio). Test primario (n=374):
baseline OOS 0.509 → +COT **0.533** (Δ +0.024, por debajo del umbral pre-registrado OOS>0.55 ∧ Δ≥0.03).
Corte focalizado (solo trades FX/oro con COT, n=178): 0.585 → **0.607** — 1ª vez que un corte cruza
0.55, PERO el lift propio del COT es solo +0.022 (dentro del ruido en n=178/5-fold), la ventana es ~1
mes con COT semanal (solo ~4-5 lecturas distintas/mercado → agrupa por régimen, no usa dinámica de
posicionamiento), y el gap in-sample/OOS persiste (k-fold 0.73 vs OOS 0.607). **Decisión: NO promover,
`ENABLE_ML_PREDICTOR` sigue OFF; re-correr el MISMO script cuando el COT acumule MÁS MESES.** El script
quedó commiteado y es reproducible. Es el proyecto funcionando como fue diseñado (MAPA §9).

**ACTUALIZACIÓN 2026-07 — BÚSQUEDA DE EDGE CERRADA (v3.9.4→v3.11.0, RESUMEN §2.8).** Se aplicó el cambio
de paradigma (unidad de análisis: trade vivo → barra/semana histórica backfilleable → veredicto en horas)
y se probaron **9 hipótesis con rigor** (pre-registro commiteado ANTES de correr en `research/HIPOTESIS_*.md`,
holdout, Bonferroni): **0 tradeables.** COT × precio (specs, 40yr), COT commercials, carry (tasas FRED, 31yr),
estacionalidad/turn-of-month, session_breakout H1 (14.213 trades), ML: MUERTOS. Viernes del oro y carry:
REALES pero NO tradeables (costos + régimen). Overnight equities (SPY/QQQ/IWM, 34yr): REAL y sobrevive
costos (~+7-10%/año) PERO fuera del scope del bot (US equities + órdenes MOC/MOO). **Conclusión: no hay edge
tradeable al alcance de este bot.** Camino honesto: consolidar (dejar correr en demo), NO re-abrir familias
cerradas (dredging), NO más modelos/IA sobre los mismos datos, NO real-money. En paralelo, auditoría de 3
agentes → fixes v3.9.4-v3.10.1 (A1 poison-message, perf del ciclo, etc.). Informe: `exports/INFORME_PROYECTO_2026-07.xlsx`.

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

### Fase D — AdvancedPredictor *(PROBADA 18-jun = CALLEJÓN SIN SALIDA en features actuales)*
- **Estado:** el gate de datos se cumplió (403/400) y se probó el `ml_predictor` XGBoost sobre la
  data viva. **CV temporal AUC 0.475 OOS (peor que azar)** — el k-fold 0.69 / split simple 0.627
  eran peeking in-sample. NO hay señal forward. **NO construir el ensemble (LightGBM + RandomForest)
  ni prender `ENABLE_ML_PREDICTOR`** — más modelos no extraen señal inexistente (anti-lista MAPA §5).
- **COT features YA se probó (21-jun, `scripts/cot_ml_experiment.py`):** inconcluso. Test primario
  OOS 0.533<0.55; corte FX/oro 0.585→0.607 pero el lift del COT (+0.022) está dentro del ruido y la
  ventana es ~1 mes (COT semanal → ~4-5 lecturas/mercado). NO alcanza la barra → ML sigue OFF.
- **Cuándo re-evaluar:** **re-correr el MISMO script `scripts/cot_ml_experiment.py`** cuando el COT
  acumule MÁS MESES (que las features varíen entre regímenes). Mirar **TimeSeriesSplit** (no k-fold).
  Solo si el corte FX/oro sube robustamente sobre ~0.55 con Δ≥0.03 del COT, ahí recién hay algo.
- **Archivos (si algún día aplica):** EXTENDER `app/learning/ml_predictor.py` (22 tests), NO reemplazar.

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
- **Lo que sigue del harness:** collector de **COT** ✅ HECHO + VIVO (v3.9.0). Diferidos:
  **instrumentos descorrelacionados** (índices/commodities D1), backfill macro VIX/DXY,
  granularidad H1 para salidas. Orden completo en `MAPA_DE_EDGE_Y_RUTA.md`.

### Lo inmediato *(estado al 18-jun-2026)*
- **Dejar correr** el libro vivo + que el COT acumule (lo más importante). El gate de Fase D ya
  se cruzó (403/400) pero la data no mostró edge (ver §3); el próximo lever es info nueva (COT).
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
- **Mantener pytest verde (692).** Al tocar `Settings`: sincronizar
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
Estado: v3.12.0, main, 801 tests verdes, corriendo en la Lenovo vía .\start_bot.ps1.
REFOCUS: 100% LA BOLSA (acciones+forex+oro); memecoins CORTADAS (bot aparte), scalping
APAGADO. Protecciones: calendar gate, cap USD, exit shadow; regime gate + COT collector VIVOS.

Leé en este orden ANTES de tocar nada: RESUMEN_COMPLETO.md (todo el proyecto en uno),
PROXIMOS_PASOS.md (qué sigue + reglas), CONTEXTO_MAESTRO_v3.8.0.md (arquitectura),
CHANGELOG.md, GO_LIVE_RUNBOOK.md (camino a real-money), y para el backtest
ESPEC_BACKTEST_REPLAY_v1.md (forex) + ESPEC_BACKTEST_STOCKS_v1.md (acciones) + MAPA_DE_EDGE_Y_RUTA.md.

Reglas inamovibles: real-money BLOQUEADO (ENABLE_REAL_TRADING=false HARDCODED) hasta
que /readiness esté verde — el user ya lo pidió 3+ veces, la respuesta es el runbook,
no el flag; order_send solo en mt5_demo_trader.py; LLM/ML SUBTRACTIVOS; los gates vivos
(calendar/cap USD/regime/vwap) son DOWNWARD-ONLY (solo bajan a paper); todo opt-in OFF +
soft-fail; mantener 801 tests verdes; al tocar Settings sincronizar los _settings() de
test_score y test_alert_rules; versionado patch/minor sin saltos. El backtest (app/backtest/)
escribe SOLO en backtest_*, NO cuenta para /readiness ni Fase D, no toca el ciclo vivo.
NO inventar edge artificial (curve-fitting): el edge se descubre, no se inyecta.

Límite de hardware: la GPU no banca LLM local rápido (~50s/gen) — nada de LLM en el
hot path del ciclo; ContinuousLearner queda OFF en esta máquina.

La verdad de fondo: NO hay edge probado, confirmado 4 vías (backtest D1 artefacto USDCHF;
diagnóstico vivo = régimen; ML AUC 0.533; CV temporal 0.475 OOS, peor que azar). El gate de
data de Fase D se CRUZÓ (403/400) pero el ML es callejón sin salida sobre los features actuales
— NO prender ENABLE_ML_PREDICTOR. Dejar correr el libro vivo + que el COT acumule; el edge sale
de INFORMACIÓN nueva, no de más modelos.

Decime qué querés hacer: (A) revisar la data (/performance, /readiness, /exposicion, /ml_status);
(B) cuando el COT tenga semanas: agregar features de COT a build_ml_dataset y re-correr el test
temporal del ML (TimeSeriesSplit); (C) completar el backtest de ACCIONES cuando Yahoo no
throttlee (stock_backtest_run.json listo); (D) instrumentos descorrelacionados / backfill macro
(MAPA §8); (E) otra cosa. NOTA: NO Fase D / más modelos sobre los features actuales — ya se
probó (AUC 0.475 OOS) = sin señal.
```
