# Pre-registro — evaluación del agente IA en sandbox demo (v3.13.0)

> **Commiteado ANTES de encender el agente** (`ENABLE_AI_AGENT=false` por defecto).
> El agente es práctica en demo: real-money sigue HARDCODED bloqueado y un PASA no lo
> cambia. Este documento fija CÓMO se va a juzgar, para no mover la vara después.

## 1. Qué hace el agente (fijado en el código de v3.13.0)

- Para cada candidato forex/gold que generan las estrategias del bot, decide
  **EJECUTAR** en MT5 demo o **NO OPERAR** con regresión lineal bayesiana + Thompson
  sampling sobre 16 features de contexto (`app/ai_agent/features.py`: estrategia,
  dirección, oro, sesión, régimen D1, VWAP semanal, Hurst, RSI, ATR, CLV).
- Aprende de TODOS los candidatos (ejecutados o no) con el R realizado de su paper
  trade (`r_multiple`, sin artifacts, recortado a [−3, +5]).
- Parámetros: prior_var 0.25, noise_var 1.0, umbral 0.05R, semilla 20261005. Límites:
  riesgo ≤ 0.5 % por trade (y ≤ DEMO_RISK_PER_TRADE_PCT), ≤ 3 posiciones abiertas, ≤ 6
  trades/día, stop diario −3R. Mantiene los gates de riesgo del bot (calendario, cap
  USD, halt). **Cambiar cualquiera de estos parámetros reinicia la evaluación desde cero.**
- Arranque en caliente opcional (`scripts/ai_agent_warmstart.py --apply`): esas
  observaciones históricas NO cuentan para la evaluación.

## 2. Qué se mide

Unidad: cada decisión hacia adelante con R realizado (tabla `ai_agent_decisions`).

- **Valor del agente** por decisión: `v = R` si quiso ejecutar, `0` si no.
- Comparadores: **no operar** (0) y **ejecutar todo** (`R` de cada candidato).
- Serie diaria: suma de `v` de las decisiones creadas cada día UTC.
- Se usa la intención del agente con el precio paper (igual para los tres
  comparadores). El P&L real de MT5 de sus órdenes (magic 250501) se reporta aparte
  como chequeo de realismo; NO decide.

## 3. Cuándo

Evaluación en la primera de estas fechas en que haya **≥ 150 decisiones con R**:
cualquier día desde el **2027-01-04**. Si al **2027-04-05** no llegó a 150, se evalúa
con lo que haya y se declara baja potencia.

## 4. Criterio (PASA si cumple TODO)

1. media de `v` por decisión > 0;
2. **t de Newey-West** (5 rezagos) de la serie diaria de `v` **≥ 2.50**;
3. media de `v` > media de "ejecutar todo";
4. `v` > 0 en ambas mitades (por fecha);
5. sin incidentes de límites rotos (ninguna orden del agente con riesgo > 0.5 % ni
   días con más de 6 trades).

## 5. Predicción declarada

**Probable NO PASA**, con la forma más probable "aprende a casi no operar": media de `v`
≈ 0, por encima de "ejecutar todo" (que hoy es negativo) pero sin t. Razones: 24 familias
sin edge en información pública, y ~150-300 decisiones son pocas para distinguir
habilidad de suerte.

## 6. Qué habilita cada resultado

- **PASA**: nada de dinero real. Habilita otros 6 meses en demo con un pre-registro nuevo
  (confirmación) antes de cualquier otra conversación.
- **NO PASA**: el agente puede seguir en demo como práctica si el user quiere, sin
  reabrir la evaluación con otros parámetros "a ver si sí".

Firmado (protocolo): parámetros y criterio fijos desde este commit.

---

## 7. Cierre anticipado de la evaluación v1 (2026-10-06)

El user pidió un agente "más activo y mejorado" (v2, v3.14.0): cambian features,
exploración y límites, así que **esta evaluación se cierra hoy, antes de su fecha**,
sin conclusiones. Se reporta lo que hubo para que no se pierda ni se reinterprete:

| Medida (decisiones con R, precio paper) | Valor |
|---|---|
| Decisiones registradas (5-oct 13:00 → 6-oct 04:33 UTC) | 13 |
| Con R realizado | 11 (2 sin R utilizable: #10 y #11) |
| Quiso ejecutar / ejecutadas en MT5 | 1 / 1 (USDCAD short breakout) |
| Valor del agente | −1.08R total (−0.098R por decisión) |
| Ejecutar todo | −9.83R total (−0.893R por decisión) |
| No operar | 0 |
| MT5 real de la única orden (magic 250501) | −9.82 USD, cerrada por el stop del broker (≈ −1R) |

n = 11 es ~7 % de las 150 previstas: **no permite ninguna conclusión** (ni a favor ni en
contra). Hallazgo de proceso (no de resultado): el cache D1 de MT5 está congelado desde el
2026-06-15, así que las features `regime_align` y `vwap_week_signed` valieron 0 en TODAS
las decisiones de v1 (el job las saca de ese cache y su guard de frescura las anula).

Las decisiones que el bot v1 siga tomando hasta el reinicio con v2 quedan como v1
(`policy_tag` vacío) y NO cuentan para la evaluación v2
(`research/AGENTE_IA_V2_PREREGISTRO_2026-10-06.md`).
