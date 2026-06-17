# Estado Actual — v3.8.0 (2026-06-17)

> Reemplaza a [[14 - Estado Actual v2.7.0]] como nota de estado vigente.
> Detalle por versión en `CHANGELOG.md`; arquitectura en `CONTEXTO_MAESTRO_v3.8.0.md`.

## Dónde estamos

- **v3.8.0**, **676 tests verdes**, corriendo en la Lenovo contra MT5 demo.
- **REFOCUS v3.7.0: 100% LA BOLSA** (acciones US + forex + oro). Memecoins CORTADAS
  (`ENABLE_MEMECOIN_ENGINE=false`; el user montó un bot aparte), scalping APAGADO, stock
  alerts ON. **v3.8.0: regime gate vivo** (`ENABLE_REGIME_GATE`, opt-in, downward-only):
  los longs contra-tendencia D1 van a paper.
- **Diagnóstico (16-jun):** los longs sangran (−0.57R) y los shorts ganan (+1.29R) = es
  RÉGIMEN, no edge. No es volatilidad (VIX ~16, calmo). Balance demo plano ~$88.6k; las
  pérdidas grandes que se veían eran memecoins en PAPEL (no tocan dinero).
- **Backtest Replay Harness** (offline, `app/backtest/`): reproduce la historia D1 con las
  estrategias REALES y mide R neto con pesimismo, en tablas `backtest_*` separadas. No toca
  el ciclo vivo, no cuenta para `/readiness` ni la Fase D. Opt-in OFF. Ya cubre acciones
  (Yahoo) además de forex/oro (MT5).
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
| v3.6.0 | **Backtest Replay Harness** (`app/backtest/`) + `regime_filter` + `trend_following_d1` (Donchian D1, hipótesis congelada). Reproduce décadas de D1 con las estrategias REALES, offline, tablas `backtest_*`. Veredicto: sin edge en D1 |
| v3.7.0 | **Refocus a la bolsa**: `ENABLE_MEMECOIN_ENGINE` corta la colección de memecoins (bot aparte) + ESPEC del backtest de acciones. Scalping off, stock alerts on |
| v3.8.0 | **Regime gate vivo** (`ENABLE_REGIME_GATE`, opt-in, downward-only): longs contra-tendencia D1 → paper. Cablea el `regime_filter` al gate. Nace del diagnóstico (longs −0.57R/shorts +1.29R) |
| backtest acciones | S1 (`stock_historical_loader`, Yahoo D1 ajustado) + S2 (harness `category=stock` + banner survivorship). Código hecho; run real pendiente (Yahoo throttle) → v3.9.0 |

## Hallazgos clave (honestos)

1. **No hay edge probado — confirmado por el backtest.** El único +R vivo (forex_session_breakout
   +0.38R, n=86) lo carga el lado SHORT de un régimen. Y el harness v3.6.0, sobre décadas de
   D1, mostró que **ninguna estrategia pasa §11**: el +4.7R del `trend_following_d1` era un
   ARTEFACTO (1 trade sintético de USDCHF = 80% del P&L; mediana real −1.03R). Nada se promovió.
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

## Cierre de sesión 2026-06-14 (v3.6.0 — Backtest Replay Harness)

- Serie de 5 sesiones (S1→S5, una por gate, ESPEC_BACKTEST_REPLAY_v1.md): tablas
  `backtest_*` + loader, `context_builder` + `regime_filter`, `trade_simulator` (B1–B13),
  `replay_harness` + `report`, y `trend_following_d1`. **657 tests verdes.**
- Profundidad real medida: D1 con décadas (EUR/CHF/JPY desde 1971), H1 topado en 50k barras.
- **Veredicto honesto:** ninguna estrategia pasa §11 en D1. El "+4.7R" del trend D1 fue un
  artefacto (1 trade sintético de USDCHF); el harness lo atrapó (drawdown 57.5R + concentración).
  **No se promovió nada.** El edge no está en estas estrategias sobre D1.
- `APP_VERSION=v3.6.0`. Preflight nuevo (`preflight.py`) para verificar el arranque sin tocar nada.

## Cierre de sesión 2026-06-17 (v3.7.0 refocus + v3.8.0 regime gate + backtest acciones)

- **v3.7.0 refocus a la bolsa:** `ENABLE_MEMECOIN_ENGINE` (corta colección de memecoins; el
  user montó un bot aparte). En el `.env`: memecoins off, scalping off, stock alerts on.
- **Diagnóstico (por qué pierde):** slicing por dirección → longs −0.57R / shorts +1.29R =
  régimen, no edge. No es volatilidad (VIX ~16). Balance demo PLANO; lo rojo grande era
  memecoins en papel.
- **v3.8.0 regime gate:** los longs contra-tendencia D1 van a paper (opt-in, downward-only).
- **Backtest de acciones:** S1 (loader Yahoo D1 ajustado, validado: AAPL 11.469 barras) + S2
  (harness `category=stock` + banner survivorship). Código hecho + testeado; run real con
  veredicto PENDIENTE (Yahoo throttleó la IP). **676 tests verdes.** `APP_VERSION=v3.8.0`.

## Qué sigue

1. Dejar correr el libro vivo limpio (data ~70→400 para la Fase D — el backtest NO la reemplaza).
2. **Probar el regime gate en vivo** (`ENABLE_REGIME_GATE=true`) — deja de tomar longs contra-tendencia.
3. **Completar el veredicto del backtest de acciones** (S2 run cuando Yahoo no throttlee) + S3
   (trend_following_d1 sobre acciones + v3.9.0).
4. **COT collector** (info nueva = mejor chance real, `MAPA §3.4`).
5. Fase D (ensemble ML) recién con ≥400; Fase E con edge + 3 meses.
6. Real-money: `GO_LIVE_RUNBOOK.md` cuando `/readiness` esté verde, con decisión deliberada.
