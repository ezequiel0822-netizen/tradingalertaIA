---
tags: [alertas, scoring, deteccion]
version: v2.7.0
updated: 2026-05-30
---

# Alertas y Scoring

> [!info] Filosofia
> Mandar **pocas alertas y de mejor calidad**. El sistema usa caps por categoria + por run, dedup, scoring threshold, learned_weights y eventualmente learning_gate.

---

## Pipeline de alerta

```
Snapshot crudo
    ↓
Token Score (analyzer + features)
    ↓
Move Estimator (gain/loss/confidence)
    ↓
Risk Check (GoPlus para cripto)
    ↓
IA Pro (setup, sesgo, riesgos)
    ↓
Learning Gate (si activo)
    ↓
Dedup check
    ↓
Cap check por categoria
    ↓
Telegram grouped alert
```

---

## Scoring base

Componentes:
- **Liquidity strength** — `liquidity_usd` vs umbral
- **Volume strength** — `volume_5m` y `volume_1h`
- **Trending/Boosted** — flag de DEX Screener
- **Anti-hype** — penaliza nombres tipicos de scam
- **Critical security** — GoPlus flags (honeypot, ownership, etc.)
- **IA Pro** — pro_high_conviction, neutral, low_conviction
- **News score** — Yahoo RSS + keywords
- **SEC catalyst** — filings recientes (10-K, 10-Q, 8-K)
- **Technical patterns** — RSI, MACD, ATR, Bollinger, S/R
- **Multi-tf alignment** — M15 + H1 confluence

Score final: 0-100.

---

## Buckets por score

| Bucket | Rango | Tag |
|---|---|---|
| Top tier | 90+ | `score:90+` |
| High | 80-90 | `score:80-90` |
| Medium | 65-80 | `score:65-80` |
| Low | 50-65 | `score:50-65` |

`score:80-90` es historicamente el unico bucket consistentemente profitable en memecoins (+6.70% avg_return en preview gate).

---

## Caps actuales (user .env, conservadores)

| Categoria | per_24h | per_run |
|---|---|---|
| Memecoin total | 30 | 10 (5 early + 5 mature) |
| Memecoin early | 10 | 3 |
| Memecoin mature | 10 | — |
| Stock | 20 | 5 |
| Forex | 30 | 5 |
| Gold | 15 | 2 |

`ALERT_CAP_WINDOW_HOURS=24`, `DEDUP_WINDOW_MINUTES=360` (6h).

---

## Thresholds para enviar

| Setting | Valor | Que |
|---|---|---|
| `ALERT_SCORE_THRESHOLD` | 65 | Memecoin score >= 65 |
| `MIN_LIQUIDITY_USD` | 8,000 | Memecoin pool minimo |
| `MIN_VOLUME_5M_USD` | 4,000 | Volumen 5min |
| `MIN_VOLUME_1H_USD` | 12,000 | Volumen 1h |
| `MIN_ESTIMATED_GAIN_PCT` | 300 | Memecoin upside esperado |
| `MIN_ESTIMATE_CONFIDENCE` | 40 | Confianza estimacion |
| `MIN_STOCK_ESTIMATED_GAIN_PCT` | 8 | Stock upside esperado |
| `MIN_STOCK_ESTIMATE_CONFIDENCE` | 60 | Confianza estimacion stock |
| `STRATEGY_MIN_CONFIDENCE` | 65 | Strategy confidence minima |
| `READINESS_MIN_SCORE` | 72 | Readiness grade A score >= 72 |
| `READINESS_MIN_CONFIDENCE` | 65 | Readiness grade A conf >= 65 |

---

## Move estimator

Calcula gain/loss/confidence con base en:
- Score base
- News score
- Pattern strength
- Volume relativo
- Liquidez
- Macro regime (risk_on/off)

Output:
- `estimated_gain_pct`
- `estimated_loss_pct`
- `confidence` (0-100)
- `label` (low/medium/high)
- `reasons` (lista corta)

---

## Learned weights (v2.6.5+)

`ENABLE_LEARNED_WEIGHTS=true` ajusta el score base segun el aprendizaje historico por feature:
- Si `volume_strength` tuvo win_rate 70% → bump +X
- Si `risk:yellow` tuvo win_rate 8% → penalty -X

Limites:
- `LEARNED_WEIGHTS_MIN_SAMPLES=5`
- `LEARNED_WEIGHTS_MIN_CONFIDENCE=40`
- `LEARNED_WEIGHTS_PER_FEATURE_MAX=3.0` (max ajuste por feature)
- `LEARNED_WEIGHTS_MAX_ADJUSTMENT=10.0` (max ajuste total)

**v2.7.0 Fase 2b** — los weights ahora aprenden del **realized-R** de paper_trades (no del drift de alerta). Ver [[18 - Realized R y Aprendizaje Honesto]].

---

## Learning gate

> [!warning] NO activar todavia
> `ENABLE_LEARNING_GATE=false`. El preview revelo que bloquearia ~todo porque los `OUTCOME_WIN_RETURN_*` son muy estrictos. Ver `/gate_preview` para chequear evolucion.

Cuando se active, filtra signals cuyo subset (`category:`, `alert:`, `score:`) tenga win_rate < `LEARNING_GATE_MIN_WIN_RATE` con N >= `LEARNING_GATE_MIN_SAMPLES` en `LEARNING_GATE_SINCE_DAYS`.

**v2.7.0 Fase 2b** — el gate ahora puede operar sobre realized-R neto (no drift). Tabla `realized_feature_lessons`.

---

## Force learning gate para memecoin

`FORCE_LEARNING_GATE_FOR_MEMECOIN=true` — aunque `ENABLE_LEARNING_GATE=false` a nivel global, **memecoin SIEMPRE pasa por el gate**. Defensa anti-rug.

---

## Dedup

`DEDUP_WINDOW_MINUTES=360` (6h). Mismo `(chain, token_address, alert_type)` no se re-envia en esa ventana.

`STRATEGY_SYMBOL_COOLDOWN_MINUTES=15` (v2.6.8) — separate del dedup de alertas: bloquea ABRIR NUEVO trade del mismo simbolo si hubo trade en los ultimos 15 min. Previene feedback loops (159 USDCHF orders en 20 min del 27-may).

---

## Telegram grouped alerts

Cada categoria se agrupa por run:
```
=== category=memecoin_early items=3 ===
1. ...
2. ...
3. ...

=== category=memecoin_mature items=5 ===
...
```

---

## Stats observadas de scoring

Per `/gate_preview` reciente:

| Feature | Samples | Win rate | Avg return | Conclusion |
|---|---|---|---|---|
| `score:80-90` (memecoin) | 10 | 0% (estricto) | +6.70% | UNICO profitable |
| `score:65-80` (memecoin) | 168 | 9.52% | -4.72% | Filter |
| `gain_estimate:1000+` (memecoin) | 238 | 14.71% | +0.61% | Moonshots OK |
| `gain_estimate:500-1000` | 325 | 4.92% | -2.24% | Filter |
| `alert:price_spike` | 603 | 9.29% | -0.88% | Filter |
| `confidence:55-70` | 525 | 8.38% | -2.11% | Filter |
| `risk:yellow` | 327 | 8.26% | -1.69% | Filter |
| `volume_strength` | 732 | 6.83% | -0.10% | Filter |

> [!warning] Mismatch entre win_rate y avg_return
> `score:80-90` tiene win_rate=0% (estricto, threshold +30%) pero avg_return positivo. La rule ES profitable, solo no hit el threshold estricto. Por eso NO activar learning_gate todavia.

---

## Links relacionados

- [[10 - Learning Engine]] - sistema completo
- [[18 - Realized R y Aprendizaje Honesto]] - Fase 2b
- [[15 - Estrategias]] - strategies que generan signals
- [[13 - Comandos Telegram]] - `/gate_preview`, `/aprendizaje`, `/expectancy`
