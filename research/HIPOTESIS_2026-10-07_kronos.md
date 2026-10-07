# H-KRON1 — Kronos (modelo base de velas) hacia adelante en forex/oro H1 (familia 28)

> **Pre-registro commiteado ANTES del primer pronóstico registrado.** Es un test
> **hacia adelante**: los datos decisorios todavía no existen. Antes de este commit solo
> se corrió Kronos sobre **velas sintéticas**, para medir tiempos (8 símbolos × 5
> trayectorias ≈ 324 s con 4 hilos, 351 s con 2 hilos). Research-only: proceso aparte
> del bot (`.venv_kronos`), sin órdenes, sin tocar flags ni el .env.

## 0. Por qué

- **El pedido:** el user trajo el repo `shiyu-coder/Kronos` (MIT; paper arXiv 2508.02739).
  Es un transformer pre-entrenado con más de 12 mil millones de velas de 45 bolsas, que
  incluyen forex y cripto, en 7 temporalidades.
- **Lo que reporta el paper:**
  - RankIC ≈ 0.025 (Kronos-small) en ordenar acciones;
  - un backtest top-k en acciones chinas con 0.15 % de costo;
  - en forex, solo error de pronóstico, no P&L neto.
- **Por qué hacia adelante:** el pre-entrenamiento llega hasta **junio de 2024**. Todas
  nuestras velas intradía de forex/oro posteriores ya están vistas en el ledger (H1
  entera, M15 hasta 2025-12), así que el único test limpio es hacia adelante.
- **Previa baja:** más modelo no crea señal (H-NN1), y las señales de velas en forex dan
  ≈ 0 antes de costos (H-FADE1, H-FVG1).

## 1. Modelo y datos (fijos desde este commit)

- **Código:** `shiyu-coder/Kronos` en el commit **`67b630e67f6a18c9e9be918d9b4337c960db1e9a`**.
- **Modelo:** **Kronos-small** (24.7M), `NeoQuasar/Kronos-small` @
  **`901c26c1332695a2a8f243eb2f37243a37bea320`**.
- **Tokenizer:** `NeoQuasar/Kronos-Tokenizer-base` @
  **`0e0117387f39004a9016484a186a908917e22426`**.
- Sin fine-tuning: entrenarlo con nuestros datos agregaría perillas y ventanas.
- **Inferencia:** CPU, 2 hilos, semilla de torch 20261007, `max_context` 512.
- **Pronóstico:**
  - contexto: las **400** últimas velas H1 COMPLETAS;
  - `pred_len` **12**;
  - `T` **1.0**, `top_p` **0.9**;
  - `sample_count` **5** (media de trayectorias).
- **Datos:** velas H1 de MT5 (MetaQuotes-Demo, solo lectura) de EURUSD, GBPUSD,
  USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD y XAUUSD.
  - Hora del servidor → UTC con la regla UE.
  - Volumen = tick volume.

## 2. Reglas de cada ronda

- **Rondas:** días hábiles a las **00:00 y 12:00 UTC (+2 min)**, desde el lunes 00:00
  hasta el viernes 12:00.
  - Si el proceso arranca hasta 30 min tarde, la ronda se hace igual.
  - Una ronda perdida no se rellena.
- **Por símbolo:**
  - Solo velas cerradas. Si la última cerró hace > 2 h, cuenta como mercado cerrado.
  - `r̂ = cierre pronosticado a 12 h / último cierre − 1`.
  - Si **|r̂| ≥ costo de definición** (forex 0.025 %, oro 0.0375 %, el central del
    harness), decide **long o short** por el signo; si no, *abstain*.
  - En la ronda del **viernes 12:00 no se decide** (cruzaría el fin de semana): solo se
    anota la cotización para cerrar lo del viernes 00:00.
- **Cotización:** bid/ask de MT5 leídos al **final** de la ronda, después de pronosticar
  todos los símbolos.
- **Resultado de cada decisión:**
  - long: entra al ask de su ronda y sale al bid de la ronda siguiente del mismo símbolo,
    a **12 h ± 1 h**;
  - short: entra al bid y sale al ask;
  - el spread real queda incluido;
  - una decisión sin ronda de salida en ese rango **no cuenta** y se reporta aparte.
- **Stress:** se resta además el costo de definición completo (forex 0.025 %, oro
  0.0375 %).

## 3. Criterio (PASA si cumple TODO; k = 1)

1. n ≥ **300** decisiones con salida;
2. media del retorno neto por decisión > 0;
3. **t de Newey-West** (5 rezagos) de la serie diaria (suma del retorno neto de las
   decisiones de cada día) **≥ 2.50**;
4. suma > 0 en ambas mitades (por fecha);
5. media en stress > 0.

**Descriptivo, NO decide:** tasa de acierto; IC de Spearman entre r̂ y el retorno
realizado (mid a mid); resultados por símbolo; cuántos *abstain*; decisiones sin salida.

## 4. Cuándo

- En la primera fecha **desde el 2027-01-15** con **≥ 300 decisiones con salida**.
- Si al **2027-03-31** no llegó, se evalúa con lo que haya y se declara baja potencia.
- **Antes de esa fecha no se mira el resultado:**
  - `--status` solo cuenta filas y estados;
  - `--evaluate` se niega.

## 5. Predicción declarada

**NO PASA.** Forma más probable:

- IC ≈ 0;
- tasa de acierto ≈ 50 %;
- retorno neto negativo por el spread;
- el modelo casi nunca hace *abstain*, porque sus pronósticos de 12 h suelen superar el
  costo.

## 6. Qué habilita

- **PASA:** NO entra directo.
  - Primero, un pre-registro de confirmación (otros 3 meses, ventana nueva).
  - Después se podría sumar como señal o feature del agente: v3 del agente, con su
    propio pre-registro.
  - Real-money sigue bloqueado.
- **NO PASA:** familia cerrada **sin re-cortes**. No se prueban otros horizontes,
  temperaturas, cantidades de muestras, Kronos-base, fine-tuning ni umbrales "a ver si sí".

## 7. Código

- **`scripts/kronos_forward.py`:**
  - `--loop` (lo lanza `start_kronos.ps1`);
  - `--once` (prueba que NO escribe en el archivo de rondas);
  - `--status`, `--evaluate`;
  - `--selftest` (sintético, sin red, sin MT5, sin torch).
- **`scripts/setup_kronos.ps1`:** crea `.venv_kronos`, clona Kronos en el commit fijado y
  baja los pesos en las revisiones fijadas.
- **Datos:** `trading_data/kronos_forward/rounds.csv` (append). Log:
  `trading_data/kronos_forward/kronos.log`.

Firmado (protocolo): modelo, parámetros, reglas, fechas, criterio y predicción fijos
desde este commit.
