---
tags: [seguridad, restricciones, inamovibles]
version: v2.7.0
updated: 2026-05-30
---

# Reglas de Seguridad

> [!danger] Estas reglas NO se rompen
> Cualquier futura sesion de Claude Code debe respetarlas. Si una tarea requiere romperlas, se PARA y se pide autorizacion explicita.

---

## Real-money trading

> [!danger] BLOQUEADO HARDCODED
> `ENABLE_REAL_TRADING=false` en codigo, no solo en `.env`. Cambiarlo requiere autorizacion nueva + 3+ meses de demo estable (sharpe>1, win_rate>50%, maxDD<10%).

### Triple defensa

1. Setting `ENABLE_REAL_TRADING=false` default + HARDCODED
2. `mt5_demo_trader._validate_demo_account()` valida `account.trade_mode == ACCOUNT_TRADE_MODE_DEMO` y RECHAZA real
3. `order_send` SOLO se invoca desde `app/brokers/mt5_demo_trader.py` (unico modulo con esa capacidad)

### Promotion gate (v2.7.0) refuerza

`should_execute_live()` agrega cuarta capa: estrategias con edge negativo PROBADO (avg_r ≤ umbral con n ≥ min_samples) quedan paper-only (SHADOW). NO toca real-money, solo el `order_send` a demo MT5.

---

## Archivos sagrados (NO TOCAR sin permiso)

| Archivo | Por que |
|---|---|
| `.env` (real) | Contiene secretos. NUNCA leer, modificar ni mostrar contenido sin autorizacion |
| `C:\Users\xxxv4\trading_data\trading_alert_ai.db` | DB con historial real (post v2.7.0) |
| `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\trading_alert_ai.db` | Backup congelado pre-movida |
| `app/brokers/mt5_demo_trader.py` | Unico modulo que ejecuta `order_send` |
| `app/portfolio/mt5_reconciler.py` | Cierra/modifica posiciones MT5 |
| `app/database/db.py::_init_db_unsafe` | Schema — usar `_ensure_column` para migraciones backward-compat |

---

## Capacidades opt-in (NO hardcodear true)

| Setting | Default | Por que opt-in |
|---|---|---|
| `ENABLE_AUTO_CONFIRM_DEMO` | false | Bypass de confirmacion manual = decision de seguridad del user |
| `ENABLE_SCALPING_ENGINE` | false | Mas agresivo que swing (mas trades, debugging threading) |
| `ENABLE_MT5_DEMO_TRADING` | false | Permite order_send a demo |
| `ENABLE_STRATEGY_PROMOTION_GATE` | **true** (excepcion) | Gate restrictivo = reduce riesgo, default ON razonable |
| `ENABLE_COST_MODEL` | **true** (excepcion) | Mide la verdad neta de costos, default ON razonable |
| `ENABLE_REALIZED_LEARNING` | **true** (excepcion) | Aprende del P&L real, default ON razonable |

---

## Comportamientos correctos (NO "corregir")

- **Lifecycle SL-to-breakeven post-TP1** — paper_trade mueve SL a entry tras hit TP1. Es disenado asi, no es bug.
- **MT5Reconciler sync de SL solo TIGHTEN** — nunca loosen. Empeorar el risk de una posicion abierta esta prohibido.
- **Lessons scalping separadas via sufijo `_scalping`** — NO mezclar con swing. Aprenden distinto.
- **Promotion gate subtractivo** — solo PREVIENE order_send. Nunca lo causa.
- **Memecoins NO ejecutan a MT5** — solo paper/lab de aprendizaje. MT5 no tiene memecoins.
- **`paper_trade.size_notional` se updatea POST-demo_order con notional MT5 real** (v2.6.8). NO es bug.
- **`alert_id` negativo en `signal_outcomes` para scalping** (`-paper_trade.id`) — evita colision con swing. NO es bug.

---

## Secretos en logs

> [!warning] Doble defensa contra fuga
> 1. `Settings.__repr__` mascarado via `_SECRET_FIELDS`
> 2. `LogRedactor` filter en logging_config
>
> Si agregas un campo secreto nuevo a Settings, debe agregarse a `_SECRET_FIELDS` set.

Campos secretos actuales:
- `telegram_bot_token`
- `telegram_chat_id`
- `mt5_login`
- `mt5_password`
- `mt5_server`
- `anthropic_api_key`

---

## Tests (no negociables)

- **397 tests verdes** baseline (v2.7.0). Mantener verde tras cualquier cambio.
- Antes de modificar Settings: sincronizar `tests/test_score.py::_settings()` Y `tests/test_alert_rules.py::_settings()` en el MISMO commit. Son los dos unicos que construyen `Settings(...)` directo.
- Tests escriben a `.test_dbs/` (in-memory o tmpdir). NO al path de produccion.

---

## Git policy

- Nunca push --force a main sin autorizacion
- Nunca skip hooks (--no-verify) sin autorizacion
- Co-Authored-By en commits que hace Claude
- Commits descriptivos (estilo `feat(vX.Y.Z): descripcion`)

---

## Memecoins (defensa anti-rug)

- `FORCE_LEARNING_GATE_FOR_MEMECOIN=true` — aunque global gate este off, memecoins siempre pasan por el filter
- `critical_security` features filtran riesgo
- Holder concentration y liquidity_locked = `None` (requieren RPC blockchain, Phase 7)
- Memecoins NO ejecutan a MT5 — solo paper

---

## Prohibiciones absolutas (sin excepcion)

El sistema NO debe:
- comprar, vender, conectar wallets reales
- conectar brokers reales
- ejecutar trades reales
- mover dinero
- cambiar `ENABLE_REAL_TRADING`
- enviar transacciones blockchain
- usar `eval()` o `exec()` con input externo
- deserializar datos sin validacion

---

## Links relacionados

- [[01 - Cerebro del Proyecto]] - identidad
- [[17 - Promotion Gate y Cost Model]] - capa nueva v2.7.0
- [[21 - Decisiones Arquitectonicas]] - por que las decisiones
