# Pre-registro — evaluación del agente IA v2 en sandbox demo (v3.14.0)

> **Commiteado ANTES de escribir el código de v2 y antes de encenderlo.** La v1 se cerró
> sin conclusiones (`AGENTE_IA_PREREGISTRO_2026-10-05.md` §7, n = 11).
> El agente sigue siendo práctica en demo: real-money sigue HARDCODED bloqueado y un
> PASA no lo cambia. No hay meta de ganancia: el objetivo es medir, no "llegar a X %".

## 0. Lo que el user pidió y lo que se le dijo

Pedido (6-oct): "hacé el agente más activo y mejoralo con todo lo que ya tenemos".
Respuesta honesta, fijada acá para que nadie la reinterprete con el resultado a la vista:

- **Más actividad no acelera el aprendizaje.** El agente ya aprende del paper trade de
  TODOS los candidatos (los que ejecuta y los que no): es un problema de información
  completa, no un bandit. Ejecutar más solo agrega (a) actividad visible en la demo y
  (b) datos de ejecución REAL de MT5 para medir cuánto se aleja la realidad del paper.
- **Sin edge, más actividad = más pérdida esperada.** 25 familias de hipótesis, 0
  operables. Los candidatos recientes perdieron −0.84R de media (15-ago → 5-oct, n = 15)
  y −1.28R desde julio (n = 125). La exploración se dimensiona CHICA por eso.
- Lo que sí puede mejorar el agente: **más candidatos** (el tope de 5 paper trades
  abiertos, que también cuenta acciones, estuvo lleno el 96 % del tiempo desde el 1-sep)
  y **mejores features** (abajo).

## 1. Qué hace v2 (fijado en el código de v3.14.0; `AI_AGENT_VERSION=2`)

Igual que v1 salvo lo listado. v1 sigue disponible (`AI_AGENT_VERSION=1`, default) y
su modelo (`ai_agent_model_v1`) no se toca.

### 1.1 Modelo y features (24)

Regresión lineal bayesiana + Thompson sampling (mismo `LinearThompson`): prior_var 0.25,
noise_var 1.0, umbral 0.05R, semilla `AI_AGENT_SEED` (20261005) con stream propio de v2.
Estado en `bot_state` key **`ai_agent_model_v2`**.

Las 16 de v1 (mismas definiciones) + 8 nuevas, todas acotadas y 0 cuando falta el dato:

| # | Feature | Definición (as-of la apertura del paper trade, `opened_at` UTC) |
|---|---|---|
| 16 | `event_near` | máx. sobre eventos **high** de `economic_events` de las monedas del símbolo (`currencies_for_symbol`) con \|Δ\| ≤ 120 min de `1 − \|Δ\|/120` |
| 17 | `cot_signed` | COT index del neto no-comercial / open interest de la moneda NO-USD del par (oro: GOLD) sobre los últimos 156 reportes disponibles con `report_date + 4 días ≤ fecha de apertura`; `(2·idx − 1)` × signo de la moneda (XXXUSD +1, USDXXX −1, oro +1) × signo de la dirección. 0 si hay < 52 reportes |
| 18 | `cost_r` | costo fijo de definición (forex 0.02 %, oro 0.03 % del precio, ida y vuelta) / riesgo % del trade (`\|entry − stop\| / entry × 100`), acotado a [0, 1] |
| 19 | `dow_mon` | 1 si es lunes (UTC) |
| 20 | `dow_fri` | 1 si es viernes (UTC) |
| 21 | `hour_sin` | sin(2π·h/24), h = hora UTC decimal |
| 22 | `hour_cos` | cos(2π·h/24) |
| 23 | `strat_recent_r` | media del R (sin artifacts, recortado a [−3, 5]) de los últimos 20 paper trades forex/oro CERRADOS de la misma estrategia con `closed_at < opened_at`, acotada a [−2, 2] y /2; 0 si hay < 5 |

Contexto D1 (régimen y VWAP semanal): del cache D1 de MT5 si está fresco; si no, de las
velas D1 de MT5 leídas en vivo (solo lectura). En ambos casos se descarta la vela D1 cuya
fecha sea ≥ la fecha UTC de la decisión (incompleta).

### 1.2 Decisión

1. Thompson: puntaje muestreado `s` del posterior (como v1).
2. **Ajuste de realismo** `ĝ = Σ(R_mt5 − R_paper) / (n + 5)` sobre las decisiones v2
   ejecutadas que ya tienen ambos R, acotado a [−1.0, +0.25] (0 sin datos).
3. **EXPLOTAR** si `s + ĝ > 0.05R` → riesgo ≤ `AI_AGENT_RISK_PCT` = **0.50 %**.
4. Si no, **EXPLORAR** con probabilidad **ε = 0.20** (azar reproducible: semilla, id del
   paper trade, stream de exploración) → riesgo ≤ **`AI_AGENT_EXPLORE_RISK_PCT` = 0.10 %**.
5. Si no, **NO OPERAR**.

Se registra `intended` ∈ {`execute`, `explore`, `skip`} y un `policy_tag` por fila.

### 1.3 Recompensa y aprendizaje

- El modelo aprende del **R del paper trade** de TODOS los candidatos (como v1): la
  etiqueta es la misma para todos, no depende de la acción (sin sesgo de selección).
- Para las ejecutadas se calcula además **`R_mt5`** = (profit + swap + comisión + fee de
  los deals de esa posición, `history_deals_get(position=ticket)`) / |pérdida en el SL|
  (`order_calc_profit` con volumen, precio de apertura real y SL de la orden). Solo
  lectura. Alimenta `ĝ` (paso 2), no el modelo.
- Arranque en caliente: `scripts/ai_agent_warmstart.py --version 2 --apply` con todos los
  paper trades forex/oro cerrados (features as-of). NO cuenta para la evaluación.

### 1.4 Límites (todos se mantienen; se agregan los de exploración)

- Todas las órdenes del agente: ≤ 3 abiertas, ≤ 6 por día UTC, stop diario −3R (suma del
  R de los trades del agente cerrados hoy, sin ponderar: conservador).
- Exploración: ≤ **3** por día (`AI_AGENT_EXPLORE_MAX_PER_DAY`) y stop diario propio
  **−2R** sobre las exploraciones cerradas hoy (`AI_AGENT_EXPLORE_DAILY_STOP_R`).
- Gates de riesgo del bot: calendario, cap USD, halt. Magic MT5 250501.
- Todo nuevo es opt-in: con los defaults del código (`AI_AGENT_VERSION=1`,
  `AI_AGENT_EXPLORE_PCT=0`) el agente se comporta igual que v3.13.2.

### 1.5 Configuración evaluada (`policy_tag`)

`v2|eps0.20|xr0.10|r0.50|thr0.05|pv0.25|nv1.00|xmax3|xstop2.0`

Solo cuentan las decisiones con EXACTAMENTE este tag. Si el user corre otros valores,
esas filas llevan otro tag y no cuentan; para evaluarlas haría falta una adenda
commiteada ANTES de encender esa configuración.

## 2. Qué se mide

Unidad: cada decisión v2 (tag de §1.5) con R del paper trade (`reward_r`).

- **Valor del agente** por decisión: `v = w · R_paper`, con `w = 1` si `execute`,
  `w = 0.2` si `explore` (= 0.10 % / 0.50 %, mismo idioma de riesgo), `w = 0` si `skip`.
  Se usa la INTENCIÓN (aunque un límite la haya frenado), como en v1.
- Comparadores: **no operar** (0) y **ejecutar todo** (`R_paper` con w = 1).
- Serie diaria: suma de `v` de las decisiones creadas cada día UTC.
- Reportado aparte, NO decide: política solo-explotación (w_explore = 0), media de R de
  las exploraciones, `ĝ` y P&L en USD de MT5 del magic 250501, desglose por estrategia,
  coeficientes aprendidos de las 8 features nuevas.

## 3. Cuándo

En la primera fecha **desde el 2027-01-11** en que haya **≥ 200 decisiones v2 con R**.
Si al **2027-04-12** no llegó a 200, se evalúa con lo que haya y se declara baja potencia.
No se mira la t antes de esa fecha (el `/agente` muestra medias, no t).

## 4. Criterio (PASA si cumple TODO)

1. media de `v` > 0;
2. **t de Newey-West** (5 rezagos) de la serie diaria de `v` **≥ 2.50**;
3. media de `v` > media de "ejecutar todo";
4. `v` > 0 en ambas mitades (por fecha);
5. sin límites rotos: ninguna orden del agente con riesgo > 0.50 % (explotar) o
   > 0.10 % (explorar) según `demo_trade_requests.risk_pct`; ningún día con > 6 órdenes
   del agente o > 3 exploraciones.

## 5. Predicción declarada

**NO PASA**, con la forma más probable: explotación ≈ 0 (casi no opera, como v1) y la
exploración restando poco. Cuenta a priori: si los candidatos siguen en ~−0.9R, cada
exploración cuesta ~0.9R × 0.10 % ≈ 0.09 % del equity; con ~2-3 por día ≈ **0.2-0.3 %
del equity por día de mercado (~4-6 % por mes de la demo)**. Ese es el precio declarado
de "más activo". En `v` (idioma de 0.5 %): ≈ −0.02 a −0.04R por decisión.

Lo que haría falta para un PASA: que las 8 features nuevas (calendario, COT, costo,
día/hora, racha de la estrategia) separen candidatos buenos de malos con una fuerza que
ninguna de las 25 familias encontró. Probabilidad previa: baja.

## 6. Qué habilita cada resultado

- **PASA**: nada de dinero real. Otros 6 meses en demo con un pre-registro de
  confirmación antes de cualquier otra conversación.
- **NO PASA**: el agente puede seguir en demo como práctica si el user quiere, sin
  reabrir la evaluación con otros parámetros "a ver si sí".
- **H-FADE1** (operar el reverso de las señales) se pre-registra aparte
  (`HIPOTESIS_2026-10-06_fade.md`). Si PASA, una acción "fade" sería un v3 con su propio
  pre-registro; v2 no la incluye.

Firmado (protocolo): parámetros, tag y criterio fijos desde este commit.
