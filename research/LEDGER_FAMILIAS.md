# Registro de familias de hipótesis — Trading Alert AI

> Un solo lugar con TODO lo probado, su veredicto y dónde está la evidencia.
> Actualizado: 2026-10-07 (H-FVG1/H-IFVG1: Fair Value Gaps e inverse FVG, familia 27).
> **Saldo: 27 familias probadas con pre-registro → 0 operables.**
>
> Regla de uso: una familia cerrada NO se re-abre ni se re-corta. Una variante es una
> hipótesis NUEVA con su propio pre-registro, y si usa una ventana ya vista se declara
> como contaminada (ver "Ventanas ya vistas" abajo).

## Tabla

| # | Fecha | Familia / hipótesis | Datos | Veredicto | Commit(s) | Archivo |
|---|---|---|---|---|---|---|
| 1 | 2026-06-21 | ML sobre features del bot (+ COT como feature) | trades propios del bot + COT | NO PASA: CV temporal 0.475 OOS; +COT 0.533 < 0.55. ML queda OFF. Re-run del COT en el checkpoint del 7-dic | 50c5cc6, 6bc8e5a, 3c93f62 (fix leakage lag 4) | `scripts/cot_ml_experiment.py`, RESUMEN §2.7 |
| 2 | 2026-07-02 | H-A1 COT legacy extremos × precio (8 mercados, ~40 años) | CFTC COT + precio | NO PASA, familia muerta (deja sin efecto el 0.607 de junio) | 3db0af7, cfcf792 | `HIPOTESIS_2026-07-02.md` |
| 3 | 2026-07-02/03 | H-B2 viernes del oro → gate §11 `gold_friday_hold` | cache D1 propio, 21 años | NO PASA §11 por expectancy (+0.040R < +0.10R). Tilt REAL (86 % de años) pero no operable | 4d87090 (v3.11.0), 29fe818 | `HIPOTESIS_2026-07-02.md` §11 |
| 4 | 2026-07-02 | H-B3 oro agosto+septiembre | cache D1 propio | NO PASA (t −0.04) | cfcf792 | `HIPOTESIS_2026-07-02.md` |
| 5 | 2026-07 | `forex_session_breakout` H1 (replayable desde v3.10.0) | harness H1 | NO PASA (−0.161R). ⚠️ Evaluada con las sesiones corridas 2-3 h (velas MT5 en hora del servidor; bug de datos hallado 2026-10-06, v3.13.3). El veredicto queda como está: ver "Integridad de datos" | 7b3c070 (v3.10.0), 85142f9 | CHANGELOG v3.10.0 y v3.13.3, memoria auditoría |
| 6 | 2026-07-04 | H-C1/H-D1 carry FX (diferencial de tasas FRED, retorno total neto de swap) | FRED + precio | NO PASA: carry real (+17 bps bruto) pero 2ª mitad negativa y el swap se lo come (t 1.46) | 829063f, 55c37e6, f70e7e5 | `HIPOTESIS_2026-07-04_carry.md` |
| 7 | 2026-07-05 | E1 turn-of-month en índices | Yahoo D1 | NO PASA | 6210edf, d15bd4a | `HIPOTESIS_2026-07-05_batch.md` |
| 8 | 2026-07-05 | F1 COT lado commercials ("smart money") | COT 40 años + precio | NO PASA (COT cerrado como señal de precio) | 6210edf, d15bd4a | `HIPOTESIS_2026-07-05_batch.md` |
| 9 | 2026-07-05 | E2 overnight en índices US (SPY/QQQ/IWM) | Yahoo D1 | PASA existencia (t ~5) y sobrevive costos idealizados, pero FUERA DE ALCANCE (US equities + MOC/MOO, Sharpe 0.7, DD 40 %) | 6210edf, d15bd4a | `HIPOTESIS_2026-07-05_batch.md` |
| 10 | 2026-07-09 | H-M1 trend multi-asset D1 vía CFD (índices + plata) | Yahoo D1 + financiamiento CFD | NO PASA (drift, no edge; DD 166R). Agota el vehículo CFD/MT5/D1 | cf30a67, aca2768 | `HIPOTESIS_2026-07-09_multiasset.md` |
| 11 | 2026-10-03/04 | H-MS1 microestructura L1 BTCUSDT perp (OFI/OBI/micro-price, 0-300 s) | data.binance.vision bookTicker + aggTrades | NO PASA: señal real (AUC 0.576) pero +0.42 bps brutos vs ~8 bps de costo. Fase 0 de la spec v5.0 = NO-GO | 270888b, 8d20f56, 38b25e1, ac35840, 92a83e8 | `HIPOTESIS_2026-10-03_microestructura.md` |
| 12 | 2026-10-04 | H-FC1 funding carry delta-neutral BTC/ETH (long spot / short perp) | Binance funding + klines 8 h, EFFR | NO PASA: 3.0-3.45 %/año vs EFFR 4.04 %; la prima se arbitró | 062394e, 99ff6d0 | `HIPOTESIS_2026-10-04_funding_carry.md` |
| 13 | 2026-10-04 | H-FC2 carry delta-neutral en altcoins (top-5 por funding) | Binance, 466 símbolos point-in-time | NO PASA: −12 % CAGR; la rotación cuesta más que el funding; 1 liquidación por mecha (−11.3 %) | 8e4a3f9, 3961dec, f53b6f0, 13a3733 | `HIPOTESIS_2026-10-04b_cripto_batch.md` |
| 14 | 2026-10-04 | H-XS1 momentum cruzado 21 d dollar-neutral (perps) | idem | NO PASA: −12.9 % de exceso; +19 % 1ª mitad, −44 % 2ª (crash) | idem | idem |
| 15 | 2026-10-04 | H-POS1 posicionamiento minorista contrario (`count_long_short_ratio`, BTC/ETH) | `metrics` diario Binance | NO PASA: t 0.69, n 148 | idem | idem |
| 16 | 2026-10-05 | B4b short perp Hyperliquid / long perp Binance, BTC+ETH, 3x por pata (k=2; secundaria requisito + forward) | HL funding horario API + Binance funding/klines 1 h (68/68 checksums), EFFR | NO PASA en la secundaria 2023-06-13 → 2024-10-01: solo falla la t Newey-West (BTC 2.34, ETH 2.46 < 2.50); exceso +9.1 %/año, DD ≤ 2.8 %, 0 liquidaciones. Near-miss; además el spread ya se comprimió (~10.5 pp en 2023-24 → ~2-4 pp hoy). Forward NO se corre, colector NO se programa | 8febc1a, d9c27a9, 52b7473 (adenda: HL pagaba cada 8 h hasta 2023-06-08), veredicto | `HIPOTESIS_2026-10-04_B4b_forward.md` |
| 17 | 2026-10-05 | H-OI1 cambio de open interest extremo → contraria al día (BTC/ETH perps, z 90 d, 3 días) | `metrics` 5 min + klines 1d + funding Binance (2.700/2.700 checksums) | NO PASA: −4.1 %/año, t_NW −0.29, n 164 (corregida por bug OI = 0; original −0.31) | e80f809, dd9e59d, 4ff468d, veredicto | `HIPOTESIS_2026-10-05_B11_posicionamiento.md` |
| 18 | 2026-10-05 | H-TT1/H-TT1b top traders por posición → SEGUIR | idem (la fuente no trae top traders en casi todo 2022 → H-TT1 INVÁLIDA; H-TT1b en 2022-12-15 → 2024-10-01) | NO PASA: −20.3 %/año, t_NW −1.23, n 135 | idem | idem |
| 19 | 2026-10-05 | H-TK1 flujo taker extremo (vela 1d) → contraria | idem | NO PASA: −25.0 %/año, t_NW −1.29, n 244 | idem | idem |
| 20 | 2026-10-05 | H-REV1 reversión semanal cruzada (perps USDT, quintiles, dollar-neutral) | velas 8 h + funding de 339 perps point-in-time (17.281/17.281 checksums; manifest sha256 fca6c943…87d94df) | NO PASA: −34.0 %/año, t_NW −2.48, DD −86 % | 595d964, d240f72, veredicto | `HIPOTESIS_2026-10-05_B13_factores_cruzados.md` |
| 21 | 2026-10-05 | H-FND1 funding 7 d como predictor cruzado (long bajo / short alto) | idem | NO PASA: +27.1 %/año pero t_NW 2.26 < 2.50 y 2ª mitad −3.4 %; por año +67/+63/+0.5/+20/−30 % (2020→2024): prima que se apagó | idem | idem |
| 22 | 2026-10-05 | H-STB1 crecimiento del supply de stablecoins → long BTC/ETH (semanal) | DefiLlama + precios B13, EFFR | NO PASA: pendiente t_NW 1.90 < 2.50; regla +10.8 %/año con 1ª mitad negativa | 1e5af5b, 7c5f321, veredicto | `HIPOTESIS_2026-10-05_B12_flujos.md` |
| 23 | 2026-10-05 | H-EXF1 flujo neto a exchanges (CoinMetrics) → short | CoinMetrics Community (no point-in-time) | NO PASA: t_NW −0.45 | idem | idem |
| 24 | 2026-10-05 | H-MVRV1 MVRV extremo → reversión a 4 semanas | CoinMetrics Community | NO PASA: pendiente con signo opuesto (t +0.98); regla −19.7 %/año | idem | idem |
| 25 | 2026-10-05 | H-NN1 redes neuronales (MLP-23 y MLP-SEQ con 30 s de historia) vs HGB en microestructura L1 BTCUSDT | bookTicker + aggTrades 2023-05-17 → 07-31 y 11-01 → 11-10 (86/86 días, checksum oficial por zip); train = los 92 días de H-MS1 | NO PASA: las redes son PEORES que el HGB (ΔAUC 30 s −0.005 t −5.2 / −0.018 t −16) y la economía pierde ~−7.5 bps/trade en las 6 combinaciones. Réplica de H-MS1 fuera de muestra: AUC HGB 0.595 / 0.576 (señal real y estable, 13× menor que el costo). No integrar redes | 8853632, 5e90204, veredicto | `HIPOTESIS_2026-10-05_redes_neuronales.md` |
| 26 | 2026-10-06 | H-FADE1 operar el REVERSO de las señales del bot (mean_reversion, momentum, forex_session_breakout; 1:1 con la distancia de riesgo de la señal), k = 3 | MT5 M15 de 7 pares + XAUUSD, 2023-01-02 → 2025-12-31 (hora del servidor → UTC, regla UE), simulador pesimista del harness | NO PASA las tres: −0.37 / −0.21 / −0.19R por trade, t_NW −18.8 / −23.7 / −12.4. Bruto ≈ 0 en ambas direcciones; se pierde el costo (0.19-0.32R por stops de velas de 15 min). El −0.92R del paper vivo de mean_reversion no se reproduce (directo bruto −0.01R): artefacto de la simulación paper, no dirección revertible | b042301, fbf1a6b, veredicto | `HIPOTESIS_2026-10-06_fade.md` |
| 27 | 2026-10-07 | H-FVG1 / H-IFVG1 Fair Value Gaps (retesteo = continuación) e inverse FVG (gap roto → retesteo del otro lado); límite en el borde del gap, stop al otro borde + 0.1 ATR, TP 2R, 48 velas; k = 2 | MT5 H1 de 7 pares + XAUUSD, decisoria 2011-01-03 → 2017-11-30 (no vista para intradía), secundaria 2026-06-16 → 2026-10-06; costos del harness | NO PASA las dos: −0.24R (n 9.854, t_NW −13.3) y −0.27R (n 7.423, t_NW −16.0) por trade; secundaria −0.23 / −0.33R. BRUTO ya negativo (−0.05 / −0.08R: el TP de 2R sale el 31 % de las veces, hace falta 33 %); costo ~0.19R. Negativo en los 8 símbolos, los 7 años y las dos direcciones | 797fe5f, 7ac8dd5, e96d690, veredicto | `HIPOTESIS_2026-10-07_fvg.md` |

## Lectura transversal (2026-10-05, 24 familias; nota del 2026-10-06 al final)

- Lo único que se acercó al umbral fueron **primas estructurales de funding/carry**: B4b
  (t 2.34/2.46 en 2023-24), H-FND1 (t 2.26, +67 % en 2020 → −30 % en 2024) y H-FC1 (prima
  real, ya debajo de la tasa libre). Las tres cuentan la misma historia: existieron cuando
  el apalancamiento minorista era caro y se arbitraron (ETF, basis trade, Ethena).
- **Más modelo no rescata poca señal** (H-NN1): en el único lugar con señal real
  (microestructura, millones de filas) las redes neuronales salieron PEORES que el
  boosting y ninguna se acerca al costo.
- Las **señales direccionales** sobre información pública (posicionamiento, OI, flujo
  taker, top traders, stablecoins, flujos on-chain, MVRV, COT, estacionalidad, trend,
  microestructura neta de costos) no mostraron nada: |t| ≤ 1.9.
- Implicancia: más familias del mismo tipo sobre las mismas fuentes públicas tienen
  probabilidad previa muy baja. Lo único con sentido es un test HACIA ADELANTE de una
  prima estructural nueva, con su propio pre-registro, nunca un re-corte de las cerradas.

- **2026-10-06 (H-FADE1):** las señales propias del bot en forex/oro tienen R BRUTO ≈ 0 en
  las dos direcciones; lo que se pierde es el costo de stops muy cortos. Invertirlas no sirve
  y, por lo mismo, ningún filtro (incluido el agente IA) puede sacar mucho de ellas: a lo sumo
  evitar las de costo/riesgo más alto.

## Integridad de datos (2026-10-06): hora del servidor MT5 en el harness H1

- **Bug**: MetaTrader5 entrega las épocas en hora del SERVIDOR (MetaQuotes-Demo: EET, UTC+2
  en invierno / UTC+3 en verano, regla UE; medido el 2026-10-06, ver CHANGELOG v3.13.3). El
  cache H1 del harness (8 series, 2017-12 → 2026-06-15) se guardó así y
  `forex_session_breakout` lo leyó como UTC → en la **familia 5** el rango asiático
  (00-08 UTC) y el overlap Londres-NY (13-17 UTC) quedaron corridos 2-3 h: la regla
  evaluada no fue la regla escrita. Lo mismo vale para el slicing por sesión de ese run.
- **No afectadas**: las familias D1 (2, 3, 4, 6, 8 y el D1 de forex/oro en general). La época
  D1 de MT5 es la FECHA de trading del servidor (sesión que cierra 17:00 NY), no un
  instante: weekday/mes/fecha salen bien y es la convención con la que se evaluaron.
  Tampoco la evidencia EN VIVO de `forex_session_breakout`: el bot usa velas de Yahoo (UTC
  real).
- **Protocolo**: el veredicto de la familia 5 NO se re-corta ni se re-abre. Si se quiere
  medir la regla con las sesiones correctas, es una hipótesis NUEVA con pre-registro
  propio, declarada como **réplica por bug de datos**, con la ventana H1 2017-12 → 2026-06
  marcada como YA VISTA (la regla está congelada, pero los datos no son nuevos) o, mejor,
  un test hacia adelante desde la fecha del pre-registro. Antes, migrar el cache
  (`scripts/mt5_cache_tz_migrate.py --server-tz EET --apply`). El harness corregido NO se
  corrió.
- **Prior**: bajo. La evidencia en vivo, con sesiones correctas, ya es negativa: recuento
  read-only del 2026-10-06 = 373 paper trades cerrados sin artifacts (filtro de
  `trade_outcomes`), −0.134R promedio (el brief del user citaba 306 trades / −0.28R con otro
  corte; las dos lecturas dan negativo). La réplica no es prioridad.

Evaluación previa SIN pre-registro (no cuenta como familia): ramas del carry (B4a, B4b,
B5, DEX, Ethena, lending) por un agente, commit 62f8905,
`EVALUACION_RAMAS_CARRY_2026-10-04.md`. Todo ≈ tasa libre o debajo; único candidato dudoso:
**B4b short Hyperliquid / long Binance**.

## Ventanas ya vistas (para no contaminar pre-registros futuros)

- **BTC/ETH semanal 2020-01 → 2024-09 con predictores de flujos** (B12, 2026-10-05):
  supply de stablecoins, flujo neto a exchanges y MVRV ya probados.
- **Cripto 2024-10-01 → 2026-09-30:** usada por H-FC1, H-FC2, H-XS1, H-POS1 y por el agente
  de ramas (incluye Hyperliquid, Bybit, OKX, trimestrales). Cualquier señal cripto sobre
  esa ventana es IN-SAMPLE. En particular, cualquier señal de retornos cruzados (reversión,
  momentum corto) ya está contaminada: se vio que el momentum crasheó en la 2ª mitad.
- **BTCUSDT microestructura (bookTicker + aggTrades):** H-MS1 usó 2023-08-01 → 10-31 (corregido
  el 2026-10-05: la fila decía 2023-05 → 2023-11, que era la disponibilidad de la fuente);
  H-NN1 usó 2023-05-17 → 07-31 y 2023-11-01 → 11-10. Con eso, TODO el bookTicker histórico
  que existe (2023-05-16 → 11-11) quedó visto.
- **Perps USDT 2020-01 → 2024-09, señales cruzadas** (B13, 2026-10-05): reversión semanal y
  funding como predictor; se vio además que el momentum semanal le ganó a la reversión en
  2020-21 → esa ventana YA NO es limpia para señales de retornos/funding cruzados.
- **`metrics` de Binance BTC/ETH 2020-09 → 2024-09** (B11, 2026-10-05): OI, top traders por
  posición y flujo taker de la vela 1d ya usados como señales direccionales a 3 días.
- **Cripto BTC/ETH 2023-05 → 2024-09** (B4b, 2026-10-05): funding de Hyperliquid (horario desde
  2023-06-08), funding y velas 1 h de los perps de Binance. Ya NO es ventana limpia para
  señales de funding/carry/spread entre venues de BTC/ETH. (El funding de Binance 2020-2024
  ya había aparecido como contexto anual en H-FC1.)
- **Forex/oro/índices D1** del cache propio: estacionalidad, carry, trend y COT ya vistos
  en las tandas de julio.
- **Forex/oro M15 de MT5 2022-11 → 2025-12** (H-FADE1, 2026-10-06): las señales de
  mean_reversion, momentum y forex_session_breakout ya se simularon en AMBAS direcciones
  (1:1). Esa ventana ya no es limpia para variantes de esas estrategias en M15.
- **Forex/oro H1 2017-12 → 2026-06-15** (cache MT5, 7 pares + XAUUSD): visto por la familia 5
  (con las sesiones corridas 2-3 h). Cualquier señal intradía/de sesión sobre esa ventana es
  IN-SAMPLE aunque se corrija la hora.
- **Forex/oro H1 2010-09 → 2017-11 y 2026-05 → 2026-10-06** (H-FVG1/H-IFVG1, 2026-10-07):
  patrones de gaps de 3 velas (FVG/iFVG) ya simulados. Con esto, la H1 de MT5 de esos 8
  símbolos quedó vista ENTERA (2010-09 → 2026-10) para señales intradía de precio.
- Ventanas NO vistas útiles: cripto **2020-01 → 2024-09** para señales que NO sean de
  funding/spread, posicionamiento ni retornos/funding cruzados (quedan muy pocas), y todo lo
  que pase **después** de la fecha de cada pre-registro (test hacia adelante). Hyperliquid
  2023-05 → 2024-09, `metrics` BTC/ETH 2020-09 → 2024-09 y perps USDT 2020-01 → 2024-09 YA
  se usaron.

## Pendiente (orden sugerido; detalle en PROXIMOS_PASOS.md)

0. **Options flow** (colecta desde v3.16.0, 2026-10-07): NO es una familia todavía. Se
   pre-registra cuando haya ≥ 120 sesiones guardadas (~abr-2027); hasta entonces NADIE
   mira los valores (`research/OPCIONES_COLECTA_2026-10-07.md`).

1. ~~B4b paper hacia adelante~~ → **CERRADA 2026-10-05** (NO PASA la secundaria por t NW;
   el forward no se corre; colector `scripts/b4b_forward_collector.py` queda en el repo sin
   programar).
2. ~~B11 resto~~ → **CERRADA 2026-10-05** (H-OI1, H-TT1b, H-TK1 NO PASAN).
3. ~~B13 otros factores cruzados~~ → **CERRADA 2026-10-05** (H-REV1 y H-FND1 NO PASAN; OI
   descartado a priori).
4. ~~B12 flujos de baja frecuencia~~ → **CERRADA 2026-10-05** (H-STB1, H-EXF1, H-MVRV1 NO
   PASAN). Flujos de ETF NO probados (historia en ventana vista, sin API gratis: solo
   valdría un test hacia adelante). **Sigue en pie: checkpoint COT 2026-12-07 09:00**
   (tarea `checkpoint-cot-reexperimento`, `--cot-lag-days 4`).
