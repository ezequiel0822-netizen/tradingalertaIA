# GO-LIVE RUNBOOK — Camino completo a dinero real

> **Qué es esto:** el plan ejecutable, completo y sin incógnitas para pasar a real-money
> **el día que los gates estén verdes**. Hoy real-money sigue BLOQUEADO (HARDCODED) y
> este documento NO lo desbloquea — lo que hace es que, llegado el día, no haya que
> pensar nada: se ejecuta este runbook de arriba a abajo y listo.
>
> El tablero vivo de progreso es el comando **`/readiness`** en Telegram.

---

## PARTE 1 — Gates que deben estar VERDES antes de empezar (no negociables)

| # | Gate | Criterio concreto | Cómo verificarlo |
|---|---|---|---|
| 1 | **Edge probado** | ≥1 estrategia con avg_R > 0 neto de costos, n ≥ 50, y que el edge NO dependa de una sola dirección/régimen (debe sostenerse en sub-períodos distintos y en `/edge` por slices) | `/expectancy` + `/edge` + `/performance` positivo sostenido ≥ 4 semanas |
| 2 | **Data suficiente** | ≥400 trades limpios con features técnicos (gate Fase D) | `/readiness` (hoy ~69/400) |
| 3 | **Performance limpia positiva** | `/performance` con R neto > 0 e impacto > 0 sobre ≥ 100 trades ejecutados | `/performance` |
| 4 | **Salidas optimizadas con evidencia** | `/exit_analysis` evaluado; si recomendó trailing, ya activado y validado en demo ≥ 2 semanas | `/exit_analysis` |
| 5 | **Sin bugs abiertos** | Suite verde completa + ≥ 2 semanas corriendo sin kill-switch falsos ni huérfanas | pytest + logs |

**Si CUALQUIERA está rojo, el go-live se pospone. Sin excepciones — el mercado no se va a ningún lado.**

## PARTE 2 — Decisiones que tomás VOS antes del día-D (sin código)

1. **Broker real.** Requisitos mínimos para elegirlo:
   - Cuentas **micro/cent** con lote mínimo **0.01** (ideal: cuenta *cent* donde 0.01 lot ≈ $10 nocional).
   - **Protección de balance negativo** (no podés deber plata). Obligatorio.
   - Regulado (CNBV/ASIC/FCA/CySEC), spreads razonables en majors, y **API MT5** habilitada.
   - Verificar el **depósito mínimo real** (muchos piden $50–200 USD).
2. **Capital inicial.** Recomendación honesta: el mínimo que el broker permita y que **podés perder entero sin dolor**. Con menos de ~$100 USD, ni el lote 0.01 da riesgo proporcional — preferible cuenta *cent*.
3. **Cuenta separada.** La cuenta real es NUEVA y separada de la demo. Nunca el mismo login en dos máquinas/procesos.
4. **Decisión escrita.** El día-D me decís explícitamente: "autorizo go-live con $X en el broker Y". Esa frase es el gatillo — no antes.

## PARTE 3 — Trabajo de código que haré llegado el día (1 sesión, ~medio día)

Esto NO se escribe hoy a propósito: depende del broker real elegido (contract sizes,
mínimos, comisiones) y un camino de ejecución real escrito meses antes sin poder
testearse llegaría oxidado al día-D. Lo que sí está definido es el diseño exacto:

1. **Perfil de sizing micro** (`app/risk/position_sizer.py` + settings):
   - `REAL_MAX_LOT=0.01` (hard cap), riesgo por trade en **USD absolutos** (`REAL_RISK_PER_TRADE_USD`), exposición total cap.
   - Kill-switch en **USD absolutos** (`REAL_MAX_DAILY_LOSS_USD`), no en %.
2. **Ejecutor real** (`app/brokers/mt5_real_trader.py`, NUEVO — espejo del demo trader):
   - MISMAS validaciones que el demo + extras: whitelist de símbolos, hard cap de lote, contador de órdenes/hora (anti-feedback-loop), y verificación de servidor (rechaza si el server no es el broker real autorizado).
   - `order_send` queda en exactamente DOS archivos auditados (demo + real). Ningún otro módulo lo llama.
3. **Doble traba de activación:** `ENABLE_REAL_TRADING=true` en `.env` **+** confirmación explícita por Telegram al arrancar (`/confirm_real_session` cada inicio). Una sola traba es poco.
4. **Tests nuevos** (~20): validaciones del ejecutor real, caps, kill-switch USD, doble traba, y el test de seguridad de que demo y real jamás corren a la vez.
5. **Audit final:** code review multi-agente del camino real completo antes del primer push.

## PARTE 4 — Runbook del día-D (checklist, en orden)

```
[ ] 1. /readiness en Telegram → 5 gates verdes (captura de pantalla como registro).
[ ] 2. Decisión escrita: "autorizo go-live con $X en broker Y".
[ ] 3. Yo construyo la Parte 3 (sesión de código + tests + review). Suite verde.
[ ] 4. Abrís la cuenta real en el broker → depositás SOLO el capital decidido.
[ ] 5. Logueás MT5 desktop a la cuenta real. Verificás balance en MT5.
[ ] 6. APAGÁS el bot demo (Ctrl+C). Backup de la DB (copiar trading_alert_ai.db).
[ ] 7. .env: credenciales reales (MT5_LOGIN/PASSWORD/SERVER) + ENABLE_REAL_TRADING=true
       + REAL_MAX_LOT=0.01 + REAL_RISK_PER_TRADE_USD + REAL_MAX_DAILY_LOSS_USD.
[ ] 8. Arrancás el bot → confirmás /confirm_real_session en Telegram.
[ ] 9. PRIMER DÍA: solo observás. Verificás que la primera orden real ejecute con
       lote 0.01 exacto. Cualquier anomalía → Ctrl+C inmediato y me escribís.
[ ] 10. Primera semana: revisión diaria de /performance + posiciones en MT5 a mano.
```

## PARTE 5 — Reglas de operación post-activación

- **Stop de emergencia:** si la cuenta pierde el `REAL_MAX_DAILY_LOSS_USD` en un día → el bot se frena solo 24h. Si pierde 30% del capital total → se apaga y se vuelve a demo hasta re-evaluar.
- **Sin escalado rápido:** el capital NO se aumenta hasta ≥ 1 mes real con resultado ≥ demo. Subidas de a máximo 2x por mes.
- **El demo sigue siendo el laboratorio:** toda estrategia/cambio nuevo prueba en demo primero, siempre.
- **Revisión semanal:** `/performance` + `/expectancy` real vs demo. Si el real diverge feo del demo (slippage/spread real), se documenta y se re-calibra el cost model.

---

*Mantra del documento: el candado de hoy no es burocracia — es lo que hace que el día
que se abra, se abra bien. Un bot simple con edge real le gana siempre a un bot genio
sin edge; este runbook existe para cruzar esa puerta una sola vez y sin sorpresas.*
