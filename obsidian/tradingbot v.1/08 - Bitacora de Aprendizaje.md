---
tags: [bitacora, learning, hallazgos]
version: v2.7.0
updated: 2026-05-30
---

# Bitacora de Aprendizaje

> [!info] Que es esto
> Hallazgos crudos del usuario y de las sesiones. Lo que el sistema aprendio + lo que el usuario aprendio operandolo.

---

## 2026-05-30 — La verdad de v2.7.0

> [!quote] Hallazgo brutal
> Toda estrategia tiene R negativo neto. El bot mide la verdad y frena losers, NO crea edge.

```
[SHADOW] unknown/stock:                n=32  avgR=-0.039  win=34%
[LIVE  ] forex_session_breakout/forex: n=24  avgR=-0.512  win=12%
[LIVE  ] momentum/forex:               n=22  avgR=-0.657  win=23%
[LIVE  ] momentum/stock:               n=20  avgR=-0.406  win=35%
[LIVE  ] unknown/memecoin:             n=16  avgR=-0.280  win=25%
[LIVE  ] forex_session_breakout/gold:  n=2   avgR=-1.107
```

Encontrar edge depende de:
1. Acumular data limpia (sin artifacts de Fix A)
2. Slice por sesion/regimen
3. Iterar parametros (Phase 6)

---

## 2026-05-29/30 — Hallazgo raiz: 86% del historial eran artifacts

> [!danger] Bug que invalido casi todo el aprendizaje historico
> `training_engine._update_paper_trades` era LONG-ONLY (`if latest <= stop`). Para shorts el stop esta ARRIBA del entry, asi que cada short se marcaba `stopped_simulated` en el MISMO ciclo de creacion. Vida ~12s. Precio congelado en entry.

**Consecuencia:** 86% del historial (764/884) eran artifacts del feedback-loop. El learning aprendia sobre data falsa.

**Fix A keystone v2.7.0:** `_update_paper_trades` ahora direction-aware. Cascada:
- Mata instant-kill
- Trades viven su horizonte
- Dedup de posiciones abiertas frena el feedback-loop
- Precios dejan de congelarse

---

## 2026-05-29 — Bug `_fresh_price` con simbolo Yahoo crudo

`lifecycle_manager._fresh_price` pasaba `'USDCHF=X'` (Yahoo) directo a `mt5_reader.get_tick`, que SIEMPRE fallaba → caia a precio stale.

**Fix C v2.7.0:** mapea Yahoo→MT5 (`yahoo_to_mt5`, ej. `USDCHF=X`→`USDCHF`, `GC=F`→`XAUUSD`) antes del tick.

---

## 2026-05-28 — Bug arquitectonico: MT5 huerfanas

> [!warning] Costo verificado: -$9,606 en 1 dia (27-may)
> El bot abria orden a MT5 demo, creaba paper_trade. Si despues el paper_trade cerraba por time/SL-breakeven, la posicion MT5 quedaba abierta con SL original. El bot la "olvidaba".

**Descubrimiento:** user vio en MT5 desktop 17+ XAUUSD shorts vivas con sus paper_trades ya cerrados en DB. 117+ total a lo largo del dia.

**Fix v2.6.7:** `MT5Reconciler.reconcile()` cada ciclo. Cierra MT5 positions cuyo paper_trade.status != 'open'. Sincroniza SL solo TIGHTEN.

---

## 2026-05-28 — Bug: size_notional inflado 100-1000×

`position_sizer` usaba `ACCOUNT_STARTING_BALANCE=1M` teorico. MT5 ejecutaba 0.1 lot (~$10k real). `paper_trade.size_notional` reflejaba el teorico → stats y `realized_pnl_today` inflados.

Disparo kill switch falso (−3.18% reportado vs −0.13% real).

**Fix v2.6.8:** `MT5DemoTrader.compute_actual_notional_usd()` recalcula post-demo_order y updatea paper_trade.

---

## 2026-05-28 — Feedback loop sin dedup por simbolo

Bot abrio **159 USDCHF orders en 20 min** (~8/min). `forex_session_breakout` re-detectaba el mismo setup tras cada SL hit. Dedup global protegia alertas pero no trades.

**Fix v2.6.8:** `RiskManager.check_can_open_trade(symbol=)` con `STRATEGY_SYMBOL_COOLDOWN_MINUTES=15`. Rechaza si hubo paper_trade del mismo simbolo en los ultimos N minutos.

---

## 2026-05-27 — La perdida de $12k

User perdio **$12k en 1 dia** operando con `.env` agresivo:
- `DEMO_RISK_PER_TRADE_PCT=5.26`
- `DEMO_MAX_OPEN_TRADES=100`
- `STRATEGY_MIN_CONFIDENCE=55`
- `MAX_OPEN_TRADES_TOTAL=100`

Conjunto causal:
- Mas volumen permitido + thresholds permisivos = mas signals debiles
- Risk per trade alto = SL ancho = USD por loss grande
- Caps grandes = concurrencia alta = correlation entre perdidas
- Bug huerfanas (no fixeado aun) = bleeding overnight no trackeado

**Aprendizaje:** apretar caps + risk + thresholds (post-sprint), arreglar bugs (v2.6.6-v2.6.9), agregar gate (v2.7.0).

---

## 2026-05-26 — 3 bugs overnight (v2.6.5)

| Bug | Sintoma |
|---|---|
| `realized_pnl_today` mal | Memecoin rug daba -82% sobre 1k = -82% portfolio falso |
| `symbol_select` no defensive | "0 velas M1" cuando agregabas simbolo nuevo |
| `account_balance` no refrescaba | `/health` mostraba 1M cuando MT5 real era 100k |

Fixes en v2.6.5.

---

## 2026-05-22 — Sprint scalping engine (v2.6.0)

Decision: scalping en thread dedicado porque:
- 100× mas data que swing (mas trades/dia)
- Necesita polling 3-5s (vs 60s del main loop)
- Caps independientes del swing
- Lessons separadas via sufijo `_scalping`

Estado actual: engine corre OK pero ranges suelen ser muy chicos para breakout. Mean_reversion (v2.6.6) cubre rangebound.

---

## 2026-05-20 — Decision: order_send a demo (v2.5.0)

Pivot: del modo "alerter" puro a poder ejecutar a MT5 demo. Reglas:
- Solo cuenta demo (HARDCODED validation)
- Confirmacion manual obligatoria (luego bypassable via auto-confirm opt-in v2.5.4)
- Solo forex/gold ejecutan (memecoin/stock solo paper)
- Logger nunca filtra credenciales (LogRedactor)

---

## 2026-05-18 — PIVOT alerter → trader engine (v2.0)

User decidio que el bot pase de "alertar y dejar al humano operar" a "decidir entradas/salidas autonomamente". Implico:
- Strategy router (5 swing)
- Portfolio manager + risk manager + position sizer
- Kill-switch automatico (drawdown) + manual
- Bot mode toggle (trader / alerts_only / hybrid)

---

## 2026-05-17 — Learning Engine (v1.5.2)

Primera version del aprendizaje:
- `signal_outcomes` (alert → outcome despues de N horas)
- `strategy_lessons` (agregado por feature)
- `paper_trades` (simulacion sin ejecutar)

Limitacion descubierta meses despues: media drift de alerta (no P&L realizado). Fixeado en v2.7.0 Fase 2b.

---

## Lecciones generales (meta)

> [!quote] Sobre velocidad vs solidez
> Los bugs mas costosos no fueron defectos chicos — fueron asunciones arquitectonicas equivocadas (`_update_paper_trades` long-only, huerfanas MT5, drift como aprendizaje). Cada uno requirio sesion de varios fixes interconectados.

> [!quote] Sobre medicion
> v2.7.0 demostro que aprender de drift de alerta != aprender de P&L realizado. La metrica "win_rate" sobre threshold absoluto puede ser 0% mientras el avg_return real es positivo. Conclusion: medir la realidad, no proxies.

> [!quote] Sobre estrategias
> 5 strategies activas, 0 con edge. La diferencia entre "el bot existe" y "el bot gana dinero" es enorme y honesto.

---

## Links relacionados

- [[16 - Bugs Resueltos]] - detalle tecnico de cada fix
- [[15 - Estrategias]] - stats actuales
- [[17 - Promotion Gate y Cost Model]] - como mide hoy
- [[18 - Realized R y Aprendizaje Honesto]] - Fase 2b
