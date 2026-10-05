# Pre-registro B13 — factores cruzados en perps USDⓈ-M: reversión semanal y funding como predictor (k = 2)

> **Commiteado ANTES de bajar los datos de esta tanda** (protocolo del proyecto).
> Familias 20-21 del ledger. k = 2, un tiro cada una, umbral **t ≥ 2.50**.
> Research-only: no toca el bot, ni flags, ni MT5, ni el .env. Un PASA habilita solo un
> diseño de paper-trading con su propio pre-registro; real-money sigue bloqueado.

## 0. Qué ya se vio (declarado)

- H-XS1 (familia 14) probó momentum cruzado a 21 días en 2024-10 → 2026-09 y vio el crash
  de momentum: esa ventana está contaminada para toda señal de retornos cruzados.
- H-FC2 (familia 13) usó el funding de altcoins en 2024-10 → 2026-09 para un carry
  delta-neutral (spot + perp); acá el funding se usa como predictor DIRECCIONAL en otra
  ventana.
- **Ventana de esta tanda: 2020-01 → 2024-09**, nunca usada para señales cruzadas de
  altcoins. Se conocen públicamente los grandes ciclos (2021 alcista, 2022 bajista).
- **Descartado a priori:** el factor de open interest. El OI por símbolo solo está en
  `metrics` de 5 min (~400 mil archivos para el universo) y el OI ya se probó en B11
  (H-OI1, NO PASA).

## 1. Datos

- data.binance.vision, con checksum oficial y manifest: velas **8 h** del perp
  (`futures/um/monthly/klines/{sym}/8h`) y `fundingRate` mensual, **2019-11 → 2024-09**,
  para el universo point-in-time de abajo (incluye deslistados → sin sesgo de
  supervivencia). Los meses de cada símbolo se toman del listado del bucket.
- Universo: todos los perpetuos USDⓈ-M con funding (`futures/um/monthly/fundingRate/`)
  cuyo símbolo termina en USDT, ASCII, base no estable (USDC, FDUSD, TUSD, BUSD, USDP, DAI,
  EUR, AEUR, USDE). A diferencia de H-XS1, se INCLUYEN los "1000…" (acá no hace falta par
  spot y la escala del precio no afecta los retornos).
- Tasa libre: EFFR del NY Fed, as-of.

## 2. Mecánica común (la de H-XS1)

- Rebalanceo cada **lunes 00:00 UTC (T)**. Elegibles: precio válido en T y en T − 7 días,
  y mediana de los 30 días previos del volumen diario en USDT del perp ≥ **US$20 M**
  (solo pasado).
- Quintiles: q = ⌊n / 5⌋. **Se exige q ≥ 2** (≥ 10 elegibles); si no, esa semana en
  efectivo (H-XS1 aceptaba q ≥ 1; con 1 nombre por lado el resultado es idiosincrático).
- Long el quintil "bajo", short el quintil "alto" según la señal; peso igual; exposición
  bruta 1.0 (0.5 long / 0.5 short) sobre el equity; se mantiene una semana. Funding
  pagado/cobrado en ambas patas cada 8 h.
- Costos: perp 0.05 % + slippage 0.05 % por lado sobre lo que cambia.
- Deslistado estando en cartera: sale al último cierre con **2 %** de pérdida extra.
- Hueco puntual de precio: se usa el último precio válido (como H-XS1).

## 3. Señales (dirección fijada acá)

| Hipótesis | Señal en T | Long | Short | Tesis |
|---|---|---|---|---|
| **H-REV1** reversión semanal | retorno del perp T − 7 d → T | quintil de MENOR retorno (perdedores) | quintil de MAYOR retorno (ganadores) | sobre-reacción de corto plazo en altcoins |
| **H-FND1** funding como predictor | suma del funding liquidado en (T − 7 d, T] | quintil de MENOR funding | quintil de MAYOR funding | apalancamiento largo concentrado (funding alto) precede retornos bajos; además el short cobra ese funding |

## 4. Ventana y criterio

- **Ventana DECISORIA: rebalanceos del 2020-01-06 al 2024-09-23; la última semana cierra
  el 2024-09-30 00:00 UTC.** 2019-11/12 solo como historia para filtros y señales.
- Retornos semanales lunes → lunes del equity (capital 1.0 de margen); exceso = retorno −
  tasa libre compuesta de la semana (EFFR as-of, ACT/360).

**PASA** si cumple TODO:
1. exceso anualizado (media semanal × 52) > 0;
2. **t de Newey-West** (Bartlett, 4 rezagos) de los excesos semanales **≥ 2.50**;
3. drawdown máximo ≤ **30 %** (curva de 8 h);
4. exceso > 0 en ambas mitades (corte en la mitad calendario de la ventana);
5. exceso > 0 con costos × 2;
6. al menos **104** semanas con posición (q ≥ 2).

Si no pasa, la familia se cierra sin re-cortes (otro horizonte, otros cuantiles, otra
dirección = pre-registro NUEVO).

## 5. Predicción declarada

- **H-REV1: probable NO PASA.** La evidencia publicada en cripto favorece momentum (no
  reversión) a horizontes de 1-4 semanas, y la rotación semanal de ~100 % cuesta ~0.2 %
  por semana (~10 %/año).
- **H-FND1: incierta, la más plausible de la tanda.** Junta un premio de crowding con el
  cobro de funding en el short; el riesgo es el squeeze de los shorts sobre monedas con
  funding alto en tendencias fuertes (2021).

## 6. Limitaciones

- Un solo exchange; contraparte no modelada; velas de 8 h (ejecución solo a los cierres).
- Liquidez de 2020 baja: pocas semanas con ≥ 10 elegibles al principio.
- Precio de cierre: no se modela impacto en altcoins chicas más allá del slippage fijo.

Firmado (protocolo): k = 2, un tiro por hipótesis, ventana fija, umbral t ≥ 2.50 (NW).
