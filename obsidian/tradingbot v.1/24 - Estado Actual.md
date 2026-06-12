# Estado Actual — v3.5.0 (2026-06-11)

> Reemplaza a [[14 - Estado Actual v2.7.0]] como nota de estado vigente.
> Detalle por versión en `CHANGELOG.md`; arquitectura en `CONTEXTO_MAESTRO_v3.5.0.md`.

## Dónde estamos

- **v3.5.0**, **572 tests verdes**, corriendo en la Lenovo contra MT5 demo.
- Real-money **BLOQUEADO** (HARDCODED). El comando `/readiness` muestra los gates
  honestos para algún día desbloquearlo. Veredicto hoy: **NO LISTO** (falta edge + data).
- Balance demo ~$88.6k. **El −11% fue sobre todo el bug de mayo** (~746 artifacts,
  corregidos en v2.6.7–v2.7.1). Limpio: ~−2% desde el inicio; desde el baseline
  2026-06-03 la cuenta está **+0.17% (plana)**. `/performance` lo mide.

## La serie v3 (qué se construyó)

| Versión | Qué |
|---|---|
| v3.0.0 | Veto del ensemble LLM en el gate (downward-only) |
| v3.1.0 | Resumen diario por Telegram |
| v3.2.0 | **Fase C — ContinuousLearner**: lección razonada por trade → `trade_lessons`; agrupa y PROPONE (no aplica) |
| v3.3.0 | `/performance` (baseline limpio post-bug) + `/readiness` (gates para real-money) |
| v3.3.1 | Caché + cooldown 429 para GeckoTerminal (saca el spam de rate limit) |
| v3.4.0 | **Exit shadow**: mide si un trailing mejoraría las salidas (forex/oro NO tienen trailing efectivo — usan params de memecoin con activación +50% inalcanzable). `/exit_analysis` |
| v3.5.0 | **Calendar gate** (conecta `is_safe_window` que estaba huérfano: el 10-jun abrió USDCAD 18 min antes del BOC) + **cap de exposición USD** (7 posiciones = 1 apuesta). `/exposicion`. Downward-only, opt-in OFF |

## Hallazgos clave (honestos)

1. **No hay edge probado.** El único +R agregado (forex_session_breakout +0.38R, n=86)
   lo carga el lado SHORT de un régimen — no es durable hasta validar fuera de régimen.
2. **Capture ratio ~0.68**: los winners devuelven ~1/3 del pico; 24% devuelven ≥1R.
   El exit shadow va a decir con data si un trailing lo arregla o corta runners.
3. **Gate de data Fase D: ~69/400** trades limpios con features. Lo único que lo mueve
   es dejar correr el bot.
4. **Hardware**: la GPU no banca un LLM local rápido (~50s/respuesta). El ContinuousLearner
   quedó OFF en esta máquina; el asesor (`/market`) funciona a demanda con paciencia.

## Cierre de sesión 2026-06-11 (deployado y verificado)

- **Config ACTIVA en el `.env` del user**: `ENABLE_CALENDAR_GATE=true`,
  `ENABLE_USD_EXPOSURE_CAP=true` (|3|), `STRATEGY_SYMBOL_COOLDOWN_MINUTES=60`,
  `ENABLE_EXIT_SHADOW=true` (~6.000 muestras acumulándose), `APP_VERSION=v3.5.0`.
- **Arranque oficial**: `.\start_bot.ps1` — pide contraseña (hash SHA-256 en `.env`,
  opt-in). Script en ASCII puro (PS 5.1 rompe con acentos/UTF-8 sin BOM).
- **Auditoría de seguridad: limpia.** Telegram autoriza por chat_id exacto; `.env`
  jamás commiteado; LogRedactor enmascara el token; SQL parametrizado; sin eval/exec;
  timeouts en toda la red. Menores aceptados: email en este vault (repo privado),
  pickle de modelos locales.
- **`GO_LIVE_RUNBOOK.md`**: el camino completo a real-money quedó documentado
  (5 gates, broker, código del día-D, checklist). Real-money sigue bloqueado.
- **`RESUMEN_COMPLETO.md`**: todo el proyecto en un solo documento, para retomar
  en cualquier chat nuevo.

## Qué sigue

1. Dejar correr (data ~70→400 es el cuello de botella real).
2. En 3-5 días: `/exit_analysis` → si el delta es positivo y robusto, cambiar el
   trailing de forex **con evidencia**.
3. Fase D (ensemble ML) recién con ≥400; Fase E con edge + 3 meses.
4. Real-money: `GO_LIVE_RUNBOOK.md` cuando `/readiness` esté verde en gates 1-2,
   con decisión deliberada y explícita.
