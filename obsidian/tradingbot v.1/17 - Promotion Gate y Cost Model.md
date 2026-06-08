---
tags: [v2.7.0, gate, cost-model, realized-r]
version: v2.7.0
updated: 2026-05-30
---

# Promotion Gate y Cost Model (v2.7.0)

> [!info] El cambio de identidad de v2.7.0
> El bot paso de medir una metrica ficticia (drift de alerta a horizonte fijo) a medir el **P&L realizado real, neto de costos, en R-multiples**, y a **no ejecutar a MT5 estrategias con edge negativo probado**.

---

## Realized-R (la metrica honesta)

### Que es R

R = Risk-multiple. 1R = el SL distance al entry.

- Trade gana 2× lo arriesgado → +2R
- Trade pierde 1.5× lo arriesgado → -1.5R
- Strategy con expectancy +0.3R promedio = gana 0.3× el risk por trade en promedio

Es la metrica estandar de la industria para evaluar strategies. Independent del notional (compara strategies con sizing distintos).

### Implementacion: `app/learning/trade_outcomes.py`

> [!success] Modulo NUEVO v2.7.0
> Centraliza calculo de realized return, R-multiple, artifact detection, cost model y promotion gate.

Funciones principales:

```python
def realized_return_pct(trade) -> float:
    """Direction-aware, con partial close, NETO de costos"""

def risk_at_entry_pct(trade) -> float:
    """Usa original_stop_loss (no el actual post-trailing/breakeven)"""

def r_multiple(trade, cost_pct) -> float:
    """realized_return / risk_at_entry, neto de costo round-trip"""

def is_artifact(trade) -> bool:
    """True si precio congelado (entry == latest, vida < N segundos)"""

def outcome_label(r) -> str:
    """big_win / win / scratch / loss / big_loss"""

def build_strategy_performance(repository, settings) -> list[dict]:
    """Agrupa por (strategy_name, category), excluye artifacts, calcula avg_r, win_rate"""

def should_execute_live(strategy, category, perf_row, min_samples, min_expectancy_r) -> tuple[bool, str]:
    """Promotion gate decision"""
```

### Tabla `strategy_performance`

PK: `(strategy_name, category)`. Columnas:
- `sample_count` — trades cerrados no-artifact
- `avg_r_net` — expectancy neta de costos
- `win_rate`, `loss_rate`, `scratch_rate`
- `arts_excl` — artifacts excluidos
- `updated_at`

Refrescada cada learning cycle via `_refresh_strategy_performance` (en `training_engine.py` linea ~57, dentro de `if enable_paper_trading`).

---

## Promotion Gate (filosofia)

> [!quote] Inocente hasta probarse culpable
> Default: cada strategy se asume valida y puede ejecutar a MT5 demo. Solo cuando junta evidencia ESTADISTICA de edge negativo, se la baja a SHADOW (paper-only).

### `should_execute_live`

```python
def should_execute_live(strategy, category, perf_row, min_samples, min_expectancy_r):
    if perf_row is None or perf_row["sample_count"] < min_samples:
        return True, f"sin data suficiente (n<{min_samples}) - LIVE por default"
    if perf_row["avg_r_net"] <= min_expectancy_r:
        return False, f"avg_R={perf_row['avg_r_net']:.3f} <= {min_expectancy_r} - SHADOW (paper-only)"
    return True, f"avg_R={perf_row['avg_r_net']:.3f} > {min_expectancy_r} - LIVE"
```

### Hooks

- `jobs._try_prepare_demo_order` (swing): valida antes de crear `demo_trade_request`
- `scalping_engine._open_scalping_trade` (scalping): valida antes de `send_prepared_request`

Si gate rechaza:
- Paper trade SE CREA (la data sigue acumulando)
- `demo_order` NO SE ENVIA
- Strategy queda en SHADOW

> [!success] Propiedad clave: SUBTRACTIVO
> El gate solo PREVIENE order_send. Nunca lo CAUSA. Imposible que el gate active real-money o invierta una decision de no-trade en si-trade.

### Settings

```bash
ENABLE_STRATEGY_PROMOTION_GATE=true    # default ON (restrictivo = reduce riesgo)
STRATEGY_PROMOTION_MIN_SAMPLES=30      # cuantos trades antes de considerar evidencia
STRATEGY_PROMOTION_MIN_EXPECTANCY_R=0.0  # umbral. R neto <= 0.0 → SHADOW
```

`STRATEGY_PROMOTION_MIN_SAMPLES=30` es conservador. Para acelerar deteccion de losers, bajar a 20.

---

## Cost Model

### Por que existe

Sin restar costos, el realized-R era optimista vs MT5 real. Una strategy con avg_return bruto +0.10R podia ser -0.10R neta si el round-trip cost era 0.20R. El gate podia promover strategies "positivas en bruto pero negativas netas".

### Implementacion

`build_strategy_performance` resta un costo round-trip por categoria (siempre, gane o pierda):

```python
cost_pct = settings.cost_roundtrip_pct[category]
r = (realized_return_pct - cost_pct) / risk_at_entry_pct
```

### Settings (% por roundtrip)

```bash
ENABLE_COST_MODEL=true                # default ON
COST_ROUNDTRIP_PCT_FOREX=0.02
COST_ROUNDTRIP_PCT_GOLD=0.03
COST_ROUNDTRIP_PCT_STOCK=0.05
COST_ROUNDTRIP_PCT_MEMECOIN=0.5
```

Defaults conservadores para MT5 demo. Pendiente calibrar con fills reales (ver [[07 - Ideas y Proximos Pasos]]).

---

## Quarantine de artifacts

`is_artifact(trade)` detecta:
- Vida demasiado corta (< N segundos)
- `entry_price == latest_price` (precio congelado)
- `unrealized_return_pct == 0` consistente

Estos trades NO entran al calculo de `strategy_performance`. Razon: son artifacts del bug Fix A (`_update_paper_trades` long-only pre-v2.7.0). Incluirlos contamina la estadistica.

`arts_excl` en `/expectancy` muestra cuantos artifacts se excluyeron por strategy.

---

## `/expectancy` Telegram command

Output:
```
v2.7.0 expectancy (realized R, NETO de costos)

[SHADOW] unknown/stock:                n=32  avgR=-0.039  win=34%
[LIVE  ] forex_session_breakout/forex: n=24  avgR=-0.512  win=12%   (arts_excl=339)
[LIVE  ] momentum/forex:               n=22  avgR=-0.657  win=23%
[LIVE  ] momentum/stock:               n=20  avgR=-0.406  win=35%
[LIVE  ] unknown/memecoin:             n=16  avgR=-0.280  win=25%
[LIVE  ] mean_reversion/forex:         n=6   avgR=-0.156
[LIVE  ] mean_reversion/stock:         n=5   avgR=-0.259  (arts_excl=171)
...

No es recomendacion financiera. Revisar manualmente.
```

- `[LIVE]` = puede mandar a MT5 demo
- `[SHADOW]` = bloqueada por gate, paper-only
- `arts_excl` = artifacts excluidos por quarantine

> [!warning] Sin emojis
> Por regla del v2.6.9 doc, output limpio sin emojis.

---

## Lo que NO hace el gate

- **No** toca real-money (`ENABLE_REAL_TRADING` sigue HARDCODED false)
- **No** modifica la creacion de paper_trades (la data sigue juntandose esten LIVE o SHADOW)
- **No** afecta scoring ni alerts a Telegram
- **No** modifica strategies (siguen ejecutando su logica, solo se bloquea el order_send)
- **No** modifica datos historicos
- **No** auto-promotional sin evidencia (default sin data = LIVE)

---

## Lo que el gate refuerza

Capa cuarta de defensa contra real-money:
1. `ENABLE_REAL_TRADING=false` HARDCODED
2. `mt5_demo_trader._validate_demo_account()` rechaza non-demo
3. `order_send` solo desde `mt5_demo_trader.py`
4. **`should_execute_live()` rechaza losers probados** (v2.7.0)

---

## Stats actuales (al cierre v2.7.0)

| Strategy | n | avgR_net | Tag | Razon |
|---|---|---|---|---|
| unknown/stock | 32 | -0.039 | **SHADOW** | n>=30, avgR<=0 |
| forex_session_breakout/forex | 24 | -0.512 | LIVE | n<30 |
| momentum/forex | 22 | -0.657 | LIVE | n<30 (pero disabled en .env) |
| momentum/stock | 20 | -0.406 | LIVE | n<30 (pero disabled) |
| unknown/memecoin | 16 | -0.280 | LIVE | n<30 |
| mean_reversion/forex | 6 | -0.156 | LIVE | n<30 |

Para acelerar:
- Bajar `STRATEGY_PROMOTION_MIN_SAMPLES` de 30 a 20
- O disable manual via `.env` (caso `forex_session_breakout`)

---

## Edge no creado, edge medido

> [!quote] La verdad de v2.7.0
> El bot mide la verdad neta de costos. NO crea edge — eso sigue siendo el problema dificil (datos + research).

Encontrar edge requiere:
1. Data limpia post-quarantine (acumular semanas/meses)
2. Slice por sesion/regimen (London/NY/Asian + risk_on/off)
3. Iterar parametros (Phase 6 evolution)
4. Cost model calibrado con fills reales (no defaults teoricos)

---

## Tests v2.7.0

| Test file | Cobertura |
|---|---|
| `test_trade_outcomes.py` | realized_return, r_multiple, is_artifact, outcome_label |
| `test_strategy_promotion_gate.py` | should_execute_live decisions, hooks en jobs/scalping |
| `test_cost_model.py` | costo round-trip per categoria, R neto |
| `test_expectancy_command.py` | output formato + LIVE/SHADOW tags |
| `test_realized_learning.py` | Fase 2b realized_feature_lessons |

Total v2.7.0: +40 tests (357 → 397).

---

## Links relacionados

- [[18 - Realized R y Aprendizaje Honesto]] - Fase 2b complement
- [[10 - Learning Engine]] - sistema completo
- [[15 - Estrategias]] - stats por strategy
- [[16 - Bugs Resueltos]] - Fix A que hizo la data limpia
- [[02 - Reglas de Seguridad]] - como protege capital
