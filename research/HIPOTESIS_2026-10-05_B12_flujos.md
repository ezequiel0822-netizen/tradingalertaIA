# Pre-registro B12 — flujos de baja frecuencia como predictores semanales de BTC/ETH (k = 3)

> **VEREDICTO (corrido 2026-10-05, 247 semanas 2020-01-06 → 2024-09-30): las TRES NO PASAN —
> familias 22-24 cerradas.** Ninguna pendiente predictiva llega a |t_NW| 2.50:
> - **H-STB1 (supply de stablecoins → long):** pendiente con el signo de la tesis pero
>   t_NW **1.90**; la regla da +10.8 %/año con la 1ª mitad negativa (−1.7 % / +23.3 %);
>   57 semanas con posición. NO PASA.
> - **H-EXF1 (flujo neto a exchanges → short):** signo de la tesis, t_NW −0.45 (ruido);
>   regla +5.9 %/año con 1ª mitad −14.2 %. NO PASA.
> - **H-MVRV1 (valuación → reversión, h = 4 semanas):** pendiente con el signo OPUESTO a la
>   tesis (t_NW +0.98); regla −19.7 %/año. NO PASA.
> Cobertura 100 % en las tres. La advertencia de potencia queda en pie: con ~247 semanas
> ni siquiera la mejor (H-STB1, t 1.90) sería distinguible de suerte entre 3 pruebas.
> Data: DefiLlama 2.498 días y CoinMetrics Community 3.044 días por activo, sin huecos ni
> nulos (sha256 de las respuestas crudas en `trading_data/b12_flows/manifest.csv`); precios
> y funding de B13 (checksums oficiales). Resultado: `research/B12_result.json`.
> Commits: 1e5af5b (pre-registro) → 7c5f321 (código, 18/18) → este.

> **Commiteado ANTES de bajar los datos de esta tanda** (protocolo del proyecto).
> Familias 22-24 del ledger. k = 3, un tiro cada una, umbral **t ≥ 2.50**.
> Research-only: no toca el bot, ni flags, ni MT5, ni el .env.
> **Advertencia de potencia (declarada antes):** ~247 semanas → pocas observaciones
> independientes. Incluso un PASA se trata como EXPLORATORIO: exigiría una confirmación
> hacia adelante con su propio pre-registro antes de cualquier otra cosa.

## 0. Alcance y qué ya se vio

- (a) **Checkpoint COT**: ya programado para el 2026-12-07 09:00 (`--cot-lag-days 4`); no
  se toca acá.
- (b) **Flujos de ETF de BTC/ETH: NO se prueban ahora.** Existen desde 2024-01 (BTC) y
  2024-07 (ETH): casi toda su historia cae en la ventana cripto 2024-10 → 2026-09, que el
  ledger marca como IN-SAMPLE, y no hay API gratuita oficial (Farside publica tablas
  HTML). Lo honesto sería un test solo hacia adelante con ≥ 2 años de datos.
- Ventana de esta tanda: **2020-01-06 → 2024-09-30** (semanas lunes → lunes). Los
  predictores (supply de stablecoins, flujos on-chain de exchanges, MVRV) no se usaron
  nunca. Los retornos de BTC/ETH de ese período sí se usaron como variable a explicar en
  B11 (señales de posicionamiento a 3 días) y son públicos.
- Disponibilidad verificada SOLO por catálogos/documentación (2026-10-05): DefiLlama
  `GET https://stablecoins.llama.fi/stablecoincharts/all` (total circulante diario);
  CoinMetrics Community API v4 (`community: true`) para BTC y ETH: `FlowInExUSD`,
  `FlowOutExUSD`, `CapMrktCurUSD`, `CapMVRVCur`, diarios desde 2011/2015.

## 1. Datos

- DefiLlama (supply total de stablecoins en USD, diario) y CoinMetrics Community (diario):
  respuestas crudas guardadas con sha256 propio (no hay checksum oficial).
- Precios y funding de los perps BTCUSDT/ETHUSDT: velas 8 h y `fundingRate` de
  data.binance.vision ya bajados con checksum oficial para B13 (`trading_data/b13_cross/`).
- Tasa libre: EFFR del NY Fed, as-of.
- **Rezago de publicación:** el predictor del lunes T usa solo datos diarios hasta
  **T − 2 días** (sábado inclusive): los diarios de un día se publican después de que
  termina.

## 2. Predictores (dirección fijada acá)

z = (x − media de las 52 semanas previas) / desvío de esas 52 (mín. 26), salvo MVRV.

| Hipótesis | x semanal (con datos hasta T − 2 d) | Lado si \|z\| > 1 | Tesis |
|---|---|---|---|
| **H-STB1** supply de stablecoins | ln(S_{T−2d} / S_{T−9d}) | z > 1 → **long**; z < −1 → **short** | Entrada de "pólvora seca" precede compras de BTC/ETH |
| **H-EXF1** flujo neto a exchanges | Σ 7 días (FlowInExUSD − FlowOutExUSD) / CapMrktCurUSD, por activo | z > 1 → **short**; z < −1 → **long** | Ingreso neto a exchanges = intención de vender |
| **H-MVRV1** valuación | CapMVRVCur del día T − 2 d, por activo; z contra las **156 semanas** previas (mín. 104) | z > 1 → **short**; z < −1 → **long** | Valuación extrema revierte |

## 3. Dos pruebas por hipótesis (las dos tienen que salir bien)

**Predicción (controla la deriva):** regresión de MCO
`y = a + b·z + e`, con y = retorno logarítmico promedio de BTC y ETH (perp) de T a T + h y
z = promedio de los z de ambos activos (en H-STB1 el z es común). Horizonte **h = 1
semana** para H-STB1 y H-EXF1, **h = 4 semanas** para H-MVRV1 (solapadas). t de
Newey-West (Bartlett) con **4 rezagos** (h = 1) u **8 rezagos** (h = 4). El intercepto
absorbe la deriva alcista del período: una señal que solo "estuvo long en el bull" no pasa.

**Operabilidad:** regla semanal por activo, libro BTC 50 % + ETH 50 %: posición ±1 (perp,
1x) según la tabla, 0 si |z| ≤ 1; rebalanceo cada lunes; costos 0.05 % + 0.02 % de
slippage por lado sobre el cambio de posición; funding pagado/cobrado; un libro sin
posición rinde la tasa libre (exceso 0).

## 4. Criterio (por hipótesis)

**PASA** si cumple TODO:
1. pendiente b con el signo de la tesis y **|t_NW| ≥ 2.50**;
2. exceso anualizado de la regla (media semanal × 52) > 0;
3. exceso de la regla > 0 en ambas mitades (mitad calendario);
4. exceso de la regla > 0 con costos × 2;
5. ≥ 52 semanas con posición (sumando ambos libros, semanas con algún libro invertido);
6. predictor disponible en ≥ 95 % de las semanas de la ventana.

Un PASA es EXPLORATORIO (ver advertencia). Si no pasa, la familia se cierra sin re-cortes.

## 5. Predicción declarada

Las tres **probablemente NO PASAN**. H-MVRV1 es la más conocida (y la de menos
observaciones independientes con h = 4); H-EXF1 depende de etiquetas de direcciones de
exchanges que CoinMetrics fue mejorando con el tiempo.

## 6. Limitaciones (declaradas antes)

- **Los flujos de exchanges de CoinMetrics no son point-in-time:** las etiquetas de
  direcciones se aprendieron después, así que la serie de 2020-2021 de hoy usa
  información que no existía entonces. Ese sesgo favorece encontrar señal: un PASA de
  H-EXF1 sería sospechoso; un NO PASA es robusto.
- DefiLlama puede revisar históricos (nuevas stablecoins agregadas): mismo tipo de sesgo.
- Un solo exchange para precios/funding; contraparte no modelada.

Firmado (protocolo): k = 3, un tiro por hipótesis, ventana fija, umbral t ≥ 2.50 (NW).
