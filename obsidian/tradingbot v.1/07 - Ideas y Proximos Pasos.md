---
tags: [roadmap, ideas, futuro]
version: v2.9.1
updated: 2026-06-04
---

# Ideas y Proximos Pasos

> [!info] Estado actual v2.9.1
> Bot mide la verdad neta de costos + tiene la herramienta de edge sliceado (`/edge`, v2.8.0) y el andamiaje ML (XGBoost dormido, v2.9.0). Toda estrategia sigue R negativo: falta **DATA**, no codigo. Phase 6+ requiere ≥1 strategy con R+ neto. Real-money bloqueado.

---

## Pendientes inmediatos (dias)

> [!todo] Lado del usuario (v2.9.1)
> 1. **Aplicar `.env`**: `ENABLE_STOCK_TELEGRAM=false` + `ENABLE_MEMECOIN_TELEGRAM=true` + `APP_VERSION=v2.9.1`.
> 2. **Arrancar** desde la carpeta del proyecto con el python del venv (`.\.venv\Scripts\python.exe main.py`), MT5 abierto+logueado. Chequear `/health`, `/ml_status` (dira DORMIDO), `/edge`.
> 3. **Considerar sacar gold de `DEMO_ALLOWED_SYMBOLS`** (XAUUSD,GOLD): es la categoria mas toxica (-2.79R, 0/12 wins) y con n<30 el gate aun la deja ejecutar a demo.
> 4. **Dejar correr** para juntar muestra limpia (lo unico que mueve la aguja del edge).

---

## Roadmap corto (semanas)

### v2.7.1 / v2.7.x

- ~~**Slice `strategy_performance` por sesion**~~ ✅ HECHO en v2.8.0 (`strategy_performance_sliced` + `/edge` + gate sliceado opt-in). Pendiente: vigilar si algun slice cruza n>=30 con R+ solido.
- ~~**Capa ML**~~ ✅ HECHO en v2.9.0 (XGBoost, dormido). **PROXIMO PASO DE MAYOR VALOR: capturar `rsi`/`macd`/`atr` al crear cada trade** — hoy NO se persisten (quedan NaN), el ML esta casi ciego sin features tecnicas reales.
- **Heartbeat diario a Telegram** con expectancy + tags LIVE/SHADOW (observabilidad).
- **Calibrar cost model** con fills reales de `demo_orders` (no defaults teoricos).
- **Auto-tune scalping params** segun observacion (SL/TP pips, lookback bars).

### v2.7.x — Session-aware lessons

Aprender que strategy gana en que sesion (London/NY/Asian) y regimen (risk_on/off). Hoy `current_session` y `regime` se computan pero no entran al feature set de scoring.

---

## Roadmap medio plazo (1-3 meses)

### Phase 6 — Strategy Evolution

> [!warning] Bloqueada hasta tener ≥1 strategy con R+ neto
> Phase 6 = mutacion automatica de parametros con base teorica + fitness sharpe + win_rate + drawdown. Sin una sola strategy profitable, evolution no tiene desde donde partir.

Precondiciones:
- ≥3 meses de outcomes scalping limpios (post v2.7.0)
- ≥1 strategy con R+ neto consistente
- Cost model calibrado con fills reales

### Recalibracion de outcomes

Los `OUTCOME_WIN_RETURN_*_PCT` actuales (memecoin +30%, stock +5%) son muy estrictos: casi nada hit eso, aunque avg_return sea positivo. Hay que recalibrar a algo mas realista (memecoin +10-15%, stock +1.5%) cuando haya data limpia.

### Activar learning_gate

Hoy `ENABLE_LEARNING_GATE=false`. Tras recalibrar OUTCOME_WIN_RETURN_*, chequear con `/gate_preview`. Si el balance bloqueados/pasa es razonable, activar.

---

## Roadmap largo (3+ meses)

### Phase 7 — Collector RPC blockchain ($30-200/mes)

Hoy `holder_concentration` y `liquidity_locked` son `None` para memecoin (placeholder). Phase 7 conecta a RPC blockchain (Alchemy, QuickNode, etc.):
- Holder concentration real (top 10 holders %)
- Liquidity locked (lock period, unlock date)
- Smart money tracking (wallets de alta perfomance)

Costo: $30-200/mes segun nivel de Alchemy/QuickNode.

### Phase 8 — Multi-timeframe

Hoy: M1 scalping + ciclo de 60s para swing. Agregar:
- M5 para confirmar scalping entries
- H4 para context de swing
- D1 para regimen macro

Cambios:
- `mt5_reader.get_rates` con multiple timeframes
- `pattern_analyzer` con confluence multi-tf (mas estricto)

### Phase 9 — News/sentiment real-time

Hoy: Yahoo RSS (lento, a veces 500). Agregar:
- X (Twitter) API ($100/mes) — sentiment per ticker
- Reddit PRAW — sentiment de subreddits financieros
- Investing.com / Benzinga — earnings calendars + tier de noticias

### Phase 10 — Real-money trading

> [!danger] BLOQUEADO
> Requiere:
> - 3+ meses de demo estable (sharpe>1, win_rate>50%, maxDD<10%)
> - Autorizacion explicita NUEVA del usuario
> - Auditoria de seguridad final
> - Pequeno capital de prueba primero ($500-1000)
>
> Hasta entonces, `ENABLE_REAL_TRADING=false` HARDCODED.

---

## Ideas exploratorias (no priorizadas)

- **Sentiment Bear/Bull index** custom (combinacion de VIX + put/call ratio + news sentiment)
- **Correlation matrix** entre symbols para detectar regimen
- **Order flow heuristics** via MT5 ticks (volumen relativo, spread anomaly)
- **Strategy ensembles** (combinar 2+ strategies para signal robusto)
- **Dashboard mobile** (Streamlit responsive o app simple)

---

## NO hacer (decidido)

- **ML profundo** (LSTM, transformers) — sobre-ingenieria que casi nunca paga en retail
- **Reinforcement Learning** — fragil para trading
- **Cifrado at-rest del SQLite** — opcional, no urgente
- **Logs a archivo con rotacion** — stderr suficiente
- **TradingView integration** — duplica data que ya tenemos
- **Webhooks externos** — out of scope
- **Activar learning_gate ahora** — preview revelo bloquearia todo

---

## La verdad de fondo (post v2.7.0)

> [!quote] Insight clave
> v2.7.0 hace que el bot (1) mida la verdad neta de costos y (2) no ejecute losers probados. **NO crea edge — eso sigue siendo el problema dificil (datos + research).**

Encontrar edge requiere:
1. Data limpia post-quarantine de artifacts (Fix A v2.7.0)
2. Slice por sesion/regimen para encontrar bolsillos +R
3. Iterar sobre strategies + parametros (eventualmente Phase 6)
4. Cost model calibrado con realidad MT5 demo

---

## Links relacionados

- [[14 - Estado Actual v2.7.0]] - donde estamos hoy
- [[15 - Estrategias]] - stats actuales por strategy
- [[17 - Promotion Gate y Cost Model]] - como medimos hoy
- [[18 - Realized R y Aprendizaje Honesto]] - Fase 2b
