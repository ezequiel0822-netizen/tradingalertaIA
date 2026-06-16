# ESPEC — Backtest de Acciones (Bolsa) v1 (propuesta, serie v3.8.0)

> **Estado: PROPUESTA — pendiente de aprobación e implementación.** Extiende el
> Backtest Replay Harness (`ESPEC_BACKTEST_REPLAY_v1.md`, ya implementado para
> forex/oro D1) a **acciones US D1**, reusando el motor existente. Este documento
> es la fuente de verdad de la serie. Ante conflicto con las reglas inamovibles
> del proyecto (`RESUMEN_COMPLETO.md` §9), ganan las reglas del proyecto.

---

## 1. Objetivo — y la trampa que hay que mirar de frente

**Qué es:** correr las estrategias REALES del bot (`breakout`, `mean_reversion`,
`momentum`, `trend_following_d1`) sobre la **historia diaria de acciones US**, medir
R neto de costos con el mismo pesimismo (B1–B13), y reportar el veredicto §11 —
para saber, antes que el demo, si alguna estrategia de bolsa tiene edge.

**Reusa casi todo el harness de forex:** `trade_simulator`, `regime_filter`,
`report` (con la métrica de concentración), el patrón de `replay_harness`, las
convenciones B1–B13 y los criterios §11. Lo único nuevo es la **fuente de datos**
y dos defensas de honestidad propias de acciones.

## 2. ⚠️ EL PROBLEMA #1 — Sesgo de supervivencia (survivorship bias)

Esto es lo que hace que un backtest de acciones mienta si no se cuida:

- Las acciones que **quebraron, fueron delisted o absorbidas DESAPARECEN** de Yahoo.
  Tu universo `STOCK_SYMBOLS` de hoy (AAPL, NVDA, TSLA, ...) son **los sobrevivientes
  / ganadores**. Backtestear "comprar y tener" sobre ellos da retornos fantásticos
  que **nadie podía conseguir en el pasado** (no sabías en 2010 que NVDA iba a 100x).
- Es el MISMO sesgo por el que la espec de forex EXCLUYÓ memecoins. En acciones es
  igual de fatal, pero más sutil porque las acciones "parecen" data limpia.

**Reglas anti-sesgo (no negociables para esta serie):**

1. **El backtest de acciones solo sirve para DESCARTAR, no para confirmar.** Si una
   estrategia pierde incluso sobre los sobrevivientes, no tiene edge — punto. Si
   "gana", es SOSPECHOSO (probablemente es el sesgo), NO una luz verde.
2. **El reporte lleva un banner de survivorship bias arriba de todo**, y el veredicto
   §11 de acciones NUNCA habilita paper por sí solo (a diferencia del de forex):
   requiere decisión humana explícita CONSCIENTE del sesgo.
3. **Universo point-in-time (ideal, diferido a v2):** la forma correcta es un universo
   histórico (qué cotizaba en cada fecha, incluidos los muertos). Gratis y bueno es
   difícil; en v1 se documenta la limitación y se trabaja con el universo actual
   marcado como sesgado.

## 3. ⚠️ EL PROBLEMA #2 — Splits y dividendos

- Un split 4:1 hace que el precio "caiga" 75% de un día al otro: si se usa el precio
  CRUDO, el simulador lo lee como un gap brutal y fabrica trades falsos.
- **Regla:** usar SIEMPRE el **adjusted close** de Yahoo (ajustado por splits y
  dividendos), de forma consistente para OHLC. Test dedicado: un split conocido NO
  debe generar un gap_sl espurio.

## 4. Arquitectura — qué se agrega y qué se reusa

Paquete `app/backtest/` (el mismo; nada corre en el ciclo vivo):

| Archivo | Nuevo/Reuso |
|---|---|
| `app/backtest/stock_historical_loader.py` | **NUEVO**: baja D1 ajustado de Yahoo por símbolo (reusa el patrón de `stock_collector`/`safe_http`), cachea en `mt5_historical_cache` con un `source='yahoo_stock'` o tabla análoga, y reporta profundidad real + completitud. |
| `context_builder.py` | **Reuso** (acepta cualquier serie de velas D1; categoría `stock`). |
| `trade_simulator.py` | **Reuso total** (B1–B13 ya son agnósticos del activo). |
| `regime_filter.py` | **Reuso** (SMA200 + ATR sirven igual para acciones). |
| `replay_harness.py` | **Extender**: aceptar `category=stock` + universo de acciones; el resto igual. |
| `report.py` | **Extender**: banner de survivorship bias + el veredicto de acciones marcado "no habilita paper solo". |

**Cost model:** `COST_ROUNDTRIP_PCT_STOCK` (ya existe, 0.05%) × el multiplicador de
pesimismo. Acciones US líquidas tienen spread chico, pero comisión + slippage cuentan.

## 5. Convenciones específicas de acciones

- **Timeframe:** D1 (RTH). Los gaps de cierre-a-apertura (overnight) son REALES en
  acciones (a diferencia de forex 24h) → B4 (gaps) se vuelve más importante, no menos.
- **Sesión:** `session_of` es poco útil para D1 de acciones (todas ~misma hora). El
  slicing relevante es por símbolo / sector / año / régimen, no por sesión.
- **Sin operar fuera de RTH.** Entradas/salidas al open/close del día (B2 intacto).
- **Universo v1:** el `STOCK_SYMBOLS` actual, MARCADO como sesgado en el reporte.

## 6. Estrategias en alcance

`breakout`, `mean_reversion`, `momentum`, `trend_following_d1` sobre stock D1. Mismo
`STRATEGY_MIN_CONFIDENCE` que vivo. `forex_session_breakout` queda FUERA (es
intradía-forex, `macro=None` en este contexto, como en el harness de forex D1).

## 7. Criterios y veredicto

Los del §11 de la espec de forex, PERO con el agregado del §2.2: el veredicto de
acciones es informativo y **NO habilita paper automáticamente** — el sesgo de
supervivencia exige que un humano decida con los ojos abiertos. "Gana sobre
sobrevivientes" ≠ "tiene edge".

## 8. Settings nuevos (opt-in / soft-fail)

```
ENABLE_STOCK_BACKTEST=false
STOCK_BACKTEST_SYMBOLS=<por defecto, el universo STOCK_SYMBOLS>
STOCK_BACKTEST_TIMEFRAME=D1
# (reusa BACKTEST_COST_MULTIPLIER / STRESS / SL_SLIPPAGE_ATR de la serie de forex)
```

## 9. Tests requeridos (~25 nuevos)

- `test_stock_historical_loader.py`: cache round-trip; adjusted close (un split conocido
  NO produce gap espurio); símbolo sin data → soft-fail; reporte de profundidad.
- `test_stock_harness.py`: corre las 4 estrategias sobre stock D1; escribe SOLO en
  `backtest_*`; determinismo; el reporte lleva el banner de survivorship bias.
- Reuso de los tests existentes del simulador/régimen/report (no se duplican).

## 10. Plan de sesiones (con gate por sesión)

| Sesión | Entrega | Gate |
|---|---|---|
| S1 | `stock_historical_loader` (Yahoo D1 ajustado) + cache + tests | pytest verde; imprime profundidad real por símbolo; el test del split pasa. |
| S2 | `replay_harness`/`report` extendidos a `category=stock` + banner de sesgo + primer run Modo A real | pytest verde; `report.md` con el banner; revisión humana. |
| S3 | `trend_following_d1` sobre acciones + veredicto §11 + cierre v3.8.0 (bump + CHANGELOG + docs) | pytest verde; veredicto documentado CON la advertencia de sesgo; merge. |

## 11. Prohibiciones explícitas

- NO mezclar la data de acciones con la de forex en el mismo run (precios y costos
  distintos).
- NO usar precio crudo de Yahoo (solo adjusted).
- El veredicto de acciones NO habilita paper ni demo automáticamente (survivorship).
- Lo de siempre: no toca el ciclo vivo, escribe SOLO en `backtest_*`, no cuenta para
  `/readiness` ni la Fase D, `ENABLE_REAL_TRADING=false` sigue HARDCODED.

---

*Preparado tras el refocus a la bolsa (v3.7.0). La pregunta que esta serie responde
con honestidad: "¿alguna estrategia de acciones tiene edge, o solo lo parece por el
sesgo de supervivencia?" Si no pasa ni sobre los sobrevivientes, la respuesta es clara.*
