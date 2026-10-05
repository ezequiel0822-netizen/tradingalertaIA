# Registro de familias de hipótesis — Trading Alert AI

> Un solo lugar con TODO lo probado, su veredicto y dónde está la evidencia.
> Actualizado: 2026-10-05 (B4b + tandas B11, B13 y B12).
> **Saldo: 24 familias probadas con pre-registro → 0 operables.**
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
| 5 | 2026-07 | `forex_session_breakout` H1 (replayable desde v3.10.0) | harness H1 | NO PASA (−0.161R) | 7b3c070 (v3.10.0), 85142f9 | CHANGELOG v3.10.0, memoria auditoría |
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
- **BTCUSDT microestructura 2023-05 → 2023-11** (bookTicker) y aggTrades usados en H-MS1.
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
- Ventanas NO vistas útiles: cripto **2020-01 → 2024-09** para señales que NO sean de
  funding/spread, posicionamiento ni retornos/funding cruzados (quedan muy pocas), y todo lo
  que pase **después** de la fecha de cada pre-registro (test hacia adelante). Hyperliquid
  2023-05 → 2024-09, `metrics` BTC/ETH 2020-09 → 2024-09 y perps USDT 2020-01 → 2024-09 YA
  se usaron.

## Pendiente (orden sugerido; detalle en PROXIMOS_PASOS.md)

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
