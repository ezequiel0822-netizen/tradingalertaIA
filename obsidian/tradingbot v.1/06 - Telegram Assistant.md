---
tags: [telegram, assistant, comandos]
version: v2.7.0
updated: 2026-05-30
---

# Telegram Assistant

> [!info] Activo desde v1.3
> Mejorado iteradamente. Hoy soporta **40+ comandos** organizados en 6 areas: estado, demo trading, scalping, modo, analisis manual, learning.

---

## Que hace

- Lee mensajes del user via Telegram Bot API (`getUpdates`)
- Despachador (`BasicTelegramAssistant.handle`) decide que metodo invocar
- Devuelve string formateado
- `TelegramAssistantPoller` se llama en cada ciclo del bot (poll `TELEGRAM_ASSISTANT_MAX_UPDATES=10` updates por ciclo)

---

## Aliases por defecto

Cada comando suele tener varios aliases (con y sin slash, en espanol). Ej:
- `/aprendizaje`, `aprendizaje`, `que aprendiste`, `/learning` → `learning_message()`

---

## Areas de comandos

| Area | Comandos clave |
|---|---|
| **Estado** | `/health`, `/status`, `/portfolio`, `/posiciones`, `/cupos` |
| **Demo trading** | `/demo_candidates`, `/demo_prepare ID`, `/confirm_demo_trade ID`, `/demo_positions`, `/demo_close_all`, `/demo_halt` |
| **Scalping** | `/scalping_on`, `/scalping_off`, `/scalping_status`, `/scalping_halt`, `/scalping_resume`, `/scalping_stats` |
| **Modo** | `/mode hybrid`, `/mode swing_only`, `/mode scalping_only`, `/mode alerts_only` |
| **Kill switch** | `/halt`, `/resume_trading`, `/pausar`, `/reanudar` |
| **Analisis manual** | `/analiza SIMBOLO`, `/noticias SIMBOLO`, `/filings SIMBOLO`, `/patron SIMBOLO`, `/pro SIMBOLO` |
| **Learning** | `/aprendizaje`, `/horizontes SIMBOLO`, `/backtest`, `/strategies`, `/gate_preview`, **`/expectancy`** (v2.7.0) |
| **CSV** | `/export_csv` |
| **Otros** | `/help`, `/ayuda`, `/start`, `/top`, `/top_memecoins`, `/top_stocks`, `/alertas`, `/descartes`, `/paper`, `/entrenar`, `/config` |

Para detalle completo de cada comando ver [[13 - Comandos Telegram]].

---

## Commands clave v2.7.0

### `/expectancy`

Muestra `strategy_performance` (P&L realizado neto de costos en R) con tags **LIVE/SHADOW** del promotion gate.

Output:
```
[SHADOW] unknown/stock:                n=32  avgR=-0.039
[LIVE  ] forex_session_breakout/forex: n=24  avgR=-0.512  (arts_excl=339)
[LIVE  ] momentum/forex:               n=22  avgR=-0.657
...
```

`LIVE` = puede mandar a MT5 demo. `SHADOW` = bloqueada por gate, paper-only.

### `/gate_preview` (v2.6.9)

Preview del impacto si activas `ENABLE_LEARNING_GATE=true`. Muestra por feature: samples, win_rate, avg_return, decision PASS/BLOCK.

Aliases: `/preview_gate`, `/learning_gate`, `preview gate`

---

## Auto-confirm path

Con `ENABLE_AUTO_CONFIRM_DEMO=true`, el flujo es:

1. Bot detecta signal apto para forex/gold
2. Crea paper_trade
3. `_try_prepare_demo_order` → crea `demo_trade_request`
4. **Promotion gate (v2.7.0)** valida `should_execute_live` → si SHADOW, frena aqui
5. `_auto_execute_demo_request` llama `trader.send_prepared_request`
6. Crea `demo_order` row
7. Updatea `paper_trade.size_notional` con MT5 real (v2.6.8)
8. Notifica Telegram "Auto-orden demo enviada"

---

## Manual confirm path

Con `ENABLE_AUTO_CONFIRM_DEMO=false`:

1-3. Igual al auto path
4. Notifica Telegram "Orden demo MT5 lista para confirmar / ID: N / /confirm_demo_trade N"
5. User manda `/confirm_demo_trade N` desde Telegram
6. Ejecuta `_auto_execute_demo_request` (mismo backend)
7-8. Igual al auto path

`DEMO_TRADE_REQUEST_TTL_MINUTES=5` — si el user no confirma en 5 min, la request expira.

---

## Notifications proactivas (sin pedirlas)

El bot manda mensajes proactivos cuando:
- Auto-orden demo enviada / fallida
- Kill switch dispara
- Scalping heartbeat cada N trades (`SCALPING_HEARTBEAT_EVERY_N_TRADES=10`)
- Alertas agrupadas por categoria (cada ciclo)
- Trade abierto / cerrado (`ENABLE_TRADE_ACTION_REPORTS=true`)

---

## Disclaimer estandar

Todas las respuestas relevantes terminan con:
```
No es recomendacion financiera. Revisar manualmente.
```

Definido como constante `DISCLAIMER` en `command_handler.py`.

---

## Links relacionados

- [[13 - Comandos Telegram]] - referencia COMPLETA de los 40+ comandos
- [[17 - Promotion Gate y Cost Model]] - `/expectancy` detail
- [[10 - Learning Engine]] - `/aprendizaje`, `/horizontes`, `/backtest`
