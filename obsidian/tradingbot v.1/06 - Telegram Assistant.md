# Telegram Assistant

## Version

Activo desde `v1.3`; mejorado iteradamente:
- `v1.5` cupos/descartes
- `v1.5.1` IA Pro
- `v1.5.2` Learning Engine
- `v1.6.0` horizons + backtest
- `v2.0.0` trader engine (portfolio, halt, strategies)
- `v2.1.0` security hardening
- `v2.2.0` forex price-action + Claude API integration (fallback "no entendi" interpreta preguntas naturales)
- `v2.3.0` Phase 4: `/mt5_status`, `/data_quality`, `/walk_forward`, `/export_csv`
- `v2.4.0` Phase 4.5: `/mode` (alerts_only|trader|hybrid). Memecoin hunter mejorado + alertas Telegram re-activadas.

## Tipo

Asistente local basado en reglas + SQLite. Desde v2.2.0 soporta integracion opcional con Claude API (Haiku 4.5) — soft-fail si no esta configurado.

Cuando `ENABLE_CLAUDE_INTEGRATION=true` y `ANTHROPIC_API_KEY` esta presente:
- Pregunta natural en Telegram (sin slash) → Claude interpreta y mapea a comando o responde directo.
- En `/pro SIMBOLO` y alertas, las reasons se enriquecen con sintesis Claude.

## Comandos

```text
# Info y control basico
/help
/status
/cupos
/config

# Tokens y alertas
/top
/top_memecoins
/top_stocks
/alertas
/descartes
/analiza NVDA
/analiza 0x...

# Inteligencia
/noticias NVDA
/filings NVDA
/patron NVDA
/pro NVDA

# Aprendizaje
/aprendizaje
/paper
/entrenar
/horizontes NVDA
/backtest [24h] [features...]

# Trader engine (v2.0.0+)
/portfolio
/posiciones
/halt [horas]
/resume_trading
/strategies

# Phase 4 (v2.3.0)
/mt5_status
/data_quality
/walk_forward STRATEGY [dias] [categoria]
/export_csv [outcomes|trades|horizons|walk_forward]

# Phase 4.5 (v2.4.0)
/mode                  # muestra modo activo
/mode alerts_only      # solo alertas, sin auto-trading
/mode trader           # default, decide y abre paper trades
/mode hybrid           # phase 5+ requerirá confirmación; hoy = trader

# Pausa global
/pausar
/reanudar
```

## Comportamiento

- Solo responde al chat autorizado (`TELEGRAM_CHAT_ID`).
- Puede explicar datos guardados.
- Puede pausar/reanudar alertas automaticas.
- Puede activar/liberar el kill switch del trader engine (`/halt`, `/resume_trading`).
- Puede mostrar portfolio, posiciones abiertas, estrategias activas.
- Reportes automaticos: cuando el bot abre o cierra un paper trade, manda mensaje al chat.
- NO puede operar mercados reales.

## Reportes automaticos (v2.0.0+)

Cuando `ENABLE_TRADE_ACTION_REPORTS=true`, el bot manda:

- Al abrir: "🟢 Abri long EURUSD (breakout, conf 78). Entry/SL/TPs. Size USD. Simulado."
- Al cerrar: "🔴 Cerre NVDA (stopped). P&L -1.2%. MFE +0.8%/MAE -1.5%."

## Pendientes

- Phase 3.5: integrar Claude API para preguntas naturales y analisis cualitativo.
- Resumir semanalmente que filtros funcionan mejor.
- Conectar memoria automatica con aprendizajes manuales del usuario.
