---
tags: [estrategias, swing, scalping, backtest, stats]
version: v3.6.0
updated: 2026-06-14
---

# Estrategias

> [!info] 7 vivas (5 swing + 2 scalping) + 1 de backtest (`trend_following_d1`, v3.6.0)
> Cada una con su filosofia + stats reales post-quarantine. Toda strategy hoy tiene **R negativo neto** — el bot mide la verdad, no inventa edge. Las tablas de stats de abajo son **históricas v2.7.0** (no se reescriben con números inventados).

> [!warning] El backtest v3.6.0 lo confirmó
> El Backtest Replay Harness corrió las estrategias REALES sobre décadas de D1: **ninguna pasa los criterios §11**. El `trend_following_d1` (Donchian, hipótesis congelada) mostró un avg +4.7R que era un **ARTEFACTO** — un solo trade sintético de USDCHF (pre-1999) cargaba el 80% del P&L; la mediana real es −1.03R. Nada se promovió. El edge no está en estas estrategias sobre D1.

---

## Estado actual por strategy

### Resumen `/expectancy` (v2.7.0, neto de costos)

| Strategy / Categoria | n | avgR | Win | Tag |
|---|---|---|---|---|
| `unknown/stock` | 32 | -0.039 | 34% | **SHADOW** |
| `forex_session_breakout/forex` | 24 | -0.512 | 12% | LIVE (n<30) |
| `momentum/forex` | 22 | -0.657 | 23% | LIVE (disabled en .env) |
| `momentum/stock` | 20 | -0.406 | 35% | LIVE (disabled en .env) |
| `unknown/memecoin` | 16 | -0.280 | 25% | LIVE |
| `mean_reversion/forex` | 6 | -0.156 | — | LIVE |
| `mean_reversion/stock` | 5 | -0.259 | — | LIVE |
| `momentum/gold` | 3 | -1.077 | — | LIVE (disabled) |
| `forex_session_breakout/gold` | 2 | -1.107 | — | LIVE (n<30) |
| `scalping_breakout/forex` | 1 | -0.362 | — | LIVE |

> [!warning] Toda en negativo
> Ninguna strategy tiene edge probado. v2.7.0 mide y frena losers — no inventa profit.

---

## Strategies SWING

### 1. `breakout` (`breakout.py`)

**Filosofia:** Precio rompe arriba con volumen confirmado.

**Filtros:**
- `pattern.trend == "bullish"` y `pattern.macd_signal == "bullish"`
- `pattern.relative_volume >= 2.0`
- `pattern.rsi entre 50-75`
- `news_score >= 50` si hay noticias

**SL/TP:** ATR-based, `ATR_STOP_MULTIPLIER=2.0`, `ATR_TP1_MULTIPLIER=2.0`, `ATR_TP2_MULTIPLIER=4.0`.

### 2. `mean_reversion` (`mean_reversion.py`)

**Filosofia:** Bounce desde extremos.

**Filtros:**
- LONG: `pattern.rsi <= 25` (oversold), `pattern.bollinger_position` extremo bajo
- SHORT: `pattern.rsi >= 75` (overbought), Bollinger position extremo alto
- Macro `regime != "risk_off"` para longs
- No news catalyst justificando el extremo

**SL/TP:** ATR-based, multiplier conservador.

**Stats:** mean_reversion/forex tuvo 2 outliers gigantes pre-v2.6.8 (-$17k netos por `size_notional` inflado). Post-fix la perfomance es razonable pero R todavia negativo.

### 3. `momentum` (`momentum.py`) — DESHABILITADA

> [!danger] DISABLED en .env
> 77% loss rate en 53 trades. -$36k impact estimado. User deshabilito post-sprint 28-may.

**Filosofia:** Seguir tendencia fuerte con confirmacion multi-indicador.

**Filtros (cuando activa):**
- MACD bullish + SMA20/SMA50 alineadas
- RSI 50-65 (no overbought)
- Multi-tf alignment M15+H1
- Macro `risk_on` bonifica

### 4. `news_catalyst` (`news_catalyst.py`)

**Filosofia:** Trade post-noticia importante.

**Filtros:**
- `news_score >= 70`
- Trend bullish acompanando
- Volume relativo alto
- Solo forex/gold/stock (no memecoin)

### 5. `forex_session_breakout` (`forex_session_breakout.py`) — PENDIENTE DESHABILITAR

> [!warning] Loser probado
> -0.51R en n=24. Pendiente flag user.

**Filosofia:** Romper rango asiatico en apertura London/NY.

**Filtros:**
- `current_session in {"london", "ny"}`
- Asian range identificado (high/low ultimas 8h pre-London)
- Breakout con buffer 0.05% sobre range_high (long) o bajo range_low (short)
- Solo forex majors + gold
- Macro `regime != "risk_off"`

**Stats:** Forex pierde (-$596 USD agregado historico), gold gana (+$3,830). Disable solo si la gain de gold no compensa.

---

## Strategies SCALPING (v2.6.0+)

### 6. `scalping_breakout` (`scalping_breakout.py`)

**Filosofia:** Range breakout sobre M1.

**Logica:**
```python
range_candles = candles[-(lookback+1):-1]
range_high = max(c["high"] for c in range_candles)
range_low = min(c["low"] for c in range_candles)

# LONG: ask > range_high * 1.00005 (buffer 0.5 bp)
# SHORT: bid < range_low * 0.99995

SL = entry +/- sl_pips * pip_size
TP = entry +/- tp_pips * pip_size
```

**Defaults (user override):**
- `SCALPING_RANGE_LOOKBACK_BARS=5` (vs default 10)
- `SCALPING_SL_PIPS=6` (vs default 8)
- `SCALPING_TP_PIPS=8` (vs default 12)

R:R 1:1.33. Cooldown 60s post-signal.

**Stats:** 1 trade real, R neto -0.36 (muestra muy chica).

### 7. `scalping_mean_reversion` (`scalping_mean_reversion.py`) — NUEVA v2.6.6

**Filosofia:** Counter-trend cuando Bollinger Band touch + RSI extremo.

**Logica:**
- BB(period=20, std=2.0) sobre M1 closes
- RSI(14) SMA-based
- LONG: `bid <= BB_lower AND RSI <= 30`
- SHORT: `ask >= BB_upper AND RSI >= 70`
- Skip mercado plano: `bandwidth < pip_size` rechaza

**SL/TP:** mismos pips que scalping_breakout (`scalping_sl_pips` / `scalping_tp_pips`) para honesta comparacion de R:R.

**Stats:** 0 trades en historico (engine activo pero ranges chicos no dan setups).

---

## ScalpingEngine (multi-strategy)

> [!success] Refactor v2.6.6
> Antes `self.strategy = ScalpingBreakoutStrategy()` (single). Ahora `self.strategies: list` construida por flags `ENABLE_SCALPING_BREAKOUT` / `ENABLE_SCALPING_MEAN_REVERSION`.

`_evaluate_signal_for_symbol` itera la lista. Primer hit no-None gana. Orden: breakout primero, MR fallback.

`_compute_candle_lookback` calcula candles necesarias para AMBAS strategies (max de range_lookback+1 vs max(BB_period, RSI_period+1)). Fetch unico via `mt5_reader.get_rates`.

---

## Strategy de BACKTEST (v3.6.0, no corre en vivo)

### 8. `trend_following_d1` (`trend_following_d1.py`) — solo harness

**Filosofia:** Trend-following Donchian D1, la familia con MÁS evidencia académica
multi-activo y multi-década. Hipótesis **CONGELADA antes de mirar la data** (anti data-dredging).

**Reglas (Modo A, params congelados):**
- Long: `regime_trend == up` y `close(N) > max(high de los 55 bars previos)`. Short espejo.
- SL inicial 2.0×ATR14. **Sin TP fijo** (dejar correr al ganador).
- Salida trailing Donchian: `close(M) < min(low de los 20 bars previos)` (close-confirmada,
  ejecución al open siguiente). Time exit 120 barras. Confianza 70.

**Estado:** `enabled_setting_key` no existe en Settings → el router la deja **OFF en vivo**.
Solo la mide el harness. Integración viva (al ciclo D1) sería v3.7 si algún día pasara §11.

**Veredicto del run real:** NO PASA (avg +4.7R artefactual; drawdown 57.5R; consistencia 58%).

---

## Por que toda strategy tiene R negativo (v2.7.0 reflection)

> [!quote] Hipotesis
> 1. **Datos historicos contaminados**: 86% eran artifacts pre-Fix A (instant-kill shorts). Post-quarantine queda muestra chica con poco signal.
> 2. **Costos reales > ganancias brutas**: cost model resta round-trip cada vez. Strategies con avg_return chico se vuelven negativas tras costos.
> 3. **Setup detection no diferenciado por regimen**: misma strategy en risk_on vs risk_off rinde distinto. Slice futuro.
> 4. **Risk:reward configurado pero no validado**: ATR multipliers son defaults teoricos, no calibrados a fills MT5 reales.

Solucion no es desactivar todas (no quedaria nada). Solucion es:
1. Acumular data limpia post-Fix A
2. Slice por sesion/regimen para encontrar bolsillos +R
3. Promotion gate frena losers probados (los demas siguen acumulando data)
4. Calibrar cost model con fills reales

Ver [[07 - Ideas y Proximos Pasos]] roadmap.

---

## Decisiones especificas

### Memecoins NO ejecutan a MT5

`mt5_demo_trader.prepare_from_paper_trade` rechaza categorias != `forex` y `gold`. Memecoins solo paper. Razon: MT5 demo no tiene memecoins. Stocks tienen pero spread/slippage simulado no refleja realidad — mejor paper.

### Lessons separadas swing vs scalping

Sufijo `_scalping` en category. NO mezclar:
- Win rates distintos (~50% scalping vs ~60%+ swing tipico)
- Tiempo de vida 10s-3min vs 1-48h
- Aprenden distinto

### scalping_mean_reversion como complemento de breakout

Cuando breakout fallaria (rangebound markets), MR puede emitir. Defensa de cobertura. Stats real cuando engine acumule data.

---

## Links relacionados

- [[17 - Promotion Gate y Cost Model]] - como el gate frena losers
- [[18 - Realized R y Aprendizaje Honesto]] - como se miden hoy
- [[16 - Bugs Resueltos]] - por que muestra chica (Fix A)
- [[10 - Learning Engine]] - como contribuyen al learning
- [[07 - Ideas y Proximos Pasos]] - donde podria venir el edge
