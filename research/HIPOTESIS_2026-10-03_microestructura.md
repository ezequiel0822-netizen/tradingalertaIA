# Pre-registro H-MS1 — Microestructura L1 (OFI / OBI / micro-price / CVD) en BTCUSDT perp: ¿predecible Y operable?

> **Commiteado ANTES de bajar un solo dato** (protocolo del proyecto). Familia
> NUEVA y FUERA del vehículo del bot (cripto perp, horizonte de segundos/minutos,
> data de order book). Nace de la auditoría de
> `especificacion_sistema_mercado_tiempo_real.md` (recibida 2026-10-03), que
> propone un sistema de microestructura en tiempo real. Antes de construir
> cualquier infraestructura en vivo, este test responde la única pregunta que
> decide si vale la pena: **¿el movimiento predecible es más grande que lo que
> cuesta operarlo?** Research-only: no toca el bot, ni flags, ni MT5, ni
> real-money (que sigue HARDCODED bloqueado).

## 1. Por qué esta familia es distinta a las 10 cerradas

Las 10 familias cerradas usaban precio/volumen agregado (OHLCV) + COT + tasas:
información que el mercado ya digirió. El order book (quién está parado en el
mejor bid/ask y cuánto, y quién cruza el spread) es información que las velas NO
tienen, con la mejor evidencia académica de predictibilidad de corto plazo que
existe (Cont-Kukanov-Stoikov 2014; Stoikov 2018; Gould-Bonart 2016). La hipótesis
honesta no es "¿existe la señal?" (casi seguro sí) sino "¿sobrevive al costo de
cruzar el spread + fees, para un participante retail?".

## 2. Data (fijada acá, gratis, verificada 2026-10-03 en data.binance.vision)

- Instrumento: **BTCUSDT USDⓈ-M perpetual** (Binance Futures).
- `bookTicker` (mejor bid/ask y sus tamaños, cada cambio — L1 tick a tick) +
  `aggTrades` (cada trade con su lado agresor vía `is_buyer_maker`; Lee-Ready NO
  hace falta en esta fuente).
- **Ventana: 2023-08-01 → 2023-10-31 (92 días).** bookTicker histórico solo existe
  2023-05-16 → 2023-11-11; se fija este bloque contiguo.
  - **Dev (walk-forward): 2023-08-01 → 2023-10-10 (71 días).**
  - **Holdout INTOCABLE: 2023-10-11 → 2023-10-31 (21 días).** Se evalúa UNA vez.
- Grilla: **1 segundo**, tiempo de exchange (`transaction_time`), UTC. Estado
  del libro = último bookTicker con tiempo ≤ fin del segundo.
- Si algún día falta en la fuente, se reporta y se sigue sin sustituir.

## 3. Features (lista CERRADA, todas solo con data ≤ t)

En el segundo t:
- `obi` = (bid_qty − ask_qty)/(bid_qty + ask_qty) al cierre del segundo.
- `micro_dev_bps` = (micro − mid)/mid × 1e4, micro = (ask·bid_qty + bid·ask_qty)/(bid_qty+ask_qty).
- `spread_bps`.
- `ofi_w`, w ∈ {1, 5, 15, 30} s: OFI de Cont-Kukanov-Stoikov sobre eventos L1
  (e_n = 1{Pb_n≥Pb_{n-1}}·qb_n − 1{Pb_n≤Pb_{n-1}}·qb_{n-1} − 1{Pa_n≤Pa_{n-1}}·qa_n + 1{Pa_n≥Pa_{n-1}}·qa_{n-1}),
  sumado en la ventana y normalizado por la profundidad media L1 de los 300 s previos.
- `cvd_w`, w ∈ {1, 5, 15, 30} s: volumen agresor comprador − vendedor en la
  ventana, normalizado por el volumen total de los 300 s previos.
- `ntr_w`, w ∈ {5, 30} s: log(1 + nº de aggTrades).
- `ret_w`, w ∈ {1, 5, 15, 30, 60, 300} s: retorno log del mid × 1e4 (control: si
  la microestructura no agrega sobre el precio pasado, eso es el resultado).
- `rv_60`, `rv_300`: volatilidad realizada (raíz de suma de retornos 1 s²).

Sin hora del día, sin día de semana, sin features adicionales. Nada se agrega
después de ver resultados.

## 4. Labels (triple-barrier sobre el mid, fijadas acá)

Barreras simétricas ≈1σ de la volatilidad de BTC 2023 (estimación a priori
~40%/año → σ_1s ≈ 0.8 bps):

| Horizonte H | Barrera ±b |
|---|---|
| 30 s | ±4 bps |
| 60 s | ±6 bps |
| 300 s | ±14 bps |

Label en t: **+1** si el mid toca mid_t·(1+b) antes que mid_t·(1−b) dentro de
(t, t+H]; **−1** al revés; **0** timeout.

## 5. Modelos (hiperparámetros FIJOS, cero tuning)

- **Regresión logística multinomial** (L2, C=1.0, features estandarizadas con
  estadísticos SOLO del train).
- **HistGradientBoosting** de sklearn (max_iter=200, learning_rate=0.05,
  max_leaf_nodes=31, min_samples_leaf=200, early_stopping=False). Equivalente
  funcional a LightGBM sin instalar dependencias nuevas.
- Nada de deep learning (DeepLOB/LSTM/Transformer): si la feature más documentada
  (OFI L1) no le gana al costo, más capas no la rescatan para un retail.
- Muestreo de entrenamiento: 1 de cada 5 segundos (reduce redundancia por
  solapamiento de labels). Evaluación: todos los segundos.

## 6. Validación (sin fuga temporal)

- **Walk-forward en dev**: bloques semanales, train expansivo (mínimo 3 semanas),
  test = semana siguiente, **purga** de los últimos (H + 300) s de train antes del
  inicio de cada test. Diagnóstico: se reportan todos los folds.
- **Holdout**: modelo final entrenado con TODO dev (con la misma purga en el
  borde), evaluado una sola vez sobre 2023-10-11 → 10-31.

## 7. Test económico (el que DECIDE)

Señal s_t = P(+1) − P(−1). Umbral θ = **percentil 90 de |s|** sobre las
predicciones OUT-OF-SAMPLE de los folds walk-forward de dev (nunca del holdout).

Regla de trading, sin solapamiento (una posición a la vez):
- s_t > θ → long: entra al **ask** de t; s_t < −θ → short: entra al **bid** de t.
- Sale en el primer segundo en que el mid toca una barrera (al bid si es long, al
  ask si es short), o en t+H si no toca.
- PnL en bps neto de fees por lado.

Escenarios de costo:

| Escenario | Fee por lado | Rol |
|---|---|---|
| Bruto | 0 | Info: ¿existe algo antes de fees? |
| Maker | 2 bps | Cota superior irreal (ignora probabilidad de fill y selección adversa). NO vale para pasar |
| **Taker 2023** | **4 bps** | **PRIMARIO — decide** |
| Taker actual | 5 bps | Sensibilidad |

Latencia: el escenario primario usa **latencia 0** (optimista a propósito: si
pierde así, pierde en la realidad). Sensibilidad: entrada a las cotizaciones de t+1 s.

## 8. Criterio de veredicto

**PASA (economía)** solo si, en el holdout, escenario primario (taker 4 bps,
latencia 0), al menos una de las 6 combinaciones (3 horizontes × 2 modelos)
cumple TODO:
1. PnL neto medio por trade > 0;
2. t-stat ≥ **2.64** (Bonferroni k=6 sobre α=0.05 bilateral);
3. n ≥ 200 trades;
4. positivo en ambas mitades del holdout (por tiempo).

Y para recomendar construir el sistema en vivo (MVP en paper), además debe
seguir positivo con latencia de 1 s.

**Existencia (secundario, solo informativo):** AUC binaria +1 vs −1 (excluye
timeouts) en holdout ≥ 0.52 para H=30 s con HistGB → "la señal existe".

## 9. Predicción declarada

- Existencia: **PASA** (AUC ~0.53-0.60 a 30 s; la señal de OFI/OBI es real).
- Economía: **NO PASA** — el movimiento predecible a 30-300 s es del orden de
  pocos bps y el costo taker ida y vuelta es ~8 bps. Resultado esperado:
  "predecible pero no operable para un retail".

## 10. Qué habilita cada resultado

- **NO PASA economía**: la familia "microestructura L1 retail" queda CERRADA. La
  spec de tiempo real no justifica construirse como sistema de trading; a lo sumo
  como herramienta de observación. Sin re-cortes, sin cambiar barreras, sin
  sumar features, sin probar otro instrumento "a ver si sí".
- **PASA economía con latencia 1 s**: habilita UN siguiente paso — un MVP en vivo
  de solo lectura (WebSocket Binance + estas mismas features + paper) con su
  propio pre-registro. Jamás ejecución real ni MT5.

## 11. Limitaciones declaradas ANTES de correr

- Data de 2023 (el bookTicker no se publica después de 2023-11).
- Solo L1 (no profundidad completa L2); un solo instrumento.
- Fees de 2023; latencia 0 es optimista; el modelo de salida sobre el mid con
  ejecución al quote opuesto es una aproximación (no modela tamaño ni impacto).
- Un PASA acá sería necesario, no suficiente: mercados de 2023 ≠ hoy.

Firmado (protocolo): k=1 familia, 6 combinaciones en el test decisivo, un tiro.
