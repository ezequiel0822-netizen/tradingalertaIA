---
tags: [v2.7.0, fase-2b, learning, realized-r]
version: v2.7.0
updated: 2026-05-30
---

# Realized R y Aprendizaje Honesto (v2.7.0 Fase 2b)

> [!info] Que es Fase 2b
> Re-apunta `learned_weights` y `learning_gate` desde el path "drift de alerta" hacia el path "P&L realizado neto de costos". El learning_gate ahora ES activable (antes era inutil).

---

## El problema previo (path drift)

`learned_weights` y `learning_gate` aprendian de `signal_outcomes`:
- Outcome = drift de alerta a horizonte fijo (1h/6h/24h/7d)
- Umbral absoluto: `OUTCOME_WIN_RETURN_*_PCT` (memecoin +30%, stock +5%)
- Casi nada hit eso → ~99% outcomes 'neutral'
- Gate inutil que bloqueaba casi todo

### Ejemplo del mismatch

`score:80-90` memecoin:
- Win rate por threshold absoluto +30%: **0%** (raramente memecoin sube tanto)
- Avg return real: **+6.70%** (rule profitable)
- Gate antiguo: BLOCK (win_rate 0% < 45%)
- Realidad: rule profitable, gate la matarias por error

---

## La solucion (path realized-R)

Aprender de paper_trades CERRADOS:
- `realized_return_pct` (direction-aware, con partial close, neto de costos)
- Risk = `risk_at_entry_pct` (SL original, no trailing)
- R-multiple = realized / risk
- Excluye artifacts (precio congelado)

---

## Implementacion

### Modulo

`app/learning/trade_outcomes.py` (mismo que [[17 - Promotion Gate y Cost Model]]).

Funcion nueva v2.7.0 Fase 2b:

```python
# trade_outcomes.py — funcion PURA (recibe la data, no el repo).
def build_realized_feature_lessons(closed_trades, features_by_alert_id,
                                   cost_pct_by_category=None,
                                   partial_fraction=0.5, min_samples=2) -> list[dict]:
    """Junta cada paper_trade cerrado -> su R neto -> features del alert.
    Agrupa por (feature, category), excluye artifacts."""
    buckets = {}
    for t in closed_trades:
        if is_artifact(t): continue
        cat = t["category"]
        cost = (cost_pct_by_category or {}).get(cat, 0.0)
        r = r_multiple(t, partial_fraction, cost)
        if r is None: continue
        feats = features_by_alert_id.get(t["alert_id"], []) + [f"category:{cat}"]
        for f in feats:
            buckets.setdefault((f, cat), []).append(r)
    # un lesson por (feature, category) con n >= min_samples; win_rate = fraccion R>0
    return [_lesson(feat, cat, rs) for (feat, cat), rs in buckets.items()
            if len(rs) >= min_samples]

# training_engine._refresh_realized_feature_lessons arma los inputs y persiste:
#   closed = repository.fetch_closed_paper_trades(limit=5000)
#   features_by_alert_id = {so["alert_id"]: json.loads(so["features"]) for so in signal_outcomes}
#   cost_map = {forex:0.02, gold:0.03, stock:0.05, memecoin:0.5}  # si enable_cost_model
#   for l in build_realized_feature_lessons(closed, features_by_alert_id, cost_map):
#       repository.upsert_realized_feature_lesson({**l, "updated_at": now})
```

### Tabla nueva

`realized_feature_lessons` (PK `(feature, category)`):
- `feature`, `category`
- `sample_count`, `wins`
- `win_rate` (fraccion con R > 0)
- `avg_r` (R-multiple promedio, neto de costos)
- `avg_return_pct`, `confidence`
- `updated_at`

Refrescada cada learning cycle via `_refresh_realized_feature_lessons`, que arma el mapa `alert_id -> features` desde `signal_outcomes` y llama a `build_realized_feature_lessons`.

### Settings

```bash
ENABLE_REALIZED_LEARNING=true    # default ON
```

Si OFF, fallback al path drift (compatible con tests viejos).

---

## Apply en `learned_weights`

`apply_learned_weights` lee de `realized_feature_lessons` (si flag ON):

```python
def apply_learned_weights(base_score, features, category, settings, repository):
    if settings.enable_realized_learning:
        lessons = repository.fetch_realized_feature_lessons(category=category)
    else:
        lessons = repository.fetch_strategy_lessons(category=category)  # drift (fallback)

    adjustment = 0.0
    for feature in features:
        lesson = lessons_by_feature.get(feature)
        if not lesson: continue
        if lesson.sample_count < settings.learned_weights_min_samples: continue
        if lesson.confidence < settings.learned_weights_min_confidence: continue
        # MISMA formula que el path drift; solo cambia la FUENTE (realized vs drift).
        # win_rate aca = fraccion de trades con R>0 (realized), no el drift.
        bonus = (lesson.win_rate - 0.5) * 2 * (lesson.confidence/100) * per_feature_max
        adjustment += bonus

    return clamp(adjustment, -max_total, max_total)
```

---

## Apply en `learning_gate`

Nuevo helper `_evaluate_gate_realized`:

```python
def _evaluate_gate_realized(features, category, settings, repository):
    subset = [f for f in features if f.startswith(("category:", "alert:", "score:"))]
    if not subset:
        subset = [f"category:{category}"]

    lessons = repository.fetch_realized_feature_lessons(category=category)
    by_feature = {l.feature: l for l in lessons}
    # solo features con muestra suficiente
    candidates = [by_feature[f] for f in subset
                  if f in by_feature and by_feature[f].sample_count >= settings.learning_gate_min_samples]
    if not candidates:
        return True, "realized: insufficient samples"

    # bloquea si la PEOR feature (min win_rate) esta por debajo del umbral
    worst = min(candidates, key=lambda l: l.win_rate)
    if worst.win_rate < settings.learning_gate_min_win_rate:
        return False, f"realized win_rate {worst.win_rate:.0%} below ({worst.feature}, n={worst.sample_count})"
    return True, f"realized win_rate ok ({worst.feature})"
```

`evaluate_learning_gate` dispatchea entre `_evaluate_gate_realized` (v2.7.0 default) y `_evaluate_gate_drift` (fallback).

---

## Por que NO activar `learning_gate` todavia

> [!warning] Data por-feature escasa
> ~120 trades reales repartidos en muchas features. `realized_feature_lessons` actua poco por feature individual hasta juntar mas data limpia (testeado).

Estado actual:
- Total trades reales: ~120
- Features distintas: muchas (cada combinacion category/alert/score)
- Samples por feature: pocas (en muchos casos 0)
- Gate efectivo solo cuando feature tiene n >= `LEARNING_GATE_MIN_SAMPLES=10`

Esperar 1-2 semanas mas + recalibrar `OUTCOME_WIN_RETURN_*` para que mas trades cuenten como "wins" del threshold absoluto (todavia se usa en signal_outcomes original).

---

## Tests v2.7.0 Fase 2b

`tests/test_realized_learning.py` (+7 tests):
- build_realized_feature_lessons con paper_trades reales
- exclude artifacts
- apply_learned_weights con flag ON usa realized
- apply_learned_weights con flag OFF usa drift (fallback)
- evaluate_learning_gate con flag ON usa realized
- evaluate_learning_gate con flag OFF usa drift (fallback)
- realized_feature_lessons refresca correctamente cada cycle

Total v2.7.0: 397 verdes.

---

## Diferencia conceptual (drift vs realized)

| | Drift | Realized |
|---|---|---|
| **Que mide** | Cambio precio entre alerta y horizonte fijo | P&L real del paper_trade ejecutado |
| **Threshold** | Absoluto (% configurado) | Relativo (% del SL distance = R) |
| **Direction-aware** | No | Si (SHORT entries valido) |
| **Partial close** | No | Si |
| **Costos** | No | Si (round-trip per categoria) |
| **Artifacts excluidos** | No | Si |
| **Util para gate** | No (~99% neutral) | Si (R+/R- per feature) |

---

## Fallback path drift (todavia activo)

`signal_outcomes` y `strategy_lessons` siguen actualizandose en paralelo. Razones:
- Tests viejos siguen funcionando
- `/aprendizaje` lee de `strategy_lessons` (path drift)
- Si `ENABLE_REALIZED_LEARNING=false`, todo vuelve a operar sobre drift

Migracion gradual:
- Hoy: realized para weights + gate, drift para `/aprendizaje`
- Futuro: tambien `/aprendizaje` sobre realized cuando data lo permita

---

## Decision arquitectonica clave

> [!quote] Por que dos paths en vez de migrar todo
> El path drift tiene 145k+ outcomes historicos. Borrarlo seria perder data. Mantener ambos paths permite:
> 1. Aprendizaje legacy sigue para reportes
> 2. Realized aprende sobre data nueva post-Fix A
> 3. Si realized falla, fallback transparente al drift via flag
> 4. Comparacion lado-a-lado para validar la transicion

---

## Links relacionados

- [[17 - Promotion Gate y Cost Model]] - companero conceptual
- [[10 - Learning Engine]] - sistema completo
- [[16 - Bugs Resueltos]] - Fix A que limpia la data
- [[15 - Estrategias]] - donde se aplica
- [[05 - Alertas y Scoring]] - como impacta el scoring
