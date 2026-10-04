# Pre-registro H-FC1 — Funding carry delta-neutral en BTC y ETH (familia B3)

> **VEREDICTO (corrido 2026-10-04): NO PASA — familia B3 cerrada para BTC/ETH en Binance.**
> Ventana decisoria 2024-10 → 2026-09: las 4 combinaciones rinden MENOS que la tasa libre
> de riesgo (EFFR media 4.04 %): BTC V0 CAGR +3.45 % (exceso −0.61 %, t −1.84), ETH V0
> +3.04 % (−1.01 %, t −2.84), V1 peor (−2.2 % / −2.6 %). Riesgo bajísimo (maxDD ≤ 0.5 %,
> 0 liquidaciones), pero la prima se comprimió: funding medio anualizado BTC 30.6 % (2021)
> → 11.9 % (2024) → 5.1 % (2025) → 2.9 % (2026); 16-19 % de los períodos con funding negativo.
> Diagnóstico POST-HOC de la limitación declarada (colateral y efectivo ocioso rindiendo la
> tasa libre completa, `scripts/funding_carry_collateral_sensitivity.py`): exceso +0.3 a
> +0.75 %, t máx 2.34 < 2.50 y segunda mitad negativa en las 4 → tampoco pasaría.
> Contexto (no decide): 2020-2021 rindió 12-29 % anual; ETH tuvo 1 liquidación en 2020.
> Prima REAL que la competencia arbitró: misma conclusión que el carry FX.
> Data: 544 archivos, 544/544 checksums oficiales OK; manifest `research/H-FC1_data_manifest.csv`
> (sha256 d0c49cb1332fc51fba533eb8c953b0f3ce0e585c7d65316ad8ef7a26b31430ce). Tasa libre: EFFR del NY Fed (= DFF de FRED, idéntica en 1.652 días).

> **Commiteado ANTES de bajar un solo dato** (protocolo del proyecto). Familia NUEVA
> (B3 del mapa de 20 familias del user, 2026-10-04) y FUERA del vehículo del bot: un
> carry cripto exigiría cuenta spot + perpetuo en un exchange, no MT5. Research-only:
> no toca el bot, ni flags, ni MT5; real-money sigue HARDCODED bloqueado. Un PASA
> habilita solo el diseño de un paper-trading con su propio pre-registro.

## 1. Hipótesis

Mantener **long spot + short perpetuo** con el mismo nocional cobra el funding que
pagan los largos apalancados. Es una prima **estructural** (demanda persistente de
apalancamiento largo), no un patrón de precio. A diferencia de todo lo probado:
rota poco (las comisiones se pagan al entrar y salir, no cada 30 s), la latencia
no importa y los datos son públicos.

La pregunta que decide no es "¿el funding es positivo?" (lo fue en promedio
2020-2024), sino: **¿en el régimen ACTUAL, neto de costos y del riesgo, rinde más
que dejar el dinero en tasa libre de riesgo?**

## 2. Datos (fijados acá; disponibilidad verificada el 2026-10-04)

- data.binance.vision: `fundingRate` mensual de BTCUSDT y ETHUSDT (USDⓈ-M, desde
  2020-01), klines de 8 h del perpetuo USDⓈ-M y del spot (velas alineadas a los
  horarios de funding 00/08/16 UTC). Si falta el mensual del último mes, se completa
  con los diarios; sin sustituciones.
- Tasa libre de riesgo: **DFF** (Fed funds efectiva, FRED), diaria, as-of.
- Manifest con checksums oficiales, como en H-MS1.

## 3. Ventanas

- **Ventana DECISORIA: 2024-10-01 00:00 UTC → 2026-09-30 24:00 UTC (24 meses).**
  Justificación a priori: es el régimen que enfrentaría hoy un operador (post-ETF
  spot y post-crecimiento de productos de basis/delta-neutral que compiten por el
  mismo funding). Una prima que existió en 2021 y ya no existe no es operable.
- Contexto (informativo, NO decide): 2020-01 → 2024-09, reportado por año.

## 4. Estrategia (parámetros FIJOS)

Capital normalizado 1.0 por activo. Margen del perpetuo m = 0.5 del nocional
(short a 2x): nocional spot = perpetuo = 1/(1+m) = 0.667; margen = 0.333.

- **Funding**: en cada liquidación de funding, el short cobra `rate × nocional del
  perpetuo` (paga si rate < 0). Nocional valuado al precio del perpetuo a esa hora.
- **Base**: la pata spot se valúa a precio spot y la pata perpetua a precio del
  perpetuo: los cambios de base entran al PnL.
- **Rebalanceo**: si el precio se movió ±20 % desde el último rebalanceo (chequeo al
  cierre de cada vela de 8 h), se vuelve a la proporción 1 : m del equity total,
  pagando comisiones sobre lo operado en cada pata.
- **Liquidación**: si con el máximo intra-vela del perpetuo el equity del margen
  cae a ≤ 0.5 % del nocional, se registra una LIQUIDACIÓN (se pierde el margen
  restante de esa pata). El gate exige cero.
- **Costos por lado** (UNVERIFIED en tabla oficial, conservadores): spot taker
  0.10 %, perpetuo taker 0.05 %, más 0.02 % de slippage por pata y por operación.
- **Rendimiento del colateral**: no se suma ningún interés al USDT del margen
  (conservador).

Dos variantes (k = 2 por activo, 4 combinaciones en total):

- **V0 "siempre adentro"**: entra al inicio de la ventana y sale al final.
- **V1 "con filtro"**: en cada funding, media de las últimas 21 tasas (7 días)
  anualizada (× 3 × 365). Entra si > **10 %** anual estando afuera; sale si < **0 %**
  estando adentro. Decide con la tasa ya liquidada en t y opera al cierre de t (cobra
  desde el funding siguiente). Umbrales elegidos por economía, no por datos: 10 %
  amortiza ~0.4 % de costo de ida y vuelta en pocas semanas; 0 % = deja de pagar.

## 5. Criterio de veredicto (por combinación, en la ventana decisoria)

**PASA** si cumple TODO:
1. Exceso anualizado sobre la tasa libre de riesgo (DFF) > 0, neto de todo costo;
2. t-stat de los retornos SEMANALES en exceso ≥ **2.50** (Bonferroni k = 4, α = 0.05);
3. drawdown máximo del equity ≤ **10 %**;
4. **cero** liquidaciones;
5. exceso positivo en ambas mitades (12 meses cada una);
6. exceso positivo con costos × 2.

H-FC1 PASA si al menos una combinación pasa. Si NINGUNA pasa, la familia B3 queda
cerrada para BTC/ETH en Binance sin re-cortes (no se prueban otros umbrales, otros
apalancamientos ni otras monedas "a ver si sí": eso sería un pre-registro nuevo).

## 6. Predicción declarada

- Funding promedio de la ventana decisoria positivo (PnL absoluto probablemente > 0).
- Pero el exceso sobre la tasa libre de riesgo (~4-5 % anual en 2024-2025) será chico
  y posiblemente NO significativo: la prima se comprimió con la competencia.
  **Predicción: probable NO PASA**, con V1 algo mejor que V0 por evitar los tramos de
  funding negativo.

## 7. Limitaciones declaradas antes de correr

- Un solo exchange (Binance); el riesgo de contraparte del exchange no se modela.
- Comisiones de nivel base no verificadas en la tabla oficial (requiere sesión).
- Velas de 8 h: el chequeo de liquidación usa el máximo intra-vela (conservador para
  la pata corta), pero el rebalanceo solo puede ocurrir a los cierres.
- El colateral no rinde nada en el modelo; en la realidad podría rendir algo (sesgo
  conservador declarado).

Firmado (protocolo): k = 4 combinaciones, un tiro, ventana decisoria fija.
