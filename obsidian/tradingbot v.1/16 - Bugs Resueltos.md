---
tags: [bugs, fixes, history]
version: v2.7.0
updated: 2026-05-30
---

# Bugs Resueltos

> [!info] La saga de fixes
> Los bugs mas costosos del proyecto, documentados con sintoma, root cause, fix y leccion.

---

## v2.7.1 (2026-06-02) — Kill switch falso por paper-only trades de gold

> [!danger] El bug del 01-jun
> Kill switch disparó con `daily drawdown -3.20% < -3.0%` pero el balance MT5 real solo bajó **−$1.40 en todo el día**.

### Sintoma

- Bot operando normal el 01-jun
- 14:32 UTC: kill switch dispara con razon "daily drawdown -3.20% < -3.0%"
- Balance MT5 antes: $88,637 | Balance MT5 después: $88,637 (sin cambio material)
- Bot bloqueado de operar por 24h hasta cleared manualmente

### Root cause

Variante del bug del 27-may (`size_notional` teórico vs MT5 real). v2.6.8 ya había tapado el caso forex (POST-demo_order notional correction). Pero **gold paper_trades con `symbol=GC=F`** (formato Yahoo) nunca matcheaban `DEMO_ALLOWED_SYMBOLS`:

- `DEMO_ALLOWED_SYMBOLS` tiene `XAUUSD,GOLD` (formato MT5 post-yahoo_to_mt5)
- Paper_trade tiene `symbol='GC=F'` (formato Yahoo, sin mapeo en este check)
- `prepare_from_paper_trade` no mapeaba GC=F → XAUUSD antes del check → rechazaba
- No se ejecuta a MT5 → no entra al hook `_correct_paper_trade_notional`
- `size_notional` queda con sizing TEÓRICO del position_sizer (~$184k para gold con balance teórico 1M)

Dos trades gold con −1% cada uno × $184k notional cada uno = −$3,680 USD "imaginario" / $88,637 balance = **−4.15% drawdown falso** que sumado al resto dió −3.20% disparando kill switch.

### Fix (v2.7.1 commit `fd59478`)

**Approach**: `realized_pnl_today` debe contar SOLO trades que realmente afectaron el balance MT5. Eso = trades con `demo_order.status='sent'` exitoso.

```python
# Repository.has_successful_demo_order(paper_trade_id) -> bool
SELECT 1 FROM demo_orders
WHERE paper_trade_id = ? AND status = 'sent'
LIMIT 1
```

```python
# portfolio_manager.realized_pnl_today
for t in closed:
    if return_pct and notional > 0:
        # v2.7.1: filtro paper-only
        if not self.repository.has_successful_demo_order(t["id"]):
            continue  # nunca llego a MT5, no afecta balance real
        total_usd_pnl += notional * (return_pct / 100.0)
```

Semántica corregida: `realized_pnl_today` = "USD impact en balance MT5 demo", no "suma de paper PnL teórico".

### Validacion live (2026-06-02)

El día siguiente al fix, el bot operó normal y el filtro v2.7.1 demostró su valor:

```
v2.7.0 calc (TODOS):           n=25  USD=-$15,295  drawdown=-17.26%  ← falso, hubiera disparado kill switch
v2.7.1 calc (con demo_order):  n=1   USD=-$4.80    drawdown=-0.005%  ← realidad MT5
```

Balance MT5 confirmó: −$1.40 neto en el día completo.

### Tests (+5 → 402 verdes)

- `_seed_closed_trade` helper extendido con `executed_to_mt5: bool = True` default.
- 3 tests para `realized_pnl_today` (excludes paper-only, includes executed, mixed scenario).
- 2 tests para `has_successful_demo_order` (true/false cases).

### Leccion

El patrón **size_notional inflado** sigue causando bugs porque el position_sizer asume balance teórico de $1M para calcular sizing, pero MT5 demo ejecuta con balance real ~$88k. Cualquier paper_trade que NO ejecuta a MT5 queda con notional inflado.

Soluciones aplicadas a lo largo del tiempo:
- v2.6.8: corregir notional POST-execute para forex
- v2.7.1: filtrar paper-only del cálculo de drawdown

Pendiente futuro: o (a) cap el `size_notional` en position_sizer al sizing MT5 real preview, o (b) mapear Yahoo→MT5 antes del allowed check para que gold GC=F sí se intente ejecutar.

---

## v2.7.0 (2026-05-30) — Fix A: `_update_paper_trades` long-only insta-killeaba shorts

> [!danger] Keystone — bug que invalido 86% del historial
> Costo: imposible cuantificar en USD directo, pero invalida toda la data de aprendizaje pre-fix.

### Sintoma

- 86% del historial de paper_trades eran artifacts (764/884)
- Cada short se marcaba `stopped_simulated` ~12 segundos despues de creacion
- Precio del paper_trade quedaba congelado en entry
- Lessons aprendidas sobre data falsa

### Root cause

`training_engine._update_paper_trades` tenia logica LONG-ONLY:

```python
if latest <= stop:  # Asume LONG: precio cae al SL
    status = "stopped_simulated"
```

Para SHORT, el stop esta ARRIBA del entry. En el mismo ciclo de creacion:
- entry = 1.5000
- stop = 1.5050 (arriba, para limitar loss en short)
- latest = entry = 1.5000 (mismo precio en ese tick)
- `latest <= stop` → `1.5000 <= 1.5050` → TRUE → instant kill

Corria junto a `lifecycle_manager.manage_open_positions` (direction-aware) = doble management conflictivo.

### Fix (v2.7.0 commit `3f0b48e`)

`_update_paper_trades` ahora direction-aware:

```python
if direction == "long":
    if latest <= stop: status = "stopped_simulated"
    elif latest >= tp: status = "target_2_simulated"
else:  # short
    if latest >= stop: status = "stopped_simulated"
    elif latest <= tp: status = "target_2_simulated"
```

Cascada del fix:
1. Mata el instant-kill
2. Trades viven su horizonte completo
3. Dedup de posiciones abiertas frena el feedback-loop
4. Precios dejan de congelarse
5. Outcomes reflejan realidad

### Leccion

Cuando agregaste shorts (v2.2 forex_session_breakout), no chequeaste que el updater original soportara direccion. Ahi se ocultaron 86% de los datos del learning.

---

## v2.7.0 (2026-05-30) — Fix C: `_fresh_price` simbolo Yahoo crudo

### Sintoma

`lifecycle_manager` no actualizaba `latest_price` de forex/gold paper trades — quedaban con precio stale del entry.

### Root cause

`_fresh_price` pasaba `'USDCHF=X'` (formato Yahoo) directo a `mt5_reader.get_tick`, que espera `'USDCHF'` (formato MT5). Siempre fallaba → caia a precio stale del token cache.

### Fix (v2.7.0)

Mapea Yahoo→MT5 antes:

```python
from app.brokers.mt5_symbol_map import yahoo_to_mt5

if mt5_reader and is_connected:
    symbol = trade.get("token_address") or trade.get("symbol")
    mt5_symbol = yahoo_to_mt5(symbol, broker_profile) or symbol
    tick = mt5_reader.get_tick(mt5_symbol)
    if tick and tick.get("bid"):
        return float(tick["bid"])
```

### Leccion

Cualquier llamada a MT5 con simbolo string debe pasar por `yahoo_to_mt5` primero. El mapping no es opcional.

---

## v2.6.7 (2026-05-28) — MT5 huerfanas

> [!danger] Costo verificado: -$9,606 en 1 dia (27-may)
> Bug arquitectonico descubierto cuando user reviso MT5 desktop manualmente.

### Sintoma

User vio 17+ posiciones XAUUSD short vivas en MT5 desktop. Sus paper_trades equivalentes en DB ya estaban `closed_by_time` o `closed_force_exit`. El bot las "olvido".

Total a lo largo del dia: 117+ ordenes USDCHF/XAUUSD huerfanas.

Gap: paper PnL trackeado -$2,162 vs balance MT5 real -$12,106. **-$9,944 de diferencia inexplicada**.

### Root cause

`paper_trade.status` lifecycle:
- Bot abre `paper_trade` + envia `demo_order` a MT5
- Si `paper_trade` cierra por reason != SL/TP real de MT5 (time exit, force exit scalping, stopped_simulated por SL movido a breakeven post-TP1), el bot:
  - Marca `paper_trade.status = closed_*`
  - **NO toca la posicion MT5**
- Posicion MT5 sigue viva con SL ORIGINAL hasta hit real

Multiplicado por horas de trading = decenas de huerfanas acumuladas.

### Fix (v2.6.7 commit `14e5cbe`)

Nuevo modulo `app/portfolio/mt5_reconciler.py`:

```python
class MT5Reconciler:
    def reconcile(self) -> ReconcileSummary:
        positions = self.trader.positions()
        orders_by_ticket = repository.fetch_demo_orders_by_tickets(tickets)
        for position in positions:
            order = orders_by_ticket.get(position.ticket)
            if order is None: continue  # manual trade
            paper = repository.fetch_paper_trade_by_id(order.paper_trade_id)
            if paper.status != "open":
                # Huerfana - cerrar
                self.trader.close_position_by_ticket(position.ticket)
            else:
                # Sync SL si difiere (solo TIGHTEN)
                if paper.stop_loss != position.sl and is_tighten(direction, paper.sl, position.sl):
                    self.trader.update_position_sl(position.ticket, paper.stop_loss)
```

Hook en `jobs.run_once()` despues de `manage_open_positions`. Soft-fail.

Nuevos metodos en `MT5DemoTrader`:
- `close_position_by_ticket(ticket)`
- `update_position_sl(ticket, new_sl)` (TRADE_ACTION_SLTP)

Regla de seguridad: **SL sync solo TIGHTEN, nunca loosen**. Empeorar el risk de una posicion abierta esta prohibido.

### Leccion

Cuando agregaste order_send a MT5 (v2.5.0), nunca pensaste en el lifecycle inverso: paper_trade cierra → posicion MT5 debe cerrar tambien. Bug arquitectonico latente meses.

---

## v2.6.8 (2026-05-28) — `size_notional` inflado 100-1000×

### Sintoma

- `realized_pnl_today` reportaba -3.18% drawdown cuando daño real era -0.13%
- Kill switch falso disparaba
- `/aprendizaje` y stats agregadas distorsionados

### Root cause

`position_sizer.calculate_position_size` usaba `ACCOUNT_STARTING_BALANCE=1M` teorico para el calculo:

```python
risk_amount = account_balance * (risk_pct / 100.0)  # 1M * 1.5% = $15k
size_units = risk_amount / per_unit_risk            # $15k / 0.0050 = 3M units
size_notional = size_units * entry                  # 3M * 1.10 = $3.3M
```

Pero MT5 demo ejecutaba `DEMO_MAX_LOT=0.1` (~$10k notional real). El `paper_trade.size_notional` reflejaba el teorico, no MT5 real.

`realized_pnl_today` = sum(notional × return%) / balance. Con notional inflado 100×, PnL inflado 100×.

### Fix (v2.6.8 commit `ac18442`)

Nuevos metodos en `MT5DemoTrader`:

```python
def compute_actual_notional_usd(symbol, volume, entry_price):
    """USD-base (USDJPY): vol × contract. USD-quote (EURUSD, XAUUSD): vol × contract × price"""
    info = symbol_info(symbol)
    contract_size = info.trade_contract_size
    if currency_base.upper() == "USD":
        return volume * contract_size
    return volume * contract_size * entry_price
```

Hook en `jobs._auto_execute_demo_request` post-demo_order exitoso:

```python
actual_notional = trader.compute_actual_notional_usd(symbol, volume, price)
self.repository.update_paper_trade(paper_id, {
    "size_notional": actual_notional,
    "size_units": volume * contract_size,
})
```

Mismo hook en `scalping_engine._open_scalping_trade`.

### Leccion

`paper_trade.size_notional` debe reflejar la EJECUCION REAL, no el sizing teorico. Si demo execution capea, el notional debe coincidir con la realidad.

---

## v2.6.8 (2026-05-28) — Feedback loop sin per-symbol cooldown

### Sintoma

Bot abrio **159 USDCHF orders en 20 min** (~8/min). User vio el problema en MT5 desktop.

### Root cause

`forex_session_breakout` detectaba el mismo setup tras cada SL hit (precio rebotaba a la zona de breakout). El dedup global (`DEDUP_WINDOW_MINUTES=360`) protegia ALERTAS de Telegram, pero no la creacion de TRADES nuevos.

### Fix (v2.6.8)

Nuevo setting `STRATEGY_SYMBOL_COOLDOWN_MINUTES=15`. Check en `RiskManager.check_can_open_trade(symbol=)`:

```python
if symbol and cooldown_min > 0:
    cutoff = utc_now() - timedelta(minutes=cooldown_min)
    if repository.has_recent_paper_trade_for_symbol(symbol, cutoff.isoformat()):
        return False, f"symbol_cooldown_active ({symbol}, last trade <{cooldown_min}min ago)"
```

Update caller en `jobs.run_once`:

```python
ok, reason = self.risk_manager.check_can_open_trade(
    snapshot.category, sizing.risk_pct_actual,
    symbol=snapshot.token_address or snapshot.symbol,
)
```

### Leccion

Dedup de alertas != dedup de trades. Necesitas ambos. Per-symbol cooldown en risk_manager es la capa correcta.

---

## v2.6.5 (2026-05-26) — 3 bugs overnight

### Bug A: `realized_pnl_today` sumaba % per-trade

Memecoin -82% sobre $1k notional daba "-82% portfolio drawdown" falso.

**Fix:** USD-based. `sum(notional × return%) / balance`. Trades sin notional (memecoin paper) se ignoran.

### Bug B: `symbol_select` no defensive en `get_rates`

Si simbolo no en MT5 Market Watch, `copy_rates_from_pos` devolvia None silencioso.

**Fix:** `get_rates` llama `symbol_select(symbol, True)` antes.

### Bug C: `account_balance` no refrescaba MT5 equity

`/health` mostraba 1M cuando MT5 real era 100k.

**Fix:** `_fetch_mt5_equity()` con retry reconnect + persist en `bot_state.account_balance`.

---

## v2.6.4 (2026-05-25) — `numpy.void` sin `.get()`

`copy_rates_from_pos` devuelve numpy structured array. Cada elemento es `numpy.void` (NO dict). Soporta `r["tick_volume"]` pero NO `r.get("tick_volume")`.

**Fix:** helper `_safe_tick_volume(r)` con try/except.

---

## v2.6.3 (2026-05-25) — Scalping no recibia candles

`_fetch_m1_candles` pasaba `timeframe="M1"` (string) a `mt5_reader.get_rates`. La lib espera `int` (`TIMEFRAME_M1=1`).

**Fix:** pasar constante `MT5_TIMEFRAME_M1 = 1`.

Bug invisible hasta `v2.6.2` (diagnostic instrumentation) — el engine corrio 1909 ciclos sin signal y nadie sabia por que.

---

## v2.6.0+ — Bugs scalping menores

- Macro_collector y economic_calendar_collector no se ejecutaban (wiring fix en `__init__`)
- Logs filtraban `mt5_password` (fix con `__repr__` mascarado + LogRedactor)
- ForexFactory cambio formato XML (parser defensivo)
- MT5 demo no expone `tick_size`/`tick_value` para algun simbolo (fallback a point + contract_size)
- `MAX_OPEN_TRADES_TOTAL=5` bloqueaba forex auto-execute (cap separado `DEMO_MAX_TOTAL_RISK_PCT`)

---

## Bugs conocidos sin fixear (no criticos)

- **GeckoTerminal 429** rate limit overnight (esperado, soft-fail)
- **Yahoo RSS 500** errors esporadicos (esperado, soft-fail)
- **Obsidian auto-gen files** dirty constantemente (intencional)
- **Worktree corrupto** `.claude/worktrees/reverent-curie-7ccc75` post-iCloud (inofensivo, dir vacio)

---

## Patron de bugs (meta-leccion)

> [!quote] Anti-patron detectado
> Los bugs mas costosos NO fueron typos o syntax errors. Fueron **asunciones arquitectonicas** que se ocultaron meses:
> - `_update_paper_trades` long-only (asumio que paper_trades eran solo long)
> - MT5 huerfanas (asumio que close de paper_trade = close de MT5)
> - `size_notional` teorico (asumio que sizing era exact)
> - `realized_pnl_today` per-trade % (asumio que notionals eran homogeneos)
> - `_fresh_price` simbolo crudo (asumio que Yahoo == MT5)

Cuando agregas un feature nuevo (shorts, MT5 execution, scalping), pensar en:
1. Que asume el codigo existente?
2. Que partes del lifecycle no estoy cubriendo?
3. Que tests cubren los CASOS NEGATIVOS, no solo los happy paths?

---

## Links relacionados

- [[03 - Versiones y Cambios]] - timeline
- [[08 - Bitacora de Aprendizaje]] - lecciones de cada uno
- [[17 - Promotion Gate y Cost Model]] - defensa post-bugs
- [[21 - Decisiones Arquitectonicas]] - por que ahora
