# H-FVG1 / H-IFVG1 — Fair Value Gaps e inverse FVG en forex/oro H1 (familia 27)

> **Pre-registro commiteado ANTES de bajar datos.** Lo único que se consultó antes fue
> la **disponibilidad**: cuántas velas H1 por año entrega MT5 para cada símbolo, sin
> precios. FX tiene H1 desde ~sep-2010 y años completos 2011-2017; el oro desde 2009;
> la ventana 2026-06-16 → 2026-10-06 trae ~1945 velas por símbolo. Research-only: no
> toca el bot, ni flags, ni el .env (Settings = defaults del código). A MT5 solo se le
> leen velas (`initialize()` sin credenciales).

## 0. Por qué

Pedido del user (7-oct): "algo que lea todas las posibilidades: noticias, estrategias,
compradores y vendedores, **iFVG y FVG**, volumen, patrones". Todo eso ya se probó o ya
está en el agente (ledger, familias 1-26), salvo los FVG/iFVG, el único concepto nuevo.
Se prueba con el protocolo de siempre, y si no pasa, se cierra.

## 1. Datos y ventanas

- **Fuente:** MT5 MetaQuotes-Demo, velas **H1** de EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD,
  USDCAD, NZDUSD (categoría `forex`) y XAUUSD (`gold`).
- **Hora:** se pasa de hora del servidor a UTC con la regla UE, igual que en H-FADE1.
- **Manifest:** CSV con sha256 commiteado (`research/H-FVG1_manifest.csv`).
- **Ventana DECISORIA: 2011-01-03 → 2017-11-30.** No vista para señales intradía: la H1
  vista en el ledger arranca en 2017-12 y la M15 en 2022-11. Del D1 de esos años solo se
  usaron señales diarias (estacionalidad, carry, trend, COT).
  - Se baja desde 2010-09-01 como calentamiento.
  - Mitades: 1ª < **2014-07-01** ≤ 2ª.
- **Ventana SECUNDARIA (requisito): 2026-06-16 → 2026-10-06.** Es posterior a la H1 vista
  (que termina el 2026-06-15). Se baja desde 2026-05-01 como calentamiento.
- **Disponibilidad:** si un símbolo no tiene ≥ 5 años de H1 dentro de la ventana
  decisoria, se excluye y se declara. Si quedan < 6 símbolos, la familia queda NO
  TESTEABLE, sin cambiar de ventana.

## 2. Definiciones (fijas desde este commit)

- **ATR14(n):** media simple del true range de las velas n−13 … n (true range = max(high,
  close previo) − min(low, close previo)).
- **FVG alcista formado al cierre de la vela n:** `high[n−2] < low[n]`. Gap =
  [`high[n−2]`, `low[n]`].
- **FVG bajista:** `low[n−2] > high[n]`. Gap = [`high[n]`, `low[n−2]`].
- **Filtro de tamaño:** el gap tiene que ser ≥ **0.5 × ATR14(n)**. Sin otros filtros (ni
  sesión, ni tendencia, ni volumen): cada filtro extra sería un grado de libertad.
- **Señal disponible** desde la vela n+1 (nunca se usa información de velas > la actual).

### H-FVG1 — continuación (retesteo del FVG)

- **Alcista:** orden límite de **compra en el borde superior del gap** (`low[n]`), válida
  durante las velas n+1 … n+24.
  - Stop: borde inferior − **0.1 × ATR14(n)**.
  - TP: **2R**.
  - Salida por tiempo: 48 velas después del llenado.
- **Bajista:** espejo (venta límite en `high[n]`, stop sobre el borde superior + 0.1 ATR).

### H-IFVG1 — inversión (el FVG roto cambia de lado)

- **FVG alcista invertido:** el gap se **invalida** si una vela m en n+1 … n+48 **cierra
  por debajo** de su borde inferior. Desde m+1 hasta m+24:
  - **venta límite en el borde inferior** (retesteo desde abajo);
  - stop: borde superior + **0.1 × ATR14(m)**;
  - TP 2R; salida por tiempo a las 48 velas.
- **FVG bajista invertido** (una vela cierra por encima de su borde superior): espejo
  (compra límite en el borde superior, stop bajo el borde inferior − 0.1 ATR).

### Ejecución (pesimista, como el harness)

- **Llenado al precio límite** cuando el rango de la vela lo alcanza. Si la vela abre
  más allá del límite a favor, igual se llena al límite: sin mejora de precio.
- **Vela que abre más allá del stop:** se llena y sale al open (gap_sl).
- **En la vela del llenado solo se mira el stop:** el TP no cuenta en esa vela.
- **Desde la vela siguiente:**
  - open más allá del stop → sale al open;
  - open más allá del TP → sale al precio del TP (el extra no se acredita);
  - si una vela toca stop y TP, gana el stop;
  - salida por tiempo al open de la vela 48 después del llenado.
- **Slippage de stop:** 0.05 × ATR14, el de `BACKTEST_SL_SLIPPAGE_ATR`.
- **Costos:** los del harness (`net_r`): roundtrip forex 0.02 % / oro 0.03 % × **1.25**
  (central) y × **1.5** (stress).
- **Una orden pendiente o abierta por (símbolo, hipótesis) a la vez.** Los FVG que se
  forman mientras tanto se ignoran para esa hipótesis.
- **Fecha del trade:** la del llenado (UTC).

## 3. Criterio (cada hipótesis por separado; k = 2; PASA si cumple TODO)

1. n ≥ 100 trades en la ventana decisoria;
2. media de R neto (central) ≥ **+0.05R**;
3. **t de Newey-West** (5 rezagos) de la serie diaria (días hábiles, suma del R neto por
   día de llenado, días sin trades = 0) **≥ 2.50**;
4. media diaria > 0 en ambas mitades;
5. media de R neto en stress > 0;
6. **secundaria 2026-06-16 → 2026-10-06:** media de R neto (central) > 0 (sin t: pocas
   semanas).

**Descriptivo, NO decide:** por símbolo, año, sesión y dirección; motivos de salida;
tasa de llenado; R bruto; costo en R; velas en posición.

## 4. Predicción declarada

**NO PASA ninguna de las dos.** Forma más probable:

- R bruto ≈ 0 o apenas positivo, porque es un patrón de precio público y muy difundido;
- el costo (~0.2-0.4R con stops de ~0.6-1 ATR de H1) lo deja negativo;
- en H-FADE1 las señales de velas de 15 min dieron bruto ≈ 0 en ambas direcciones.

## 5. Qué habilita cada resultado

- **PASA (alguna):**
  - NO entra directo a operar.
  - Se pre-registra una confirmación hacia adelante (paper, ≥ 3 meses).
  - Si la confirma, entra como **estrategia nueva del bot** (opt-in OFF, primero en
    paper) y el agente IA decide sobre sus candidatos como con cualquier otra.
  - No es un agente aparte ni una feature del agente: sus 24 features están fijas bajo
    el tag `px1`.
  - Real-money sigue bloqueado.
- **NO PASA:** la familia se cierra **sin re-cortes**: no se prueban otros tamaños de
  gap, otros múltiplos de R, otros timeframes, filtros de sesión o tendencia, ni la
  ventana 2018-2026 "a ver si sí".

## 6. Código

`scripts/h_fvg1_study.py`:

- `--selftest`: sintético, sin red ni MT5. Patrones FVG/iFVG plantados con resultado
  conocido, sin mirar el futuro, reglas de llenado y de stop/TP, costos y NW.
- `--download`: velas + manifest.
- `--run`: un tiro → `research/H-FVG1_result.json`.

El código se congela y se commitea con el selftest pasando ANTES de `--download`.

Firmado (protocolo): definiciones, ventanas, k, criterio y predicción fijos desde este
commit.

---

## 7. Veredicto (2026-10-07) — **NO PASA las dos. Familia 27 cerrada.**

Un tiro con el código congelado (7ac8dd5) sobre los datos del manifest (e96d690, sha256
`9400d828…`): 8/8 símbolos con ≥ 5 años en la ventana; 0 huecos > 3 días hábiles en todo
el dataset. Resultado completo: `research/H-FVG1_result.json`.

| | H-FVG1 (continuación) | H-IFVG1 (inversión) |
|---|---|---|
| n (decisoria) | 9.854 | 7.423 |
| R neto por trade (central) | **−0.239** | **−0.274** |
| R neto en stress | −0.276 | −0.313 |
| t NW diaria | **−13.3** | **−16.0** |
| media diaria 1ª / 2ª mitad | −1.25 / −1.19 | −1.10 / −1.15 |
| secundaria 2026 (n, R neto) | 408, −0.23 | 302, −0.33 |
| criterios cumplidos | solo n ≥ 100 | solo n ≥ 100 |

**Descriptivo (no decide):**

- El R **bruto ya es negativo**: −0.05R (FVG) y −0.08R (iFVG).
- Con TP a 2R hace falta acertar el 33.3 % para empatar en bruto. Llegó al TP el 31.5 % y
  el 31.3 % de las veces; el resto es stop (65-66 %) o salida por tiempo.
- El costo suma ~0.19R por trade.
- Negativo en los 8 símbolos (−0.18 a −0.33R), en los 7 años (2011-2017) y en las dos
  direcciones.
- Nota de método: las reglas pesimistas del pre-registro restan algo al bruto (el TP no
  cuenta en la vela del llenado y no hay mejora de precio). Pero con −0.05/−0.08R de
  bruto y ~0.19R de costo, ninguna variante "optimista" lo llevaría a +0.05R neto con
  t ≥ 2.50.

**Lectura:** el FVG es un patrón de precio público y muy difundido; acá se comporta
como cualquier otra señal de velas: ≈ 0 o algo peor antes de costos y negativo después.
Coincide con H-FADE1 (familia 26).

**Qué habilita:** nada. NO entra al bot ni al agente. Sin re-cortes: no se prueban
otros tamaños de gap, múltiplos de R, timeframes, filtros de sesión o tendencia, ni
otras ventanas. La H1 de MT5 de los 8 símbolos queda vista entera (ledger).
