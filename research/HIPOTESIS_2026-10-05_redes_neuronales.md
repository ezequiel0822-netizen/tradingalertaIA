# Pre-registro H-NN1 — ¿Una red neuronal le gana al boosting en microestructura L1 de BTCUSDT, y cambia la economía?

> **VEREDICTO (corrido 2026-10-05, 47 min): NO integrar redes neuronales.**
> - **A — ¿la red modela mejor? NO, las dos son SIGNIFICATIVAMENTE PEORES que el HGB a
>   30 s** (prueba decisiva 2023-05-17 → 07-31, 76 días): MLP-23 ΔAUC −0.005 (t −5.2);
>   MLP-SEQ ΔAUC −0.018 (t −16.0). AUC test 30 s: HGB 0.595, MLP-23 0.590, MLP-SEQ 0.575.
>   Igual en 60 s (0.566 / 0.564 / 0.551). A 300 s MLP-23 +0.002 (t 0.53, ruido).
> - **B — ¿cambia la economía? NO en las 6 combinaciones.** Ventaja bruta −0.03 a +0.52
>   bps (redes) contra ~8 bps de costo taker: neto −7.5 a −8.0 bps por trade, t de −77 a
>   −481. También negativo en noviembre (causal) y con latencia 1 s.
> - **Réplica fuera de muestra de H-MS1 (informativa):** el HGB de H-MS1, en datos nunca
>   vistos, da AUC 0.595 (may-jul) y 0.576 (nov) a 30 s y +0.62 bps brutos: la señal de
>   microestructura es REAL y ESTABLE; su tamaño es ~13 veces menor que el costo.
> - Diagnóstico POST-HOC (no decide): agregar 150 entradas crudas de historia empeora a la
>   red (más ruido que señal; features con colas pesadas como OFI/CVD le cuestan más a una
>   red estandarizada que a un árbol, que es invariante a la escala). Más capacidad no
>   rescata una señal de 0.5 bps.
> Datos: 86/86 días nuevos con checksum oficial verificado por zip (manifests
> `research/H-NN1_manifest_2023-05-17_2023-07-31.csv` sha256 3e539381…32939725 y
> `research/H-NN1_manifest_2023-11-01_2023-11-10.csv` sha256 05d4fcf4…64c9a3a3); resultado
> `research/H-NN1_result.json` (sha256 a04931ef…41ed36f957). Commits: 8853632
> (pre-registro) → 5e90204 (código, selftest 8/8) → este.

> **Commiteado ANTES de bajar un solo dato de la ventana de prueba** (protocolo del
> proyecto). Experimento de APRENDIZAJE, offline: responde la pregunta del user
> "¿conviene integrar redes neuronales?" donde más chance tienen (millones de filas de
> order book). No reabre H-MS1 (familia 11, cerrada) ni toca el bot, ni flags, ni MT5,
> ni el .env. Fila 25 del ledger.

## 0. Ventanas: qué está visto y qué no (verificado 2026-10-05)

- H-MS1 bajó y usó SOLO **2023-08-01 → 2023-10-31**: `trading_data/binance_micro/BTCUSDT_1s`
  tiene exactamente 92 parquets de esas fechas. La fila del ledger que dice
  "2023-05 → 2023-11" describía la disponibilidad de la fuente, no lo usado: se corrige.
- El bookTicker histórico de Binance existe **2023-05-16 → 2023-11-11**. Nunca se bajó
  ni se miró nada de **2023-05-16 → 2023-07-31** ni de **2023-11-01 → 2023-11-11**.

## 1. Datos y ventanas

- **Entrenamiento**: los 92 días de H-MS1 (2023-08-01 → 2023-10-31), ya vistos; solo se
  usan para entrenar y calibrar.
- **Prueba DECISIVA (nunca vista): 2023-05-17 → 2023-07-31 (76 días).** Es ANTERIOR al
  entrenamiento ("hacia atrás", declarado): vale para comparar clases de modelo (todos
  entrenan con lo mismo), pero para la economía no es causal → por eso hay chequeo causal.
- **Chequeo causal (informativo): 2023-11-01 → 2023-11-10** (10 días, después del
  entrenamiento).
- Fuente: data.binance.vision, bookTicker + aggTrades de BTCUSDT perp, agregados a 1 s
  con las MISMAS funciones de `scripts/microstructure_backfill.py`, y **cada zip
  verificado contra su `.CHECKSUM` oficial antes de procesarlo** (si no coincide, el
  día se excluye y se reporta). Manifest con sha256.
- Cada ventana se carga por separado (las features de su primer tramo quedan NaN; no hay
  datos cruzados entre ventanas). Si falta más del 10 % de los días de la prueba, la
  prueba es INVÁLIDA.

## 2. Features y etiquetas

Idénticas a H-MS1 (§3-§4): 23 features (OBI, micro-price, spread, OFI y CVD a 1/5/15/30 s,
nº de trades, retornos 1-300 s, volatilidad 60/300 s) y triple barrera H ∈ {30, 60, 300} s
con ±4 / ±6 / ±14 bps.

## 3. Modelos (hiperparámetros FIJOS, cero tuning, semilla 0)

- **HGB** (línea de base): exactamente el de H-MS1 (§5).
- **MLP-23**: red neuronal `MLPClassifier` de scikit-learn, capas (64, 32), ReLU, Adam,
  alpha 1e-4, batch 2048, learning rate 1e-3, **15 épocas**, sin early stopping; mismas
  23 features estandarizadas con estadísticos del entrenamiento.
- **MLP-SEQ** ("DeepLOB-lite"): las 23 features + los últimos **30 s** de historia de 5
  series crudas por segundo (OBI, micro-price, OFI 1 s, CVD 1 s, retorno 1 s) = 173
  entradas; capas (128, 64), resto igual. Pregunta práctica: ¿la red saca algo de la
  secuencia cruda que el boosting no usa?
- Sin GPU ni PyTorch (no instalado; no se toca el entorno del bot): la secuencia se aplana.

Entrenamiento: 1 de cada 5 segundos (como H-MS1). Umbral de trading θ de cada modelo:
percentil 90 de |s| sobre sus predicciones FUERA de muestra en 2023-10-18 → 10-31, con el
modelo entrenado en 2023-08-01 → 10-17 (purga H + 300 s). Modelos finales: entrenados con
los 92 días y evaluados en la prueba.

## 4. Criterios

**A. ¿La red modela mejor? (H = 30 s, k = 2: MLP-23 y MLP-SEQ contra HGB).** AUC binaria
(+1 vs −1, sin timeouts) por día de la prueba decisiva; Δ_d = AUC_red − AUC_HGB.
**La red le gana al boosting** si media(Δ) ≥ **+0.010** (efecto mínimo relevante) **y**
t pareado por días ≥ **2.50**. Otros horizontes y noviembre: informativos.

**B. ¿Cambia la economía? (lo que decide "integrar").** Regla de H-MS1 (§7) idéntica:
θ de la calibración, taker 4 bps por lado, latencia 0, sin solapamiento, en la prueba
decisiva, para cada red × horizonte (6 combinaciones). **PASA** si neto medio > 0,
t ≥ **2.64**, n ≥ 200 y ambas mitades > 0, Y además sigue > 0 con latencia 1 s y en
noviembre. El HGB se reporta igual (réplica fuera de muestra de H-MS1, informativa).

**Recomendación de integrar redes neuronales al bot: SOLO si B pasa.** A sola dice que la
red modela mejor, no que gane plata.

## 5. Predicción declarada

- A: MLP-23 ≈ HGB (NO); MLP-SEQ quizás +0.005 a +0.015 de AUC (incierto, probable NO por
  el umbral práctico).
- B: **NO PASA** en las 6: ventaja bruta < 2 bps contra ~8 bps de costo.
- Recomendación esperada: no integrar.

## 6. Limitaciones (declaradas antes)

- MLP de scikit-learn en CPU, no CNN/LSTM reales; la historia de 30 s va aplanada.
- 2023, un solo instrumento, fees de 2023; latencia 0 optimista.
- Prueba decisiva anterior al entrenamiento (no causal para la economía).

## 7. Qué habilita cada resultado

- **B NO PASA** (lo esperado): las redes neuronales no se integran al bot; el
  experimento queda como aprendizaje (con A diciendo si la red al menos modela mejor).
- **B PASA** (con latencia 1 s y noviembre): habilita SOLO un pre-registro de MVP en
  paper, como H-MS1 §10. Jamás ejecución real.

Firmado (protocolo): k = 2 en A (t ≥ 2.50 y Δ ≥ 0.010), 6 combinaciones en B (t ≥ 2.64),
un tiro, ventanas y parámetros fijos.
