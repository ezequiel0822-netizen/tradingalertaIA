---
tags: [comandos, telegram, referencia]
version: v2.7.0
updated: 2026-05-30
---

# Comandos Telegram - Referencia Completa v2.7.0

> [!info] 40+ comandos disponibles
> Cada uno con varios aliases (con/sin slash, espanol/ingles). Todas las respuestas terminan con disclaimer estandar.

---

## Estado del sistema

### `/health`

Panel completo de salud operativa.

**Aliases:** `/salud`, `salud`

**Muestra:**
- Version del codigo
- Bot mode (trader/alerts_only/hybrid)
- MT5: reader OK?, broker profile, demo trading ON?, auto-confirm ON?, real trading BLOQUEADO
- Paper trades open por categoria
- Riesgo agregado vs caps
- Balance demo MT5
- P&L hoy
- Kill switch estado
- Demo trading halt
- Scalping engine estado (activo/halt, trades hoy, abiertos, simbolos)
- Auto-orders demo (ultimas 20: sent/failed)
- Ultima auto-order info

### `/status`

Estado basico (resumido).

**Aliases:** `status`, `estado`, `/estado`

### `/portfolio`

Posiciones simuladas + balance + P&L.

### `/posiciones`

Paper trades actualmente abiertos.

### `/cupos`

Cuotas restantes de alertas por categoria.

**Aliases:** `cupos`, `alertas restantes`

---

## Demo Trading (Phase 5)

### `/demo_candidates`

Paper trades listos para orden demo (forex/gold abiertos sin demo_order asociada).

**v2.5.3:** valida cada candidato contra precio MT5 actual antes de mostrar.

### `/demo_prepare ID`

Prepara manualmente orden demo desde paper_trade `ID`. Crea `demo_trade_request`. Usuario debe confirmar con `/confirm_demo_trade ID`.

> [!warning] Solo si auto-confirm OFF
> Con `ENABLE_AUTO_CONFIRM_DEMO=true`, el bot prepara y envia automaticamente.

### `/confirm_demo_trade ID`

Confirma `demo_trade_request` con ID. Ejecuta order_send a MT5 demo. NO necesario con auto-confirm.

### `/demo_positions`

Posiciones REALES en MT5 demo (via `mt5_demo_trader.positions()`). Util para auditar huerfanas.

### `/demo_close_all`

Cierra TODAS las posiciones MT5 demo. Llama `close_all_positions()` que itera y manda close orders.

> [!success] Disponible desde v2.6.1
> Usado el 27-may para cerrar 17+ XAUUSD shorts huerfanas manualmente.

### `/demo_halt`

Bloquea nuevas ordenes demo (set `bot_state.demo_trading_halted=true`). Paper trades siguen, solo no se ejecutan a MT5.

---

## Scalping (Phase 5.5)

### `/scalping_on` / `/scalping_off`

Toggle del scalping engine (set `bot_state.scalping_active`).

### `/scalping_status`

Estado actual: trades hoy / cap, abiertos / cap, simbolos permitidos.

### `/scalping_halt` / `/scalping_resume`

Kill switch especifico del scalping (set `bot_state.scalping_halted`). Independiente del global.

### `/scalping_stats`

Win rate + avg return de scalping trades cerrados.

---

## Modo Macro

### `/mode hybrid`

Bot mode = `trader` + scalping ACTIVO. Todo on.

### `/mode swing_only`

Bot mode = `trader` + scalping OFF.

### `/mode scalping_only`

Bot mode = `alerts_only` + scalping ACTIVO. Solo scalping ejecuta.

### `/mode alerts_only`

Bot mode = `alerts_only`. Sin trading (solo alertas Telegram).

Resolution order: CLI > `bot_state` > `setting` > default trader.

---

## Kill Switches Globales

### `/halt [horas]`

Activa kill switch global por N horas. Si omitis `horas`, usa `KILL_SWITCH_COOLDOWN_HOURS=24`.

### `/resume_trading`

Libera kill switch + demo halt. Permite que el bot opere de nuevo.

### `/pausar` / `/reanudar`

Pausa/reanuda envio de alertas (set `bot_state.alerts_paused`). Trades siguen.

---

## Analisis Manual

### `/analiza SIMBOLO`

Analisis general del simbolo (pattern, score, IA Pro).

### `/noticias SIMBOLO`

Titulares recientes (Yahoo RSS) del simbolo.

### `/filings SIMBOLO`

Filings SEC recientes (10-K, 10-Q, 8-K).

### `/patron SIMBOLO`

Patron tecnico detallado (RSI, MACD, ATR, Bollinger, S/R, multi-tf).

### `/pro SIMBOLO`

Analisis IA Pro completo (setup, sesgo, score, confianza, riesgos, checklist).

---

## Learning

### `/aprendizaje`

Lessons aprendidas separadas SWING vs SCALPING.

**Aliases:** `aprendizaje`, `que aprendiste`, `/learning`

**Output:**
```
Aprendizaje local de Trading Alert AI v2.7.0
Ultimo entrenamiento: Evaluadas N senales; outcomes nuevos N; lecciones N

== SWING LESSONS ==
1. feature (cat) | casos N | win X% | retorno medio Y%
   Texto humano de la leccion

== SCALPING LESSONS ==
...
```

### `/horizontes SIMBOLO`

Performance del simbolo por horizonte (1h, 6h, 24h, 7d). Util para detectar si responde mejor a corto o largo plazo.

### `/backtest`

Backtest historico de reglas y rankeo. Output: top features por sharpe.

### `/strategies`

Lista de strategies activas con su flag y configuracion.

### `/gate_preview` (v2.6.9)

Preview del impacto si activas `ENABLE_LEARNING_GATE=true`. Muestra por feature: samples, win_rate, avg_return, decision PASS/BLOCK.

**Aliases:** `/preview_gate`, `/learning_gate`, `preview gate`

**Output:**
```
Learning Gate Preview (v2.7.0)
Settings: horizon=24h | since=30d | min_samples=10 | min_wr=45%
ENABLE_LEARNING_GATE actual: False
FORCE_FOR_MEMECOIN: True

Top features por sharpe (samples >= min_samples):

X feature_name                    n=N wr=X% ret=Y% [BLOCK]
Y feature_name                    n=N wr=X% ret=Y% [PASS]

Resumen si activas el gate: N bloqueados | M pasan
```

### `/expectancy` (v2.7.0)

`strategy_performance` real con tags LIVE/SHADOW del promotion gate.

**Output:**
```
[SHADOW] unknown/stock:                n=32  avgR=-0.039  win=34%
[LIVE  ] forex_session_breakout/forex: n=24  avgR=-0.512  win=12%   (arts_excl=339)
[LIVE  ] momentum/forex:               n=22  avgR=-0.657  win=23%
...
```

- `[LIVE]` = strategy puede mandar a MT5 demo
- `[SHADOW]` = strategy bloqueada por gate, paper-only
- `avgR` = expectancy en R-multiples (neto de costos)
- `arts_excl` = artifacts excluidos por precio congelado

### `/entrenar`

Fuerza un learning cycle inmediato (no espera al schedule). Util para refrescar lessons tras nueva data.

**Aliases:** `entrenar`, `train`, `/train`

---

## Memecoin / Stock Highlights

### `/top`

Mejores candidatos actuales (memecoin + stock combinado).

**Aliases:** `top`, `mejor`, `mejores`, `que es lo mejor ahorita`

### `/top_memecoins`

Top memecoins por score.

**Aliases:** `top memecoins`, `top memes`, `mejores memecoins`

### `/top_stocks`

Top stocks por score.

**Aliases:** `top stocks`, `top acciones`, `mejores acciones`

---

## Recientes / Descartes

### `/alertas`

Ultimas alertas enviadas a Telegram.

**Aliases:** `/ultimas_alertas`, `alertas`, `ultimas alertas`

### `/descartes`

Candidatos descartados (no enviados por dedup o caps).

**Aliases:** `descartes`, `descartados`

---

## CSV Export

### `/export_csv`

Exporta outcomes, paper_trades, horizons, walk_forward a `exports/` (CSV). Util para analisis en Excel/Python.

---

## Paper Trading

### `/paper`

Paper trades abiertos resumidos.

**Aliases:** `paper`, `simulacion`, `/paper_trades`

---

## Configuracion

### `/config`

Muestra configuracion actual relevante (sin secretos).

**Aliases:** `config`, `configuracion`

---

## Ayuda

### `/help`

Lista de comandos disponibles.

**Aliases:** `/start`, `help`, `ayuda`, `/ayuda`

---

## Setup en BotFather

Para tener el menu nativo de Telegram, configurar en BotFather:

```
/setcommands
@TuBotName
health - Estado completo del bot
status - Estado basico
portfolio - Resumen de posiciones
posiciones - Paper trades abiertos
cupos - Cuotas restantes
expectancy - R real por strategy
aprendizaje - Lessons aprendidas
backtest - Backtest historico
gate_preview - Preview del learning gate
top - Mejores candidatos
top_memecoins - Top memecoins
top_stocks - Top stocks
alertas - Ultimas alertas
descartes - Candidatos descartados
paper - Paper trades
analiza - Analiza simbolo
noticias - Noticias del simbolo
filings - Filings SEC
patron - Patron tecnico
pro - Analisis IA Pro
horizontes - Performance por horizonte
strategies - Strategies activas
demo_candidates - Trades listos para demo
demo_positions - Posiciones MT5 reales
demo_close_all - Cerrar todo MT5
demo_halt - Halt demo trading
scalping_on - Activar scalping
scalping_off - Desactivar scalping
scalping_status - Estado scalping
scalping_halt - Halt scalping
scalping_resume - Resume scalping
scalping_stats - Stats scalping
mode - Cambiar modo (hybrid/swing_only/scalping_only/alerts_only)
halt - Kill switch manual
resume_trading - Liberar kill switch
pausar - Pausar alertas
reanudar - Reanudar alertas
export_csv - Exportar CSV
entrenar - Forzar learning cycle
config - Configuracion actual
help - Ayuda
```

---

## Links relacionados

- [[06 - Telegram Assistant]] - overview
- [[17 - Promotion Gate y Cost Model]] - `/expectancy` detail
- [[10 - Learning Engine]] - `/aprendizaje`, `/backtest`, `/gate_preview`
- [[12 - Guia de Uso]] - como usarlos diariamente
