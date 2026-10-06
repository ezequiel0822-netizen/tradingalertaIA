# Pre-registro H-FADE1 — operar el REVERSO de las señales del bot (forex/oro, M15; k = 3)

> **VEREDICTO (corrido 2026-10-06, un tiro): las TRES NO PASAN — familia 26 cerrada.**
>
> | Estrategia | n reversos | R neto/trade | estrés ×1.5 | t NW diaria | mitades (media diaria) |
> |---|---|---|---|---|---|
> | mean_reversion | 5.379 | −0.373 | −0.436 | −18.8 | −2.96 / −2.00 |
> | momentum | 18.326 | −0.212 | −0.254 | −23.7 | −4.82 / −4.95 |
> | forex_session_breakout | 12.618 | −0.192 | −0.230 | −12.4 | −2.99 / −3.19 |
>
> - **La forma es la predicha (§6):** el R BRUTO es ≈ 0 en las dos direcciones — reverso
>   −0.057 / −0.004 / −0.001R, directo −0.013 / −0.042 / −0.051R — y lo que se pierde es el
>   costo: 0.32 / 0.21 / 0.19R por trade, porque los stops salen de ~1.5-2 ATR de velas de 15
>   min. Las señales son ruido; dar vuelta ruido vuelve a pagar el spread. Ningún año, símbolo
>   ni sesión da positivo (descriptivo, no decisorio).
> - **Diagnóstico post-hoc (rotulado, no decide nada):** el −0.92R de `mean_reversion` en el
>   paper VIVO no se reproduce en el replay (directo bruto −0.01R, neto −0.33R). La pérdida
>   extra del paper vivo viene de la mecánica de simulación (precio de entrada y monitoreo
>   del paper), no de una dirección predecible que se pueda revertir.
> - Datos: 8 símbolos M15 de MT5 (78.662 velas EURUSD; 74.777 XAUUSD), 2022-10-31 → 2025-12-31
>   UTC, 0 huecos > 3 días hábiles; manifest `research/H-FADE1_manifest.csv` (sha256
>   a6d62387…472687a7b); resultado completo `research/H-FADE1_result.json` (36.323 trades).
>   La v3.13.3 (otra sesión, misma fecha) confirmó la regla EET/UE usada acá.
> - Consecuencia: el agente NO suma una acción "fade". No se re-corta (ni otra geometría,
>   ni otro timeframe, ni otra ventana).
> - Commits: b042301 (pre-registro) → fbf1a6b (código, selftest 33/33) → este veredicto.

> **Commiteado ANTES de bajar los datos** (protocolo del proyecto). Familia 26 del ledger.
> k = 3 (una por estrategia), un tiro cada una, umbral **t ≥ 2.50** (Newey-West).
> Research-only: no toca el bot, ni flags, ni el .env; a MT5 solo se le LEEN velas
> (`mt5.initialize()` sin credenciales, `copy_rates_range`, `shutdown`). Un PASA NO manda
> nada a MT5: habilita solo diseñar una acción "fade" del agente (v3) con su propio
> pre-registro y una prueba hacia adelante en demo. Real-money sigue bloqueado.

## 0. Motivación y qué ya se vio (declarado)

- Motivación (dato VISTO, no cuenta como evidencia): los paper trades vivos forex/oro
  pierden de forma muy consistente — `mean_reversion` −0.92R de media (n = 190, mediana
  −1.09R), `forex_session_breakout` −0.13R (n = 373), `momentum` −0.23R (n = 29), mayo →
  octubre 2026. De ahí la pregunta del user: "¿y si hacemos lo contrario?".
- Por qué la previa es BAJA: (1) si las señales son ruido, el reverso también es ruido y
  vuelve a pagar costos; (2) con stops de ~1.5 ATR de velas de 15 min el costo ya es
  ~0.15-0.25R por trade; (3) la pérdida del paper vivo puede ser en parte un artefacto
  (precio de entrada de Yahoo viejo frente al precio con que se monitorea), que una
  simulación con entrada en la apertura de la vela siguiente NO reproduce; (4) en B11 se
  advirtió que "que una señal pierda no convierte a la opuesta en hallazgo".
- Ventanas ya vistas que tocan esto: paper vivo 2026-05 → 2026-10 (EXCLUIDO); replay H1
  de `forex_session_breakout` 2018-06 → 2026-06 directo (familia 5, −0.161R neto) →
  **contaminación leve declarada para `forex_session_breakout`** (se conoce el resultado
  del lado directo en H1, no el del reverso en M15). Nunca se hizo un replay M15 de
  ninguna estrategia ni se miró el reverso de ninguna.
- Disponibilidad: NO verificada todavía. El script la verifica primero y la escribe en el
  manifest (solo fechas y conteos, sin precios) antes de calcular nada.

## 1. Datos

- MT5 MetaQuotes-Demo, velas **M15** (bid), `copy_rates_range`, para los 8 símbolos del
  bot: EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD, XAUUSD (= GC=F en vivo).
- Rango bajado: 2022-11-01 → 2026-01-01 (2 meses de warm-up antes de la ventana).
- **Hora:** las épocas de MT5 vienen en hora del SERVIDOR (memoria `mt5-server-time`).
  Se convierten a UTC con la regla EET/EEST de la UE (UTC+2; UTC+3 desde el último
  domingo de marzo 01:00 UTC hasta el último domingo de octubre 01:00 UTC). Límite
  declarado: si el servidor usara la regla de EE.UU., ~3 semanas por año quedan corridas
  1 h (solo afecta a `forex_session_breakout`).
- Guardado en `trading_data/h_fade1/{SYM}_M15.csv` (UTC) + manifest con sha256 por
  archivo, conteos, primera/última vela y huecos > 3 días fuera de fines de semana.
- Si a algún símbolo le falta historia, su ventana empieza en su primer día completo +
  250 velas de warm-up (se reporta; no se cambia nada más).

## 2. Ventana decisoria y mitades

- **2023-01-02 → 2025-12-31** (3 años; nada de 2026).
- Mitades por fecha de entrada: **2023-01-02 → 2024-06-30** y **2024-07-01 → 2025-12-31**.

## 3. Señales (código REAL de las estrategias, sin tocarlo)

- Estrategias (k = 3): `mean_reversion`, `momentum`, `forex_session_breakout` — las tres
  que generan candidatos forex/oro en vivo (`breakout` y `news_catalyst` no los generan).
- En cada vela N se arma el contexto con `app.backtest.context_builder.build_context`
  (ventana de 250 velas que TERMINA en N; macro/news/pro vacíos, como el harness) y se
  llama a `strategy.evaluate`; vale si `confidence ≥ 60` (STRATEGY_MIN_CONFIDENCE default).
- Settings: los DEFAULTS del código, sin leer el .env.
- Una posición por (símbolo, estrategia) a la vez, contada sobre la vida del trade
  reverso (B12 del harness).
- Diferencias con vivo (declaradas): en vivo las velas son de Yahoo (15 min, ~480 velas)
  y acá de MT5 (bid, 250 velas); en vivo hay un paper trade por snapshot y tope de
  posiciones abiertas; acá no.

## 4. El trade reverso (definición única, F1)

- Dirección: la OPUESTA a la señal.
- Entrada: apertura de la vela N+1 (B2).
- Distancia de riesgo `D = |signal.entry − signal.stop|` (el 1R de la señal original).
- **Stop** a `D` en contra del reverso; **objetivo** a `D` a favor (1:1). Sin parciales
  ni trailing.
- Salida por tiempo: al open de la vela `K = ceil(time_horizon_hours × 60 / 15)` de la
  señal original (mean_reversion 6 h, momentum 48 h, session_breakout 8 h).
- Simulación: `app.backtest.trade_simulator.simulate_trade` (pesimista: empate en la
  misma vela → gana el stop; gaps; slippage de stop = 0.05 × ATR% × precio, como el
  harness).
- Costos: `net_r` del harness con el costo por categoría de los defaults (forex 0.02 %,
  oro 0.03 % ida y vuelta) × 1.25. Estrés: × 1.5.
- **Control (diagnóstico, no decide):** el trade DIRECTO con la misma geometría 1:1.

## 5. Estadística y criterio (por estrategia s)

- Serie diaria: suma del R neto de los reversos de s por día UTC de entrada, sobre TODOS
  los días hábiles (lunes-viernes) de la ventana; días sin trades = 0.
- **PASA s si cumple TODO:**
  1. n ≥ 100 trades reversos;
  2. media del R neto por trade ≥ **+0.05R**;
  3. **t de Newey-West (5 rezagos) de la serie diaria ≥ 2.50**;
  4. media de la serie diaria > 0 en ambas mitades;
  5. media del R neto por trade > 0 con costos de estrés (× 1.5).
- k = 3 declarado; sin corrección adicional (como B11). La familia PASA si al menos una
  estrategia pasa; SOLO las que pasan serían candidatas a la acción "fade".
- Se reporta además (descriptivo): por símbolo, por año, por sesión, % de salidas por
  stop/objetivo/tiempo, el control directo y el costo medio en R.

## 6. Predicción declarada

**NO PASA ninguna.** Forma más probable: el reverso bruto ≈ −(directo bruto) cerca de 0
y el neto negativo por costos (~−0.15 a −0.25R por trade), con el control directo
también negativo. Si `mean_reversion` mostrara un reverso bruto claramente positivo, lo
más probable es que no alcance para cubrir el costo de stops tan cortos.

## 7. Verificación antes de correr (código congelado)

Selftest con datos SINTÉTICOS (sin bajar nada) que el script debe pasar antes del tiro:
conversión de hora del servidor (fechas de cambio de horario de 2023-2025), geometría del
reverso long/short, empate → stop, salida por tiempo, costos en R, serie diaria con
ceros, t de Newey-West contra un caso conocido, una posición por (símbolo, estrategia), y
que una señal plantada en datos sintéticos genere el reverso esperado.

## 8. Qué habilita cada resultado

- **NO PASA**: familia 26 cerrada sin re-cortes (ni otra geometría, ni otro timeframe,
  ni otra ventana). El agente sigue sin acción "fade".
- **PASA (alguna s)**: nada a MT5 todavía. Se diseña la acción "fade" para el agente (v3)
  SOLO para las s que pasaron, con su propio pre-registro y prueba hacia adelante en
  demo con riesgo reducido.

Firmado (protocolo): definición, ventana, k y criterio fijos desde este commit.
